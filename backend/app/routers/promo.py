"""Nuolaidų kodai ir kuponai (peržiūra). Panaudojami POST /bookings/confirm."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..db import db
from ..deps import current_user

router = APIRouter(tags=["promo"])


class CodeIn(BaseModel):
    code: str


@router.post("/promo/validate", summary="Patikrinti nuolaidos kodą (nepanaudoja)")
def validate_promo(body: CodeIn, user: dict = Depends(current_user)):
    now = datetime.utcnow()
    p = db.promo_codes.find_one({"code": body.code.upper(), "validFrom": {"$lte": now}, "validTo": {"$gte": now}})
    if not p or p["usedCount"] >= p["maxUses"]:
        raise HTTPException(404, "Kodas negalioja")
    return {"code": p["code"], "discountPct": p["discountPct"], "usesLeft": p["maxUses"] - p["usedCount"]}


@router.get("/vouchers/{code}", summary="Dovanų kupono likutis")
def voucher_balance(code: str, user: dict = Depends(current_user)):
    v = db.vouchers.find_one({"code": code.upper()})
    if not v:
        raise HTTPException(404, "Kuponas nerastas")
    return {"code": v["code"], "value": v["value"], "remaining": v["remaining"],
            "expiresAt": v["expiresAt"], "expired": v["expiresAt"] < datetime.utcnow()}
