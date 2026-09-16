import io
import os
import time
import zipfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from pptx import Presentation
from designer.app import create_app
from designer.audit import audit
from designer.layout import compose
from designer.models import Visual
from designer.parsing import parse_template

# Corporate templates are not committed: they belong to the case organisers.
# Point DESIGNER_TEMPLATE_DIR at a folder with .pptx files, or drop them into
# <repo>/templates. Tests that need real templates skip when the folder is empty.
TEMPLATES = Path(
    os.getenv("DESIGNER_TEMPLATE_DIR")
    or Path(__file__).resolve().parents[2] / "templates"
)


def sample_templates():
    return sorted(TEMPLATES.glob("*.pptx")) if TEMPLATES.is_dir() else []


def require_template(name_hint=""):
    files = sample_templates()
    if not files:
        pytest.skip(f"No .pptx templates in {TEMPLATES}")
    for path in files:
        if name_hint and name_hint.lower() in path.stem.lower():
            return path
    return files[0]


def template_bytes():
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[1])
    slide.shapes.title.text = "Sample title"
    slide.placeholders[1].text = "Sample content"
    out = io.BytesIO()
    deck.save(out)
    return out.getvalue()


def outline(count=3):
    return {
        "title": "Проверка пайплайна",
        "slides": [
            {
                "title": f"Вывод {i + 1}",
                "bullets": ["Первый тезис", "Второй тезис"],
                "source_refs": ["brief"],
                "visual": visual,
            }
            for i, visual in enumerate(
                [
                    {
                        "kind": "bar",
                        "categories": ["А", "Б"],
                        "series": [{"name": "Продажи", "values": [10, 20]}],
                        "unit": "млн руб.",
                    },
                    {
                        "kind": "table",
                        "columns": ["Этап", "Срок"],
                        "rows": [["А", "10"], ["Б", "20"]],
                    },
                    {"kind": "process", "steps": ["План", "Работа", "Итог"]},
                ][:count]
            )
        ],
    }


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("DESIGNER_API_KEY", raising=False)
    with TestClient(create_app(tmp_path)) as c:
        yield c


def wait_job(client, identifier):
    for _ in range(200):
        job = client.get("/api/v1/jobs/" + identifier).json()
        if job["status"] in ("completed", "failed"):
            assert job["status"] == "completed", job
            return job
        time.sleep(0.05)
    pytest.fail("generation timed out")


def generate(client, data=None):
    response = client.post(
        "/api/v1/templates", files={"file": ("template.pptx", data or template_bytes())}
    )
    assert response.status_code == 201, response.text
    template = response.json()
    response = client.post(
        "/api/v1/generations",
        json={
            "template_id": template["id"],
            "brief": "Первый тезис. Второй тезис. Продажи А 10 Б 20 млн руб. План Работа Итог. Выводы 1 2 3.",
            "slide_count": 3,
            "outline": outline(),
        },
    )
    assert response.status_code == 202, response.text
    return template, wait_job(client, response.json()["id"])


