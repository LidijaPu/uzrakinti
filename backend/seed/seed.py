"""Testinių duomenų generatorius.

Paleidimas:  docker compose exec backend python -m seed.seed [--bookings 12000]
Visi demo vartotojai turi slaptažodį: demo123
  admin@uzrakinti.lt, gm@uzrakinti.lt (žaidimo vedėjas), vadovas@uzrakinti.lt (filialo vadovas),
  zaidejas@uzrakinti.lt ir draugas@uzrakinti.lt (žaidėjai; Žana – komandos „Demo komanda“ kapitonė)
"""
import argparse
import json
import random
from datetime import date, datetime, time, timedelta

from bson import ObjectId
from faker import Faker
from pymongo import UpdateOne

from app.db import ROOMS_INDEX, ch, db, es, r
from app.events import COLUMNS
from app.init_db import init_all
from app.routers.leaderboards import record_result
from app.security import hash_password
from app.services.search_sync import reindex_all_rooms

fake = Faker("lt_LT")
random.seed(42)
Faker.seed(42)

LOCATIONS = [
    ("Užrakinti Senamiestis", "Vilnius", "Pilies g. 10", [25.2895, 54.6840]),
    ("Užrakinti Naujamiestis", "Vilnius", "Naugarduko g. 24", [25.2702, 54.6762]),
    ("Užrakinti Kaunas", "Kaunas", "Laisvės al. 55", [23.9139, 54.8972]),
    ("Užrakinti Klaipėda", "Klaipėda", "Tiltų g. 8", [21.1324, 55.7085]),
]

