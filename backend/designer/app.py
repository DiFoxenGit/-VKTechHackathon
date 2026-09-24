import asyncio
import copy
import hashlib
import logging
import os
import shutil
import subprocess
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from starlette.concurrency import run_in_threadpool

from .assets import (
    drop_lettered,
    generate_illustrations,
    harvest_pptx,
    library,
    parse_pack_zip,
    resolve,
    save_assets,
    tag_assets,
)
from .audit import apply_fixes, audit, contextual_audit, merge_file_issues, visual_audit
from .exporting import (
    HTML_EXPORT_MARKER,
    convert_pdf,
    export_html,
    export_pptx,
    render_slides,
    sample_backgrounds,
    branding_drift,
    verify_pptx,
)
from .generation import (
    balance_outline,
    generate_outline,
    image_available,
    provider,
    sources_for,
    vision_available,
    workflow,
)
from .inference import llm_settings
from .layout import compose
from .models import Brief, FixRequest, GenerateRequest, Outline, SlideEdit
from .parsing import PARSER_VERSION, parse_content, parse_template
from .storage import Store

LOGGER = logging.getLogger(__name__)
MAX_UPLOAD = 50 * 1024 * 1024
# Сколько картинок рисовать на колоду: каждая — отдельный платный запрос,
# а иллюстрация нужна не всякому слайду.
IMAGE_LIMIT = max(0, int(os.getenv("DESIGNER_IMAGE_LIMIT", "3")))


async def upload_bytes(file):
    data = bytearray()
    while chunk := await file.read(1024 * 1024):
        data.extend(chunk)
        if len(data) > MAX_UPLOAD:
            raise HTTPException(413, "Upload exceeds 50 MB")
    return bytes(data)


def attach_assets(store, template, data, previous=None):
    """Собрать картинки шаблона на диск и в запись; подписи прежнего разбора сохраняются."""
    known = {a["id"]: a for a in (previous or {}).get("assets") or []}
    try:
        harvested = harvest_pptx(data, {tuple(b) for b in template.get("branding") or []})
    except Exception:  # noqa: BLE001 - без картинок шаблон всё равно пригоден
        LOGGER.exception("Cannot harvest pictures from %s", template.get("name"))
        harvested = []
    metas = save_assets(store.directory("templates", template["id"]) / "assets", harvested)
    for meta in metas:
        old = known.get(meta["id"])
        if old:
            for key in ("tags", "label", "tag_tried"):
                if key in old:
                    meta[key] = old[key]
    template["assets"] = metas
    return template


def asset_counts(assets):
    counts = {"icon": 0, "illustration": 0, "photo": 0, "tagged": 0}
    for meta in assets or []:
        counts[meta["kind"]] = counts.get(meta["kind"], 0) + 1
        counts["tagged"] += bool(meta.get("tags"))
    return counts


def register_template(store, data, name):
    digest = hashlib.sha256(data).hexdigest()
    with store.lock:
        existing = next(
            (t for t in store.list("templates") if t["sha256"] == digest), None
        )
        if existing:
            return existing
        try:
            template = parse_template(data, name)
        except Exception as exc:
            raise HTTPException(422, "Invalid or unsupported PPTX template") from exc
        template.update(id=store.new_id(), sha256=digest)
        source = store.directory("templates", template["id"]) / "source.pptx"
        source.write_bytes(data)
        measure_backgrounds(template, source)
        attach_assets(store, template, data)
        return store.put("templates", template)


def measure_backgrounds(template, source: Path):
    """Дописать в паттерны измеренный фон. Без LibreOffice остаётся разбор XML."""
    try:
        stats = sample_backgrounds(source)
    except Exception:
        LOGGER.warning("Background sampling unavailable for %s", template.get("name"))
        return template
    for pattern, measured in zip(template["patterns"], stats):
        pattern["bg_luma"] = measured["luma"]
        pattern["bg_spread"] = measured["spread"]
    return template


