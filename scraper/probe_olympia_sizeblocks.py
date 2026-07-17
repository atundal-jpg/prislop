#!/usr/bin/env python3
"""
probe_olympia_sizeblocks.py (v2) — diagnostisk: v1 viste at data-productid KUN
sitter på "Velg variant"-knappene (input) og på ÉN ytre div (default-valgt
størrelse) — de 12-13 ".prices"/".additional-details"-blokkene (som matcher
antall størrelser i lager-ord-skanningen) er IKKE selv tagget med
data-productid. Denne runden dumper konteksten RUNDT hver slik blokk (300 tegn
før, 600 etter) for å finne den faktiske identifikator-mekanismen (id=, annen
data-attributt, eller ren DOM-rekkefølge/indeks) som binder blokk til
størrelse — nødvendig for en presis pris/lager-per-størrelse-parser.
Stdlib only. probe.yml (script=probe_olympia_sizeblocks.py).
"""
from __future__ import annotations
import re
import urllib.request

UA = "Mozilla/5.0 (prislop-probe)"
BASE = "https://www.olympiasport.no"
SAMPLE = "/adidas-supernova-rise-3-crystal-jadesilver-metallic"


def get(path):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": UA, "Accept-Language": "nb-NO"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:
        print("feil:", e)
        return ""


def dump_context(html, needle_re, label, max_hits=4):
    print(f"\n### {label} ###")
    hits = list(re.finditer(needle_re, html, re.I))
    print(f"{len(hits)} treff totalt, viser {min(max_hits, len(hits))}")
    for m in hits[:max_hits]:
        lo, hi = max(0, m.start() - 300), min(len(html), m.end() + 600)
        chunk = re.sub(r"\s+", " ", html[lo:hi])
        print("  ---")
        print("  ", chunk)


def main():
    html = get(SAMPLE)
    print("PDP:", SAMPLE, "  HTTP-lengde:", len(html))

    dump_context(html, r'class="[^"]*\bprices\b[^"]*"', "class~=prices")
    dump_context(html, r'class="[^"]*\badditional-details\b[^"]*"', "class~=additional-details")
    dump_context(html, r'legg i handlekurv', "tekst: legg i handlekurv")
    dump_context(html, r'utsolgt', "tekst: utsolgt")
    dump_context(html, r'\bid="[^"]*\d{6}[^"]*"', "id= med 6-sifret tall (mulig productid-bærer)")


if __name__ == "__main__":
    main()
