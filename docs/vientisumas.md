# Vientisumas ir lygiagretumas (gynimui)

Kaip sistema užtikrina, kad duomenys liktų teisingi, kai keli vartotojai veikia vienu metu.
Bendra taisyklė: **niekada „pirma patikrink, tada rašyk“ dviem atskiromis užklausomis** (race condition) –
sąlyga tikrinama toje pačioje atominėje operacijoje arba ją užtikrina unikalus indeksas.

| Situacija | Kaip užtikrinama | Kur kode |
|---|---|---|
| Tas pats laikas neparduodamas dukart | Redis `SET NX EX` (užlaikymas 10 min.) + MongoDB unikalus dalinis indeksas `{roomId, startAt}` kai `active=true` | `routers/bookings.py` |
| Vienai rezervacijai – vienas žaidimas | unikalus indeksas `game_sessions.bookingId` → `DuplicateKeyError` → 409 | `routers/games.py` |
| Ta pati užuomina nesiunčiama dukart | Redis `SADD game:{sid}:hints` grąžina 0, jei jau buvo | `routers/games.py` |
| Žaidimas baigiamas tik kartą | `find_one_and_update` su filtru `finishedAt: {$exists: false}` | `routers/games.py` |
| Rekordas atnaujinamas tik pagerėjus | Redis `ZADD ... LT` | `routers/leaderboards.py` |
| Pasiekimas suteikiamas tik kartą | `update_one({"achievements.code": {$ne: code}}, {$push: ...})` | `services/achievements.py` |

**Kodėl žaidimo būsena Redis'e?** Laikmatis ir užuominos keičiasi kas kelias sekundes ir yra laikini (TTL 3 h);
MongoDB įrašomas tik galutinis rezultatas. **Kodėl Pub/Sub + WebSocket?** Ekranas neklausinėja serverio kas sekundę –
vedėjas `PUBLISH`, ekranas per WebSocket gauna žinutę akimirksniu.

## Redis vs MongoDB vaidmenys
- **MongoDB** – tiesos šaltinis; galutinės garantijos (unikalūs indeksai, atominiai update, transakcijos).
- **Redis** – greitis ir laikina būsena: užlaikymai, sesijos, cache, rekordai (ZSET), žaidimo būsena, Pub/Sub.
  Jei Redis raktas pasibaigtų ar dingtų, MongoDB indeksai vis tiek neleistų sugadinti duomenų.
