"""Wspólne elementy: konfiguracja, baza SQLite, klienci API z limitem zapytań."""

import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

KATALOG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLIK_KONFIGURACJI = os.path.join(KATALOG, "config.json")
PLIK_BAZY = os.environ.get("SERIALE_DB", os.path.join(KATALOG, "seriale.db"))

SA_URL = os.environ.get("SA_BASE_URL", "https://api.movieofthenight.com/v4")
TMDB_URL = os.environ.get("TMDB_BASE_URL", "https://api.themoviedb.org/3")

JAKOSCI = ["sd", "hd", "qhd", "uhd"]


def teraz():
    return int(time.time())


def miesiac():
    return datetime.now(timezone.utc).strftime("%Y-%m")


def log(*a):
    print(*a, flush=True)


def wczytaj_konfiguracje():
    with open(PLIK_KONFIGURACJI, encoding="utf-8") as f:
        return json.load(f)


# --------------------------------------------------------------------------
# Baza danych
# --------------------------------------------------------------------------
SCHEMAT = """
CREATE TABLE IF NOT EXISTS seriale (
    id            TEXT PRIMARY KEY,      -- id w Streaming Availability
    imdb_id       TEXT,
    tmdb_id       TEXT,                  -- np. "tv/1399"
    tytul         TEXT,
    tytul_oryg    TEXT,
    rok_od        INTEGER,
    rok_do        INTEGER,
    sezony        INTEGER,
    odcinki       INTEGER,
    gatunki       TEXT,                  -- JSON: ["Drama", ...]
    ocena         INTEGER,               -- 0-100
    opis          TEXT,
    tworcy        TEXT,                  -- JSON
    obsada        TEXT,                  -- JSON
    plakat        TEXT,                  -- URL
    popularnosc   INTEGER,               -- miejsce w rankingu (1 = najpopularniejszy)
    zaktualizowano INTEGER
);

CREATE TABLE IF NOT EXISTS dostepnosc (
    serial_id   TEXT NOT NULL,
    serwis      TEXT NOT NULL,
    typ         TEXT,                    -- subscription / free / addon
    jakosc      TEXT,                    -- sd / hd / qhd / uhd
    audio       TEXT,                    -- JSON: ["pol", "eng"]
    napisy      TEXT,                    -- JSON
    napisy_cc   TEXT,                    -- JSON: napisy dla niesłyszących
    od          INTEGER,                 -- od kiedy dostępny (unix)
    wygasa      INTEGER,                 -- ostatni dzień (unix) lub NULL
    link        TEXT,
    widziano    INTEGER,                 -- kiedy ostatnio potwierdzono
    PRIMARY KEY (serial_id, serwis)
);

CREATE TABLE IF NOT EXISTS historia (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    data        INTEGER NOT NULL,
    serial_id   TEXT NOT NULL,
    serwis      TEXT NOT NULL,
    zdarzenie   TEXT NOT NULL,           -- dodano / usunieto / zmiana
    szczegoly   TEXT                     -- JSON
);
CREATE INDEX IF NOT EXISTS historia_data ON historia(data);

CREATE TABLE IF NOT EXISTS zapowiedzi (
    serial_id   TEXT NOT NULL,
    serwis      TEXT NOT NULL,
    typ         TEXT NOT NULL,           -- expiring (znika) / upcoming (wchodzi)
    data        INTEGER,                 -- NULL = data nieznana
    sezon       INTEGER,
    link        TEXT,
    PRIMARY KEY (serial_id, serwis, typ, sezon)
);

CREATE TABLE IF NOT EXISTS tmdb (
    serial_id     TEXT PRIMARY KEY,
    tytul_pl      TEXT,
    opis_pl       TEXT,
    dlugosc_med   INTEGER,               -- mediana długości odcinka (min)
    dlugosc_min   INTEGER,
    dlugosc_max   INTEGER,
    swiat         TEXT,                  -- JSON: {"DE": ["Netflix", ...], ...}
    plakat        TEXT,
    pobrano       INTEGER,
    sezony_przy_pobraniu INTEGER
);

CREATE TABLE IF NOT EXISTS stan (
    klucz   TEXT PRIMARY KEY,
    wartosc TEXT
);

CREATE TABLE IF NOT EXISTS budzet (
    miesiac   TEXT PRIMARY KEY,
    zapytania INTEGER NOT NULL DEFAULT 0
);
"""


