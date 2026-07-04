#!/usr/bin/env python3
"""
probe_adidas.py (v2) — test Adidas gjennom PIPELINENS EGNE adaptere.

v1 (generiske regexer) avklarte: Foss fører ikke Adidas (sitemap: 0), Brukås
sannsynligvis ikke (0 slugs, samme uttrekk som i drift). For SportHolding/
Torshov/XXL var v1-målingen ubrukelig (markør-regexen matcher ikke deres markup
engang for Asics). v2 gjør det avgjørende: monkey-patcher butikk-konfigene til
Adidas-innganger og kjører EKTE discovery.discover() + EKTE adapter per butikk.

Svarer på:
  1) Gir Adidas-listingene produkt-URL-er via de ekte adapterne?
  2) Parser den ekte parseren en Adidas-PDP riktig (brand? modell? sizes? EAN)?
     (Avslører også hvor 'Asics' er hardkodet i parserne -> generaliserings-liste.)
  3) XXL: hva er riktig Adidas-kategorikode? (leter i brand-facet-lenkene)

Kjøres via probe.yml (script=probe_adidas.py, working-directory: scraper).
Trenger repo-modulene; requests-fallback hvis den mangler.
"""
from __future__ import annotations
import json
import re
import sys
import traceback
import types

# probe.yml installerer ikke psycopg2 (stdlib-only av design). discovery ->
# loader -> psycopg2 er en import-kjede, men loader bruker driveren kun inne i
# get_conn() (aldri på import-tid, og aldri i denne proben). Stub modulnavnet
# FØR discovery-importen så kjeden går gjennom uten DB-driver.
if "psycopg2" not in sys.modules:
    _pg = types.ModuleType("psycopg2")
    _pg.extras = types.ModuleType("psycopg2.extras")
    def _no_db(*a, **k):
        raise RuntimeError("psycopg2 er stubbet i proben — ingen DB-tilgang her.")
    _pg.connect = _no_db
    sys.modules["psycopg2"] = _pg
    sys.modules["psycopg2.extras"] = _pg.extras

# --- Fetcher: bruk pipelinens, med urllib-fallback om requests mangler ------
try:
    from fetch import Fetcher
except Exception:
    import urllib.request

    class Fetcher:                                   # minimal shim, samme .get()
        def __init__(self, *a, **k):
            pass

        def get(self, url):
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (prislop-probe)",
                "Accept-Language": "nb-NO"})
            try:
                with urllib.request.urlopen(req, timeout=40) as r:
                    return r.read().decode("utf-8", "replace")
            except Exception as e:
                print("    fetch-feil %s: %s" % (url, e))
                return None

import discovery   # ekte discovery + adaptere

ADIDAS_MODELS = ["Adizero SL 2", "Adizero Boston 13", "Adizero Adios Pro 4",
                 "Ultraboost 5", "Supernova Rise 2", "Adizero Evo SL"]


def show_record(rec, limit_sizes=4):
    keys = ("brand", "model", "gender", "color", "manufacturer_code", "price")
    print("      rec:", {k: rec.get(k) for k in keys})
    sizes = rec.get("sizes") or []
    print("      sizes: %d stk, første: %s" % (
        len(sizes), [(s.get("size_label"), s.get("ean"), s.get("in_stock")) for s in sizes[:limit_sizes]]))


