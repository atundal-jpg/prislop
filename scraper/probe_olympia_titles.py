#!/usr/bin/env python3
"""
probe_olympia_titles.py — diagnostisk: finner en REN modell-tittel (uten farge-
halen) på Olympia-PDP-er, som grunnlag for en produkt-telling (bruker-spørsmål:
hvor mange NYE produkter gir Olympia, og hvor mange matcher eksisterende katalog).

Tile-titlene fra kategori-listingene («Adidas Supernova Solution 3 Womens
Crystal Sky/Silver Metallic/Lime») har farge klistret rett på modellnavnet uten
klart skille — ikke egnet for normalize.product_key() uten risiko for falsk
oppsplitting per fargevei. Denne proben dumper de kandidat-feltene en ekte
parser ville brukt: itemprop="name" (schema.org), og:title, <h1>, og
.color span.value (som RenderProductDetails bytter ut per fargevariant, jf.
probe_olympia_ajax) — for å se hvilket felt som gir modellnavn UTEN farge.
Stdlib only. probe.yml (script=probe_olympia_titles.py).
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


def get(path):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": UA, "Accept-Language": "nb-NO"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:
        print("feil:", e)
        return ""


def show(label, pattern, html, flags=re.I):
    for m in re.finditer(pattern, html, flags):
        print(f"  [{label}]", re.sub(r"\s+", " ", m.group(0))[:300])


def main():
    for path in SAMPLES:
        print("=" * 74)
        print("PDP:", path)
        html = get(path)
        print("  HTTP-lengde:", len(html))
        show("itemprop=name meta", r'<meta[^>]+itemprop="name"[^>]*>', html)
        show("og:title", r'<meta[^>]+property="og:title"[^>]*>', html)
        show("title-tag", r'<title>.*?</title>', html, re.I | re.S)
        show("h1", r'<h1\b[^>]*>.*?</h1>', html, re.I | re.S)
        show("product-name block", r'class="product-name"[^>]*>.*?(?=<div|<span class="color")', html, re.I | re.S)
        show("color block", r'class="color"[^>]*>.*?</div>', html, re.I | re.S)
        show("breadcrumb", r'class="breadcrumb"[^>]*>.*?</(?:ul|nav|div)>', html, re.I | re.S)
        # JSON-LD hele blokka, om den finnes uansett @type
        for m in re.finditer(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S | re.I):
            print("  [ld+json]", re.sub(r"\s+", " ", m.group(1))[:500])


if __name__ == "__main__":
    main()
