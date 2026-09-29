"""Regressions from the 27 September decks: sources, native charts and honest audits."""

import asyncio
import json

import pytest
from fastapi import HTTPException

from designer.comparisons import add_comparison_charts
from designer.models import Outline
from tests.test_pipeline import client, outline, template_bytes, wait_job


def comparison_outline(text="Сборка занимает 4 минуты вместо 186"):
    return Outline.model_validate({"title": "Результаты", "slides": [
        {"title": "Результаты пилота"},
        {"title": "Сборка презентации ускорилась", "bullets": [text], "source_refs": ["material"]},
    ]})


def test_before_after_chart_is_native_and_preserves_source_direction(tmp_path):
    from designer.exporting import export_pptx, verify_pptx
    from designer.layout import compose
    from designer.parsing import parse_template
    from tests.test_pipeline import template_bytes

    plan = add_comparison_charts(comparison_outline(), [{"id": "material", "text": "Средняя сборка — 4 минуты вместо 186."}])
    chart = plan.slides[1].visual
    assert chart.kind == "bar" and chart.unit == "мин"
    assert chart.categories == ["До", "После"]
    assert chart.series[0].values == [186, 4]
    raw = template_bytes()
    source = tmp_path / "unknown.pptx"
    source.write_bytes(raw)
    template = parse_template(raw, "unknown.pptx")
    for variant in ("classic", "split", "focus"):
        deck = compose(plan.model_dump(), template, variant)
        target = tmp_path / f"{variant}.pptx"
        export_pptx(source, template, deck, target)
        checked = verify_pptx(target, 2)
        assert len(checked["charts"]) == 1
        assert checked["charts"][0]["value_labels"]
        assert not checked["raster_slides"]


@pytest.mark.parametrize("source,text", [
    ("Сборка — 186 минут вместо 4.", "Сборка — 4 минуты вместо 186"),
    ("Сборка — 4 минуты вместо 186 секунд.", "Сборка — 4 минуты вместо 186"),
    ("Стоимость 186 рублей, время 4 минуты.", "Сборка — 4 минуты вместо 186"),
    ("38 запросов за 6 недель; 11 запросов в неделю.", "Закрыли 38 запросов вместо 11"),
    ("Сборка — 4 минуты вместо 186.", "Сборка — 5 минут вместо 186"),
    ("Сборка — 4 минуты вместо 186.", "Сборка — 4 минуты вместо 186 секунд"),
])
def test_ambiguous_or_invented_comparison_is_not_turned_into_a_chart(source, text):
    result = add_comparison_charts(comparison_outline(text), [{"id": "material", "text": source}])
    assert result.slides[1].visual.kind == "none"


def test_chart_requires_the_cited_source_and_does_not_replace_a_visual():
    result = add_comparison_charts(comparison_outline(), [{"id": "another", "text": "4 минуты вместо 186"}])
    assert result.slides[1].visual.kind == "none"
    result.slides[1].visual.kind = "icon"
    result.slides[1].visual.steps = ["Сборка"]
    result = add_comparison_charts(result, [{"id": "material", "text": "4 минуты вместо 186"}])
    assert result.slides[1].visual.kind == "icon"


def test_content_audit_retries_incomplete_review_and_counts_unsupported_claims(monkeypatch):
    from designer import generation
    from designer.audit import contextual_audit

    slides = [{"content": {"title": title, "bullets": [], "visual": {"kind": "none"}}} for title in [
        "Пилотный запуск можно реализовать в течение нескольких месяцев",
        "Нужно принять решение о запуске и выделить бюджет",
        "Для внедрения требуется IT-ресурсы",
    ]]
    answers = [
        {"issues": []},
        {"checked_slide_indices": [0, 1, 2], "issues": [
            {"slide_index": 0, "code": "unsupported_fact", "message": "В источнике нет срока пилота"},
            {"slide_index": 1, "code": "unsupported_fact", "message": "Источник не запрашивает бюджет"},
            {"slide_index": 2, "code": "typo", "message": "Нужно «требуются IT-ресурсы»"},
        ]},
    ]
    calls = []

    async def ask(messages):
        calls.append(messages)
        return json.dumps(answers.pop(0))

    monkeypatch.setattr(generation, "ask", ask)
    monkeypatch.setattr(generation, "RETRY_DELAY", 0)
    found = asyncio.run(contextual_audit({"slides": slides}, [{"id": "brief", "text": "Вики-система обеспечивает обмен информацией"}]))
    assert len(calls) == 2
    assert len(found) == 3 and all(f["severity"] == "error" for f in found)
    assert not any(f["fixable"] for f in found)


