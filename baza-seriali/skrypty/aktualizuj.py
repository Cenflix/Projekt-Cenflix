#!/usr/bin/env python3
"""
Aktualizacja bazy seriali.

Tryby (--tryb albo zmienna TRYB):
  auto    – domyślnie: pełne pobranie, jeśli potrzebne (pierwsze uruchomienie, co N dni
            albo przerwa dłuższa niż 30 dni), a potem pobranie zmian
  pelne   – wymuś pełne pobranie katalogu
  zmiany  – tylko zmiany od ostatniej aktualizacji
  tmdb    – tylko dane z TMDB (bez zużywania limitu Streaming Availability)

Klucze: zmienne środowiskowe SA_API_KEY (wymagany) i TMDB_API_KEY (opcjonalny).
"""

import argparse
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wspolne import (TMDB, BladKlucza, LimitWyczerpany, StreamingAvailability, dostepnosc_z_show,  # noqa: E402
                     log, otworz_baze, podsumowanie, stan_del, stan_get, stan_set, teraz, usun_dostepnosc,
                     wczytaj_konfiguracje, zapisz_serial, zastosuj_dostepnosc, zuzyte_w_miesiacu)

DZIEN = 86400


def _norm(s):
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


def ustal_serwisy(db, sa, cfg):
    """Sprawdza (raz na 30 dni, 1 zapytanie), które z wybranych serwisów API obsługuje w kraju."""
    cache = stan_get(db, "serwisy")
    if cache and cache.get("kraj") == cfg["kraj"] and teraz() - cache["ts"] < 30 * DZIEN \
            and cache.get("konfig") == [s["id"] for s in cfg["serwisy"]]:
        return cache
    kraj = sa.get(f"/countries/{cfg['kraj']}", {"output_language": cfg["jezyk_danych_api"]})
    api = {s["id"]: s for s in kraj.get("services", [])}
    wybrane, brak = [], []
    for s in cfg["serwisy"]:
        trafienie = s["id"] if s["id"] in api else next(
            (k for k, v in api.items() if _norm(v.get("name")) in (_norm(s["nazwa"]), _norm(s["id"]))), None)
        if not trafienie:
            brak.append(s["nazwa"])
            continue
        typy = api[trafienie].get("streamingOptionTypes", {})
        wybrane.append({"id": trafienie, "nazwa": s["nazwa"], "kolor": api[trafienie].get("themeColorCode"),
                        "typy": [t for t in cfg["typy_dostepu"] if typy.get(t, t == "subscription")]})
    cache = {"ts": teraz(), "kraj": cfg["kraj"], "konfig": [s["id"] for s in cfg["serwisy"]],
             "wybrane": wybrane, "brak": brak,
             "wszystkie": sorted(f"{k} ({v.get('name')})" for k, v in api.items())}
    stan_set(db, "serwisy", cache)
    return cache


def katalogi(serwisy):
    return ",".join(f"{s['id']}.{t}" for s in serwisy["wybrane"] for t in s["typy"])


def pelne_pobranie(db, sa, cfg, serwisy):
    st = stan_get(db, "pelne") or {"start": teraz(), "kursor": None, "pozycja": 0, "strony": 0}
    stan_set(db, "pelne", st)
    ids = {s["id"] for s in serwisy["wybrane"]}
    typy = set(cfg["typy_dostepu"])
    zrodlo = "pelne" if stan_get(db, "ostatnie_pelne") else "start"
    log(f"Pełne pobranie katalogu{' (kontynuacja)' if st['kursor'] else ''}...")
    while True:
        p = {"country": cfg["kraj"], "catalogs": katalogi(serwisy), "show_type": "series",
             "order_by": "popularity_alltime", "output_language": cfg["jezyk_danych_api"]}
        if st["kursor"]:
            p["cursor"] = st["kursor"]
        dane = sa.get("/shows/search/filters", p)
        for show in dane.get("shows", []):
            st["pozycja"] += 1
            zapisz_serial(db, show, popularnosc=st["pozycja"])
            zastosuj_dostepnosc(db, show["id"], dostepnosc_z_show(show, cfg["kraj"], ids, typy), zrodlo)
        st["strony"] += 1
        if dane.get("hasMore") and dane.get("nextCursor"):
            st["kursor"] = dane["nextCursor"]
            stan_set(db, "pelne", st)          # zapisuje też zmiany w bazie (commit)
            if st["strony"] % 10 == 0:
                log(f"   {st['pozycja']} seriali, zapytań w tym miesiącu: {zuzyte_w_miesiacu(db)}")
            continue
        break

    # Czego nie widzieliśmy w tym pełnym przebiegu, to zniknęło z serwisów.
    znikniete = db.execute("SELECT serial_id, serwis FROM dostepnosc WHERE widziano < ?", (st["start"],)).fetchall()
    for r in znikniete:
        usun_dostepnosc(db, r["serial_id"], r["serwis"], "pelne")
    stan_set(db, "ostatnie_pelne", teraz())
    if not stan_get(db, "zmiany_od"):
        stan_set(db, "zmiany_od", st["start"])
    stan_del(db, "pelne")
    db.commit()
    return {"seriali": st["pozycja"], "usunieto": len(znikniete)}


