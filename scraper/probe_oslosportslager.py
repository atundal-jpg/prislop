#!/usr/bin/env python3
"""
probe_oslosportslager.py (v4) — struktur-dump før parser skrives.

v1-v3 (15. juli) etablerte GO: sitemap.xml (robots.txt) gir ~11 800
/produkt/…aspx-URL-er (hele katalogen, filtrerbar på "lopesko" i slug), og
PDP-en bærer per-størrelse EAN + EKSAKT lagerantall i et rått inline JSON-
blob (ikke JSON-LD):
    {"Id": 293022, "Qty": 3, "GTIN": [4550215825487], "Size": "37"}
gruppert per fargevariant ("Details": [[type], [colorway1-meta, size1, size2,
…], [colorway2-meta, …], …]).

Det vi IKKE vet ennå, og som v4 skal svare på FØR parseren skrives:
  A) Hvilken <script>-tag bærer blob-en (id/type-attributt), og er den GYLDIG
     JSON alene (kan vi json.loads() den direkte), eller sitter den inni en
     JS-setning (var x = {...};) vi må trimme?
  B) Hvor er VISNINGSPRISEN (kr)? "Pri" i blob-en så ut som et lite heltall
     (41, 1) som ikke kan være kr-pris — finn riktig felt.
  C) Hvilke topp-nivå-felter finnes for navn/merke/modell/URL/bilde, så
     parseren kan hente dem uten HTML-skraping.
  D) Merkedekning: hvor mange /produkt/…lopesko…aspx-URL-er i sitemapen per
     merke (asics/adidas/saucony/nike/hoka/brooks/mizuno/new-balance/puma)?

Stdlib only. probe.yml (script=probe_oslosportslager.py).
"""
from __future__ import annotations
import re
import urllib.request
import urllib.error

UA = "Mozilla/5.0 (prislop-probe)"
BASE = "https://www.oslosportslager.no"
SITEMAP = "https://oslosportslager.no/sitemap.xml"

# Ferske, bekreftet-ekte PDP-er (fra sitemapen, ikke websøk-cache).
SHOE_PDP = "/produkt/asics-gel-nimbus-22-100-lopesko-dame-52868.aspx"

BRANDS = ["asics", "adidas", "saucony", "nike", "hoka", "brooks", "mizuno",
          "new-balance", "puma", "kiprun", "salomon"]


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


SCRIPT_RE = re.compile(r'<script([^>]*)>(.*?)</script>', re.S | re.I)
LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)
PROD_LOPESKO_RE = re.compile(r"/produkt/[^\"'<>\s]*lopesko[^\"'<>\s]*\.aspx", re.I)


def probe_blob_structure():
    print("=" * 78)
    print("A+B+C) STRUKTUR-DUMP av variant-blob-en på en bekreftet ekte sko-PDP")
    print("  PDP:", SHOE_PDP)
    st, html = get(SHOE_PDP)
    print("  HTTP %s, %d B" % (st, len(html)))
    if not html:
        print("  INGEN respons.")
        return

    scripts = SCRIPT_RE.findall(html)
    print("  Antall <script>-tagger: %d" % len(scripts))
    hit = None
    for i, (attrs, body) in enumerate(scripts):
        if "GTIN" in body:
            print("  --- script #%d MED GTIN ---" % i)
            print("  attributter: %r" % attrs.strip())
            print("  lengde: %d tegn" % len(body))
            hit = (i, attrs, body)
    if not hit:
        print("  Fant ingen <script> med GTIN — blob-en ligger utenfor <script>-tagger?")
        # Dump en generell kontekst rundt "GTIN" i rå HTML som fallback.
        idx = html.find("GTIN")
        if idx >= 0:
            print("  Rå kontekst (2000 tegn før/etter):")
            print(html[max(0, idx - 2000):idx + 2000])
        return

    i, attrs, body = hit
    # Prøv å finne det STØRSTE {...}-JSON-objektet i scriptet (naiv brace-
    # telling — funker for velformet JSON uten strenger med ubalanserte {}).
    start = body.find("{")
    print("  Første '{' i scriptet ved tegn-indeks: %d" % start)
    print("  --- FØRSTE 1500 tegn av scriptet (for å se hva som INNLEDER JSON-en, "
          "f.eks. 'var X = ' eller ren <script type=\"application/json\">) ---")
    print(body[:1500])
    print("  --- SISTE 800 tegn av scriptet (for å se hva som AVSLUTTER, f.eks. ';') ---")
    print(body[-800:])

    # Finn Pri/Price/pris-relaterte felter og kr-formatert tekst nær blob-en.
    print("\n  --- Pris-felter i scriptet ---")
    for m in re.finditer(r'"(Pri|Price|price|Pris|SalesPrice|ListPrice|RRP)"\s*:\s*([^,}]+)', body):
        print("   ", m.group(0))

    print("\n  --- Navn/merke/URL-relaterte topp-nivå-nøkler (rundt 'Logo'/'Name'/'Brand') ---")
    for key in ("Name", "Title", "Brand", "BrandName", "Manufacturer", "ProductId", "Id", "Url", "Sku", "ArtNo", "ArticleNo"):
        m = re.search(r'"%s"\s*:\s*"?([^,"}]{0,60})"?' % re.escape(key), body)
        if m:
            print("   %-14s %s" % (key, m.group(1)))

    # Er HELE scriptet gyldig JSON alene?
    import json
    stripped = body.strip()
    try:
        json.loads(stripped)
        print("\n  => HELE scriptet er gyldig JSON alene (kan json.loads() direkte).")
    except Exception as e:
        print("\n  => Scriptet er IKKE gyldig JSON alene (%s) — må trimmes (JS-variabel-tildeling e.l.)." % e)
        # Prøv å trimme en ledende "var x = " / "window.x = " og trailing ";"
        m = re.match(r'^\s*(?:var\s+\w+\s*=|window\.\w+\s*=|\w+\s*=)\s*(.*?);?\s*$', stripped, re.S)
        if m:
            candidate = m.group(1)
            try:
                json.loads(candidate)
                print("  => ETTER trim av JS-tildeling er resten gyldig JSON.")
            except Exception as e2:
                print("  => Fortsatt ikke gyldig JSON etter naiv trim (%s)." % e2)


def probe_brand_coverage():
    print("\n" + "=" * 78)
    print("D) MERKEDEKNING for løpesko i sitemapen")
    st, xml = get(SITEMAP, cap=8_000_000)
    print("  %s -> HTTP %s, %d B" % (SITEMAP, st, len(xml)))
    locs = LOC_RE.findall(xml)
    print("  Totalt <loc>-er: %d" % len(locs))
    lopesko = [l for l in locs if PROD_LOPESKO_RE.search(l)]
    print("  Herav med 'lopesko' i slug: %d" % len(lopesko))
    counts = {}
    for b in BRANDS:
        counts[b] = sum(1 for l in lopesko if re.search(r"[/-]%s[-/]" % re.escape(b), l, re.I)
                        or ("/%s-" % b) in l.lower())
    for b, n in counts.items():
        print("    %-12s %d" % (b, n))
    unmatched = [l for l in lopesko if not any(
        re.search(r"[/-]%s[-/]" % re.escape(b), l, re.I) or ("/%s-" % b) in l.lower()
        for b in BRANDS)]
    print("  Uten kjent merke-slug (%d), eksempel:" % len(unmatched))
    for l in unmatched[:10]:
        print("    ", l)


def main():
    print("probe_oslosportslager v4 — struktur-dump for parser-skriving\n")
    probe_blob_structure()
    probe_brand_coverage()


if __name__ == "__main__":
    main()
