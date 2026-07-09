#!/usr/bin/env python3
"""
probe_brands.py — dekningskart for Nike/Hoka/Saucony/Puma/Kiprun × butikkene.

Injiserer KANDIDAT-by_brand-konfiger i discovery.STORES (mønstrene fra Adidas)
og kjører ekte discover() per merke × butikk. SportHolding-markeren er bevisst
PERMISSIV her: vi vet ikke kodeformatene ennå, så proben samler bredt og
skriver ut slug-HALER (siste token) — derfra leser vi hvert merkes
artikkelkode-format og strammer markeren i den ekte wiringen.
Foss/Brukås skannes direkte (sitemap/kategorier) uten konfig.
Kjøres via probe.yml (script=probe_brands.py). psycopg2 stubbes.

9. juli: lagt til Brooks/Mizuno (New Balance er alt skrudd på hos Foss —
se discovery.py — men uverifisert hos de fem andre, så den blir med her også
for å sjekke resten). Antatte URL-slugs («new-balance», «brooks», «mizuno»)
er gjetninger etter samme mønster som adidas/nike/etc. — proben avslører om
gjetningen stemmer (>0 treff) eller trenger justering.
"""
from __future__ import annotations
import re, sys, types, urllib.request
from collections import Counter

if "psycopg2" not in sys.modules:
    _pg = types.ModuleType("psycopg2"); _pg.extras = types.ModuleType("psycopg2.extras")
    _pg.connect = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("stub"))
    sys.modules["psycopg2"] = _pg; sys.modules["psycopg2.extras"] = _pg.extras

try:
    from fetch import Fetcher
except Exception:
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

BRANDS = ["nike", "hoka", "saucony", "puma", "kiprun", "brooks", "mizuno", "new-balance"]
PERMISSIV = re.compile(r"/[a-z0-9-]+-[a-z0-9]{4,10}/?($|\?)", re.I)


def inject():
    for b in BRANDS:
        # slug uten bindestrek der butikk-URL-en trolig ikke bruker den
        # (SportHolding/XXL Brand-param forventer ofte compact form).
        b_compact = b.replace("-", "")
        discovery.STORES["torshov"]["by_brand"][b] = {
            "cat_slug": f"{b}-lopesko",
            "search_url": (lambda q, _b=b: f"https://www.torshovsport.no/lop/lopesko/vare-merker/{_b}-lopesko"),
            "link_re": re.compile(rf"/lop/lopesko/vare-merker/{b}-lopesko/[a-z0-9-]+", re.I),
        }
        for host, slug in [("www.intersport.no", "intersport"), ("www.sport1.no", "sport1")]:
            discovery.STORES[slug]["by_brand"][b] = {
                "listing_urls": [f"https://{host}/sko/lopesko?Brand={b_compact.upper()}"],
                "marker_re": PERMISSIV, "max_pages": 5,
            }
        discovery.STORES["loplabbet"]["by_brand"][b] = {
            "listing_urls": [f"https://loplabbet.no/lopesko?Brand={b_compact.upper()}"],
            "marker_re": PERMISSIV, "max_pages": 5,
        }
        discovery.STORES["xxl"]["by_brand"][b] = {
            "brand_filter": b_compact.capitalize(),
            "search_url": (lambda q, _b=b_compact: f"https://www.xxl.no/herre/sko/lopesko-herre/{_b}/c/140202?f.brand={_b}"),
        }


def tails(urls):
    c = Counter(u.rstrip("/").rsplit("-", 1)[-1] for u in urls)
    return ", ".join(f"{t}×{n}" for t, n in c.most_common(6))


def main():
    print("probe_brands — Nike/Hoka/Saucony/Puma/Kiprun/Brooks/Mizuno/New Balance\n")
    inject()
    f = Fetcher()
    for slug in ["torshov", "intersport", "sport1", "loplabbet", "xxl"]:
        print("=" * 70)
        print("BUTIKK:", slug)
        for b in BRANDS:
            try:
                urls = discovery.discover(f, slug, b, "x", limit=4)
            except Exception as e:
                print(f"  {b:12s}: FEIL {e}"); continue
            print(f"  {b:12s}: {len(urls):3d} URL-er | haler: {tails(urls[:40]) if urls else '-'}")
            for u in urls[:2]:
                print("           ", u)

    # Foss: sitemap-skann per merke (uten konfig)
    print("=" * 70)
    print("FOSS (sitemap):")
    xml = f.get("https://www.foss-sport.no/sitemap.xml") or ""
    locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml)
    for b in BRANDS + ["topo"]:
        n = [l for l in locs if re.search(rf"/{b}/\d+/", l, re.I)]
        print(f"  {b:12s}: {len(n)} produkt-URL-er" + (f"  eks: {n[0]}" if n else ""))

    # Brukås: kategorisider, merke-slugs
    print("=" * 70)
    print("BRUKÅS (kategorier):")
    title = re.compile(r'class="product-title"[^>]*>\s*<a[^>]*href="([^"#?]+)"', re.I)
    hits = Counter()
    for cat in ["/joggesko-herre", "/joggesko-dame", "/terrengsko-herre", "/terrengsko-dame"]:
        html = f.get("https://www.brukas.no" + cat) or ""
        for h in title.findall(html):
            for b in BRANDS:
                if h.lower().startswith(f"/{b}-"):
                    hits[b] += 1
    for b in BRANDS:
        print(f"  {b:12s}: {hits.get(b, 0)} produkt-lenker (side 1 av kategoriene)")

    print("\nKONKLUSJON: >0 = inngangen virker; les kodeformat av «haler» og stram")
    print("markeren per merke i den ekte wiringen. XXL 0 kan bety annet facet-navn.")
    print("New Balance hos Foss er alt skrudd på i discovery.py — dette er kun")
    print("for de fem andre butikkene, pluss en dobbeltsjekk av Brooks/Mizuno der.")


if __name__ == "__main__":
    main()
