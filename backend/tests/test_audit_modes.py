"""Model audit results coexist within a presentation revision."""

import pytest
from tests.test_pipeline import client, generate  # client is the shared API fixture


@pytest.mark.parametrize("first,second", [("contextual", "visual"), ("visual", "contextual"), ("contextual=true&visual", "contextual=true&visual")])
def test_model_audits_keep_other_mode_and_replace_own_findings(client, monkeypatch, first, second):
    import designer.app as module
    from designer.audit import issue

    _, job = generate(client)
    identifier = job["presentation_ids"][0]
    calls = {"text": 0, "image": 0}

    async def text_audit(*args):
        calls["text"] += 1
        return [issue(0, "context_0", "content", f"text-{calls['text']}", category="contextual")]

    async def image_audit(*args):
        calls["image"] += 1
        return [issue(0, "slide_image", "alignment", f"image-{calls['image']}", category="contextual")]

    monkeypatch.setattr(module, "contextual_audit", text_audit)
    monkeypatch.setattr(module, "visual_audit", image_audit)
    monkeypatch.setattr(module, "convert_pdf", lambda *args: None)
    monkeypatch.setattr(module, "render_slides", lambda *args: [b"PNG"])
    store = client.app.state.store
    record = store.get("presentations", identifier)
    record["export_check"] = {"opens": True, "raster_slides": [0], "charts": []}
    store.put("presentations", record)

    for mode in (first, second, second):
        response = client.post(f"/api/v1/presentations/{identifier}/audit?{mode}=true")
        assert response.status_code == 200, response.text
    report = response.json()
    model_issues = [i for i in report["issues"] if i.get("category") == "contextual"]
    assert sorted(i["message"] for i in model_issues) == sorted([f"text-{calls['text']}", f"image-{calls['image']}"])
    assert "raster_slide" in {i["code"] for i in report["issues"]}
    assert report["counts"]["warnings"] == sum(i["severity"] == "warning" for i in report["issues"])
    assert report["counts"]["errors"] == sum(i["severity"] == "error" for i in report["issues"])
    rules_only = client.post(f"/api/v1/presentations/{identifier}/audit").json()
    assert [i for i in rules_only["issues"] if i.get("category") == "contextual"] == model_issues
    assert rules_only["contextual"]["status"] == "completed"

    # Editing creates a new revision, so model findings for old content expire.
    content = client.get(f"/api/v1/presentations/{identifier}").json()["deck"]["slides"][0]["content"]
    content["title"] = "Обновлённый заголовок"
    edited = client.patch(f"/api/v1/presentations/{identifier}/slides/0", json={"revision": report["revision"], "content": content})
    assert edited.status_code == 200, edited.text
    assert not any(i.get("category") == "contextual" for i in edited.json()["audit"]["issues"])