ROOMS = [  # (pavadinimas, tema, sudėtingumas, min, max, žymos, aprašymas)
    ("Sovietinis bunkeris", "history", 3, 2, 6, ["istorija", "šnipai"],
     "1984-ieji. Slaptas bunkeris po miestu, o jūsų komanda turi 60 minučių iššifruoti kodus."),
    ("Alchemiko laboratorija", "fantasy", 4, 2, 5, ["magija", "chemija"],
     "Senovinė alchemiko dirbtuvė pilna eliksyrų, mįslių ir paslaptingų mechanizmų."),
    ("Dingęs rankraštis", "detective", 3, 2, 6, ["detektyvas", "biblioteka"],
     "Iš bibliotekos dingo vertingas rankraštis. Sekite įkalčius ir raskite vagį."),
    ("Kosminė stotis Gaia", "sci-fi", 5, 3, 6, ["kosmosas", "technologijos"],
     "Stoties deguonies sistema genda. Perprogramuokite valdymą, kol dar ne vėlu."),
    ("Siaubo ligoninė", "horror", 4, 3, 8, ["siaubas", "18+"],
     "Apleista psichiatrijos ligoninė. Tamsa, garsai ir paslaptis, kurios niekas neišsprendė."),
    ("Piratų lobis", "adventure", 2, 2, 8, ["vaikams", "nuotykiai"],
     "Kapitono Juodbarzdžio laivas ir paslėptas lobis. Puikiai tinka šeimoms su vaikais."),
    ("Faraono kapas", "adventure", 3, 2, 6, ["egiptas", "nuotykiai"],
     "Egipto piramidės gilumoje laukia faraono prakeiksmas ir hieroglifų mįslės."),
    ("Banko apiplėšimas", "heist", 4, 3, 6, ["apiplėšimas", "seifas"],
     "Turite valandą, kol suveiks signalizacija. Atidarykite seifą ir pabėkite."),
    ("Burtininko bokštas", "fantasy", 2, 2, 5, ["magija", "vaikams"],
     "Jaunieji burtininkai turi išlaisvinti mokytoją iš užkeikto bokšto."),
    ("Zombių laboratorija", "horror", 5, 4, 8, ["siaubas", "zombiai"],
     "Laboratorijoje ištrūko virusas. Raskite priešnuodį, kol nevirtote zombiais."),
    ("Šerloko kabinetas", "detective", 4, 2, 4, ["detektyvas", "Londonas"],
     "Beikerio gatvė 221B. Išspręskite paskutinę didžiojo detektyvo bylą."),
    ("Laiko mašina", "sci-fi", 3, 2, 6, ["laikas", "istorija"],
     "Sugedusi laiko mašina išmetė jus į praeitį. Pataisykite ją ir grįžkite."),
]
HINTS = {  # 6 užuominos kiekvienam kambariui – nuo švelnios iki beveik atsakymo
    "Sovietinis bunkeris": ["Pažiūrėkite į kalendorių ant sienos – viena data apibraukta.",
        "Radijo dažnis užrašytas ant pelenines dugno.", "Morzės kodo lentelė paslėpta už Lenino portreto.",
        "Seifo kodas – keturi skaitmenys iš apibrauktos datos.", "Žemėlapyje raudoni taškai rodo stalčių eilės tvarką.",
        "Paskutinis kodas: sudėkite skaičius ant visų keturių telefonų."],
    "Alchemiko laboratorija": ["Ne visi buteliukai skirti gerti – kai kurie rodo spalvą.",
        "Spalvų tvarka užrašyta senoje knygoje ant lentynos.", "Svarstyklės turi būti lygiai subalansuotos.",
        "Žvakė atskleidžia nematomą rašalą ant pergamento.", "Sumaišykite mėlyną ir geltoną – gausite raktą į spintą.",
        "Paskutinis eliksyras: trys lašai raudono, vienas žalio."],
    "Dingęs rankraštis": ["Bibliotekininko užrašų knygelėje trūksta vieno puslapio.",
        "Knygų numeriai lentynoje sudaro kodą.", "Pažiūrėkite, kurios knygos stovi aukštyn kojomis.",
        "Vagis paliko pėdsaką – patikrinkite kilimą prie lango.", "Lempos šviesa ant gaublio rodo miestą.",
        "Rankraštis paslėptas trečioje lentynoje, už enciklopedijos."],
    "Kosminė stotis Gaia": ["Valdymo pulte mirksi trys lemputės – jų tvarka svarbi.",
        "Deguonies balionų slėgis rodo kodą.", "Instrukcija paslėpta astronauto šalme.",
        "Žvaigždėlapyje sujunkite tris ryškiausias žvaigždes.", "Laidus junkite pagal spalvą ant durų.",
        "Paskutinis kodas – 4-7-1-9, įveskite jį pagrindiniame pulte."],
    "Siaubo ligoninė": ["Paciento kortelėje apibrauktas palatos numeris.",
        "Užgesus šviesai, žiūrėkite į sienas – kai kurie užrašai šviečia.", "Vaistų buteliukų etiketės sudaro žodį.",
        "Raktas nuo palatos – rentgeno nuotraukoje.", "Rentgeno nuotrauką priglauskite prie šviesos dėžės.",
        "Išėjimo kodas – gydytojo gimimo metai iš diplomo ant sienos."],
    "Piratų lobis": ["Kapitono žemėlapis suplėšytas – raskite visas keturias dalis.",
        "Viena žemėlapio dalis paslėpta statinėje.", "Kompasas rodo ne į šiaurę, o į skrynią.",
        "Papūgos narvelyje yra raktas.", "Suskaičiuokite inkarus ant sienos.",
        "Lobis – po grindų lenta su kryželiu."],
    "Faraono kapas": ["Hieroglifų lentelė paslėpta sarkofago šone.",
        "Skarabėjai turi būti sudėti pagal dydį.", "Šviesa iš deglo turi kristi ant akies simbolio.",
        "Kodas – keturi hieroglifai virš durų.", "Pasukite statulėles veidu į sarkofagą.",
        "Faraono kaukė atidaro paskutines duris."],
    "Banko apiplėšimas": ["Apsaugos darbuotojo pamainos grafikas – ant skelbimų lentos.",
        "Kameros išjungiamos jungikliu už paveikslo.", "Banko vadovo stalčiuje – kortelė su PIN.",
        "Lazeriai matomi tik pro rūką – naudokite purkštuvą.", "Seifo kodas – sąskaitos numerio paskutiniai skaitmenys.",
        "Signalizacija išsijungia įvedus 0-0-0-0 prie galinių durų."],
    "Burtininko bokštas": ["Burtų knygoje trūksta vieno žodžio.",
        "Kristalinis rutulys rodo spalvas eilės tvarka.", "Pelėda žino atsakymą – pažiūrėkite į jos akis.",
        "Lazdelę reikia įdėti į žvaigždės formos skylę.", "Ištarkite burtažodį, užrašytą ant laiptų.",
        "Mokytojas – už veidrodžio, kuris atsidaro paspaudus mėnulį."],
    "Zombių laboratorija": ["Mokslininko dienoraštyje aprašyti priešnuodžio ingredientai.",
        "Mėgintuvėlių spalvos atitinka grafiką ant lentos.", "Mikroskope – kodas mažomis raidėmis.",
        "Šaldytuvo kodas – laboratorijos įkūrimo metai.", "Priešnuodį reikia įkaitinti iki 37 laipsnių.",
        "Išėjimas atsidaro įdėjus priešnuodį į dozatorių."],
    "Šerloko kabinetas": ["Pypkė nėra dekoracija – pažiūrėkite į jos vidų.",
        "Laikraščio iškarpose pabrauktos raidės sudaro žodį.", "Smuiko stygos atitinka skaičius.",
        "Daktaro Vatsono laiške – užuomina apie seifą.", "Didinamasis stiklas atskleidžia pirštų atspaudus ant lango.",
        "Kaltininkas – sodininkas; jo vardas ir yra slaptažodis."],
    "Laiko mašina": ["Laikrodžiai ant sienos rodo skirtingus laikus – tai kodas.",
        "Instrukcijų knygoje trūksta 3 puslapio.", "Detales reikia rikiuoti pagal istorinius laikotarpius.",
        "Kalendorius rodo datą, į kurią reikia grįžti.", "Sujunkite laidus pagal epochų spalvas.",
        "Paleidimo kodas: 1-9-8-5."],
}
REVIEW_TEXTS = [
    "Labai patiko, galvosūkiai logiški ir įdomūs!", "Puiki atmosfera, vedėjas labai malonus.",
    "Buvo sunkoka, bet pabėgome paskutinę minutę.", "Rekomenduoju draugų kompanijai.",
    "Šventėme gimtadienį – visiems patiko.", "Kai kurios užduotys per sunkios, bet smagu.",
    "Dekoracijos nuostabios, jaučiausi kaip filme.", "Būtinai grįšime į kitą kambarį!",
    "Per mažai laiko, norėjosi dar.", "Vienas geriausių pabėgimo kambarių, kuriuose esame buvę.",
    "Truputį nuobodoka pradžia, bet pabaiga puiki.", "Vaikams labai patiko, ačiū!",
]
SLOT_TIMES = ["10:00", "11:30", "13:00", "14:30", "16:00", "17:30", "19:00", "20:30"]
DEMO_PASSWORD = hash_password("demo123")


