# Užrakinti – escape room tinklo sistema

VU MIF „Nereliacinės duomenų bazės“ projektas.
Backend: **Python FastAPI**. Duomenų bazės: **MongoDB** (pagrindinė), **Redis** (cache, sesijos,
užraktai, rekordai), **ElasticSearch** (pilno teksto paieška), **ClickHouse** (analitika).

## Reikalavimai
- Docker Desktop (Windows – su WSL2; skirkite Docker'iui **bent 4 GB RAM**)
- Git, Python 3.12 (jei leisite backend be Docker), Node.js 20+ (frontend'ui)

## Paleidimas
```bash
cp .env.example .env
docker compose up -d --build        # pirmą kartą užtrunka kelias minutes
docker compose ps                   # visi servisai turi būti "healthy"
docker compose exec backend python -m seed.seed   # testiniai duomenys (~1–2 min.)
```
- API dokumentacija (Swagger): http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- Sveikatos patikra: http://localhost:8000/health

Demo vartotojai (slaptažodis `demo123`): `admin@uzrakinti.lt`, `gm@uzrakinti.lt`, `zaidejas@uzrakinti.lt`.

### Prisijungimas prie DB klientais
| DB | Adresas | Klientas |
|---|---|---|
| MongoDB | `mongodb://localhost:27017/?directConnection=true` | MongoDB Compass |
| Redis | `localhost:6379` | RedisInsight arba `docker compose exec redis redis-cli` |
| ElasticSearch | http://localhost:9200 | naršyklė, Postman, `curl localhost:9200/rooms/_search?pretty` |
| ClickHouse | http://localhost:8123/play (user `app`, pass `app`) | naršyklė, DBeaver |

### Backend be Docker (greitesniam derinimui)
```bash
docker compose up -d mongo redis elasticsearch clickhouse
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp ../.env .env
uvicorn app.main:app --reload
```

### Viską išvalyti
```bash
docker compose down -v   # -v ištrina ir duomenis
```

## Struktūra
```
backend/app/
  main.py          – FastAPI programa, maršrutizatoriai
  config.py        – nustatymai iš .env
  db.py            – prisijungimai prie 4 DB
  init_db.py       – kolekcijos + validatoriai + indeksai, ES indeksas, CH lentelė
  cache.py         – Redis cache pagalbininkas
  events.py        – įvykių rašymas į ClickHouse
  deps.py          – autentifikacija (Redis sesijos), rolės
  routers/         – API endpoint'ai
  services/        – dalykinė logika (ES sinchronizacija ir kt.)
backend/seed/seed.py – testinių duomenų generatorius
docs/              – duomenų modelis, Redis raktų schema, prezentacija
frontend/          – React + Vite
```

## Darbo eiga (Git)
- `main` – visada veikianti versija; tiesiogiai į ją necommitinam.
- Nauja funkcija → `git switch -c feature/<pavadinimas>` → commit → push → Pull Request → kitas komandos narys peržiūri → merge.
- Commit žinutės: `feat: ...`, `fix: ...`, `docs: ...`.
