#!/usr/bin/env python3
"""probe_xxl_price.py v5 — per-fargevei-pris i variantene?
Bruker-funn 10. juli: XXL har ULIK pris per fargevei i samme stilfamilie
(svart#1=1519, svart#2«kun i butikk»=1399, hvit=1749). range.min = billigste
søsken → feil pris stemples på alle. Sjekk: bærer products[].variants[] egne,
riktige priser per artikkel?"""
from __future__ import annotations
import json, re, urllib.request

URL = "https://www.xxl.no/nike-vomero-18-lopesko-herre-svart/p/1244055_1_Style"
NEXT_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "nb-NO"})
html = urllib.request.urlopen(req, timeout=40).read().decode("utf-8", "replace")
d = json.loads(NEXT_RE.search(html).group(1))
prods = d["props"]["pageProps"]["newPdpProps"]["initialElevateProductPageData"]["baseProduct"]["products"]
print("Fasit: 1244055-svart=1519 · 1253876-svart(kun butikk)=1399 · hvit=1749\n")
for p in prods:
    print(f"=== code={p.get('code')} color={p.get('localizedColorName') or p.get('baseColor')}")
    print("  toppnivå price:", json.dumps(p.get("price"), ensure_ascii=False)[:250])
    for v in (p.get("variants") or [])[:3]:
        prisfelt = {k: v[k] for k in v if re.search(r"price|pris", k, re.I)}
        print(f"  variant {v.get('code','?')} str={v.get('size') or v.get('sizeLabel','?')}:",
              json.dumps(prisfelt, ensure_ascii=False)[:300])
