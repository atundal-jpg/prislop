#!/usr/bin/env python3
"""
probe_olympia_sizeblocks.py — diagnostisk: dumper de PER-STØRRELSE data-blokkene
RenderProductDetails bytter inn (jf. probe_olympia_ajax), for å designe en presis
parser for pris/lager per størrelse.

Knappene i "Velg variant"-gridet gir bare data-productid + størrelsesverdi.
RenderProductDetails leser derimot innhold fra egne containere merket
data-productid="<id>" (`.additional-details`, `.overview-info-wrapper`,
`.prices .overview` osv.) — denne proben finner ALLE slike containere på én
PDP og dumper råteksten deres, slik at pris/lager-mønsteret per størrelse blir
synlig før parseren skrives.
Stdlib only. probe.yml (script=probe_olympia_sizeblocks.py).
"""
from __future__ import annotations
import re
import urllib.request

UA = "Mozilla/5.0 (prislop-probe)"
BASE = "https://www.olympiasport.no"
SAMPLES = [
    "/adidas-supernova-rise-3-crystal-jadesilver-metallic",
    "/saucony-guide-19-womens-blacksilver",
]

# Finn hver data-productid="<id">-bærende blokk (div/li/section) og ta med
# en generøs bit av det som følger, til neste data-productid eller en
# fornuftig lengdegrense.
BLOCK_START = re.compile(r'<(\w+)[^>]*\bdata-productid="(\d+)"[^>]*>', re.I)


def get(path):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": UA, "Accept-Language": "nb-NO"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:
        print("feil:", e)
        return ""


def main():
    for path in SAMPLES:
        print("=" * 74)
        print("PDP:", path)
        html = get(path)
        print("  HTTP-lengde:", len(html))

        starts = list(BLOCK_START.finditer(html))
        print(f"  {len(starts)} data-productid-bærende tagger funnet (alle typer)")
        seen_ids = []
        for m in starts:
            tag, pid = m.group(1), m.group(2)
            if pid in seen_ids:
                continue
            seen_ids.append(pid)
            snippet = html[m.start():m.start() + 900]
            print(f"\n  -- <{tag} data-productid=\"{pid}\"> --")
            print("   ", re.sub(r"\s+", " ", snippet))

        # Direkte søk på kjente RenderProductDetails-mål, uavhengig av tag:
        for cls in ["additional-details", "overview-info-wrapper", "prices",
                    "attribute", "morvare"]:
            hits = list(re.finditer(r'class="[^"]*\b' + re.escape(cls) + r'\b[^"]*"', html, re.I))
            print(f"  class~='{cls}': {len(hits)} treff")


if __name__ == "__main__":
    main()