def test_end_to_end_native_variants_and_revision(client):
    template, job = generate(client)
    assert len(job["presentation_ids"]) == 3
    positions = []
    for identifier in job["presentation_ids"]:
        record = client.get("/api/v1/presentations/" + identifier).json()
        positions.append([e["box"] for e in record["deck"]["slides"][0]["elements"]])
        response = client.get(record["exports"]["pptx"])
        assert response.status_code == 200
        deck = Presentation(io.BytesIO(response.content))
        assert len(deck.slides) == 3
        assert any(s.has_chart for s in deck.slides[0].shapes)
        assert any(s.has_table for s in deck.slides[1].shapes)
        assert any(
            s.has_text_frame and "Вывод" in s.text for s in deck.slides[0].shapes
        )
        assert "Sample content" not in "\n".join(
            s.text for slide in deck.slides for s in slide.shapes if s.has_text_frame
        )
    assert len({str(p) for p in positions}) == 3
    identifier = job["presentation_ids"][0]
    response = client.patch(
        f"/api/v1/presentations/{identifier}/slides/0",
        json={
            "revision": 1,
            "content": {
                "title": "Новый вывод",
                "bullets": ["Подтвержденный тезис"],
                "source_refs": ["brief"],
            },
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["revision"] == 2
    assert (
        client.patch(
            f"/api/v1/presentations/{identifier}/slides/0",
            json={"revision": 1, "content": {"title": "Конфликт"}},
        ).status_code
        == 409
    )
    old = client.get(f"/api/v1/presentations/{identifier}/export/pptx?revision=1")
    assert old.status_code == 200
    assert (
        client.get(
            f"/api/v1/presentations/{identifier}/export/pptx?revision=999"
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "path", sample_templates(), ids=lambda p: p.stem
)
def test_supplied_templates(client, path):
    template, job = generate(client, path.read_bytes())
    assert template["tokens"]["colors"]
    assert template["patterns"]
    for identifier in job["presentation_ids"]:
        response = client.get(f"/api/v1/presentations/{identifier}/export/pptx")
        deck = Presentation(io.BytesIO(response.content))
        assert len(deck.slides) == 3
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            assert archive.testzip() is None


def test_content_upload_invalid_inputs_and_dedup(client, monkeypatch):
    data = template_bytes()
    a = client.post("/api/v1/templates", files={"file": ("a.pptx", data)}).json()
    b = client.post("/api/v1/templates", files={"file": ("b.pptx", data)}).json()
    assert a["id"] == b["id"]
    assert (
        client.post(
            "/api/v1/templates", files={"file": ("x.pptx", b"broken")}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/content-packs", files={"file": ("source.csv", "name,value\nA,10")}
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/v1/content-packs", files={"file": ("source.txt", b"")}
        ).status_code
        == 422
    )
    assert client.get("/api/v1/templates/unknown").status_code == 404
    monkeypatch.delenv("DESIGNER_LLM_BASE_URL", raising=False)
    assert (
        client.post(
            "/api/v1/generations", json={"template_id": a["id"], "brief": "test brief"}
        ).status_code
        == 503
    )
    assert (
        client.post(
            "/api/v1/generations",
            json={
                "template_id": a["id"],
                "brief": "test brief",
                "slide_count": 2,
                "outline": outline(),
            },
        ).status_code
        == 422
    )


def test_selective_fixes(client):
    _, job = generate(client)
    identifier = job["presentation_ids"][0]
    store = client.app.state.store
    record = store.get("presentations", identifier)
    record["deck"]["slides"][0]["elements"][0]["box"][0] = -100
    record["deck"]["slides"][1]["elements"][0]["box"][0] = -100
    record["audit"] = audit(
        record["deck"], store.get("templates", record["template_id"]), record["sources"]
    )
    store.put("presentations", record)
    findings = [i for i in record["audit"]["issues"] if i["code"] == "out_of_bounds"]
    response = client.post(
        f"/api/v1/presentations/{identifier}/fixes",
        json={"revision": 1, "issue_ids": [findings[0]["id"]]},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["deck"]["slides"][0]["elements"][0]["box"][0] == 0
    assert data["deck"]["slides"][1]["elements"][0]["box"][0] == -100
    assert (
        client.post(
            f"/api/v1/presentations/{identifier}/fixes",
            json={"revision": 2, "issue_ids": ["unknown"]},
        ).status_code
        == 422
    )


def test_auth_cors_and_recovery(tmp_path, monkeypatch):
    monkeypatch.setenv("DESIGNER_API_KEY", "test-token")
    app = create_app(tmp_path)
    app.state.store.put("jobs", {"id": "a" * 32, "status": "running"})
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/v1/templates").status_code == 401
        assert (
            client.get(
                "/api/v1/templates", headers={"Authorization": "Bearer test-token"}
            ).status_code
            == 200
        )
        response = client.options(
            "/api/v1/generations",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization,Content-Type",
            },
        )
        assert response.status_code == 200
        assert (
            response.headers["access-control-allow-origin"] == "http://localhost:3000"
        )
        assert app.state.store.get("jobs", "a" * 32)["status"] == "failed"


def test_visual_validation():
    with pytest.raises(ValueError):
        Visual(
            kind="bar",
            categories=["A"],
            series=[{"name": "x", "values": [1, 2]}],
            unit="units",
        )
    with pytest.raises(ValueError):
        Visual(kind="table", columns=["A"], rows=[["1", "2"]])


def test_openapi(client):
    spec = client.get("/openapi.json").json()
    assert "/api/v1/generations" in spec["paths"]
    assert "/api/v1/presentations/{presentation_id}/fixes" in spec["paths"]


def test_provider_contract_and_failures(client, monkeypatch):
    import httpx
    from designer import generation

    monkeypatch.setenv("DESIGNER_LLM_BASE_URL", "https://inference.example/v1")
    monkeypatch.setenv("DESIGNER_LLM_MODEL", "test-open-model")
    captured = []
    real_client = httpx.AsyncClient

    def handler(request):
        import json

        payload = json.loads(request.content)
        captured.append(payload)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(outline())}}]}
        )

    monkeypatch.setattr(
        generation.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    response = client.post(
        "/api/v1/outlines", json={"brief": "Данные: 10 и 20", "slide_count": 3}
    )
    assert response.status_code == 200, response.text
    assert len(response.json()["slides"]) == 3
    assert captured[0]["model"] == "test-open-model"
    assert captured[0]["response_format"] == {"type": "json_object"}
    response = client.post(
        "/api/v1/outlines", json={"brief": "Данные: 10 и 20", "slide_count": 4}
    )
    assert response.status_code == 502

    def bad_handler(request):
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "not json"}}]}
        )

    monkeypatch.setattr(
        generation.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            transport=httpx.MockTransport(bad_handler), **kwargs
        ),
    )
    assert (
        client.post(
            "/api/v1/outlines", json={"brief": "Данные для проверки"}
        ).status_code
        == 502
    )


