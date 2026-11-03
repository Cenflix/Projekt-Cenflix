#!/usr/bin/env python3
"""Tworzy seriale.html: szablon strony + aktualne dane z bazy, w jednym pliku działającym offline."""

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wspolne import KATALOG, log, otworz_baze, stan_get, teraz, wczytaj_konfiguracje  # noqa: E402

SZABLON = os.path.join(KATALOG, "szablon", "strona.html")
WYJSCIE = os.environ.get("SERIALE_HTML", os.path.join(KATALOG, "seriale.html"))

JEZYKI = {
    "pol": "polski", "eng": "angielski", "deu": "niemiecki", "ger": "niemiecki", "fra": "francuski",
    "fre": "francuski", "spa": "hiszpański", "ita": "włoski", "por": "portugalski", "rus": "rosyjski",
    "ukr": "ukraiński", "ces": "czeski", "cze": "czeski", "slk": "słowacki", "slo": "słowacki",
    "hun": "węgierski", "ron": "rumuński", "rum": "rumuński", "nld": "niderlandzki", "dut": "niderlandzki",
    "swe": "szwedzki", "nor": "norweski", "nob": "norweski", "dan": "duński", "fin": "fiński",
    "tur": "turecki", "ell": "grecki", "gre": "grecki", "jpn": "japoński", "kor": "koreański",
    "zho": "chiński", "chi": "chiński", "cmn": "mandaryński", "yue": "kantoński", "hin": "hindi",
    "ara": "arabski", "heb": "hebrajski", "tha": "tajski", "ind": "indonezyjski", "msa": "malajski",
    "may": "malajski", "vie": "wietnamski", "hrv": "chorwacki", "srp": "serbski", "slv": "słoweński",
    "bul": "bułgarski", "lit": "litewski", "lav": "łotewski", "est": "estoński", "cat": "kataloński",
    "tam": "tamilski", "tel": "telugu", "fil": "filipiński", "tgl": "tagalski", "isl": "islandzki",
    "mal": "malajalam", "kan": "kannada", "ben": "bengalski", "mar": "marathi", "eus": "baskijski",
    "baq": "baskijski", "glg": "galicyjski", "fas": "perski", "per": "perski", "urd": "urdu",
}
GATUNKI = {
    "Action": "Akcja", "Adventure": "Przygodowy", "Animation": "Animacja", "Biography": "Biograficzny",
    "Comedy": "Komedia", "Crime": "Kryminał", "Documentary": "Dokumentalny", "Drama": "Dramat",
    "Family": "Familijny", "Fantasy": "Fantasy", "History": "Historyczny", "Horror": "Horror",
    "Music": "Muzyczny", "Musical": "Musical", "Mystery": "Tajemnica", "News": "Informacyjny",
    "Reality": "Reality show", "Romance": "Romans", "Science Fiction": "Sci-fi", "Sport": "Sportowy",
    "Talk Show": "Talk-show", "Thriller": "Thriller", "War": "Wojenny", "Western": "Western",
}