def reset() -> None:
    for name in db.list_collection_names():
        db.drop_collection(name)
    if es.indices.exists(index=ROOMS_INDEX):
        es.indices.delete(index=ROOMS_INDEX)
    ch().command("DROP TABLE IF EXISTS events")
    r.flushdb()


def seed(n_users: int, n_teams: int, n_bookings: int) -> None:
    reset()
    init_all()
    now = datetime.now().replace(microsecond=0)
    events: list[list] = []

    def ev(ts, etype, **kw):
        events.append([ts, etype, kw.get("user", ""), kw.get("room", ""), kw.get("loc", ""),
                       kw.get("booking", ""), "", float(kw.get("value", 0)),
                       json.dumps(kw.get("meta", {}), default=str)])

    # --- filialai
    loc_ids = db.locations.insert_many([
        {"name": n, "city": c, "address": a, "geo": {"type": "Point", "coordinates": g},
         "openingHours": ["10:00-22:00"]} for n, c, a, g in LOCATIONS]).inserted_ids

    # --- kambariai (paskirstomi per filialus)
    rooms = []
    for i, (name, theme, diff, mn, mx, tags, desc) in enumerate(ROOMS):
        rooms.append({
            "locationId": loc_ids[i % len(loc_ids)], "slug": name.lower().replace(" ", "-").translate(str.maketrans("ąčęėįšųūž", "aceeisuuz")),
            "name": name, "theme": theme, "description": desc, "difficulty": diff,
            "minPlayers": mn, "maxPlayers": mx, "durationMin": 60, "ageLimit": 18 if "18+" in tags else 10,
            "pricePerPlayer": float(random.choice([15, 18, 20, 22, 25])), "tags": tags,
            "slotTimes": SLOT_TIMES, "isActive": True, "rating": {"avg": 0.0, "count": 0},
            "hints": [{"hintId": f"h{k}", "order": k, "text": HINTS[name][k - 1],
                       "penaltySec": 120} for k in range(1, 7)],
        })
    db.rooms.insert_many(rooms)

    # --- vartotojai
    staff = [
        {"type": "admin", "email": "admin@uzrakinti.lt", "firstName": "Ada", "lastName": "Administratorė"},
        {"type": "gameMaster", "email": "gm@uzrakinti.lt", "firstName": "Gytis", "lastName": "Vedėjas"},
        {"type": "player", "email": "zaidejas@uzrakinti.lt", "firstName": "Žana", "lastName": "Žaidėja"},
        {"type": "manager", "email": "vadovas@uzrakinti.lt", "firstName": "Vytas", "lastName": "Vadovas"},
        {"type": "player", "email": "draugas@uzrakinti.lt", "firstName": "Darius", "lastName": "Draugas"},
    ]
    users = []
    for s in staff:
        users.append({**s, "passwordHash": DEMO_PASSWORD, "birthYear": 1998, "achievements": [],
                      "stats": {"games": 0, "escapes": 0}, "createdAt": now - timedelta(days=400)})
    emails = set()
    while len(users) < n_users:
        email = fake.unique.email()
        if email in emails:
            continue
        emails.add(email)
        users.append({"type": "player", "email": email, "passwordHash": DEMO_PASSWORD,
                      "firstName": fake.first_name(), "lastName": fake.last_name(),
                      "birthYear": random.randint(1965, 2010), "achievements": [],
                      "stats": {"games": 0, "escapes": 0},
                      "createdAt": now - timedelta(days=random.randint(0, 365))})
    db.users.insert_many(users)
    players = [u for u in users if u["type"] == "player"]
    gm_id = users[1]["_id"]
    for u in users:
        ev(u["createdAt"], "register", user=str(u["_id"]), meta={"birthYear": u["birthYear"]})

    # --- komandos
    adjectives = ["Greitieji", "Gudrieji", "Drąsieji", "Tylieji", "Paslaptingieji", "Laukiniai", "Kosminiai"]
    nouns = ["Lapės", "Vilkai", "Pelėdos", "Detektyvai", "Ninjos", "Bebrai", "Kiškiai", "Ereliai"]
    teams, names = [], set()
    while len(teams) < n_teams:
        name = f"{random.choice(adjectives)} {random.choice(nouns)} {random.randint(1, 99)}"
        if name in names:
            continue
        names.add(name)
        members = random.sample(players, random.randint(2, 6))
        teams.append({"name": name, "captainId": members[0]["_id"], "createdAt": now - timedelta(days=380),
                      "members": [{"userId": m["_id"], "role": "captain" if k == 0 else "member",
                                   "joinedAt": now - timedelta(days=380)} for k, m in enumerate(members)]})
    # demo komanda: Žana (kapitonė) + Darius
    zana, darius = users[2], users[4]
    teams.append({"name": "Demo komanda", "captainId": zana["_id"], "createdAt": now - timedelta(days=30),
                  "members": [{"userId": zana["_id"], "role": "captain", "joinedAt": now - timedelta(days=30)},
                              {"userId": darius["_id"], "role": "member", "joinedAt": now - timedelta(days=30)}]})
    db.teams.insert_many(teams)

    # --- rezervacijos + žaidimai (praeityje ir ateityje)
    bookings, sessions, used = [], [], set()
    reviews = []
    for _ in range(n_bookings):
        room = random.choice(rooms)
        day = date.today() + timedelta(days=random.randint(-365, 14))
        # savaitgaliai ir vakarai populiaresni – kad heatmap būtų įdomus
        weights = [1, 1, 2, 2, 3, 5, 6, 4] if day.weekday() < 5 else [3, 4, 5, 6, 6, 6, 5, 3]
        t = random.choices(SLOT_TIMES, weights=weights)[0]
        start = datetime.combine(day, time.fromisoformat(t))
        if (room["_id"], start) in used:
            continue
        used.add((room["_id"], start))
        # 60 % komandų, 40 % pavienių žaidėjų (Pareto → daug vienkartinių, keli lojalūs)
        if random.random() < 0.6:
            team = random.choice(teams)
            booker_id = team["captainId"]
            players_cnt = max(room["minPlayers"], min(room["maxPlayers"], len(team["members"])))
        else:
            team = None
            booker_id = players[min(len(players) - 1, int(random.paretovariate(1.2)) - 1
                                    + random.randint(0, len(players) // 3) * (random.random() < 0.7))]["_id"]
            players_cnt = random.randint(room["minPlayers"], room["maxPlayers"])
        price = room["pricePerPlayer"] * players_cnt
        past = start < now
        cancelled = random.random() < 0.06
        status = "cancelled" if cancelled else ("completed" if past else "confirmed")
        created = start - timedelta(days=random.randint(1, 20), hours=random.randint(0, 12))
        b = {"_id": ObjectId(), "roomId": room["_id"], "locationId": room["locationId"], "teamId": team["_id"] if team else None,
             "bookedBy": booker_id, "startAt": start, "endAt": start + timedelta(minutes=60),
             "playersCount": players_cnt, "status": status, "active": not cancelled,
             "totalPrice": price, "promoCode": None,
             "payment": {"method": random.choice(["card", "card", "voucher"]), "amount": price, "paidAt": created},
             "createdAt": created}
        bookings.append(b)
        common = {"user": str(booker_id), "room": str(room["_id"]),
                  "loc": str(room["locationId"]), "booking": str(b["_id"])}
        for _v in range(random.randint(1, 4)):
            ev(created - timedelta(minutes=random.randint(5, 600)), "room_view", **common)
        ev(created - timedelta(minutes=3), "booking_held", **common, meta={"startAt": start})
        ev(created, "booking_confirmed", **common, value=price, meta={"startAt": start, "players": players_cnt})
        if cancelled:
            ev(created + timedelta(days=1), "booking_cancelled", **common)

        if status == "completed":
            # Pabėgimo tikimybė priklauso nuo sudėtingumo ir komandos dydžio
            p_escape = min(0.95, 1.05 - room["difficulty"] * 0.15 + players_cnt * 0.03)
            escaped = random.random() < p_escape
            n_hints = min(6, max(0, int(random.gauss(room["difficulty"] * 0.8, 1))))
            hints = sorted(random.sample(range(1, 7), n_hints))
            hints_used = [{"hintId": f"h{h}", "atSec": max(60, min(3500, int(h * 500 + random.gauss(0, 200))))} for h in hints]
            time_sec = int(random.uniform(2400, 3590)) if escaped else 3600
            penalty = sum(120 for _ in hints_used)
            sessions.append({"bookingId": b["_id"], "roomId": room["_id"], "teamId": team["_id"] if team else None,
                             "_booker": booker_id, "gameMasterId": gm_id,
                             "startedAt": start, "finishedAt": start + timedelta(seconds=time_sec),
                             "escaped": escaped, "timeSec": time_sec, "penaltySec": penalty,
                             "finalTimeSec": time_sec + penalty, "hintsUsed": hints_used})
            ev(start, "game_started", **common)
            for h in hints_used:
                ev(start + timedelta(seconds=h["atSec"]), "hint_used", **common, value=h["atSec"],
                   meta={"hintId": h["hintId"]})
            ev(start + timedelta(seconds=time_sec), "game_finished", **common, value=time_sec + penalty,
               meta={"escaped": escaped, "hints": n_hints, "players": players_cnt})
            if random.random() < 0.3:
                rating = max(1, min(5, round(random.gauss(4.2, 0.8))))
                reviews.append({"bookingId": b["_id"], "roomId": room["_id"], "userId": booker_id,
                                "rating": rating, "text": random.choice(REVIEW_TEXTS),
                                "createdAt": start + timedelta(hours=random.randint(2, 48))})

    # demo: šiandienos rezervacija „Siaubo ligoninei“
    demo_room, demo_team = rooms[4], teams[-1]
    for t in reversed(SLOT_TIMES):
        start = datetime.combine(date.today(), time.fromisoformat(t))
        if (demo_room["_id"], start) not in used:
            break
    used.add((demo_room["_id"], start))
    price = demo_room["pricePerPlayer"] * 4
    bookings.append({"_id": ObjectId(), "roomId": demo_room["_id"], "locationId": demo_room["locationId"],
                     "teamId": demo_team["_id"], "bookedBy": demo_team["captainId"], "startAt": start,
                     "endAt": start + timedelta(minutes=60), "playersCount": 4, "status": "confirmed",
                     "active": True, "totalPrice": price, "promoCode": None,
                     "payment": {"method": "card", "amount": price, "paidAt": now - timedelta(days=2)},
                     "createdAt": now - timedelta(days=2)})
    db.bookings.insert_many(bookings)
    bookers = {x["bookingId"]: x.pop("_booker") for x in sessions}
    if sessions:
        db.game_sessions.insert_many(sessions)
    if reviews:
        db.reviews.insert_many(reviews)

    # --- computed laukai: žaidėjų statistika
    team_members = {t["_id"]: [m["userId"] for m in t["members"]] for t in teams}
    stats: dict = {}
    for s_ in sessions:
        for uid in team_members.get(s_["teamId"]) or [bookers[s_["bookingId"]]]:
            st = stats.setdefault(uid, {"games": 0, "escapes": 0, "rooms": set()})
            st["games"] += 1
            st["escapes"] += int(s_["escaped"])
            st["rooms"].add(s_["roomId"])
    if stats:
        db.users.bulk_write([UpdateOne({"_id": uid}, {"$set": {"stats": {
            "games": st["games"], "escapes": st["escapes"], "rooms": list(st["rooms"])}}})
            for uid, st in stats.items()])

    # --- computed laukai: kambario reitingas
    for row in db.reviews.aggregate([{"$group": {"_id": "$roomId", "avg": {"$avg": "$rating"}, "n": {"$sum": 1}}}]):
        db.rooms.update_one({"_id": row["_id"]}, {"$set": {"rating": {"avg": round(row["avg"], 2), "count": row["n"]}}})

    # --- Redis rekordų lentelės
    for s in sessions:
        if s["escaped"] and s["teamId"]:
            record_result(str(s["roomId"]), str(s["teamId"]), s["finalTimeSec"], s["startedAt"].strftime("%Y%m"),
                          len(s["hintsUsed"]))

    # --- promo kodai ir kuponai
    db.promo_codes.insert_many([
        {"code": "RUDUO20", "discountPct": 20, "validFrom": now - timedelta(days=30),
         "validTo": now + timedelta(days=60), "maxUses": 100, "usedCount": 0},
        {"code": "STUDENTAS", "discountPct": 15, "validFrom": now - timedelta(days=300),
         "validTo": now + timedelta(days=300), "maxUses": 1000, "usedCount": 0},
    ])
    db.vouchers.insert_one({"code": "DOVANA-2026", "value": 100.0, "remaining": 100.0,
                            "expiresAt": now + timedelta(days=365), "purchasedBy": players[0]["_id"]})

    # --- naršytojai be rezervacijų (piltuvėliui)
    for _ in range(n_bookings):
        u, room = random.choice(players), random.choice(rooms)
        ts = now - timedelta(minutes=random.randint(0, 525600))
        common = {"user": str(u["_id"]), "room": str(room["_id"]), "loc": str(room["locationId"])}
        ev(ts, "room_view", **common)
        if random.random() < 0.15:
            ev(ts + timedelta(minutes=2), "booking_held", **common)

    # --- paieškos įvykiai
    queries = ["siaubo", "vaikams", "detektyvas", "kosmosas", "lengvas", "8 žmonėms", "gimtadienis", "zombiai", "pabėgimas"]
    for _ in range(n_bookings // 2):
        ev(now - timedelta(minutes=random.randint(0, 525600)), "search",
           user=str(random.choice(players)["_id"]), value=random.randint(0, 6), meta={"q": random.choice(queries)})

    # --- ClickHouse (paketais)
    for i in range(0, len(events), 50_000):
        ch().insert("events", events[i:i + 50_000], column_names=COLUMNS)

    n_rooms = reindex_all_rooms()
    print(f"Paruošta: {len(LOCATIONS)} filialai, {n_rooms} kambariai, {len(users)} vartotojai, "
          f"{len(teams)} komandos, {len(bookings)} rezervacijos, {len(sessions)} žaidimai, "
          f"{len(reviews)} atsiliepimai, {len(events)} įvykiai ClickHouse.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", type=int, default=1500)
    ap.add_argument("--teams", type=int, default=300)
    ap.add_argument("--bookings", type=int, default=12000)
    a = ap.parse_args()
    seed(a.users, a.teams, a.bookings)
