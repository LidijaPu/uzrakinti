import json
import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from pymongo.errors import DuplicateKeyError

from ..config import settings
from ..db import db, r
from ..deps import current_user
from ..events import log_event
from ..security import hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    firstName: str
    lastName: str
    birthYear: int = Field(ge=1900, le=2030)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


@router.post("/register", status_code=201, summary="Žaidėjo registracija")
def register(body: RegisterIn):
    doc = {
        "type": "player", "email": body.email.lower(), "passwordHash": hash_password(body.password),
        "firstName": body.firstName, "lastName": body.lastName, "birthYear": body.birthYear,
        "achievements": [], "stats": {"games": 0, "escapes": 0}, "createdAt": datetime.utcnow(),
    }
    try:
        res = db.users.insert_one(doc)  # unikalus indeksas ant email
    except DuplicateKeyError:
        raise HTTPException(409, "Šis el. paštas jau užregistruotas")
    log_event("register", user_id=str(res.inserted_id), meta={"birthYear": body.birthYear})
    return {"id": str(res.inserted_id)}


@router.post("/login", summary="Prisijungimas – grąžina sesijos token'ą (saugomas Redis)")
def login(body: LoginIn, request: Request):
    # Rate limiting: max 10 bandymų per minutę iš vieno IP
    rate_key = f"rate:login:{request.client.host if request.client else 'unknown'}"
    attempts = r.incr(rate_key)
    if attempts == 1:
        r.expire(rate_key, 60)
    if attempts > 10:
        raise HTTPException(429, "Per daug bandymų, palaukite minutę")

    user = db.users.find_one({"email": body.email.lower()})
    if not user or not verify_password(body.password, user["passwordHash"]):
        raise HTTPException(401, "Neteisingas el. paštas arba slaptažodis")

    token = secrets.token_urlsafe(32)
    session = {"userId": str(user["_id"]), "type": user["type"], "firstName": user["firstName"]}
    r.set(f"session:{token}", json.dumps(session), ex=settings.session_ttl)
    log_event("login", user_id=session["userId"])
    return {"token": token, "user": session}


@router.post("/logout", summary="Atsijungimas – ištrina sesiją iš Redis")
def logout(user: dict = Depends(current_user)):
    r.delete(f"session:{user['token']}")
    return {"ok": True}


@router.get("/me", summary="Prisijungusio vartotojo duomenys")
def me(user: dict = Depends(current_user)):
    return {k: v for k, v in user.items() if k != "token"}
