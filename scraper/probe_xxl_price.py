#!/usr/bin/env python3
"""
probe_xxl_price.py v2 — dump HELE price-objektet per XXL-fargevariant.

v1 druknet i oversettelsesstrenger. v2 går rett på parserens egen sti
(newPdpProps.initialElevateProductPageData.baseProduct.products[]) og
skriver price-objektet i sin helhet + søker hele JSON-treet etter
fasit-verdiene 1229/1519/1749 med full sti.

Fasit fra bruker 10. juli: svart artikkel = 1519 («Få igjen»),
hvit = 1749. Vi lagret 1229 (= price.selling.range.min) for alle fire.
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
                                                       "Accept-Language": "nb-NO"})
            try:
                with urllib.request.urlopen(req, timeout=40) as r:
                    return r.read().decode("utf-8", "replace")
            except Exception as e:
                print("    fetch-feil %s: %s" % (url, e)); return None

URLS = [
    "https://www.xxl.no/nike-vomero-18-lopesko-herre-svart/p/1244055_1_Style",
    "https://www.xxl.no/nike-vomero-18-lopesko-herre-hvit/p/1240624_1_Style",
]
FASIT = {1229, 1519, 1749}
NEXT_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def finn_fasit(node, path, out):
    if isinstance(node, dict):
        for k, v in node.items():
            finn_fasit(v, path + "." + str(k), out)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            finn_fasit(v, f"{path}[{i}]", out)
    else:
        try:
            if float(node) in FASIT:
                out.append((path, node))
        except (TypeError, ValueError):
            pass


def main():
    f = Fetcher()
    for url in URLS:
        print("=" * 78)
        print("URL:", url)
        html = f.get(url)
        if not html:
            continue
        m = NEXT_RE.search(html)
        if not m:
            print("  FANT IKKE __NEXT_DATA__"); continue
        data = json.loads(m.group(1))

        try:
            products = (data["props"]["pageProps"]["newPdpProps"]
                        ["initialElevateProductPageData"]["baseProduct"]["products"])
        except (KeyError, TypeError) as e:
            print("  fant ikke products-stien:", e); products = []

        for p in products:
            print(f"\n  --- fargevariant code={p.get('code')} color={p.get('localizedColorName') or p.get('baseColor')} url={p.get('url','')}")
            print("  price-objekt (FULLT):")
            print("   ", json.dumps(p.get("price"), ensure_ascii=False))
            v0 = (p.get("variants") or [{}])[0]
            pris_ig_v = {k: v for k, v in v0.items() if re.search(r"price|pris", str(k), re.I)}
            if pris_ig_v:
                print("  variant[0] prisfelter:", json.dumps(pris_ig_v, ensure_ascii=False)[:400])

        print("\n  --- fasit-verdier (1229/1519/1749) hvor som helst i treet ---")
        hits = []
        finn_fasit(data, "$", hits)
        for path, val in hits[:25]:
            print(f"  {val}  <-  {path}")
        if not hits:
            print("  (ingen — prisene kan ha endret seg siden fasit ble notert)")
    print("=" * 78)


if __name__ == "__main__":
    main()
