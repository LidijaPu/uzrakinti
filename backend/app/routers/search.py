from fastapi import APIRouter

from ..db import ROOMS_INDEX, es
from ..events import log_event

router = APIRouter(prefix="/search", tags=["search"])


@router.get("/rooms", summary="Pilno teksto paieška (ElasticSearch) su filtrais ir facets")
def search_rooms(q: str = "", city: str | None = None, players: int | None = None,
                 difficulty: int | None = None, userId: str = ""):
    must = [{"multi_match": {"query": q, "fields": ["name^3", "description", "tags^2", "theme^2"],
                             "fuzziness": "AUTO"}}] if q else [{"match_all": {}}]
    filters: list[dict] = [{"term": {"isActive": True}}]
    if city:
        filters.append({"term": {"city": city}})
    if players:
        filters += [{"range": {"minPlayers": {"lte": players}}},
                    {"range": {"maxPlayers": {"gte": players}}}]
    if difficulty:
        filters.append({"term": {"difficulty": difficulty}})

    res = es.search(index=ROOMS_INDEX, query={"bool": {"must": must, "filter": filters}},
                    aggs={"byCity": {"terms": {"field": "city"}},
                          "byTheme": {"terms": {"field": "theme"}},
                          "byDifficulty": {"terms": {"field": "difficulty"}}},
                    size=20)
    hits = [{"id": h["_id"], "score": h["_score"], **h["_source"]} for h in res["hits"]["hits"]]
    log_event("search", user_id=userId, value=len(hits), meta={"q": q, "city": city, "players": players})
    return {
        "total": res["hits"]["total"]["value"],
        "hits": hits,
        "facets": {k: [{"key": b["key"], "count": b["doc_count"]} for b in v["buckets"]]
                   for k, v in res["aggregations"].items()},
    }


@router.get("/suggest", summary="Autocomplete pagal kambario pavadinimą")
def suggest(q: str):
    res = es.search(index=ROOMS_INDEX, size=5, source=["name", "slug"], query={
        "multi_match": {"query": q, "type": "bool_prefix",
                        "fields": ["name.suggest", "name.suggest._2gram", "name.suggest._3gram"]}})
    return [h["_source"] for h in res["hits"]["hits"]]
