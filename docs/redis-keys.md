# Redis raktų schema

| Raktas | Tipas | TTL | Paskirtis | Kur kode |
|---|---|---|---|---|
| `session:{token}` | STRING (JSON) | 24 h, slenkantis | prisijungę vartotojai | `routers/auth.py`, `deps.py` |
| `rate:login:{ip}` | STRING (INCR) | 60 s | prisijungimo bandymų ribojimas | `routers/auth.py` |
| `hold:{roomId}:{startAt}` | STRING, `SET NX` | 10 min. | laikinas laiko užlaikymas mokant | `routers/bookings.py` |
| `cache:availability:{roomId}:{date}` | STRING (JSON) | 60 s | užimti laikai; invaliduojama rezervuojant/atšaukiant | `routers/rooms.py` |
| `cache:room:{slug}` | STRING (JSON) | 10 min. | kambario puslapis | `routers/rooms.py` |
| `cache:report:{name}:{params}` | STRING (JSON) | 10 min. | ClickHouse ataskaitos | `routers/reports.py` |
| `lb:room:{roomId}` | ZSET (score = laikas s) | – | kambario rekordai | `routers/leaderboards.py` |
| `lb:month:{yyyymm}` | ZSET | – | mėnesio TOP | `routers/leaderboards.py` |
| `game:{sessionId}` | HASH | 3 h | gyva žaidimo būsena | TODO |
| `room:{roomId}:screen` | Pub/Sub kanalas | – | užuominos į kambario ekraną | TODO |
