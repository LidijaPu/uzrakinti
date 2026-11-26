"""Komandos ir kvietimai."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from pymongo.errors import DuplicateKeyError

from ..db import db
from ..deps import current_user
from ..events import log_event
from ..utils import oid, serialize

router = APIRouter(tags=["teams"])
MAX_MEMBERS = 10


class TeamIn(BaseModel):
    name: str = Field(min_length=2, max_length=40)


class InviteIn(BaseModel):
    email: EmailStr


def team_with_members(team: dict) -> dict:
    users = {u["_id"]: u for u in db.users.find(
        {"_id": {"$in": [m["userId"] for m in team["members"]]}}, {"firstName": 1, "lastName": 1})}
    out = serialize(team)
    out["members"] = [{"userId": str(m["userId"]), "role": m["role"],
                       "name": f'{users.get(m["userId"], {}).get("firstName", "?")} '
                               f'{users.get(m["userId"], {}).get("lastName", "")}'.strip()}
                      for m in team["members"]]
    return out


def get_team(team_id: str) -> dict:
    team = db.teams.find_one({"_id": oid(team_id)})
    if not team:
        raise HTTPException(404, "Komanda nerasta")
    return team


@router.post("/teams", status_code=201, summary="Sukurti komandą (kūrėjas tampa kapitonu)")
def create_team(body: TeamIn, user: dict = Depends(current_user)):
    uid = oid(user["userId"])
    now = datetime.utcnow()
    try:
        res = db.teams.insert_one({"name": body.name.strip(), "captainId": uid, "createdAt": now,
                                   "members": [{"userId": uid, "role": "captain", "joinedAt": now}]})
    except DuplicateKeyError:
        raise HTTPException(409, "Komanda tokiu pavadinimu jau egzistuoja")
    log_event("team_created", user_id=user["userId"], meta={"teamId": str(res.inserted_id)})
    return {"id": str(res.inserted_id)}


@router.get("/teams/mine", summary="Mano komandos")
def my_teams(user: dict = Depends(current_user)):
    return [team_with_members(t) for t in db.teams.find({"members.userId": oid(user["userId"])})]


@router.get("/teams/{team_id}", summary="Komandos informacija su nariais")
def team_detail(team_id: str, user: dict = Depends(current_user)):
    return team_with_members(get_team(team_id))


@router.post("/teams/{team_id}/invites", status_code=201, summary="Pakviesti žaidėją (tik kapitonas)")
def invite(team_id: str, body: InviteIn, user: dict = Depends(current_user)):
    team = get_team(team_id)
    if str(team["captainId"]) != user["userId"]:
        raise HTTPException(403, "Kviesti gali tik kapitonas")
    invitee = db.users.find_one({"email": body.email.lower()}, {"_id": 1})
    if not invitee:
        raise HTTPException(404, "Vartotojas su tokiu el. paštu nerastas")
    if any(m["userId"] == invitee["_id"] for m in team["members"]):
        raise HTTPException(409, "Vartotojas jau yra komandoje")
    if len(team["members"]) >= MAX_MEMBERS:
        raise HTTPException(409, f"Komandoje jau {MAX_MEMBERS} nariai")
    try:
        res = db.team_invitations.insert_one({"teamId": team["_id"], "userId": invitee["_id"],
                                              "invitedBy": oid(user["userId"]), "status": "pending",
                                              "createdAt": datetime.utcnow()})
    except DuplicateKeyError:
        raise HTTPException(409, "Šis žaidėjas jau pakviestas")
    return {"id": str(res.inserted_id)}


@router.get("/invites/mine", summary="Man skirti laukiantys kvietimai")
def my_invites(user: dict = Depends(current_user)):
    rows = db.team_invitations.aggregate([
        {"$match": {"userId": oid(user["userId"]), "status": "pending"}},
        {"$lookup": {"from": "teams", "localField": "teamId", "foreignField": "_id", "as": "team"}},
        {"$project": {"teamId": 1, "createdAt": 1, "team": {"$arrayElemAt": ["$team.name", 0]}}},
    ])
    return [serialize(x) for x in rows]


@router.post("/invites/{invite_id}/accept", summary="Priimti kvietimą")
def accept(invite_id: str, user: dict = Depends(current_user)):
    uid = oid(user["userId"])
    inv = db.team_invitations.find_one({"_id": oid(invite_id), "userId": uid, "status": "pending"})
    if not inv:
        raise HTTPException(404, "Kvietimas nerastas")
    # atomiškai: dar ne narys ir narių < 10 ("members.9" neegzistuoja)
    res = db.teams.update_one(
        {"_id": inv["teamId"], "members.userId": {"$ne": uid},
         f"members.{MAX_MEMBERS - 1}": {"$exists": False}},
        {"$push": {"members": {"userId": uid, "role": "member", "joinedAt": datetime.utcnow()}}})
    if res.modified_count == 0:
        raise HTTPException(409, "Komanda pilna arba jūs jau esate narys")
    db.team_invitations.update_one({"_id": inv["_id"]}, {"$set": {"status": "accepted"}})
    log_event("team_joined", user_id=user["userId"], meta={"teamId": str(inv["teamId"])})
    return {"ok": True}


@router.post("/invites/{invite_id}/decline", summary="Atmesti kvietimą")
def decline(invite_id: str, user: dict = Depends(current_user)):
    res = db.team_invitations.update_one(
        {"_id": oid(invite_id), "userId": oid(user["userId"]), "status": "pending"},
        {"$set": {"status": "declined"}})
    if res.modified_count == 0:
        raise HTTPException(404, "Kvietimas nerastas")
    return {"ok": True}


@router.delete("/teams/{team_id}/members/{user_id}", summary="Pašalinti narį (kapitonas) arba išeiti (pats)")
def remove_member(team_id: str, user_id: str, user: dict = Depends(current_user)):
    team = get_team(team_id)
    is_captain = str(team["captainId"]) == user["userId"]
    if not is_captain and user_id != user["userId"]:
        raise HTTPException(403, "Šalinti gali tik kapitonas")
    if user_id == str(team["captainId"]):
        raise HTTPException(400, "Kapitono pašalinti negalima")
    res = db.teams.update_one({"_id": team["_id"]}, {"$pull": {"members": {"userId": oid(user_id)}}})
    if res.modified_count == 0:
        raise HTTPException(404, "Toks narys nerastas")
    return {"ok": True}
