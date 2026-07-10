#!/usr/bin/env python3
"""
probe_xxl_price.py v3 — XXLs SSR-priser er CDN-stale (samme URL ga 1399 og
1229 sekunder fra hverandre; nettleser viser 1519). Ekte pris hydreres fra
«price-information-api» klient-side. v3 sjekker to alternative kilder:
  1. JSON-LD offers på siden (reddet Bull) — er den fersk hos XXL?
  2. Jakter pris-API-endepunktet i HTML/JS (price-information-mønstre)
     og prøver å kalle det med style-kodene.
"""
from __future__ import annotations
import json, re, sys, types, urllib.request

if "psycopg2" not in sys.modules:
    _pg = types.ModuleType("psycopg2"); _pg.extras = types.ModuleType("psycopg2.extras")
    _pg.connect = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("stub"))
    sys.modules["psycopg2"] = _pg; sys.modules["psycopg2.extras"] = _pg.extras

try:
    from fetch import Fetcher
except Exception:
    class Fetcher:
        def get(self, url):
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (prislop-probe)",
                                                       "Accept-Language": "nb-NO", "Accept": "*/*"})
            try:
                with urllib.request.urlopen(req, timeout=40) as r:
                    return r.read().decode("utf-8", "replace")
            except Exception as e:
                print("    fetch-feil %s: %s" % (url, e)); return None

URL = "https://www.xxl.no/nike-vomero-18-lopesko-herre-svart/p/1244055_1_Style"
STYLES = ["1244055_1_Style", "1240624_1_Style"]
LD = re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S | re.I)
API_HINT = re.compile(r'["\'](https?://[^"\']*price[^"\']*|/[a-z0-9/_.-]*price[a-z0-9/_.-]*)["\']', re.I)


def main():
    f = Fetcher()
    html = f.get(URL) or ""
    print("HTML-lengde:", len(html))

    print("\n--- 1) JSON-LD offers (er prisen fersk her?) ---")
    for i, m in enumerate(LD.finditer(html)):
        raw = m.group(1)
        # skriv kun offers-delene for kompakthet
        for om in re.finditer(r'"offers"\s*:\s*(\{.*?\}|\[.*?\])', raw, re.S):
            print(f"[LD {i}]", re.sub(r"\s+", " ", om.group(1))[:500])

    print("\n--- 2) API-kandidater i HTML (price-mønstre i URL-er) ---")
    seen = set()
    for m in API_HINT.finditer(html):
        u = m.group(1)
        if u in seen or u.endswith((".css", ".svg", ".png")):
            continue
        seen.add(u)
        print("  ", u[:160])
        if len(seen) >= 15:
            break

    print("\n--- 3) Gjett-test av vanlige endepunktsmønstre ---")
    kandidater = [
        f"https://www.xxl.no/rest-api/price-information?styleIds={','.join(STYLES)}",
        f"https://www.xxl.no/api/price-information?styleIds={','.join(STYLES)}",
        f"https://www.xxl.no/p/api/price-information?ids={','.join(STYLES)}",
    ]
    for u in kandidater:
        body = f.get(u)
        print("  ", u)
        print("    ->", (re.sub(r"\s+", " ", body)[:300] if body else "ingen respons"))


if __name__ == "__main__":
    main()