def test_failed_generation_visible(client, monkeypatch):
    from designer import app as module

    monkeypatch.setenv("DESIGNER_LLM_BASE_URL", "https://inference.example/v1")
    monkeypatch.setenv("DESIGNER_LLM_MODEL", "test-open-model")

    async def fail(*args):
        raise RuntimeError("provider disconnected")

    monkeypatch.setattr(module, "generate_outline", fail)
    template = client.post(
        "/api/v1/templates", files={"file": ("template.pptx", template_bytes())}
    ).json()
    job = client.post(
        "/api/v1/generations",
        json={"template_id": template["id"], "brief": "Проверка ошибки"},
    ).json()
    for _ in range(50):
        result = client.get("/api/v1/jobs/" + job["id"]).json()
        if result["status"] == "failed":
            break
        time.sleep(0.02)
    assert result["status"] == "failed"
    assert result["error"]


def test_pdf_html_export(client):
    if not client.get("/health").json()["pdf_available"]:
        pytest.skip("LibreOffice not installed")
    _, job = generate(client)
    identifier = job["presentation_ids"][0]
    response = client.get(f"/api/v1/presentations/{identifier}/export/pdf")
    assert response.status_code == 200, response.text
    from pypdf import PdfReader

    assert len(PdfReader(io.BytesIO(response.content)).pages) == 3
    response = client.get(f"/api/v1/presentations/{identifier}/export/html")
    assert response.status_code == 200, response.text
    assert response.text.count('<section class="slide">') == 3
    assert "<svg" in response.text
    response = client.get(
        f"/api/v1/presentations/{identifier}/slides/0/preview?highlight=true"
    )
    assert response.status_code == 200, response.text
    assert "image/svg+xml" in response.headers["content-type"]
    assert response.headers["x-presentation-revision"] == "1"


def test_twelve_slide_target(client):
    from copy import deepcopy

    template = client.post(
        "/api/v1/templates", files={"file": ("unknown.pptx", template_bytes())}
    ).json()
    contents = outline()
    contents["slides"] = [deepcopy(contents["slides"][i % 3]) for i in range(12)]
    for i, slide in enumerate(contents["slides"]):
        slide["title"] = f"Уникальный вывод {i + 1}"
    response = client.post(
        "/api/v1/generations",
        json={
            "template_id": template["id"],
            "brief": "Источник: 10, 20. Тестовые данные.",
            "slide_count": 12,
            "outline": contents,
        },
    )
    job = wait_job(client, response.json()["id"])
    assert len(job["presentation_ids"]) == 3
    for identifier in job["presentation_ids"]:
        response = client.get(f"/api/v1/presentations/{identifier}/export/pptx")
        assert len(Presentation(io.BytesIO(response.content)).slides) == 12


def test_dark_template_color_and_title_geometry():
    from designer.parsing import best_text_color

    assert best_text_color("000000", ["FFFFFF", "000000", "0077FF"]) == "FFFFFF"
    template = parse_template(template_bytes(), "unknown.pptx")
    content = outline(1)
    content["slides"][0]["title"] = (
        "Длинный заголовок должен помещаться в рамку и не накладываться на основной текст"
    )
    from designer.models import Outline

    deck = compose(Outline.model_validate(content).model_dump(), template, "classic")
    title = deck["slides"][0]["elements"][0]
    body = deck["slides"][0]["elements"][1]
    assert title["box"][1] + title["box"][3] < body["box"][1]


