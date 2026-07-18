#!/usr/bin/env python3
"""
probe_bull_vendors.py — vendor-id-recon + discovery-verifisering for Bull.

Bakgrunn (18. juli): bruker fant Hoka Skyward X hos Bull som manglet i
katalogen. Årsak i discovery.py: Bull var merke-bundet til Asics — API-URL-en
hadde hardkodet vendor-facet 13524, og discover() ga [] for alle andre merker.
v1 av proben fant Hoka = vendor 13490 (fra items' product_vendor/-_text) og
viste at bull_parser takler Hoka-sider (men manglet colorway-koden — fikset
ved å lære CODE_RE/CODE_IMG_RE Hoka-formatet 1147911-CSLP).

v2 verifiserer fiksen ende-til-ende mot det ekte API-et:
  1. Dumper product_vendor-FACETEN (alle merkenavn + id-er + antall) —
     autoritativ kilde for fremtidige by_brand-utvidelser.
  2. Kjører discovery.discover(None, "bull", <merke>, …) LIVE for Hoka og
     Asics med den nye by_brand-konfigen; printer antall URL-er + eksempler,
     og sjekker at Skyward X-URL-en faktisk er blant Hoka-treffene.
  3. Henter Skyward X-produktsiden og kjører bull_parser.parse — nå skal
     manufacturer_code være satt (1147911-CSLP).

Kjøres via probe.yml (script=probe_bull_vendors.py). Kun stdlib.
"""
from __future__ import annotations
import json
import sys
import types
import urllib.request

if "psycopg2" not in sys.modules:                 # loader (via discovery)
    _pg = types.ModuleType("psycopg2")
    _pg.extras = types.ModuleType("psycopg2.extras")
    sys.modules["psycopg2"] = _pg
    sys.modules["psycopg2.extras"] = _pg.extras

import bull_parser
import discovery

BASE = "https://bull-ski-kajakk.no"
API = BASE + "/api/navigation/product"
SKYWARD_URL = BASE + "/sko/lopesko/lettvekt-konkurransesko/hoka-skyward-x-herre"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (prislop)",
    "Accept": "application/json, */*",
    "Referer": BASE + "/sko/lopesko",
}


def get_json(url: str) -> dict | None:
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        print(f"    API-feil {url}: {e}")
        return None


def get_html(url: str) -> str | None:
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (prislop)",
                          "Accept-Language": "nb-NO"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:
        print(f"    fetch-feil {url}: {e}")
        return None


def main():
    ok = True

    # --- 1) Hele vendor-faceten (alle merker + id-er) ------------------------
    print("=" * 78)
    print("1) VENDOR-FACETEN (query=, uten vendor-filter)")
    d = get_json(f"{API}?query=&page=1") or {}
    for facet in d.get("facets") or []:
        if facet.get("field") != "product_vendor":
            continue
        for it in facet.get("items") or []:
            print(f"  {it.get('name'):<20} id={it.get('search_key')}  "
                  f"count={it.get('count')}")
        break
    else:
        print("  fant ingen product_vendor-facet i responsen!")

    # --- 2) discovery.discover LIVE med ny by_brand-konfig -------------------
    print("=" * 78)
    print("2) DISCOVERY LIVE (ny by_brand-konfig)")
    for brand in ("Hoka", "Asics"):
        urls = discovery.discover(None, "bull", brand, "")
        print(f"  {brand}: {len(urls)} løpesko-URL-er")
        for u in urls[:5]:
            print(f"    {u}")
    hoka_urls = discovery.discover(None, "bull", "Hoka", "")
    if SKYWARD_URL in hoka_urls:
        print("  ✓ Skyward X-URL-en er blant Hoka-treffene")
    else:
        ok = False
        print("  ✗ Skyward X-URL-en MANGLER blant Hoka-treffene!")
    if any("barn" in u for u in hoka_urls):
        ok = False
        print("  ✗ barne-URL-er slapp gjennom skip_category!")

    # --- 3) bull_parser på Skyward X — nå med kode ---------------------------
    print("=" * 78)
    print("3) BULL_PARSER på", SKYWARD_URL)
    html = get_html(SKYWARD_URL)
    if html:
        rec = bull_parser.parse(html, SKYWARD_URL)
        if rec is None:
            ok = False
            print("  parse() -> None!")
        else:
            slim = {k: v for k, v in rec.items() if k != "sizes"}
            print(json.dumps(slim, ensure_ascii=False, indent=1))
            print(f"  størrelser: {len(rec['sizes'])} "
                  f"(på lager: {sum(s['in_stock'] for s in rec['sizes'])})")
            if not rec.get("manufacturer_code"):
                ok = False
                print("  ✗ manufacturer_code mangler fortsatt!")

    print("=" * 78)
    print("RESULTAT:", "OK" if ok else "FEIL — se ✗ over")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