def otworz_baze(sciezka=None):
    db = sqlite3.connect(sciezka or PLIK_BAZY)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMAT)
    return db


def stan_get(db, klucz, domyslnie=None):
    r = db.execute("SELECT wartosc FROM stan WHERE klucz=?", (klucz,)).fetchone()
    return json.loads(r[0]) if r else domyslnie


def stan_set(db, klucz, wartosc):
    db.execute("INSERT INTO stan(klucz, wartosc) VALUES(?,?) "
               "ON CONFLICT(klucz) DO UPDATE SET wartosc=excluded.wartosc",
               (klucz, json.dumps(wartosc, ensure_ascii=False)))
    db.commit()


def stan_del(db, klucz):
    db.execute("DELETE FROM stan WHERE klucz=?", (klucz,))
    db.commit()


def zuzyte_w_miesiacu(db):
    r = db.execute("SELECT zapytania FROM budzet WHERE miesiac=?", (miesiac(),)).fetchone()
    return r[0] if r else 0


# --------------------------------------------------------------------------
# Streaming Availability API (z twardym limitem miesięcznym)
# --------------------------------------------------------------------------
class LimitWyczerpany(Exception):
    pass


class BladKlucza(Exception):
    pass


class StreamingAvailability:
    def __init__(self, klucz, db, limit):
        self.klucz = klucz
        self.db = db
        self.limit = limit
        self.w_tym_uruchomieniu = 0

    def zostalo(self):
        return self.limit - zuzyte_w_miesiacu(self.db)

    def _policz(self):
        self.db.execute("INSERT INTO budzet(miesiac, zapytania) VALUES(?,1) "
                        "ON CONFLICT(miesiac) DO UPDATE SET zapytania=zapytania+1", (miesiac(),))
        self.db.commit()
        self.w_tym_uruchomieniu += 1

    def get(self, sciezka, parametry):
        if self.zostalo() <= 0:
            raise LimitWyczerpany(f"osiągnięto limit {self.limit} zapytań w miesiącu {miesiac()}")
        url = f"{SA_URL}{sciezka}?{urllib.parse.urlencode(parametry)}"
        req = urllib.request.Request(url, headers={"X-API-Key": self.klucz, "Accept": "application/json",
                                                   "User-Agent": "seriale-pl/1.0"})
        for proba in range(5):
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    dane = json.loads(r.read().decode("utf-8"))
                self._policz()
                return dane
            except urllib.error.HTTPError as e:
                tresc = e.read().decode("utf-8", "replace")[:300]
                if e.code in (401, 403):
                    raise BladKlucza(f"API odrzuciło klucz (HTTP {e.code}): {tresc}")
                if e.code == 429:
                    self._policz()
                    if "quota" in tresc.lower() or proba == 4:
                        raise LimitWyczerpany(f"API zgłosiło wyczerpanie limitu: {tresc}")
                    czekaj = int(e.headers.get("Retry-After", "0") or 0) or 10 * (proba + 1)
                    log(f"   limit na minutę, czekam {czekaj}s...")
                    time.sleep(czekaj)
                    continue
                if e.code >= 500 and proba < 4:
                    time.sleep(5 * (proba + 1))
                    continue
                raise RuntimeError(f"Błąd API HTTP {e.code} dla {sciezka}: {tresc}")
            except urllib.error.URLError as e:
                if proba < 4:
                    time.sleep(5 * (proba + 1))
                    continue
                raise RuntimeError(f"Brak połączenia z API: {e.reason}")
        raise RuntimeError("Zbyt wiele nieudanych prób")