def test_contextual_audit_inside_generation(client, monkeypatch):
    from designer import app as module

    monkeypatch.setenv("DESIGNER_LLM_BASE_URL", "https://inference.example/v1")
    monkeypatch.setenv("DESIGNER_LLM_MODEL", "test-open-model")
    called = []

    async def fake_audit(deck, sources):
        from designer.audit import issue

        called.append(deck)
        return [
            issue(
                0,
                "context_0",
                "title_mismatch",
                "Проверить заголовок",
                category="contextual",
            )
        ]

    monkeypatch.setattr(module, "contextual_audit", fake_audit)
    template = client.post(
        "/api/v1/templates", files={"file": ("template.pptx", template_bytes())}
    ).json()
    response = client.post(
        "/api/v1/generations",
        json={
            "template_id": template["id"],
            "brief": "Данные 10 и 20",
            "slide_count": 3,
            "outline": outline(),
            "contextual_audit": True,
        },
    )
    assert response.status_code == 202
    job = wait_job(client, response.json()["id"])
    assert len(called) == 1
    for identifier in job["presentation_ids"]:
        report = client.get(f"/api/v1/presentations/{identifier}/audit").json()
        assert report["contextual"]["status"] == "completed"
        assert any(i["category"] == "contextual" for i in report["issues"])


def audited(template, slide_mutator=None, content_mutator=None, count=1):
    """Compose a deck from an unknown template, break it on purpose, then audit."""
    from designer.models import Outline

    content = outline(count)
    if content_mutator:
        content_mutator(content)
    deck = compose(Outline.model_validate(content).model_dump(), template, "classic")
    if slide_mutator:
        slide_mutator(deck["slides"][0])
    report = audit(deck, template, [{"id": "brief", "text": "Первый тезис 10 20"}])
    return deck, report, {i["code"] for i in report["issues"]}


def test_clean_deck_on_supplied_templates_has_no_layout_findings():
    """The checks must stay quiet on decks the service itself composed."""
    noisy = {
        "out_of_bounds",
        "margin_encroachment",
        "misaligned",
        "branding_overlap",
        "low_contrast",
        "font_not_in_template",
        "font_size_off_scale",
        "color_not_in_palette",
        "font_variety",
        "layout_not_from_template",
        "text_overflow",
    }
    for path in sample_templates() or pytest.skip(f"No .pptx templates in {TEMPLATES}"):
        template = parse_template(path.read_bytes(), path.name)
        for variant in ("classic", "split", "focus"):
            from designer.models import Outline

            deck = compose(
                Outline.model_validate(outline(3)).model_dump(), template, variant
            )
            report = audit(deck, template, [{"id": "brief", "text": "Первый тезис"}])
            found = {i["code"] for i in report["issues"]} & noisy
            assert not found, (path.name, variant, found)


def test_layout_checks_fire_on_broken_geometry():
    template = parse_template(template_bytes(), "unknown.pptx")

    def off_slide(slide):
        slide["elements"][0]["box"][1] = -80

    assert "out_of_bounds" in audited(template, off_slide)[2]

    def into_margin(slide):
        slide["elements"][0]["box"][0] = 1.0

    codes = audited(template, into_margin)[2]
    assert "margin_encroachment" in codes and "out_of_bounds" not in codes

    def nudged(slide):
        slide["elements"][1]["box"][0] += 17

    assert "misaligned" in audited(template, nudged)[2]


def test_template_token_checks_fire():
    # A real template carries a type scale; the synthetic one has none, and the
    # check correctly stays silent when the template defines no sizes.
    branded = parse_template(
        require_template("VK Tech").read_bytes(), "vk.pptx"
    )
    assert branded["tokens"]["font_sizes"]

    def off_scale(slide):
        slide["elements"][0]["font_size"] = 37.5

    assert "font_size_off_scale" in audited(branded, off_scale)[2]
    assert "font_size_off_scale" not in audited(branded)[2]

    template = parse_template(template_bytes(), "unknown.pptx")

    def off_palette(slide):
        slide["elements"][0]["color"] = "123456"

    assert "color_not_in_palette" in audited(template, off_palette)[2]

    def unreadable(slide):
        slide["background"], slide["elements"][0]["color"] = "FFFFFF", "FEFEFE"

    assert "low_contrast" in audited(template, unreadable)[2]

    def third_font(slide):
        slide["elements"][0]["font"] = "Comic Sans MS"
        slide["elements"][1]["font"] = "Courier New"

    # Two replaced fonts plus the base font on the other slides make three families.
    assert "font_variety" in audited(template, third_font, count=3)[2]

    def foreign_layout(slide):
        slide["layout_index"] = 99

    assert "layout_not_from_template" in audited(template, foreign_layout)[2]


