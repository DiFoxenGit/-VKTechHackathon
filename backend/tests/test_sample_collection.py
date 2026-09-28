"""Submission collection must exercise arbitrary imports and include all export formats."""

import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("make_samples", Path(__file__).resolve().parents[2] / "tools" / "make_samples.py")
samples = importlib.util.module_from_spec(spec)
spec.loader.exec_module(samples)


def test_collector_requests_content_audit_and_keeps_errors_separate_from_warnings(tmp_path, monkeypatch):
    source = tmp_path / "source.md"
    source.write_text("Материал", encoding="utf-8")
    template = tmp_path / "never_seen_before.pptx"
    template.write_bytes(b"template")
    uploads, exports = [], []

    def upload(base, path, file, content_type):
        uploads.append((path, file.name))
        return {"id": "pack" if "content-packs" in path else "template", "name": file.name}

    def call(base, path, payload=None, **kwargs):
        if path == "/api/v1/generations":
            assert payload["contextual_audit"] is True
            assert payload["content_pack_ids"] == ["pack"]
            return {"id": "job"}
        if "/jobs/" in path:
            return {"status": "completed", "presentation_ids": ["classic", "split", "focus"], "elapsed_seconds": 2, "warnings": []}
        if "/export/" in path:
            exports.append(path.split("/export/")[1].split("?")[0])
            return b"exported file"
        variant = path.rsplit("/", 1)[1]
        return {"id": variant, "variant": variant, "revision": 1, "deck": {"slides": [{}, {}]},
                "audit": {"contextual": {"status": "completed"}, "issues": [
                    {"code": "unsupported_fact", "severity": "error"},
                    {"code": "fill_ratio", "severity": "warning"},
                ]}, "workflow": {"version": "1.12.0"}}

    monkeypatch.setattr(samples, "upload", upload)
    monkeypatch.setattr(samples, "call", call)
    output = tmp_path / "result"
    rows = samples.collect("http://test", [template], source, output, require_chart=True)
    assert uploads == [("/api/v1/content-packs", "source.md"), ("/api/v1/templates", "never_seen_before.pptx")]
    assert exports == ["pptx", "pdf", "html"] * 3
    assert len(rows) == 3
    assert all(row["errors"] == 1 and row["warnings"] == {"fill_ratio": 1} for row in rows)
    assert len(list((output / "evidence").glob("*__audit.json"))) == 3
    run = json.loads((output / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "completed"
    assert run["quality"] == "needs_review" and run["missing_native_chart"] is True


def test_collector_refuses_empty_template_set_and_records_failed_generation(tmp_path, monkeypatch):
    source = tmp_path / "source.md"
    source.write_text("Источник", encoding="utf-8")
    template = tmp_path / "template.pptx"
    template.write_bytes(b"template")
    with pytest.raises(ValueError, match="No templates"):
        samples.collect("http://test", [], source, tmp_path / "empty")
    monkeypatch.setattr(samples, "upload", lambda *args: {"id": "id", "name": "template"})
    monkeypatch.setattr(samples, "call", lambda *args, **kwargs: {"id": "job", "status": "failed", "error": "LLM unavailable"})
    output = tmp_path / "failed"
    with pytest.raises(RuntimeError, match="LLM unavailable"):
        samples.collect("http://test", [template], source, output)
    assert json.loads((output / "run.json").read_text(encoding="utf-8"))["status"] == "failed"
    assert json.loads((output / "report.json").read_text(encoding="utf-8")) == []