def main():
    cfg = wczytaj_konfiguracje()
    db = otworz_baze()
    serwisy = (stan_get(db, "serwisy") or {}).get("wybrane") or \
        [{"id": s["id"], "nazwa": s["nazwa"], "kolor": None} for s in cfg["serwisy"]]

    dost = {}
    for r in db.execute("SELECT * FROM dostepnosc"):
        dost.setdefault(r["serial_id"], []).append(r)
    zap = {}
    for r in db.execute("SELECT * FROM zapowiedzi"):
        zap.setdefault(r["serial_id"], []).append(r)
    tm = {r["serial_id"]: r for r in db.execute("SELECT * FROM tmdb")}

    jezyki_uzyte, dostawcy, kraje = {}, {}, {}

    def j(kod):
        jezyki_uzyte[kod] = JEZYKI.get(kod, kod)
        return kod

    def idx(slownik, klucz):
        if klucz not in slownik:
            slownik[klucz] = len(slownik)
        return slownik[klucz]

    granica = teraz() - cfg["historia_na_stronie_dni"] * 86400
    z_historia = {r[0] for r in db.execute("SELECT DISTINCT serial_id FROM historia WHERE data >= ?", (granica,))}

    seriale = []
    for s in db.execute("SELECT * FROM seriale ORDER BY IFNULL(popularnosc, 999999), tytul"):
        if s["id"] not in dost and s["id"] not in zap and s["id"] not in z_historia:
            continue
        t = tm.get(s["id"])
        swiat = json.loads(t["swiat"]) if t and t["swiat"] else {}
        mapa = {}
        for kraj, nazwy in swiat.items():
            for n in nazwy:
                mapa.setdefault(idx(dostawcy, n), []).append(idx(kraje, kraj))
        tytul_pl = t["tytul_pl"] if t and t["tytul_pl"] else None
        seriale.append({
            "id": s["id"],
            "t": tytul_pl or s["tytul"],
            "te": s["tytul"] if tytul_pl and tytul_pl != s["tytul"] else None,
            "to": s["tytul_oryg"] if s["tytul_oryg"] not in (s["tytul"], tytul_pl) else None,
            "y": [s["rok_od"], s["rok_do"]],
            "se": s["sezony"], "ep": s["odcinki"],
            "g": [GATUNKI.get(g, g) for g in json.loads(s["gatunki"] or "[]")],
            "r": s["ocena"], "p": s["popularnosc"],
            "o": (t["opis_pl"] if t and t["opis_pl"] else None) or s["opis"],
            "img": s["plakat"] or (t["plakat"] if t else None),
            "c": json.loads(s["tworcy"] or "[]"), "ob": json.loads(s["obsada"] or "[]")[:6],
            "rt": [t["dlugosc_med"], t["dlugosc_min"], t["dlugosc_max"]] if t and t["dlugosc_med"] else None,
            "imdb": s["imdb_id"], "tmdb": s["tmdb_id"],
            "d": [{"s": d["serwis"], "q": d["jakosc"], "a": [j(x) for x in json.loads(d["audio"] or "[]")],
                   "n": [j(x) for x in json.loads(d["napisy"] or "[]")],
                   "cc": [j(x) for x in json.loads(d["napisy_cc"] or "[]")],
                   "od": d["od"], "wy": d["wygasa"], "l": d["link"], "ty": d["typ"]}
                  for d in sorted(dost.get(s["id"], []), key=lambda d: d["serwis"])],
            "z": [{"s": z["serwis"], "ty": z["typ"], "dt": z["data"], "sz": z["sezon"] or None, "l": z["link"]}
                  for z in zap.get(s["id"], [])],
            "w": mapa or None,
        })

    widoczne = {s["id"] for s in seriale}
    historia = [{"dt": h["data"], "id": h["serial_id"], "s": h["serwis"], "e": h["zdarzenie"],
                 "x": json.loads(h["szczegoly"] or "{}")}
                for h in db.execute("SELECT * FROM historia WHERE data >= ? ORDER BY data DESC LIMIT 3000",
                                    (granica,))
                if h["serial_id"] in widoczne]
    for h in historia:
        h["x"].pop("zrodlo", None)

    pierwsze = stan_get(db, "ostatnie_pelne")
    dane = {
        "meta": {"aktualizacja": datetime.now(timezone.utc).isoformat(timespec="minutes"),
                 "kraj": cfg["kraj"], "liczba": sum(1 for s in seriale if s["d"]),
                 "pierwsze_pobranie": pierwsze,
                 "serwisy": [{"id": s["id"], "nazwa": s["nazwa"], "kolor": s.get("kolor")} for s in serwisy]},
        "jez": jezyki_uzyte,
        "dost": list(dostawcy), "kraje": list(kraje),
        "s": seriale, "h": historia,
    }
    with open(SZABLON, encoding="utf-8") as f:
        szablon = f.read()
    znacznik = "/*__DANE__*/null"
    if znacznik not in szablon:
        sys.exit("W szablonie brakuje znacznika /*__DANE__*/null")
    json_txt = json.dumps(dane, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = szablon.replace(znacznik, json_txt, 1)
    with open(WYJSCIE, "w", encoding="utf-8") as f:
        f.write(html)
    log(f"Zapisano {WYJSCIE}: {len(seriale)} seriali, {len(historia)} wpisów historii, "
        f"{len(html) / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
