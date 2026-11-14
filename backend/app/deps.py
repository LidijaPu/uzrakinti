"""FastAPI priklausomybės: dabartinis vartotojas iš Redis sesijos, rolių patikra."""
import json

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings
from .db import r

bearer = HTTPBearer(auto_error=False)


def current_user(cred: HTTPAuthorizationCredentials | None = Depends(bearer)) -> dict:
    if cred is None:
        raise HTTPException(401, "Reikia prisijungti")
    key = f"session:{cred.credentials}"
    raw = r.get(key)
    if raw is None:
        raise HTTPException(401, "Sesija pasibaigė arba neegzistuoja")
    r.expire(key, settings.session_ttl)  # „slenkanti“ sesija – aktyvus vartotojas neišmetamas
    user = json.loads(raw)
    user["token"] = cred.credentials
    return user


def require_role(*roles: str):
    def checker(user: dict = Depends(current_user)) -> dict:
        if user["type"] not in roles:
            raise HTTPException(403, "Neturite teisių")
        return user
    return checker
