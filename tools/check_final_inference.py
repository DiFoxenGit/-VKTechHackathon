"""Verify the real transport and the real planner; no key in logs or artifacts."""
import asyncio
import json
import time
from pathlib import Path
from run_final_server import load_server_env, ROOT


async def main():
    load_server_env()
    from designer.ai import ask, parse_json
    from designer.inference import require_llm
    from designer.pipeline import generate_outline
    from designer.models import GenerateRequest
    settings=require_llm()
    started=time.monotonic()
    answer=parse_json(await ask([{"role":"system","content":"Return only JSON."},{"role":"user","content":"Return an object with ok: true"}]))
    transport_elapsed=time.monotonic()-started
    if answer.get("ok") is not True:raise ValueError("Unexpected transport response")
    request=GenerateRequest(brief="Проверка сервиса: продажи на Севере 100 руб., на Юге 200 руб. Нужно сравнить результаты регионов без рекомендаций и выдуманных фактов.",template_id="integration-check",slide_count=1)
    warnings=[]
    started=time.monotonic()
    outline=await generate_outline(request,[{"id":"brief","text":request.brief}],warnings)
    planner_elapsed=time.monotonic()-started
    target=ROOT/"output"/"final";target.mkdir(parents=True,exist_ok=True)
    report=dict(provider=settings.profile,model=settings.model,transport_seconds=round(transport_elapsed,3),planner_seconds=round(planner_elapsed,3),planner_slides=len(outline.slides),warnings=warnings,scope="Real server client + planner schema, not VLM and not full browser generation")
    (target/"inference.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False))


if __name__=="__main__":asyncio.run(main())