ZMIANY = [("new", "show"), ("new", "season"), ("removed", "show"), ("updated", "show")]
ZAPOWIEDZI = [("expiring", "show"), ("upcoming", "show"), ("upcoming", "season")]


def _stronicuj(sa, parametry):
    kursor = None
    while True:
        p = dict(parametry)
        if kursor:
            p["cursor"] = kursor
        dane = sa.get("/changes", p)
        yield dane
        if dane.get("hasMore") and dane.get("nextCursor"):
            kursor = dane["nextCursor"]
        else:
            return


def pobierz_zmiany(db, sa, cfg, serwisy):
    ids = {s["id"] for s in serwisy["wybrane"]}
    typy = set(cfg["typy_dostepu"])
    start = teraz()
    od = stan_get(db, "zmiany_od") or start - 7 * DZIEN
    najwczesniej = start - 31 * DZIEN + 3600
    if od < najwczesniej:
        podsumowanie(f"⚠️ Przerwa w aktualizacjach dłuższa niż 31 dni – część zmian mogła umknąć "
                     f"(zostaną nadrobione przy najbliższym pełnym pobraniu).")
        od = najwczesniej
    od = max(najwczesniej, od - 6 * 3600)       # mała zakładka na wszelki wypadek

    do_zapisu, usuniecia, liczba_zmian = {}, set(), 0
    for change_type, item_type in ZMIANY:
        p = {"country": cfg["kraj"], "catalogs": katalogi(serwisy), "change_type": change_type,
             "item_type": item_type, "from": od, "output_language": cfg["jezyk_danych_api"]}
        if item_type == "show":
            p["show_type"] = "series"
        for dane in _stronicuj(sa, p):
            for z in dane.get("changes", []):
                if z.get("showType") != "series" or (z.get("service") or {}).get("id") not in ids:
                    continue
                liczba_zmian += 1
                if change_type == "removed":
                    usuniecia.add((z["showId"], z["service"]["id"]))
            for sid, show in (dane.get("shows") or {}).items():
                if show.get("showType") == "series":
                    do_zapisu[show.get("id", sid)] = show

    zmienione = 0
    for sid, show in do_zapisu.items():
        zapisz_serial(db, show)
        if "streamingOptions" in show:
            zmienione += zastosuj_dostepnosc(db, sid, dostepnosc_z_show(show, cfg["kraj"], ids, typy), "zmiany")
    for sid, serwis in usuniecia:   # gdyby obiekt serialu nie miał już opcji – usuń jawnie
        if sid not in do_zapisu or "streamingOptions" not in do_zapisu[sid]:
            if db.execute("SELECT 1 FROM dostepnosc WHERE serial_id=? AND serwis=?", (sid, serwis)).fetchone():
                usun_dostepnosc(db, sid, serwis, "zmiany")
                zmienione += 1
    db.commit()

    # Zapowiedzi: co wkrótce zniknie, co wkrótce wejdzie (tabela budowana od nowa)
    nowe_zapowiedzi = []
    for change_type, item_type in ZAPOWIEDZI:
        p = {"country": cfg["kraj"], "catalogs": katalogi(serwisy), "change_type": change_type,
             "item_type": item_type, "include_unknown_dates": "true", "output_language": cfg["jezyk_danych_api"]}
        if item_type == "show":
            p["show_type"] = "series"
        for dane in _stronicuj(sa, p):
            for sid, show in (dane.get("shows") or {}).items():
                if show.get("showType") == "series":
                    zapisz_serial(db, show)
            for z in dane.get("changes", []):
                if z.get("showType") != "series" or (z.get("service") or {}).get("id") not in ids:
                    continue
                nowe_zapowiedzi.append((z["showId"], z["service"]["id"], change_type, z.get("timestamp"),
                                        z.get("season") if item_type == "season" else 0, z.get("link")))
    db.execute("DELETE FROM zapowiedzi")
    db.executemany("INSERT OR REPLACE INTO zapowiedzi(serial_id, serwis, typ, data, sezon, link) VALUES(?,?,?,?,?,?)",
                   nowe_zapowiedzi)
    stan_set(db, "zmiany_od", start)
    db.commit()
    return {"zmian": liczba_zmian, "seriali_zmienionych": len(do_zapisu), "wpisow_historii": zmienione,
            "zapowiedzi": len(nowe_zapowiedzi)}


