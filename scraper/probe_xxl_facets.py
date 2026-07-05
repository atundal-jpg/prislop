#!/usr/bin/env python3
"""
probe_xxl_facets.py — finn XXLs eSales-facet-navn for Hoka/Saucony/Puma.

probe_brands (5. juli) viste at `f.brand` med .capitalize() traff for Nike men
ikke for Hoka/Saucony/Puma — facet-verdiene må altså staves slik XXL selv gjør
det. Denne proben POSTer eSales' landing-page-query (samme params som
discovery._esales_paths) med ÉN side per kandidat-verdi og skriver totalHits +
et eksempel-link. >0 = riktig facet-navn -> legg den inn i xxl.by_brand.

Kjøres via probe.yml (script=probe_xxl_facets.py). Stdlib-only; psycopg2
stubbes fordi discovery -> loader -> psycopg2.
"""
from __future__ import annotations
import json, sys, types, urllib.request, uuid
from urllib.parse import urlencode

if "psycopg2" not in sys.modules:
    _pg = types.ModuleType("psycopg2"); _pg.extras = types.ModuleType("psycopg2.extras")
    _pg.connect = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("stub"))
    sys.modules["psycopg2"] = _pg; sys.modules["psycopg2.extras"] = _pg.extras

import discovery

CANDIDATES = {
    "hoka":    ["Hoka", "HOKA", "hoka", "Hoka One One", "HOKA ONE ONE", "Hoka one one"],
    "saucony": ["Saucony", "SAUCONY", "saucony"],
    "puma":    ["Puma", "PUMA", "puma"],
    # kontroll (kjent OK): skal gi ~95 og ~190 treff
    "nike":    ["Nike"],
    "asics":   ["Asics"],
}


def probe(api: dict, brand_value: str):
    params = {
        "channels": "ONLINE|STORE",
        "customerKey": api["customerKey"],
        "sessionKey": str(uuid.uuid4()),
        "site": api["site"],
        "stores": api["stores"],
        "touchpoint": "DESKTOP",
        "priceId": "member",
        "f.brand": brand_value,
        "notify": "true",
        "pageReference": api["pageReference"],
        "locale": "nb-NO",
        "market": "NO",
        "templateId": "PLP",
        "limit": "8",
        "skip": "0",
    }
    headers = {
        "Content-Type": "application/json", "Accept": "application/json",
        "Origin": "https://www.xxl.no", "Referer": "https://www.xxl.no/",
        "User-Agent": "Mozilla/5.0 (prislop-probe)",
    }
    url = api["url"] + "?" + urlencode(params)
    req = urllib.request.Request(url, data=b"", headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    primary = data.get("primaryList") or {}
    total = primary.get("totalHits") or 0
    sample = None
    for g in primary.get("productGroups") or []:
        for p in g.get("products") or []:
            if p.get("link"):
                sample = p["link"]
                break
        if sample:
            break
    return total, sample


def main():
    api = discovery.STORES["xxl"]["api"]
    print("probe_xxl_facets — eSales f.brand-kandidater (kategori /c/142010 Løpesko)\n")
    for brand, values in CANDIDATES.items():
        print(f"{brand.upper()}:")
        for v in values:
            try:
                total, sample = probe(api, v)
            except Exception as e:
                print(f"  f.brand={v!r:24s} FEIL: {e}")
                continue
            mark = " ✅" if total else ""
            print(f"  f.brand={v!r:24s} totalHits={total}{mark}" + (f"  eks: {sample}" if sample else ""))
        print()
    print("KONKLUSJON: verdien med totalHits>0 legges inn som brand_filter i")
    print("discovery.STORES['xxl']['by_brand'][<merke>] (+ search_url-fallback).")


if __name__ == "__main__":
    main()