def run_store(slug, patch: dict, note=""):
    print("\n" + "=" * 74)
    print("BUTIKK: %s  %s" % (slug, note))
    cfg = discovery.STORES.get(slug)
    if not cfg:
        print("  (ikke i STORES — hopper over)")
        return
    # patch konfig til Adidas-inngang
    saved = {}
    for k, v in patch.items():
        saved[k] = cfg.get(k)
        cfg[k] = v
    # tøm evt. liste-cache så patchen slår inn
    for cache_name in ("_LIST_CACHE",):
        c = getattr(discovery, cache_name, None)
        if isinstance(c, dict):
            c.pop(slug, None)

    fetcher = Fetcher()
    urls, seen = [], set()
    for model in ADIDAS_MODELS:
        try:
            found = discovery.discover(fetcher, slug, "Adidas", model, limit=4)
        except Exception as e:
            print("  discover(%r) FEIL: %s" % (model, e))
            continue
        n_new = 0
        for u in found:
            if u not in seen:
                seen.add(u)
                urls.append(u)
                n_new += 1
        print("  discover(%r): %d URL-er (%d nye)" % (model, len(found), n_new))
    print("  TOTALT unike produkt-URL-er: %d" % len(urls))
    for u in urls[:5]:
        print("    ", u)

    # parse én PDP med den EKTE adapteren
    if urls:
        u = urls[0]
        html = fetcher.get(u)
        if html:
            try:
                recs = cfg["adapter"](html, u)
                agg = cfg.get("aggregate")
                if agg and recs:
                    recs = agg(recs)
                print("  adapter -> %d record(s)" % len(recs))
                for r in recs[:1]:
                    show_record(r)
            except Exception as e:
                print("  adapter FEIL:", e)
                traceback.print_exc(limit=2)
    # restore
    for k, v in saved.items():
        if v is None:
            cfg.pop(k, None)
        else:
            cfg[k] = v


def xxl_find_adidas_code():
    print("\n" + "=" * 74)
    print("XXL: finn Adidas-kategorikode (brand-facet-lenker)")
    f = Fetcher()
    for base in ["https://www.xxl.no/herre/sko/lopesko-herre/c/140202",
                 "https://www.xxl.no/dame/sko/lopesko-dame/c/140203"]:
        html = f.get(base) or ""
        print("  %s -> %d B" % (base, len(html)))
        # facet-lenker: /<sti>/Adidas/c/<kode> eller f.brand=adidas
        cands = sorted(set(re.findall(r'"(/[^"]*[Aa]didas[^"]*/c/\d+[^"]*)"', html)))
        for c in cands[:6]:
            print("     facet-URL:", c)
        codes = sorted(set(re.findall(r'[Aa]didas/c/(\d+)', html)))
        print("     kode-kandidater:", codes or "INGEN — sjekk f.brand-param i stedet")
        m = re.findall(r'"(f\.brand=[^"&]*[Aa]didas[^"&]*)"', html)
        if m:
            print("     f.brand-varianter:", sorted(set(m))[:4])


def main():
    print("probe_adidas v2 — gjennom pipelinens egne adaptere")

    # Torshov: swap kategorien + link_re til adidas-lopesko
    run_store("torshov", {
        "search_url": (lambda q: "https://www.torshovsport.no/lop/lopesko/vare-merker/adidas-lopesko"),
        "link_re": re.compile(r"/lop/lopesko/vare-merker/adidas-lopesko/[a-z0-9-]+", re.I),
    }, note="(adidas-lopesko)")

    # SportHolding-trioen: swap listing /asics -> /adidas
    for slug, url in [("intersport", "https://www.intersport.no/adidas"),
                      ("sport1", "https://www.sport1.no/adidas"),
                      ("loplabbet", "https://www.loplabbet.no/adidas")]:
        run_store(slug, {"listing_urls": [url]}, note="(/adidas)")

    # XXL: finn riktig kode først; kjør så discover med beste gjetning hvis funnet
    xxl_find_adidas_code()

    print("\n" + "=" * 74)
    print("KONKLUSJON-HINT:")
    print("  * discover>0 + adapter gir fornuftig record (riktig modell/sizes) =")
    print("    butikken er en ren konfig-swap; sjekk om 'brand' i rec er hardkodet 'Asics'.")
    print("  * XXL: bruk funnet Adidas-kode i search_url og kjør v3/discover manuelt.")
    print("  * Foss/Brukås utelatt: fører ikke Adidas (v1).")


if __name__ == "__main__":
    main()