@pytest.mark.parametrize("answer", [
    {"checked_slide_indices": [], "issues": []},
    {"checked_slide_indices": [True], "issues": []},
    {"checked_slide_indices": [0, 0], "issues": []},
    {"checked_slide_indices": [0], "issues": [{"slide_index": 9, "code": "typo", "message": "x"}]},
    {"checked_slide_indices": [0], "issues": [{"slide_index": 0, "code": "typo", "message": ""}]},
])
def test_invalid_text_audit_is_never_clean(monkeypatch, answer):
    from designer import generation
    from designer.audit import contextual_audit

    async def ask(messages):
        return json.dumps(answer)

    monkeypatch.setattr(generation, "ask", ask)
    monkeypatch.setattr(generation, "RETRY_DELAY", 0)
    with pytest.raises(HTTPException) as failure:
        asyncio.run(contextual_audit({"slides": [{"content": {"title": "Текст"}}]}, []))
    assert failure.value.status_code == 502


@pytest.mark.parametrize("answer", [None, {}, {"issues": None}, {"issues": ["garbage"]}])
def test_invalid_visual_audit_fails_instead_of_returning_zero_issues(monkeypatch, answer):
    import designer.audit as module

    async def vision(*args):
        return answer

    monkeypatch.setattr(module, "vision_completion", vision)
    deck = {"slides": [{"content": {"title": "Текст", "bullets": [], "visual": {"kind": "none"}}}]}
    with pytest.raises(HTTPException):
        asyncio.run(module.visual_audit(deck, [], [b"PNG"]))
    with pytest.raises(HTTPException):
        asyncio.run(module.visual_audit(deck, [], []))


def test_generation_exposes_content_errors_in_all_three_reports(client, monkeypatch):
    import designer.app as module
    from designer.audit import issue

    monkeypatch.setenv("DESIGNER_LLM_BASE_URL", "https://inference.example/v1")
    monkeypatch.setenv("DESIGNER_LLM_MODEL", "test-open-model")

    async def findings(*args):
        return [issue(0, "context_0", "unsupported_fact", "В источнике нет срока", category="contextual", severity="error")]

    monkeypatch.setattr(module, "contextual_audit", findings)
    template = client.post("/api/v1/templates", files={"file": ("unknown.pptx", template_bytes())}).json()
    response = client.post("/api/v1/generations", json={
        "template_id": template["id"], "brief": "Данные 10 и 20", "slide_count": 3,
        "outline": outline(), "contextual_audit": True,
    })
    assert response.status_code == 202
    job = wait_job(client, response.json()["id"])
    for identifier in job["presentation_ids"]:
        report = client.get(f"/api/v1/presentations/{identifier}/audit").json()
        assert report["counts"]["errors"] >= 1
        assert report["counts"]["errors"] == sum(i["severity"] == "error" for i in report["issues"])
        assert report["counts"]["warnings"] == sum(i["severity"] != "error" for i in report["issues"])


def test_failed_visual_review_preserves_existing_report(client, monkeypatch):
    import designer.app as module
    from tests.test_pipeline import generate

    _, job = generate(client)
    identifier = job["presentation_ids"][0]
    before = client.get(f"/api/v1/presentations/{identifier}/audit").json()

    async def fail(*args):
        raise HTTPException(502, "Не удалось проверить слайд")

    monkeypatch.setattr(module, "convert_pdf", lambda *args: None)
    monkeypatch.setattr(module, "render_slides", lambda *args: [b"PNG"] * 3)
    monkeypatch.setattr(module, "visual_audit", fail)
    result = client.post(f"/api/v1/presentations/{identifier}/audit?visual=true")
    assert result.status_code == 502
    after = client.get(f"/api/v1/presentations/{identifier}/audit").json()
    assert after == before


def test_visual_audit_marks_source_context_limits(monkeypatch):
    import designer.audit as module

    seen = []

    async def vision(prompt, payload, image):
        seen.append(payload)
        return {"issues": []}

    monkeypatch.setattr(module, "vision_completion", vision)
    noise = ("Материалы о парковке. " * 100 + "\n\n") * 15
    sources = [{"id": "material", "text": noise + "Сборка презентаций сократилась с 186 до 4 минут."}]
    deck = {"slides": [{"content": comparison_outline().slides[1].model_dump()}]}
    found = asyncio.run(module.visual_audit(deck, sources, [b"PNG"]))
    assert seen[0]["source_context_complete"] is False
    assert "186 до 4" in seen[0]["sources"][0]["text"]
    assert sum(len(s["text"]) for s in seen[0]["sources"]) <= 8000
    assert [i["code"] for i in found] == ["source_context_incomplete"]