def aktualizuj_tmdb(db, cfg, klucz):
    tmdb = TMDB(klucz, cfg["tmdb_jezyk"])
    granica = teraz() - cfg["tmdb_odswiezanie_co_dni"] * DZIEN
    wiersze = db.execute("""
        SELECT s.id, s.tmdb_id, s.sezony FROM seriale s
        LEFT JOIN tmdb t ON t.serial_id = s.id
        WHERE (EXISTS (SELECT 1 FROM dostepnosc d WHERE d.serial_id = s.id)
               OR EXISTS (SELECT 1 FROM zapowiedzi z WHERE z.serial_id = s.id))
          AND s.tmdb_id LIKE 'tv/%'
          AND (t.serial_id IS NULL OR t.pobrano < ? OR IFNULL(t.sezony_przy_pobraniu, -1) != IFNULL(s.sezony, -1))
        ORDER BY (t.serial_id IS NOT NULL), IFNULL(s.popularnosc, 999999)
        LIMIT ?""", (granica, cfg["tmdb_max_seriali_na_uruchomienie"])).fetchall()
    log(f"TMDB: do pobrania {len(wiersze)} seriali")
    zrobione = bledy = 0
    for i, r in enumerate(wiersze, 1):
        nr = r["tmdb_id"].split("/", 1)[1]
        sezony = max(1, min(r["sezony"] or 1, 19))
        try:
            d = tmdb.get(f"/tv/{nr}", {"append_to_response": "watch/providers," +
                                       ",".join(f"season/{n}" for n in range(1, sezony + 1))})
        except BladKlucza:
            raise
        except Exception as e:      # jedna dziwna odpowiedź nie przerywa całości
            bledy += 1
            log(f"   TMDB: pominięto {r['tmdb_id']} ({type(e).__name__}: {e})")
            if bledy >= 10:
                log("   TMDB: zbyt wiele błędów z rzędu – przerywam, reszta przy następnym uruchomieniu")
                break
            continue
        bledy = 0
        if d is None:
            db.execute("INSERT OR REPLACE INTO tmdb(serial_id, pobrano, sezony_przy_pobraniu) VALUES(?,?,?)",
                       (r["id"], teraz(), r["sezony"]))
            continue
        dlugosci = [e["runtime"] for n in range(1, sezony + 1)
                    for e in (d.get(f"season/{n}") or {}).get("episodes", []) if e.get("runtime")]
        if not dlugosci:
            dlugosci = [x for x in d.get("episode_run_time", []) if x]
        swiat = {}
        for kraj, w in ((d.get("watch/providers") or {}).get("results") or {}).items():
            nazwy = sorted({p["provider_name"] for k in ("flatrate", "free", "ads") for p in w.get(k, [])})
            if nazwy:
                swiat[kraj] = nazwy
        db.execute("""INSERT OR REPLACE INTO tmdb(serial_id, tytul_pl, opis_pl, dlugosc_med, dlugosc_min, dlugosc_max,
                      swiat, plakat, pobrano, sezony_przy_pobraniu) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                   (r["id"], d.get("name"), d.get("overview") or None,
                    int(statistics.median(dlugosci)) if dlugosci else None,
                    min(dlugosci) if dlugosci else None, max(dlugosci) if dlugosci else None,
                    json.dumps(swiat, ensure_ascii=False),
                    f"https://image.tmdb.org/t/p/w342{d['poster_path']}" if d.get("poster_path") else None,
                    teraz(), r["sezony"]))
        zrobione += 1
        if i % 200 == 0:
            db.commit()
            log(f"   TMDB: {i}/{len(wiersze)}")
    db.commit()
    return {"seriali": zrobione, "zapytan": tmdb.zapytania}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tryb", default=os.environ.get("TRYB") or "auto",
                    choices=["auto", "pelne", "zmiany", "tmdb"])
    tryb = ap.parse_args().tryb
    cfg = wczytaj_konfiguracje()
    db = otworz_baze()
    blad = None

    podsumowanie(f"## Aktualizacja bazy seriali (tryb: {tryb})\n")
    sa_klucz = os.environ.get("SA_API_KEY", "").strip()
    if tryb != "tmdb":
        if not sa_klucz:
            sys.exit("Brak SA_API_KEY – dodaj klucz Streaming Availability w Settings → Secrets → Actions.")
        sa = StreamingAvailability(sa_klucz, db, cfg["limit_zapytan_miesiecznie"])
        try:
            serwisy = ustal_serwisy(db, sa, cfg)
            podsumowanie("Serwisy: " + ", ".join(s["nazwa"] for s in serwisy["wybrane"]))
            if serwisy["brak"]:
                podsumowanie(f"⚠️ API nie obsługuje w tym kraju: {', '.join(serwisy['brak'])}. "
                             f"Dostępne serwisy: {', '.join(serwisy['wszystkie'])}")
            ostatnie = stan_get(db, "ostatnie_pelne")
            zmiany_od = stan_get(db, "zmiany_od")
            potrzebne_pelne = (tryb == "pelne" or stan_get(db, "pelne") is not None or not ostatnie
                               or teraz() - ostatnie > cfg["pelne_odswiezenie_co_dni"] * DZIEN
                               or (zmiany_od and teraz() - zmiany_od > 30 * DZIEN))
            if potrzebne_pelne and tryb != "zmiany":
                w = pelne_pobranie(db, sa, cfg, serwisy)
                podsumowanie(f"- Pełne pobranie zakończone: {w['seriali']} seriali, "
                             f"zniknęło z serwisów: {w['usunieto']}")
            if tryb != "pelne" and stan_get(db, "pelne") is None:
                w = pobierz_zmiany(db, sa, cfg, serwisy)
                podsumowanie(f"- Zmiany: {w['zmian']} zmian w API, {w['seriali_zmienionych']} seriali odświeżonych, "
                             f"{w['wpisow_historii']} wpisów w historii, {w['zapowiedzi']} zapowiedzi")
        except LimitWyczerpany as e:
            podsumowanie(f"⏸️ Limit zapytań wyczerpany ({e}). Postęp zapisany – reszta przy kolejnym "
                         f"uruchomieniu w nowym miesiącu.")
        except BladKlucza as e:
            blad = str(e)
        except Exception as e:   # zapisz to, co się udało, i pokaż błąd
            blad = f"{type(e).__name__}: {e}"
        db.commit()
        podsumowanie(f"- Zapytania Streaming Availability: {sa.w_tym_uruchomieniu} w tym uruchomieniu, "
                     f"{zuzyte_w_miesiacu(db)}/{cfg['limit_zapytan_miesiecznie']} w tym miesiącu")

    tmdb_klucz = os.environ.get("TMDB_API_KEY", "").strip()
    if tmdb_klucz:
        try:
            w = aktualizuj_tmdb(db, cfg, tmdb_klucz)
            podsumowanie(f"- TMDB: zaktualizowano {w['seriali']} seriali ({w['zapytan']} zapytań, bez limitu)")
        except BladKlucza as e:
            blad = blad or str(e)
    else:
        podsumowanie("- TMDB: pominięto (brak TMDB_API_KEY) – bez długości odcinków i mapy świata")

    n = db.execute("SELECT COUNT(DISTINCT serial_id) FROM dostepnosc").fetchone()[0]
    podsumowanie(f"- Seriali dostępnych w bazie: **{n}**")
    db.close()
    if blad:
        podsumowanie(f"\n❌ Błąd: {blad}")
        sys.exit(1)


if __name__ == "__main__":
    main()
