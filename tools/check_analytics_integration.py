"""Real HTTP acceptance of Dima's published contract, service and native exports."""
import argparse
import io
import json
import time
from pathlib import Path
import httpx
from pptx import Presentation
from pypdf import PdfReader
from run_final_server import ROOT


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--url",default="http://127.0.0.1:8002/api/v1")
    args=parser.parse_args()
    output=ROOT/"output"/"dima-integration";output.mkdir(parents=True,exist_ok=True)
    samples=ROOT/"samples"/"analytics"
    report={"synthetic":True,"source_commit":"108199a","checks":[],"runs":[]}
    with httpx.Client(base_url=args.url,timeout=180) as client:
        def req(method,url,**kw):
            response=client.request(method,url,**kw);response.raise_for_status();return response
        def upload(path):
            return req("POST","/content-packs",files={"file":(path.name,path.read_bytes())}).json()
        packs=[];requests={};goals={}
        for request_path in sorted((samples/"datasets").glob("*.request.json")):
            stem=request_path.name.removesuffix(".request.json")
            path=next(p for p in (samples/"datasets").glob(stem+".*") if p.suffix in {".csv",".md"})
            pack=upload(path);packs.append(pack)
            request=json.loads(request_path.read_text(encoding="utf-8"))
            dataset=pack["datasets"][0]["dataset_id"]
            requests[dataset]=request;goals[pack["id"]]=request["goal"]
            preview=req("POST",f"/content-packs/{pack['id']}/analysis",json={"goal":request["goal"],"requests":{dataset:request}}).json()
            expected=json.loads((samples/"datasets"/(stem+".result.json")).read_text(encoding="utf-8"))
            assert preview["analysis_results"][0]==expected,stem
            assert len(pack["datasets"][0]["rows"])==expected["profile"]["row_count"]
            report["checks"].append(dict(dataset=stem,exact_contract_match=True,rows=expected["profile"]["row_count"]))
        templates=req("GET","/templates").json()["items"]
        assert len(templates)>=2,"Need two registered templates"
        def generate(name,selected,template,limit=30,pdf=False):
            started=time.monotonic()
            payload=dict(brief="Проверка интеграции аналитики Димы: синтетические данные",template_id=template["id"],slide_count=limit,
                content_pack_ids=[p["id"] for p in selected],analysis_goals={p["id"]:goals[p["id"]] for p in selected},
                analysis_requests={t["dataset_id"]:requests[t["dataset_id"]] for p in selected for t in p["datasets"]})
            job=req("POST","/generations",json=payload).json();deadline=time.monotonic()+240
            while job["status"] not in {"completed","failed"} and time.monotonic()<deadline:
                time.sleep(.2);job=req("GET",f"/jobs/{job['id']}").json()
            assert job["status"]=="completed",job
            records=[req("GET",f"/presentations/{identifier}").json() for identifier in job["presentation_ids"]]
            record=records[0]
            assert all(r["analysis_results"]==record["analysis_results"] for r in records)
            assert not any(i["code"] in {"analysis_mismatch","unverified_number","chart_without_data"} for i in record["audit"]["issues"])
            pptx=req("GET",f"/presentations/{record['id']}/export/pptx").content
            (output/(name+".pptx")).write_bytes(pptx)
            deck=Presentation(io.BytesIO(pptx));assert len(deck.slides)==len(record["deck"]["slides"])
            for slide,expected in zip(deck.slides,record["deck"]["slides"]):
                visual=expected["content"]["visual"]
                if visual["kind"] in {"line","bar","pie","histogram","grouped_bar","stacked_bar"}:
                    chart=next(s.chart for s in slide.shapes if s.has_chart)
                    assert [c.label for c in chart.plots[0].categories]==visual["categories"]
                    assert [list(s.values) for s in chart.series]==[s["values"] for s in visual["series"]]
            if pdf:
                content=req("GET",f"/presentations/{record['id']}/export/pdf").content
                (output/(name+".pdf")).write_bytes(content)
                document=PdfReader(io.BytesIO(content));assert len(document.pages)==len(deck.slides)
            (output/(name+".json")).write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding="utf-8")
            report["runs"].append(dict(name=name,slides=len(deck.slides),variants=len(records),seconds=round(time.monotonic()-started,3),audit=record["audit"]["counts"]))
            print(report["runs"][-1],flush=True)
            return record
        first=generate("seven-datasets",packs,templates[0],pdf=True)
        assert len(first["deck"]["slides"])==30
        second=generate("other-template",[packs[1]],templates[1])
        original=first["analysis_results"][1]
        assert second["analysis_results"][0]==original
        path=samples/"datasets"/"02-regions.csv"
        changed=path.read_text(encoding="utf-8").replace(",60",",600")
        pack=req("POST","/content-packs",files={"file":("changed.csv",changed.encode())}).json()
        goals[pack["id"]]=goals[packs[1]["id"]]
        requests[pack["datasets"][0]["dataset_id"]]=requests[packs[1]["datasets"][0]["dataset_id"]]
        result=generate("changed-value",[pack],templates[0],pdf=True)
        assert result["analysis_results"][0]["data"]!=original["data"]
        assert result["analysis_results"][0]["presentation"]["title"]!=original["presentation"]["title"]
        content=result["deck"]["slides"][0]["content"]
        content["visual"]["series"][0]["values"].reverse()
        response=client.patch(f"/presentations/{result['id']}/slides/0",json={"revision":result["revision"],"content":content})
        assert response.status_code==422,response.text
        report["checks"].append(dict(changed_value_updates_graph_and_conclusion=True,tampered_chart_rejected=True))
    (output/"acceptance.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print("PASS: real contract, three variants, two templates, native PPTX/PDF and input mutation",flush=True)


if __name__=="__main__":
    main()