def refresh_templates(store):
    """Переразобрать шаблоны, разобранные прежней версией парсера.

    Идентификаторы сохраняются: ссылки в презентациях и на фронтенде не ломаются.
    """
    updated = 0
    for record in store.list("templates"):
        if record.get("parser") == PARSER_VERSION:
            continue
        source = store.directory("templates", record["id"]) / "source.pptx"
        if not source.exists():
            continue
        try:
            template = parse_template(source.read_bytes(), record["name"])
        except Exception:
            LOGGER.exception("Cannot re-parse template %s", record["id"])
            continue
        template.update(id=record["id"], sha256=record["sha256"])
        measure_backgrounds(template, source)
        attach_assets(store, template, source.read_bytes(), record)
        store.put("templates", template)
        updated += 1
    if updated:
        LOGGER.info("Re-parsed %s template(s) with parser v%s", updated, PARSER_VERSION)
    return updated


def create_app(data_dir=None, seed_dir=None):
    store = Store(Path(data_dir or os.getenv("DESIGNER_DATA_DIR", "./designer_data")))
    tasks = set()
    semaphore = asyncio.Semaphore(2)

    @asynccontextmanager
    async def lifespan(app):
        store.recover()
        await run_in_threadpool(refresh_templates, store)
        seed = seed_dir or os.getenv("DESIGNER_TEMPLATE_DIR")
        if seed:
            for path in sorted(Path(seed).glob("*.pptx")):
                await run_in_threadpool(
                    register_template, store, path.read_bytes(), path.name
                )
        yield
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def authorize(request: Request):
        import secrets

        key = os.getenv("DESIGNER_API_KEY")
        if key and not secrets.compare_digest(
            request.headers.get("authorization", ""), "Bearer " + key
        ):
            raise HTTPException(401, "Invalid API token")

    # Public prefix when a reverse proxy serves the API under a sub-path, e.g.
    # https://example.com/presentations. Empty means the service owns the root.
    base_path = (os.getenv("DESIGNER_BASE_PATH") or "").strip().rstrip("/")
    if base_path and not base_path.startswith("/"):
        base_path = "/" + base_path
    # Swagger и схема — инструмент разработчика, а не публичная страница сервиса.
    # На сервере DESIGNER_DOCS=0 закрывает их полностью, включая /openapi.json.
    docs_open = os.getenv("DESIGNER_DOCS", "1").lower() not in ("0", "false", "no", "off")
    app = FastAPI(
        title="VK Presentation Designer API",
        version="1.0.0",
        lifespan=lifespan,
        root_path=base_path,
        description="Headless presentation pipeline. Coordinates in points; revisions protect edits.",
        docs_url="/docs" if docs_open else None,
        redoc_url="/redoc" if docs_open else None,
        openapi_url="/openapi.json" if docs_open else None,
    )
    app.state.store = store
    origins = [
        o.strip().rstrip("/")
        for o in os.getenv(
            "DESIGNER_CORS_ORIGINS", "http://localhost:3000,http://localhost:5173"
        ).split(",")
        if o.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=["Content-Disposition"],
    )
    from fastapi import APIRouter

    api = APIRouter(prefix="/api/v1", dependencies=[Depends(authorize)])

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "llm_configured": llm_settings().configured,
            "pdf_available": bool(
                shutil.which("libreoffice")
                or shutil.which("soffice")
                or Path("/Applications/LibreOffice.app/Contents/MacOS/soffice").exists()
            ),
        }

    @api.get("/workflow", tags=["Workflow"])
    def get_workflow():
        return workflow()

    @api.get("/templates", tags=["Templates"])
    def templates():
        return {
            "items": [
                {
                    **{k: v for k, v in t.items() if k not in ("patterns", "assets")},
                    "asset_counts": asset_counts(t.get("assets")),
                }
                for t in store.list("templates")
            ]
        }

    @api.post("/templates", status_code=201, tags=["Templates"])
    async def upload_template(file: Annotated[UploadFile, File()]):
        if not (file.filename or "").lower().endswith(".pptx"):
            raise HTTPException(422, "Template must be a .pptx file")
        data = await upload_bytes(file)
        return await run_in_threadpool(register_template, store, data, file.filename)

    @api.get("/templates/{template_id}", tags=["Templates"])
    def template(template_id: str):
        return store.get("templates", template_id)

    def read_pack(data, name):
        """Текст и картинки контент-пакета: zip, одиночная картинка или документ."""
        suffix = Path(name).suffix.lower()
        if suffix == ".zip":
            return parse_pack_zip(data, parse_content)
        if suffix in (".svg", ".png", ".jpg", ".jpeg"):
            # Одна картинка — пакет из одного ассета, теги из имени файла.
            import io
            import zipfile

            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as archive:
                archive.writestr(Path(name).name, data)
            return parse_pack_zip(buffer.getvalue(), parse_content)
        text = parse_content(data, name)
        assets = harvest_pptx(data) if suffix == ".pptx" else []
        return text, assets

    @api.post("/content-packs", status_code=201, tags=["Content"])
    async def upload_content(file: Annotated[UploadFile, File()]):
        data = await upload_bytes(file)
        name = file.filename or ""
        try:
            text, assets = await run_in_threadpool(read_pack, data, name)
        except Exception as exc:
            raise HTTPException(
                422,
                "Cannot extract content; use UTF-8 text, CSV, JSON, DOCX, PPTX, a text PDF, "
                "images (SVG, PNG, JPEG) or a ZIP of them",
            ) from exc
        if not text.strip() and not assets:
            raise HTTPException(422, "Content pack has neither text nor pictures")
        identifier = store.new_id()
        metas = await run_in_threadpool(
            save_assets, store.directory("content_packs", identifier) / "assets", assets
        )
        return store.put(
            "content_packs",
            {
                "id": identifier,
                "name": Path(name).name,
                "text": text,
                "assets": metas,
                "asset_counts": asset_counts(metas),
                "sha256": hashlib.sha256(data).hexdigest(),
            },
        )

    @api.get("/content-packs", tags=["Content"])
    def content_packs():
        return {
            "items": [
                {k: v for k, v in p.items() if k not in ("text", "assets")}
                for p in store.list("content_packs")
            ]
        }

    def deck_library(template, pack_ids, generated=None):
        """Картинки колоды: нарисованные моделью, пакеты запроса, шаблон и встроенный набор."""
        packs = []
        for identifier in pack_ids or []:
            try:
                packs.append(store.get("content_packs", identifier))
            except HTTPException:
                continue
        return list(generated or []) + library(template, packs)

    def stored_illustrations(owner):
        """Картинки, нарисованные при сборке колоды: нужны и при правке слайда."""
        if not owner:
            return []
        try:
            return store.get("illustrations", owner).get("assets") or []
        except HTTPException:
            return []

    async def draw_illustrations(outline, template):
        """Нарисовать иллюстрации к слайдам, если генератор изображений настроен.

        Картинки рисуются один раз на колоду и достаются всем трём вариантам:
        так они не разъезжаются между вариантами и не тратится лишний запрос.
        """
        if not image_available():
            return None, []
        owner = store.new_id()
        folder = store.directory("illustrations", owner) / "assets"
        tokens = template["tokens"]
        accents = tokens.get("accents") or []
        palette = {
            # Те же цвета, по которым верстается слайд: картинка не должна
            # выбиваться из фирменного стиля шаблона.
            "background": "#" + tokens.get("theme", {}).get("lt1", "FFFFFF"),
            "accent": "#" + (accents[0] if accents else tokens.get("theme", {}).get("accent1", "1478F4")),
            "secondary": "#" + (accents[1] if len(accents) > 1 else (accents[0] if accents else "1478F4")),
        }
        try:
            async with asyncio.timeout(180):
                metas = await generate_illustrations(
                    [s["content"] if "content" in s else s for s in outline["slides"]],
                    palette,
                    folder,
                    owner,
                    limit=IMAGE_LIMIT,
                )
                metas = await drop_lettered(metas, folder)
        except TimeoutError:
            LOGGER.warning("Illustration generation timed out; deck goes without drawn pictures")
            return None, []
        if not metas:
            return None, []
        store.put("illustrations", {"id": owner, "assets": metas})
        return owner, metas

    @api.get("/templates/{template_id}/assets", tags=["Templates"])
    def template_assets(template_id: str):
        template = store.get("templates", template_id)
        return {
            "counts": asset_counts(template.get("assets")),
            "items": [
                {**meta, "url": f"{base_path}/api/v1/assets/template/{template_id}/{meta['file']}"}
                for meta in template.get("assets") or []
            ],
        }

    @api.get("/content-packs/{pack_id}/assets", tags=["Content"])
    def pack_assets(pack_id: str):
        pack = store.get("content_packs", pack_id)
        return {
            "counts": asset_counts(pack.get("assets")),
            "items": [
                {**meta, "url": f"{base_path}/api/v1/assets/pack/{pack_id}/{meta['file']}"}
                for meta in pack.get("assets") or []
            ],
        }

    @api.get("/assets/{source}/{owner}/{name}", tags=["Content"])
    def asset_file(source: Literal["template", "pack"], owner: str, name: str):
        try:
            path = resolve(f"{source}:{owner}:{name}", store.root)
        except ValueError as exc:
            raise HTTPException(404, "Asset not found") from exc
        if not path.exists():
            raise HTTPException(404, "Asset not found")
        media = {"svg": "image/svg+xml", "png": "image/png", "jpeg": "image/jpeg"}
        return FileResponse(
            path,
            media_type=media[path.suffix.lstrip(".")],
            # SVG пользователя не должен исполнять скрипты в браузере.
            headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"},
        )

    async def label_assets(template, pack_ids):
        """Подписать картинки шаблона и пакетов моделью, пока их не с чем сопоставить."""
        if not vision_available():
            return 0

        def loader(kind, owner):
            def load(meta):
                return resolve(f"{kind}:{owner}:{meta['file']}", store.root).read_bytes()

            return load

        total = 0
        try:
            async with asyncio.timeout(120):
                total += await tag_assets(template.get("assets") or [], loader("template", template["id"]))
                with store.lock:
                    current = store.get("templates", template["id"])
                    current["assets"] = template.get("assets") or []
                    store.put("templates", current)
                for identifier in pack_ids or []:
                    pack = store.get("content_packs", identifier)
                    tagged = await tag_assets(pack.get("assets") or [], loader("pack", identifier))
                    if tagged:
                        pack["asset_counts"] = asset_counts(pack["assets"])
                        store.put("content_packs", pack)
                    total += tagged
        except TimeoutError:
            LOGGER.warning("Asset labelling timed out; continuing with what is labelled")
        return total

    @api.post("/templates/{template_id}/assets/tags", tags=["Templates"])
    async def tag_template_assets(template_id: str):
        """Подписать картинки шаблона мультимодальной моделью (иначе они не подбираются)."""
        template = store.get("templates", template_id)
        if not vision_available():
            raise HTTPException(503, "Configure DESIGNER_VLM_MODEL to label template pictures")
        tagged = await label_assets(template, [])
        return {"tagged": tagged, "counts": asset_counts(store.get("templates", template_id).get("assets"))}

    @api.get("/content-packs/{pack_id}", tags=["Content"])
    def content_pack(pack_id: str):
        return store.get("content_packs", pack_id)

    @api.post("/outlines", tags=["Generation"])
    async def outline(request: Brief):
        return await generate_outline(request, sources_for(store, request))

    def generate_variant(
        request,
        outline,
        template,
        sources,
        variant,
        contextual_findings=None,
        illustrations=None,
    ):
        identifier = store.new_id()
        deck = compose(
            outline,
            template,
            variant,
            deck_library(template, request.content_pack_ids, illustrations[1] if illustrations else None),
        )
        report = audit(deck, template, sources, request.language)
        if contextual_findings is not None:
            report["issues"].extend(copy.deepcopy(contextual_findings))
            report["counts"]["warnings"] += len(contextual_findings)
            report["contextual"] = {"status": "completed", "input": "structured_text"}
        record = {
            "id": identifier,
            "template_id": request.template_id,
            "title": outline["title"],
            "variant": variant,
            "revision": 1,
            "deck": deck,
            "audit": report,
            "sources": sources,
            "workflow": workflow(),
            "generation": {
                "mode": "provided_outline" if request.outline else "llm",
                "model": llm_settings().model or None,
                "provider": llm_settings().profile,
                "purpose": request.purpose,
                "language": request.language,
            },
            "created_at": time.time(),
            # Пакеты с картинками нужны снова при правке слайда и исправлениях.
            "content_pack_ids": list(request.content_pack_ids),
            # То же для нарисованных моделью иллюстраций.
            "illustrations_id": illustrations[0] if illustrations else None,
        }
        folder = store.directory("presentations", identifier)
        source = store.directory("templates", template["id"]) / "source.pptx"
        export_pptx(source, template, deck, folder / "r1.pptx", store.root)
        # Проверки Приложения 1, которые видны только в записанном файле.
        check = verify_pptx(folder / "r1.pptx", len(deck["slides"]))
        check["moved_branding"] = branding_drift(source, deck, folder / "r1.pptx")
        record["export_check"] = check
        merge_file_issues(record["audit"], check)
        store.put("revisions", {**copy.deepcopy(record), "id": identifier + "_1"})
        return store.put("presentations", record)

    async def run_job(identifier, request, template, sources):
        job = store.get("jobs", identifier)
        started = time.monotonic()
        try:
            async with semaphore:
                job.update(status="running", stage="outline", progress=5)
                store.put("jobs", job)
                async with asyncio.timeout(300):
                    outline = request.outline or await generate_outline(
                        request, sources, job["warnings"]
                    )
                    # Тексты подгоняются под вместимость шаблона до вёрстки, чтобы
                    # все три варианта собирались из одного выверенного содержания.
                    job.update(stage="balance", progress=12)
                    store.put("jobs", job)
                    balanced = await balance_outline(outline.model_dump(), template)
                    outline = Outline.model_validate(balanced)
                    job["outline"] = outline.model_dump()
                    if vision_available():
                        job.update(stage="assets", progress=14)
                        store.put("jobs", job)
                        await label_assets(template, request.content_pack_ids)
                    illustrations = None
                    if image_available():
                        job.update(stage="illustrations", progress=15)
                        store.put("jobs", job)
                        owner, metas = await draw_illustrations(
                            {"slides": [{"content": s.model_dump()} for s in outline.slides]},
                            template,
                        )
                        illustrations = (owner, metas) if metas else None
                    contextual_findings = None
                    if request.contextual_audit:
                        job.update(stage="contextual_audit", progress=15)
                        store.put("jobs", job)
                        contextual_findings = await contextual_audit(
                            {
                                "slides": [
                                    {"content": s.model_dump()} for s in outline.slides
                                ]
                            },
                            sources,
                        )
                    for i, variant in enumerate(workflow()["variants"]):
                        job.update(stage="layout_and_audit", progress=20 + i * 25)
                        store.put("jobs", job)
                        result = await run_in_threadpool(
                            generate_variant,
                            request,
                            outline.model_dump(),
                            template,
                            sources,
                            variant["id"],
                            contextual_findings,
                            illustrations,
                        )
                        job["presentation_ids"].append(result["id"])
                    job.update(status="completed", stage="completed", progress=100)
        except asyncio.CancelledError:
            job.update(
                status="failed",
                stage="interrupted",
                error="Server stopped; submit generation again",
            )
            raise
        except Exception as exc:
            LOGGER.exception("Generation failed for job %s", identifier)
            job.update(
                status="failed",
                stage="failed",
                error=exc.detail
                if isinstance(exc, HTTPException)
                else "Generation failed or exceeded 300 seconds",
            )
        finally:
            job["elapsed_seconds"] = round(time.monotonic() - started, 3)
            store.put("jobs", job)

    @api.post("/generations", status_code=202, tags=["Generation"])
    async def generate(request: GenerateRequest):
        template = store.get("templates", request.template_id)
        sources = sources_for(store, request)
        if request.outline is None or request.contextual_audit:
            provider()
        if len(tasks) >= 20:
            raise HTTPException(429, "Generation queue is full")
        job = store.put(
            "jobs",
            {
                "id": store.new_id(),
                "status": "queued",
                "stage": "queued",
                "progress": 0,
                "presentation_ids": [],
                # То, о чём пользователь должен знать, но что не прерывает работу.
                "warnings": [],
                "created_at": time.time(),
                "workflow": workflow(),
            },
        )
        task = asyncio.create_task(run_job(job["id"], request, template, sources))
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return {**job, "status_url": f"{base_path}/api/v1/jobs/{job['id']}"}

    @api.get("/jobs/{job_id}", tags=["Generation"])
    def job(job_id: str):
        return store.get("jobs", job_id)

    @api.get("/presentations", tags=["Presentations"])
    def presentations(
        offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)
    ):
        records = store.list("presentations")
        return {
            "total": len(records),
            "items": [
                {k: v for k, v in p.items() if k not in ("deck", "sources", "audit")}
                for p in records[offset : offset + limit]
            ],
        }

    def public_presentation(record):
        return {
            **{k: v for k, v in record.items() if k != "sources"},
            "exports": {
                fmt: f"{base_path}/api/v1/presentations/{record['id']}"
                f"/export/{fmt}?revision={record['revision']}"
                for fmt in ("pptx", "pdf", "html")
            },
        }

    @api.get("/presentations/{presentation_id}", tags=["Presentations"])
    def presentation(presentation_id: str):
        return public_presentation(store.get("presentations", presentation_id))

    @api.get("/presentations/{presentation_id}/audit", tags=["Audit"])
    def get_audit(presentation_id: str):
        record = store.get("presentations", presentation_id)
        return {"revision": record["revision"], **record["audit"]}

    def slide_images(record):
        """PNG каждого слайда текущей ревизии; PDF рендерится один раз и кэшируется."""
        folder = store.directory("presentations", record["id"])
        pdf = folder / f"r{record['revision']}.pdf"
        with store.lock:
            if not pdf.exists():
                convert_pdf(folder / f"r{record['revision']}.pptx", pdf)
        return render_slides(pdf)

    @api.post("/presentations/{presentation_id}/audit", tags=["Audit"])
    async def run_audit(
        presentation_id: str, contextual: bool = False, visual: bool = False
    ):
        record = store.get("presentations", presentation_id)
        report = audit(
            record["deck"],
            store.get("templates", record["template_id"]),
            record["sources"],
            record.get("generation", {}).get("language"),
        )
        if visual:
            # Проверка по картинке слайда: то, что просит Приложение 1.
            try:
                images = await run_in_threadpool(slide_images, record)
            except (RuntimeError, subprocess.TimeoutExpired) as exc:
                raise HTTPException(503, str(exc)) from exc
            findings = await visual_audit(record["deck"], record["sources"], images)
            report["issues"].extend(findings)
            report["counts"]["warnings"] += len(findings)
            report["contextual"] = {"status": "completed", "input": "slide_images"}
        if contextual:
            findings = await contextual_audit(record["deck"], record["sources"])
            report["issues"].extend(findings)
            report["counts"]["warnings"] += len(findings)
            report["contextual"] = {"status": "completed", "input": "structured_text"}
        # Отчёт собран заново, поэтому проверки самого файла нужно вернуть: иначе
        # повторный аудит «терял» находки, которые видны только в pptx.
        merge_file_issues(report, record.get("export_check") or {})
        with store.lock:
            current = store.get("presentations", presentation_id)
            if current["revision"] != record["revision"]:
                raise HTTPException(409, "Presentation changed during audit; retry")
            # Keep the other model check for this revision. Re-running a mode
            # replaces its findings instead of accumulating them. Read under the
            # lock so concurrent text/image checks do not overwrite each other.
            retained = [
                copy.deepcopy(issue)
                for issue in current.get("audit", {}).get("issues", [])
                if issue.get("category") == "contextual"
                and not (visual if issue.get("element_id") == "slide_image" else contextual)
            ]
            report["issues"].extend(retained)
            report["counts"] = {
                "errors": sum(i["severity"] == "error" for i in report["issues"]),
                "warnings": sum(i["severity"] != "error" for i in report["issues"]),
            }
            if retained and not (contextual or visual) and "contextual" in current.get("audit", {}):
                report["contextual"] = copy.deepcopy(current["audit"]["contextual"])
            current["audit"] = report
            store.put("presentations", current)
        return {"revision": record["revision"], **report}

    def save_revision(record):
        template = store.get("templates", record["template_id"])
        record["revision"] += 1
        record["audit"] = audit(
            record["deck"],
            template,
            record["sources"],
            record.get("generation", {}).get("language"),
        )
        folder = store.directory("presentations", record["id"])
        target = folder / f"r{record['revision']}.pptx"
        source = store.directory("templates", template["id"]) / "source.pptx"
        export_pptx(source, template, record["deck"], target, store.root)
        check = verify_pptx(target, len(record["deck"]["slides"]))
        check["moved_branding"] = branding_drift(source, record["deck"], target)
        record["export_check"] = check
        merge_file_issues(record["audit"], check)
        store.put(
            "revisions",
            {
                **copy.deepcopy(record),
                "id": record["id"] + "_" + str(record["revision"]),
            },
        )
        return public_presentation(store.put("presentations", record))

    @api.post("/presentations/{presentation_id}/fixes", tags=["Audit"])
    def fixes(presentation_id: str, request: FixRequest):
        with store.lock:
            record = store.get("presentations", presentation_id)
            if record["revision"] != request.revision:
                raise HTTPException(409, "Stale revision; reload presentation")
            try:
                record["deck"] = apply_fixes(
                    record["deck"],
                    record["audit"],
                    request.issue_ids,
                    store.get("templates", record["template_id"]),
                )
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            return save_revision(record)

    @api.patch(
        "/presentations/{presentation_id}/slides/{index}", tags=["Presentations"]
    )
    def edit_slide(presentation_id: str, index: int, request: SlideEdit):
        with store.lock:
            record = store.get("presentations", presentation_id)
            if record["revision"] != request.revision:
                raise HTTPException(409, "Stale revision; reload presentation")
            if not 0 <= index < len(record["deck"]["slides"]):
                raise HTTPException(404, "Slide not found")
            outline = {"slides": [s["content"] for s in record["deck"]["slides"]]}
            outline["slides"][index] = request.content.model_dump()
            template = store.get("templates", record["template_id"])
            rebuilt = compose(
                outline,
                template,
                record["variant"],
                deck_library(
                    template,
                    record.get("content_pack_ids"),
                    stored_illustrations(record.get("illustrations_id")),
                ),
            )
            record["deck"]["slides"][index] = rebuilt["slides"][index]
            return save_revision(record)

    @api.get("/presentations/{presentation_id}/export/{format}", tags=["Export"])
    def export(
        presentation_id: str,
        format: Literal["pptx", "pdf", "html"],
        revision: int | None = Query(None, ge=1),
    ):
        record = store.get("presentations", presentation_id)
        rev = revision or record["revision"]
        folder = store.directory("presentations", presentation_id)
        source = folder / f"r{rev}.pptx"
        if not source.exists():
            raise HTTPException(404, "Revision not found")
        output = folder / f"r{rev}.{format}"
        # The standalone server deliberately runs one worker. Lock protects concurrent conversions.
        with store.lock:
            cached = output.exists()
            if cached and format == 'html':
                with output.open(encoding='utf-8') as saved:
                    cached = HTML_EXPORT_MARKER in saved.read(256)
            if not cached:
                try:
                    pdf = folder / f"r{rev}.pdf"
                    if not pdf.exists():
                        convert_pdf(source, pdf)
                    if format == "html":
                        export_html(pdf, output, record["title"],
                                    language=(record.get("generation") or {}).get("language", "ru"))
                except (RuntimeError, TimeoutError, subprocess.TimeoutExpired) as exc:
                    raise HTTPException(503, str(exc)) from exc
        return FileResponse(
            output,
            media_type={
                "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                "pdf": "application/pdf",
                "html": "text/html",
            }[format],
            filename=f"{record['variant']}-r{rev}.{format}",
        )

    @api.get("/presentations/{presentation_id}/slides/{index}/preview", tags=["Audit"])
    def preview(presentation_id: str, index: int, highlight: bool = False):
        import html

        import pymupdf

        record = store.get("presentations", presentation_id)
        if not 0 <= index < len(record["deck"]["slides"]):
            raise HTTPException(404, "Slide not found")
        folder = store.directory("presentations", presentation_id)
        pdf = folder / f"r{record['revision']}.pdf"
        with store.lock:
            if not pdf.exists():
                try:
                    convert_pdf(folder / f"r{record['revision']}.pptx", pdf)
                except (RuntimeError, subprocess.TimeoutExpired) as exc:
                    raise HTTPException(503, str(exc)) from exc
        with pymupdf.open(pdf) as document:
            page = document[index]
            svg = page.get_svg_image(text_as_path=True)
            sx, sy = (
                page.rect.width / record["deck"]["width"],
                page.rect.height / record["deck"]["height"],
            )
        if highlight:
            boxes = []
            for finding in record["audit"]["issues"]:
                if finding["slide_index"] != index or not finding["box"]:
                    continue
                x, y, w, h = finding["box"]
                boxes.append(
                    f'<rect x="{x * sx}" y="{y * sy}" width="{w * sx}" height="{h * sy}" fill="red" fill-opacity="0.12" stroke="red" stroke-width="2"><title>{html.escape(finding["message"])}</title></rect>'
                )
            svg = svg.replace("</svg>", "".join(boxes) + "</svg>")
        return Response(
            svg,
            media_type="image/svg+xml",
            headers={"X-Presentation-Revision": str(record["revision"])},
        )

    app.include_router(api)
    return app