# --------------------------------------------------------------------------
# TMDB (darmowe, bez limitu miesięcznego; ok. 40 zapytań/s)
# --------------------------------------------------------------------------
class TMDB:
    def __init__(self, klucz, jezyk):
        self.klucz = klucz
        self.jezyk = jezyk
        self.bearer = len(klucz) > 60          # długi "Read Access Token" vs krótki "API Key"
        self.zapytania = 0

    def get(self, sciezka, parametry=None):
        p = dict(parametry or {})
        p["language"] = self.jezyk
        naglowki = {"Accept": "application/json", "User-Agent": "seriale-pl/1.0"}
        if self.bearer:
            naglowki["Authorization"] = f"Bearer {self.klucz}"
        else:
            p["api_key"] = self.klucz
        url = f"{TMDB_URL}{sciezka}?{urllib.parse.urlencode(p)}"
        for proba in range(5):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=naglowki), timeout=30) as r:
                    self.zapytania += 1
                    time.sleep(0.03)
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return None
                if e.code == 401:
                    raise BladKlucza("TMDB odrzuciło klucz (HTTP 401)")
                if e.code == 429 or e.code >= 500:
                    time.sleep(int(e.headers.get("Retry-After", "0") or 0) or 2 * (proba + 1))
                    continue
                raise RuntimeError(f"Błąd TMDB HTTP {e.code} dla {sciezka}")
            except urllib.error.URLError:
                time.sleep(3 * (proba + 1))
        return None


# --------------------------------------------------------------------------
# Zapis serialu i jego dostępności (wspólne dla pełnego pobrania i zmian)
# --------------------------------------------------------------------------
def _lista(x):
    return sorted(set(x))


def zapisz_serial(db, show, popularnosc=None):
    plakat = ((show.get("imageSet") or {}).get("verticalPoster") or {}).get("w240")
    db.execute("""
        INSERT INTO seriale(id, imdb_id, tmdb_id, tytul, tytul_oryg, rok_od, rok_do, sezony, odcinki,
                            gatunki, ocena, opis, tworcy, obsada, plakat, popularnosc, zaktualizowano)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            imdb_id=excluded.imdb_id, tmdb_id=excluded.tmdb_id, tytul=excluded.tytul,
            tytul_oryg=excluded.tytul_oryg, rok_od=excluded.rok_od, rok_do=excluded.rok_do,
            sezony=excluded.sezony, odcinki=excluded.odcinki, gatunki=excluded.gatunki,
            ocena=excluded.ocena, opis=excluded.opis, tworcy=excluded.tworcy, obsada=excluded.obsada,
            plakat=COALESCE(excluded.plakat, seriale.plakat),
            popularnosc=COALESCE(excluded.popularnosc, seriale.popularnosc),
            zaktualizowano=excluded.zaktualizowano
    """, (
        show["id"], show.get("imdbId"), show.get("tmdbId"), show.get("title"), show.get("originalTitle"),
        show.get("firstAirYear") or show.get("releaseYear"), show.get("lastAirYear"),
        show.get("seasonCount"), show.get("episodeCount"),
        json.dumps([g.get("name") for g in show.get("genres", [])], ensure_ascii=False),
        show.get("rating"), show.get("overview"),
        json.dumps(show.get("creators", []), ensure_ascii=False),
        json.dumps(show.get("cast", [])[:8], ensure_ascii=False),
        plakat, popularnosc, teraz(),
    ))


