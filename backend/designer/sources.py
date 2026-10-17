from fastapi import HTTPException
from .models import Brief

def sources_for(store, request: Brief):
    result = [{"id": "brief", "text": request.brief}]
    for identifier in request.content_pack_ids:
        item = store.get("content_packs", identifier)
        result.append({"id": identifier, "text": item["text"], "datasets": item.get("datasets", []), "analysis_goal": getattr(request, "analysis_goals", {}).get(identifier, "")})
    if sum(len(s["text"]) for s in result) > 120000:
        raise HTTPException(422, "Combined source text exceeds 120000 characters")
    return result

