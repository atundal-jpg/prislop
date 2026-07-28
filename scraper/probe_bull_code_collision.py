#!/usr/bin/env python3
"""
probe_bull_code_collision.py — HVILKEN kodekilde gir den delte koden?

probe_bull_saucony_sweep (28. juli) viste at 12 Saucony-grupper deler én
manufacturer_code på tvers av flere fargevei-URL-er — 23 URL-er tapes fordi
get_or_create_variant nøkler på kode og upsert_offer dropper resten.

bull_parser har tre kodekilder, i prioritert rekkefølge:
  1. og:image-filnavn        (CODE_IMG_RE)      — forankret
  2. «Produktnummer»/«Art#»  (etikett-søk)      — forankret
  3. fri tekst i html[:«Relaterte produkter»]   — UFORANKRET

Fiksen avhenger helt av hvilken som slår til. Er det (3), er dette samme
feilklasse som fraktbanneret og tilbehørs-karusellen: første regex-treff i rå
HTML uten å vite hvilken blokk man står i — og da skal grenen ikke få lov til
å levere en kode den ikke kan forankre. Er det (1), deler sidene og:image, og
fiksen må ligge et annet sted.

Kjøres via probe.yml. Kun stdlib.
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
GROUPS = {
    "Endorphin Speed 5 dame (5 URL-er, alle S11007-144)": [
        "/sko/lopesko/treningssko/saucony-endorphin-speed-5-dame",
        "/sko/lopesko/treningssko/saucony-endorphin-speed-5-dame-3",
        "/sko/lopesko/treningssko/saucony-endorphin-speed-5-dame-4",
        "/sko/lopesko/treningssko/saucony-endorphin-speed-5-dame-5",
        "/sko/lopesko/treningssko/saucony-endorphin-speed-5-dame-7",
    ],
    "Kinvara 16 herre (3 URL-er, alle S21020-172)": [
        "/sko/lopesko/treningssko/saucony-kinvara-16-herre",
        "/sko/lopesko/treningssko/saucony-kinvara-16-herre-0",
        "/sko/lopesko/treningssko/saucony-kinvara-16-herre-1",
    ],
    "Triumph 23 herre (3 av 8 — disse har DISTINKTE koder)": [
        "/sko/lopesko/treningssko/saucony-triumph-23-herre",
        "/sko/lopesko/treningssko/saucony-triumph-23-herre-1",
        "/sko/lopesko/treningssko/saucony-triumph-23-herre-2",
    ],
}


def get_html(url: str) -> str | None:
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (prislop)",
                      "Accept-Language": "nb-NO"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:
        print(f"    fetch-feil: {e}")
        return None


def main():
    for label, paths in GROUPS.items():
        print("=" * 78)
        print(label)
        print("=" * 78)
        for path in paths:
            html = get_html(BASE + path)
            slug = path.rsplit("/", 1)[-1]
            if not html:
                continue

            im = bull_parser.OG_IMAGE_RE.search(html)
            og_img = im.group(1) if im else None
            src1 = None
            if im and (cm := bull_parser.CODE_IMG_RE.search(im.group(1))):
                src1 = cm.group(1).upper()

            pm = re.search(
                r"(?:Produktnummer|Art\s*#)[^0-9]{0,40}?"
                + bull_parser.CODE_RE.pattern, html, re.I)
            src2 = pm.group(1).upper() if pm else None

            rm = bull_parser.RELATED_RE.search(html)
            head = html[:rm.start()] if rm else html
            free = [m.group(1).upper()
                    for m in bull_parser.CODE_RE.finditer(head)]
            uniq = list(dict.fromkeys(free))
            src3 = uniq[0] if uniq else None

            final = bull_parser.parse(html, BASE + path)
            print(f"\n  {slug}")
            print(f"    og:image            = {og_img}")
            print(f"    1) CODE_IMG_RE      = {src1}")
            print(f"    2) Produktnummer    = {src2}")
            print(f"    3) fri tekst[0]     = {src3}   "
                  f"({len(uniq)} distinkte koder i head, {len(free)} treff)")
            if len(uniq) > 1:
                print(f"       alle i head: {uniq[:8]}")
            print(f"    => parse() kode     = "
                  f"{final.get('manufacturer_code') if final else None}"
                  f"   farge={final.get('color') if final else None}")
            print(f"    JSON-LD sku (GTIN)  = {bull_parser._ld_sku(html)}")

    print("\n" + "=" * 78)
    print("TOLKNING")
    print("  Er «=> parse() kode» lik kilde 3 og ulik per farge i kilde 1,")
    print("  kommer den delte koden fra den UFORANKREDE fri-tekst-grenen.")
    print("  Er GTIN distinkt per URL, har vi allerede en trygg nøkkel.")


if __name__ == "__main__":
    main()
