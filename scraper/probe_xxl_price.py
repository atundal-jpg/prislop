#!/usr/bin/env python3
"""
probe_xxl_price.py v4 — hvilken cache-busting gir FERSK XXL-side?

Bekreftet 10. juli: ekte pris (1519) ligger i server-HTML-en når nettleser
henter siden — fetcheren vår får stale CDN-kopier (1229/1399). Tester tre
strategier og leser price.selling.range.min + ser etter fasit 1519.
"""
from __future__ import annotations
import json, re, time, urllib.request

URL = "https://www.xxl.no/nike-vomero-18-lopesko-herre-svart/p/1244055_1_Style"
NEXT_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
BASE_H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
          "Accept-Language": "nb-NO,nb;q=0.9", "Accept": "text/html,application/xhtml+xml"}


def hent(url, ekstra=None):
    h = dict(BASE_H)
    if ekstra:
        h.update(ekstra)
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            body = r.read().decode("utf-8", "replace")
            alder = r.headers.get("age") or r.headers.get("x-cache") or "-"
            return body, alder
    except Exception as e:
        return None, str(e)


def pris(html):
    m = NEXT_RE.search(html or "")
    if not m:
        return None
    try:
        d = json.loads(m.group(1))
        prods = d["props"]["pageProps"]["newPdpProps"]["initialElevateProductPageData"]["baseProduct"]["products"]
        return [p.get("price", {}).get("selling", {}).get("range", {}).get("min", {}).get("value") for p in prods]
    except Exception as e:
        return f"parse-feil: {e}"


STRATEGIER = [
    ("A: vanlig (kontroll)",            URL, None),
    ("B: ?_=tidsstempel",               URL + "?_=" + str(int(time.time())), None),
    ("C: no-cache headere",             URL, {"Cache-Control": "no-cache", "Pragma": "no-cache"}),
    ("D: B+C kombinert",                URL + "?_=" + str(int(time.time()) + 1),
                                        {"Cache-Control": "no-cache", "Pragma": "no-cache"}),
]

for navn, url, hdr in STRATEGIER:
    html, alder = hent(url, hdr)
    p = pris(html)
    fasit = "1519 FUNNET ✓" if html and "1519" in html else "1519 mangler ✗"
    print(f"{navn:26s} cache-info={alder!s:20s} priser={p}  {fasit}")

print("\nFasit fra nettleser: svart=1519. Strategien som gir 1519 vinner.")
