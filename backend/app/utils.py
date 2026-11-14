from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException


def oid(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        raise HTTPException(400, f"Neteisingas ID: {value}")


def serialize(doc: dict | None) -> dict | None:
    """ObjectId → str, kad būtų galima grąžinti JSON."""
    if doc is None:
        return None
    out = {}
    for k, v in doc.items():
        key = "id" if k == "_id" else k
        if isinstance(v, ObjectId):
            out[key] = str(v)
        elif isinstance(v, dict):
            out[key] = serialize(v)
        elif isinstance(v, list):
            out[key] = [serialize(x) if isinstance(x, dict) else str(x) if isinstance(x, ObjectId) else x for x in v]
        else:
            out[key] = v
    return out
