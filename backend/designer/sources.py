from fastapi import HTTPException
from .models import Brief

def sources_for(store, request: Brief):
    result = [{"id": "brief", "text": request.brief}]
    for identifier in request.content_pack_ids:
        item = store.get("content_packs", identifier)
        result.append({"id": identifier, "text": item["text"], "datasets": item.get("datasets", []), "analysis_goal": getattr(request, "analysis_goals", {}).get(identifier, ""),
                       "analysis_requests": {k:v.model_dump(mode="json") for k,v in getattr(request,"analysis_requests",{}).items() if k in {t["dataset_id"] for t in item.get("datasets",[])}}})
    if sum(len(s["text"]) for s in result) > 120000:
        raise HTTPException(422, "Combined source text exceeds 120000 characters")
    return result

