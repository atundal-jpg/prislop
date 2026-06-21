#!/usr/bin/env python3
"""
probe_foss.py (v3) — enumerer Asics via sitemap + dump full JSON-LD.

v2 løste per-variant: PDP-en har JSON-LD ProductGroup med hasVariant[] (gtin13 +
size + offers per størrelse) + ProductAltId-stilkode. Men paginering er uløst:
/asics server-rendrer kun 30, ingen query-param paginerer (Knockout/AJAX).

v3 svarer på det siste:
  A) ENUMERERING: finnes en sitemap som lister ALLE produkt-URL-er? Produkt-URL
     = /asics/<id>/<slug>, så Asics-produkter filtreres på «/asics/<tall>/».
     Gir oss både enumererings-kilde for discovery OG sant Asics-antall (er 30
     hele katalogen, eller et side-tak?).
  B) PARSER-GRUNNLAG: dump HELE ld+json-blokken (ProductGroup + hasVariant) fra
     en sko-PDP, så parseren skrives mot ekte full struktur (availability/pris
     per størrelse, brand, navn, productGroupID).

Stdlib only. Kjøres via .github/workflows/probe.yml (script=probe_foss.py).
"""
from __future__ import annotations
import re
import urllib.request
import urllib.error

UA = "Mozilla/5.0 (prislop-probe)"
BASE = "https://www.foss-sport.no"
PDP = "/asics/200481/asics-dame-l%c3%b8pesko-trabuco-max-5-terrengsko-med-godt-grep-rd-sc"

LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)
ASICS_PROD = re.compile(r"/asics/\d+/", re.I)
LDJSON = re.compile(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I)


def get(path, cap=None):
    url = path if path.startswith("http") else BASE + path
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "nb-NO"})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            data = r.read(cap) if cap else r.read()
            return r.status, data.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return None, "FEIL %s" % e


def probe_sitemap():
    print("=" * 78)
    print("A) SITEMAP-ENUMERERING")

    # robots.txt -> Sitemap-linjer
    st, robots = get("/robots.txt")
    print("  /robots.txt -> HTTP %s" % st)
    sm_urls = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", robots)
    for s in sm_urls:
        print("    robots Sitemap:", s)
    candidates = sm_urls or [BASE + "/sitemap.xml"]

    all_locs, asics = set(), set()
    visited = 0
    queue = list(candidates)
    while queue and visited < 12:
        sm = queue.pop(0)
        visited += 1
        st, xml = get(sm, cap=5_000_000)
        locs = LOC.findall(xml)
        # sitemap-indeks? (loc-er som selv peker på .xml)
        children = [l for l in locs if l.lower().endswith(".xml")]
        if children:
            print("  INDEX %s -> %d under-sitemaps (HTTP %s)" % (sm, len(children), st))
            queue.extend(children[:12])
            continue
        a = [l for l in locs if ASICS_PROD.search(l)]
        print("  %s -> HTTP %s, %d URL-er, %d Asics-produkt" % (sm, st, len(locs), len(a)))
        all_locs.update(locs)
        asics.update(a)

    print("  ----")
    print("  TOTALT Asics-produkt-URL-er i sitemap(s): %d" % len(asics))
    for u in sorted(asics)[:8]:
        print("    ", u)
    if asics:
        print("  => discovery kan enumerere Asics rett fra sitemap (filter /asics/<id>/).")
    else:
        print("  => INGEN sitemap-treff; må finne listing-AJAX-endepunkt i stedet.")


def probe_full_ldjson():
    print("\n" + "=" * 78)
    print("B) FULL JSON-LD (ProductGroup + hasVariant) fra sko-PDP")
    st, html = get(PDP)
    print("  PDP -> HTTP %s, %d B" % (st, len(html)))
    blocks = LDJSON.findall(html)
    print("  ld+json-blokker: %d" % len(blocks))
    target = None
    for b in blocks:
        if "hasVariant" in b or "ProductGroup" in b:
            target = b
            break
    if target is None:
        target = blocks[0] if blocks else ""
    # komprimer whitespace, vis opp til 6000 tegn
    compact = re.sub(r"\s+", " ", target).strip()
    print("  --- JSON-LD (lengde %d, viser <=6000) ---" % len(compact))
    print(compact[:6000])
    print("  --- slutt JSON-LD ---")


def main():
    print("probe_foss v3 — sitemap-enumerering + full JSON-LD\n")
    probe_sitemap()
    probe_full_ldjson()
    print("\nKONKLUSJON-HINT:")
    print("  A: Asics-antall i sitemap >> 30 -> discovery 'foss_sitemap' (filter /asics/<id>/).")
    print("     Asics-antall ~= 30 -> /asics-listingen ER hele katalogen; bruk de 30 direkte.")
    print("  B: hasVariant[].{gtin13,size,offers.availability,offers.price} -> rett inn i parser.")


if __name__ == "__main__":
    main()
