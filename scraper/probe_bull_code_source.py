#!/usr/bin/env python3
"""
probe_bull_code_source.py — HVOR i markupen fant bull_parser koden?

Bakgrunn (27. juli, rett etter PR #26): første harvest med den nye parseren ga
648 Bull-tilbud på 648 URL-er (bra — én rad per URL), men bare 634 distinkte
store_sku. Åtte koder satt på flere URL-er, og flere av dem på HELT ulike
produkter:

  2632400-SHAKEOUT  -> Xodus Ultra 3, Xodus Ultra 4, Triumph 23,
                       Triumph 23 GTX, Triumph 23 Wide   (5 produkter!)
  1170330-BLK       -> Peregrine 15, Peregrine 15 GTX, Peregrine 16, Ride TR2
  1164155-TLS       -> Saucony Endorphin Pro 4 dame OG Kiprun Kipsummit Race

Ingen dekning gikk tapt (SKU-broen er nøklet på (sku, product_id), så koder på
ulike produkter kan ikke slå sammen rader), men koden er attribuert til sko den
ikke tilhører. Mistanken er den UFORANKREDE fri-tekst-grenen i bull_parser:

    if not code and (cm := CODE_RE.search(html)): ...

Den har alltid vært der, men var ufarlig så lenge CODE_RE kun kjente Asics
(4 siffer + bokstav + 3 siffer) og Hoka (7 siffer + 2-5 bokstaver). Den nye
Kiprun-grenen \\d{6,7}-[A-Za-z]{2,8} er mye bredere og treffer trolig koder i
«Relaterte produkter»-karusellen. Nøyaktig samme klasse feil som Bull-
fraktbanneret i juli: første regex-treff i rå HTML.

Denne proben BEKREFTER eller AVKREFTER det før parseren røres igjen. Per URL:
  - hvilken av de tre kildene som gir treff (og:image / etikett / fri tekst),
  - hva hver kilde ville gitt hver for seg,
  - 120 tegn kontekst rundt fri-tekst-treffet, så vi ser hvilken blokk det står i,
  - om treffet ligger FØR eller ETTER «Relaterte produkter» i dokumentet.

Kjøres via probe.yml (script=probe_bull_code_source.py). Kun stdlib.
"""
from __future__ import annotations
import re
import sys
import types
import urllib.request

if "psycopg2" not in sys.modules:
    _pg = types.ModuleType("psycopg2")
    _pg.extras = types.ModuleType("psycopg2.extras")
    sys.modules["psycopg2"] = _pg
    sys.modules["psycopg2.extras"] = _pg.extras

import bull_parser

BASE = "https://bull-ski-kajakk.no"
HEADERS = {"User-Agent": "Mozilla/5.0 (prislop)",
           "Accept-Language": "nb-NO,nb;q=0.9,no;q=0.8,en;q=0.5"}

# URL-ene som deler kode i prod (siste harvest). Første i hvert par/gruppe er
# den koden SANNSYNLIGVIS hører til.
URLS = [
    "/sko/lopesko/terrengsko/saucony-xodus-ultra-3-herre",
    "/sko/lopesko/terrengsko/saucony-xodus-ultra-4-herre",
    "/sko/lopesko/treningssko/saucony-triumph-23-herre-6",
    "/sko/lopesko/treningssko/saucony-triumph-23-gore-tex-herre-0",
    "/sko/lopesko/treningssko/saucony-triumph-23-wide-herre",
    "/sko/lopesko/terrengsko/saucony-peregrine-16-herre",
    "/sko/lopesko/terrengsko/saucony-ride-tr2-herre-0",
    "/sko/lopesko/terrengsko/kiprun-kipsummit-race-dame",
    "/sko/lopesko/lettvekt-konkurransesko/saucony-endorphin-pro-4-dame-4",
    "/sko/lopesko/treningssko/saucony-ride-19-herre-0",
    # URL-er som forsvant fra harvesten 12:53 — 404 her betyr at Bull har
    # avlistet dem (alle var allerede utsolgt), ikke at parseren mistet dem.
    "/sko/lopesko/treningssko/saucony-triumph-23-herre",
    "/sko/lopesko/treningssko/saucony-triumph-23-herre-3",
    "/sko/lopesko/treningssko/saucony-triumph-23-dame-2",
    "/sko/lopesko/terrengsko/saucony-xodus-ultra-4-herre-0",
]

TAG_RE = re.compile(r"<[^>]+>")
RELATED_RE = re.compile(r"Relaterte\s+produkter", re.I)


def get(url: str) -> str | None:
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:
        print(f"    fetch-feil: {e}")
        return None


def main() -> int:
    for path in URLS:
        url = BASE + path
        print("=" * 78)
        print(path)
        html = get(url)
        if not html:
            continue

        # Kilde 1: og:image
        im = bull_parser.OG_IMAGE_RE.search(html)
        img = im.group(1) if im else ""
        c_img = bull_parser.CODE_IMG_RE.search(img)
        c_adi = bull_parser.ADIDAS_CODE_IMG_RE.search(img)
        print(f"  og:image      : {img.rsplit('/', 1)[-1] if img else '(mangler)'}")
        print(f"  [1] fra bilde : {c_img.group(1).upper() if c_img else None}"
              f"   (adidas-regel: {c_adi.group(1).upper() if c_adi else None})")

        # Kilde 2: etikett-forankret
        pm = re.search(r"(?:Produktnummer|Art\s*#)[^0-9]{0,40}?" + bull_parser.CODE_RE.pattern,
                       html, re.I)
        print(f"  [2] fra etikett: {pm.group(1).upper() if pm else None}")

        # Kilde 3: uforankret fri tekst — den mistenkte
        fm = bull_parser.CODE_RE.search(html)
        if fm:
            rel = RELATED_RE.search(html)
            hvor = "ETTER «Relaterte produkter»" if rel and fm.start() > rel.start() \
                   else "før «Relaterte produkter»"
            s = max(0, fm.start() - 120)
            ctx = re.sub(r"\s+", " ", TAG_RE.sub(" ", html[s:fm.end() + 60]))
            print(f"  [3] fri tekst  : {fm.group(1).upper()}   ({hvor})")
            print(f"      kontekst   : …{ctx.strip()}…")
        else:
            print("  [3] fri tekst  : None")

        rec = bull_parser.parse(html, url)
        print(f"  => parser gir  : kode={rec['manufacturer_code'] if rec else None!r} "
              f"store_sku={rec['store_sku'] if rec else None!r}")

    print("=" * 78)
    print("Les [1]/[2]/[3]: er koden som havner i basen den etikett-forankrede,")
    print("eller kommer den fra fri-tekst-grenen (og da fra hvilken blokk)?")
    return 0



if __name__ == "__main__":
    sys.exit(main())
