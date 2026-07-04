#!/usr/bin/env python3
"""
probe_adidas.py — sjekk Adidas-inngangen i alle butikkene før multi-merke-wiring.

For hver butikk: prøv Adidas-analogen til Asics-inngangen (som regel sti-swap
asics->adidas), rapporter om den gir Adidas-løpesko, og bekreft at PDP-en
gjenbruker samme struktur som Asics (så parseren generaliserer ved bare å lese
merke dynamisk). Dyp-sjekk på Foss + Brukås (de vi kjenner best); lettere
statussjekk på SportHolding/Torshov/XXL.

Nøkkelspørsmål: (1) hvilke Adidas-URL-er funker, (2) samme PDP-mal? (3) XXLs
Adidas-kategori (Asics = /lopesko-herre/Asics/c/140202?f.brand=Asics).
Stdlib only. probe.yml (script=probe_adidas.py).
"""
from __future__ import annotations
import json
import re
import urllib.request
import urllib.error

UA = "Mozilla/5.0 (prislop-probe)"
LD = re.compile(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I)
LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)
TITLE_A = re.compile(r'class="product-title"[^>]*>\s*<a[^>]*href="([^"#?]+)"', re.I)
GRID_SPAN = re.compile(r'<span[^>]*class="[^"]*button-dropdown[^"]*"', re.I)


def get(url, cap=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "nb-NO"})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            data = r.read(cap) if cap else r.read()
            return r.status, data.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return None, "FEIL %s" % e


def head(txt, label):
    print("  %-14s %s" % (label, txt))


def foss():
    print("\n=== FOSS (sitemap /adidas/<id>/) ===")
    st, xml = get("https://www.foss-sport.no/sitemap.xml", cap=5_000_000)
    locs = LOC.findall(xml)
    if any(l.lower().endswith(".xml") for l in locs):
        # indeks: følg noen barn
        subs = [l for l in locs if l.lower().endswith(".xml")][:12]
        locs = []
        for s in subs:
            locs += LOC.findall(get(s, cap=5_000_000)[1])
    ad = sorted(set(l for l in locs if re.search(r"/adidas/\d+/", l, re.I)))
    head("HTTP %s, %d Adidas-produkt-URL-er i sitemap" % (st, len(ad)), "sitemap:")
    for u in ad[:4]:
        print("      ", u)
    # dyp-sjekk: én Adidas-PDP -> ProductGroup + brand + hasVariant + gtin13
    if ad:
        p = ad[0]
        if p.startswith("http") and "www." not in p:
            p = p.replace("http://foss-sport.no", "https://www.foss-sport.no")
        st2, html = get(p)
        grp = None
        for blk in LD.findall(html):
            try:
                d = json.loads(blk)
            except Exception:
                continue
            for it in (d if isinstance(d, list) else [d]):
                if isinstance(it, dict) and it.get("@type") == "ProductGroup":
                    grp = it
        if grp:
            hv = grp.get("hasVariant") or []
            brand = (grp.get("brand") or {}).get("name") if isinstance(grp.get("brand"), dict) else grp.get("brand")
            head("name=%r brand=%r hasVariant=%d gtin13[0]=%s"
                 % (grp.get("name"), brand, len(hv),
                    (hv[0].get("gtin13") if hv and isinstance(hv[0], dict) else None)), "PDP:")
            print("      => Foss: SAMME mal (ProductGroup.hasVariant). Parser trenger bare lese brand.")
        else:
            head("PDP uten ProductGroup — sjekk manuelt: %s" % p, "PDP:")


def brukas():
    print("\n=== BRUKÅS (kategorier, /adidas-…-slugs) ===")
    base = "https://www.brukas.no"
    found = []
    for cat in ["/joggesko-herre", "/joggesko-dame", "/terrengsko-herre"]:
        st, html = get(base + cat)
        ad = [h for h in TITLE_A.findall(html) if re.search(r"/adidas-", h, re.I)]
        found += ad
        head("HTTP %s | %d adidas-produkt-lenker" % (st, len(set(ad))), cat + ":")
    found = sorted(set(found))
    if found:
        p = found[0] if found[0].startswith("http") else base + found[0]
        st2, html = get(p)
        grid = bool(GRID_SPAN.search(html))
        has_ld = "ProductGroup" in html or '"@type":"Product"' in html
        head("%s | button-dropdown-grid=%s | json-ld=%s" % (p, grid, has_ld), "PDP:")
        print("      => Brukås: %s" % ("SAMME størrelses-grid som Asics -> gjenbruk brukas_parser." if grid
                                        else "IKKE grid — Adidas kan ha annen struktur, sjekk PDP."))


def simple(label, url, needle_re=r"adidas"):
    st, html = get(url)
    hits = len(re.findall(needle_re, html, re.I)) if html else 0
    # grovt produkt-antall-hint
    prod = len(re.findall(r'data-productid=|"productId"|product-item|product-title|/product/', html, re.I)) if html else 0
    head("HTTP %s, %d B | 'adidas'x%d | produkt-markører~%d" % (st, len(html), hits, prod), label)
    return st, html


def sportholding():
    print("\n=== SPORTHOLDING (Intersport/Sport 1/Löplabbet: /asics -> /adidas) ===")
    for name, url in [("intersport", "https://www.intersport.no/adidas"),
                      ("sport1", "https://www.sport1.no/adidas"),
                      ("loplabbet", "https://www.loplabbet.no/adidas")]:
        simple(name + ":", url)


def torshov():
    print("\n=== TORSHOV (adidas-lopesko) ===")
    simple("torshov:", "https://www.torshovsport.no/lop/lopesko/vare-merker/adidas-lopesko")


def xxl():
    print("\n=== XXL (Asics: /lopesko-herre/Asics/c/140202?f.brand=Asics) ===")
    # test: samme kategori-kode, bytt merke-segment + facet
    for tag, url in [
        ("herre-swap", "https://www.xxl.no/herre/sko/lopesko-herre/Adidas/c/140202?f.brand=Adidas"),
        ("uten-facet", "https://www.xxl.no/herre/sko/lopesko-herre/c/140202?f.brand=Adidas"),
    ]:
        simple(tag + ":", url)
    print("      (XXL kan blokkere datasenter-IP / kreve API — se HTTP-status.)")


def main():
    print("probe_adidas — Adidas-inngang per butikk\n" + "=" * 70)
    for fn in (foss, brukas, sportholding, torshov, xxl):
        try:
            fn()
        except Exception as e:
            print("  FEIL i %s: %s" % (fn.__name__, e))
    print("\n" + "=" * 70)
    print("KONKLUSJON: butikker der Adidas-URL gir produkter + samme PDP-mal =")
    print("  ren swap i discovery-config. Avvik (XXL-kode, annen PDP) håndteres eksplisitt.")
    print("  Bull ikke testet her (egen AJAX/ES-discovery) — egen recon ved behov.")


if __name__ == "__main__":
    main()
