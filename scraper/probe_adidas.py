#!/usr/bin/env python3
"""
probe_adidas.py (v3) — verifiser multi-merke-wiringen FØR harvest.

Ingen monkey-patching lenger: v3 kaller discover(slug, "Adidas", modell) mot de
EKTE per-merke-konfigene (by_brand) og parser én Adidas-PDP per butikk med den
ekte adapteren. Forventet: torshov/intersport/sport1/loplabbet/xxl > 0 URL-er
med adidas-slugs; foss/brukas/bull -> 0 (fører ikke merket, gated).
Kjøres via probe.yml (script=probe_adidas.py). psycopg2 stubbes (ingen DB).
"""
from __future__ import annotations
import sys, types, traceback

if "psycopg2" not in sys.modules:
    _pg = types.ModuleType("psycopg2"); _pg.extras = types.ModuleType("psycopg2.extras")
    def _no_db(*a, **k): raise RuntimeError("psycopg2 stubbet i probe")
    _pg.connect = _no_db
    sys.modules["psycopg2"] = _pg; sys.modules["psycopg2.extras"] = _pg.extras

try:
    from fetch import Fetcher
except Exception:
    import urllib.request
    class Fetcher:
        def __init__(self, *a, **k): pass
        def get(self, url):
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (prislop-probe)",
                                                       "Accept-Language": "nb-NO"})
            try:
                with urllib.request.urlopen(req, timeout=40) as r:
                    return r.read().decode("utf-8", "replace")
            except Exception as e:
                print("    fetch-feil %s: %s" % (url, e)); return None

import discovery

MODELS = ["Adizero SL 2", "Adizero Boston 13", "Adizero Adios Pro 4",
          "Adizero Evo SL", "Ultraboost 5", "Supernova Rise 2"]

def main():
    print("probe_adidas v3 — ekte by_brand-konfig, ingen patching\n")
    f = Fetcher()
    for slug in ["torshov", "intersport", "sport1", "loplabbet", "xxl", "foss", "brukas", "bull"]:
        print("=" * 70)
        print("BUTIKK:", slug)
        urls, seen = [], set()
        for model in MODELS:
            try:
                for u in discovery.discover(f, slug, "Adidas", model, limit=4):
                    if u not in seen:
                        seen.add(u); urls.append(u)
            except Exception as e:
                print("  discover-feil:", e); traceback.print_exc(limit=1); break
        print("  Adidas-URL-er: %d" % len(urls))
        for u in urls[:4]:
            print("    ", u)
        if urls:
            html = f.get(urls[0])
            if html:
                try:
                    cfg = discovery.STORES[slug]
                    recs = cfg["adapter"](html, urls[0])
                    agg = cfg.get("aggregate")
                    if agg and recs: recs = agg(recs)
                    print("  adapter -> %d rec(s)" % len(recs))
                    for r in recs[:1]:
                        print("      brand=%r model=%r color=%r code=%r pris=%s sizes=%d"
                              % (r.get("brand"), r.get("model"), r.get("color"),
                                 r.get("manufacturer_code"), r.get("price"), len(r.get("sizes") or [])))
                        for sz in (r.get("sizes") or [])[:3]:
                            print("        ", sz.get("size_label"), sz.get("ean"), sz.get("in_stock"))
                except Exception as e:
                    print("  adapter-feil:", e); traceback.print_exc(limit=2)
    print("\nFasit: torshov/SportHolding×3/xxl > 0 med brand='ADIDAS'-recs; foss/brukas/bull = 0.")

if __name__ == "__main__":
    main()
