#!/usr/bin/env python3
"""
probe_olympia_priceblock.py — diagnostisk: olympia_parser sin PRICE_BY_ID_RE
matchet pris på Saucony-PDP-er (6/6) og på FØRSTE Adidas-PDP, men feilet
(pris=None) på 5 av 6 andre Adidas-PDP-er i probe_olympia_dryrun, trass i at
ALLE størrelser var på lager der. Dumper rå kontekst rundt "price-value-" på
en av de feilende sidene for å se det faktiske avviket (kampanjepris/rabatt-
markup, komma-desimaler, el.l.) før regexen fikses.
Stdlib only. probe.yml (script=probe_olympia_priceblock.py).
"""
from __future__ import annotations
import re
import urllib.request

UA = "Mozilla/5.0 (prislop-probe)"
BASE = "https://www.olympiasport.no"
# Feilet i dryrun: kode=JR7395, "Adidas Supernova Solution 3 Womens Crystal Sky/Silver Metallic/Lime"
SAMPLE = "/adidas-supernova-solution-3-womens-crystal-skysilver-metalliclime"


def get(path):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": UA, "Accept-Language": "nb-NO"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:
        print("feil:", e)
        return ""


def main():
    html = get(SAMPLE)
    print("PDP:", SAMPLE, "  HTTP-lengde:", len(html))

    hits = list(re.finditer(r'id="price-value-\d+"', html, re.I))
    print(f"\n{len(hits)} 'id=\"price-value-N\"'-treff totalt")
    for m in hits[:6]:
        lo, hi = max(0, m.start() - 100), min(len(html), m.end() + 300)
        print("  ---")
        print("  ", re.sub(r"\s+", " ", html[lo:hi]))

    print("\n-- class~=prices (full kontekst, 3 første) --")
    for m in list(re.finditer(r'class="[^"]*\bprices\b[^"]*"', html, re.I))[:3]:
        lo, hi = max(0, m.start() - 50), min(len(html), m.end() + 400)
        print("  ---")
        print("  ", re.sub(r"\s+", " ", html[lo:hi]))

    print("\n-- 'kr' i nærheten av 'price' (evt. annen struktur) --")
    for m in list(re.finditer(r'\bkr\b', html, re.I))[:8]:
        lo, hi = max(0, m.start() - 80), min(len(html), m.end() + 80)
        print("  ", re.sub(r"\s+", " ", html[lo:hi]))


if __name__ == "__main__":
    main()