def test_density_and_chart_checks_fire():
    template = parse_template(template_bytes(), "unknown.pptx")

    def wide_table(content):
        content["slides"][0]["visual"] = {
            "kind": "table",
            "columns": [f"К{i}" for i in range(6)],
            "rows": [[f"з{i}" for i in range(6)] for _ in range(8)],
        }

    assert "table_size" in audited(template, content_mutator=wide_table)[2]

    def many_series(content):
        content["slides"][0]["visual"] = {
            "kind": "bar",
            "categories": ["А", "Б"],
            "series": [{"name": f"С{i}", "values": [1, 2]} for i in range(6)],
            "unit": "шт.",
        }

    assert "chart_series" in audited(template, content_mutator=many_series)[2]

    def unlabelled(content):
        content["slides"][0]["visual"] = {
            "kind": "bar",
            "categories": ["А", "Б"],
            "series": [{"name": "С", "values": [1, 2]}],
        }

    assert "chart_labels" in audited(template, content_mutator=unlabelled)[2]

    def sparse(content):
        content["slides"][0]["bullets"] = ["Мало"]
        content["slides"][0]["visual"] = {"kind": "none"}

    assert "fill_ratio" in audited(template, content_mutator=sparse)[2]


def test_new_fixes_repair_the_deck():
    from designer.audit import apply_fixes

    template = parse_template(template_bytes(), "unknown.pptx")

    def broken(slide):
        slide["elements"][0]["box"][0] = 1.0
        slide["elements"][0]["font_size"] = 37.5
        slide["elements"][0]["color"] = "123456"
        slide["elements"][1]["box"][0] += 17

    deck, report, codes = audited(template, broken)
    repairable = ("margin_encroachment", "font_size_off_scale", "color_not_in_palette")
    selected = [i["id"] for i in report["issues"] if i["code"] in repairable]
    assert {"margin_encroachment", "color_not_in_palette", "misaligned"} <= codes
    fixed = apply_fixes(deck, report, selected, template)
    element = fixed["slides"][0]["elements"][0]
    assert element["box"][0] > 1.0
    assert element["color"] in template["tokens"]["colors"]
    after = audit(fixed, template, [{"id": "brief", "text": "x"}])
    assert not [
        i
        for i in after["issues"]
        if i["code"] == "margin_encroachment" and i["element_id"] == "title"
    ]
    # An unselected finding must survive: the user chooses what gets changed.
    assert [i for i in after["issues"] if i["code"] == "misaligned"]


def test_export_verification_proves_native_objects(client):
    _, job = generate(client)
    record = client.app.state.store.get("presentations", job["presentation_ids"][0])
    check = record["export_check"]
    assert check["opens"] and check["slides"] == 3
    assert check["native_objects"] >= 3 and check["raster_slides"] == []


def test_base_path_makes_urls_proxy_safe(tmp_path, monkeypatch):
    """Behind a reverse proxy sub-path, returned URLs must carry the prefix."""
    monkeypatch.setenv("DESIGNER_BASE_PATH", "/presentations")
    monkeypatch.delenv("DESIGNER_API_KEY", raising=False)
    with TestClient(create_app(tmp_path)) as client:
        template = client.post(
            "/api/v1/templates", files={"file": ("t.pptx", template_bytes())}
        ).json()
        accepted = client.post(
            "/api/v1/generations",
            json={
                "template_id": template["id"],
                "brief": "Первый тезис. Второй тезис. Продажи А 10 Б 20 млн руб.",
                "slide_count": 3,
                "outline": outline(),
            },
        )
        assert accepted.status_code == 202, accepted.text
        # status_url is only returned by the 202 response, not by the job resource.
        assert accepted.json()["status_url"].startswith("/presentations/api/v1/jobs/")
        job = wait_job(client, accepted.json()["id"])
        record = client.get(
            "/api/v1/presentations/" + job["presentation_ids"][0]
        ).json()
        for url in record["exports"].values():
            assert url.startswith("/presentations/api/v1/presentations/")
        assert client.get("/openapi.json").json()["servers"] == [
            {"url": "/presentations"}
        ]