def dostepnosc_z_show(show, kraj, serwisy, typy):
    """Zwraca {serwis: wiersz} dla naszych serwisów, łącząc kilka opcji tego samego serwisu."""
    wynik = {}
    for o in (show.get("streamingOptions") or {}).get(kraj, []):
        sid = (o.get("service") or {}).get("id")
        if sid not in serwisy or o.get("type") not in typy:
            continue
        w = wynik.setdefault(sid, {"typ": set(), "jakosc": None, "audio": set(), "napisy": set(),
                                   "napisy_cc": set(), "od": None, "wygasa": None, "link": o.get("link")})
        w["typ"].add(o.get("type"))
        q = o.get("quality")
        if q in JAKOSCI and (w["jakosc"] is None or JAKOSCI.index(q) > JAKOSCI.index(w["jakosc"])):
            w["jakosc"] = q
        for a in o.get("audios", []):
            if a.get("language"):
                w["audio"].add(a["language"])
        for s in o.get("subtitles", []):
            jez = (s.get("locale") or {}).get("language")
            if jez:
                (w["napisy_cc"] if s.get("closedCaptions") else w["napisy"]).add(jez)
        if o.get("availableSince"):
            w["od"] = min(w["od"] or o["availableSince"], o["availableSince"])
        if o.get("expiresOn"):
            w["wygasa"] = min(w["wygasa"] or o["expiresOn"], o["expiresOn"])
    for w in wynik.values():
        w["typ"] = ",".join(sorted(w["typ"]))
        for k in ("audio", "napisy", "napisy_cc"):
            w[k] = _lista(w[k])
    return wynik


def zastosuj_dostepnosc(db, serial_id, nowe, zrodlo):
    """Porównuje nową dostępność z bazą, zapisuje historię i podmienia wiersze."""
    t = teraz()
    stare = {r["serwis"]: r for r in db.execute("SELECT * FROM dostepnosc WHERE serial_id=?", (serial_id,))}
    zmiany = 0
    for sid, w in nowe.items():
        s = stare.get(sid)
        if s is None:
            if zrodlo == "start":      # pierwsze pobranie bazy – to nie są „nowości”
                pass
            else:
                db.execute("INSERT INTO historia(data, serial_id, serwis, zdarzenie, szczegoly) VALUES(?,?,?,?,?)",
                           (t, serial_id, sid, "dodano", json.dumps({"zrodlo": zrodlo})))
                zmiany += 1
        else:
            szczegoly = {}
            for k in ("audio", "napisy"):
                a, b = set(json.loads(s[k] or "[]")), set(w[k])
                if a != b:
                    szczegoly[k] = {"dodano": sorted(b - a), "usunieto": sorted(a - b)}
            if s["jakosc"] != w["jakosc"]:
                szczegoly["jakosc"] = {"bylo": s["jakosc"], "jest": w["jakosc"]}
            if szczegoly:
                db.execute("INSERT INTO historia(data, serial_id, serwis, zdarzenie, szczegoly) VALUES(?,?,?,?,?)",
                           (t, serial_id, sid, "zmiana", json.dumps(szczegoly, ensure_ascii=False)))
                zmiany += 1
        db.execute("""INSERT OR REPLACE INTO dostepnosc
                      (serial_id, serwis, typ, jakosc, audio, napisy, napisy_cc, od, wygasa, link, widziano)
                      VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                   (serial_id, sid, w["typ"], w["jakosc"], json.dumps(w["audio"]), json.dumps(w["napisy"]),
                    json.dumps(w["napisy_cc"]), w["od"], w["wygasa"], w["link"], t))
    for sid in stare:
        if sid not in nowe:
            usun_dostepnosc(db, serial_id, sid, zrodlo)
            zmiany += 1
    return zmiany


def usun_dostepnosc(db, serial_id, serwis, zrodlo):
    db.execute("DELETE FROM dostepnosc WHERE serial_id=? AND serwis=?", (serial_id, serwis))
    db.execute("INSERT INTO historia(data, serial_id, serwis, zdarzenie, szczegoly) VALUES(?,?,?,?,?)",
               (teraz(), serial_id, serwis, "usunieto", json.dumps({"zrodlo": zrodlo})))


def podsumowanie(tekst):
    """Dopisuje tekst do podsumowania uruchomienia w GitHub Actions (i wypisuje go)."""
    log(tekst)
    plik = os.environ.get("GITHUB_STEP_SUMMARY")
    if plik:
        with open(plik, "a", encoding="utf-8") as f:
            f.write(tekst + "\n")


def wymagaj_env(nazwa, opis):
    v = os.environ.get(nazwa, "").strip()
    if not v:
        sys.exit(f"Brak {nazwa}. {opis}")
    return v
