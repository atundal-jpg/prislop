#!/usr/bin/env python3
"""
probe_oslosportslager_verify.py — ende-til-ende-verifisering av
oslosportslager_parser.py mot ekte sider, FØR full harvest.

Kan ikke importere discovery.py her (den importerer loader -> psycopg2, som
ikke finnes i probe-miljøet — se probe_discover_counts.py). Reimplementerer
derfor sitemap-enumereringen minimalt (samme regex som discovery.py sin
_oslosportslager_paths) og importerer oslosportslager_parser direkte (ingen
eksterne avhengigheter der).

Henter et utvalg ekte /produkt/…lopesko…aspx-sider fra sitemapen og kjører
dem gjennom parseren, for å bekrefte i skala (ikke bare ett hånd-bygget
eksempel) at: blob-en finnes og trekkes ut, Header tolkes til rimelig
merke/modell/kjønn, og EAN+Qty-lager kommer ut som forventet.

Stdlib only. probe.yml (script=probe_oslosportslager_verify.py).
"""
from __future__ import annotations
import re
import urllib.request
import urllib.error
from urllib.parse import urljoin, urlparse

import oslosportslager_parser as osl

UA = "Mozilla/5.0 (prislop-probe)"
BASE = "https://www.oslosportslager.no"
SITEMAP = "https://oslosportslager.no/sitemap.xml"
SAMPLE_N = 20

LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)
PROD_LOPESKO_RE = re.compile(r"/produkt/[^\"'<>\s]*lopesko[^\"'<>\s]*\.aspx", re.I)


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "nb-NO"})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return None, "FEIL %s" % e


def lopesko_urls():
    st, xml = get(SITEMAP)
    print("sitemap -> HTTP %s, %d B" % (st, len(xml)))
    out, seen = [], set()
    for loc in LOC_RE.findall(xml):
        if not PROD_LOPESKO_RE.search(loc):
            continue
        full = urljoin(BASE, urlparse(loc).path)
        if full not in seen:
            seen.add(full)
            out.append(full)
    print("løpesko-URL-er i sitemap: %d" % len(out))
    return out


def main():
    print("probe_oslosportslager_verify — parser mot %d ekte sider\n" % SAMPLE_N)
    urls = lopesko_urls()
    if not urls:
        print("INGEN URL-er — kan ikke verifisere.")
        return

    # Jevnt utvalg over hele lista (ikke bare de første — de kan skjeve mot én
    # kategori/butikkalder), heller enn tilfeldig (reproduserbart mellom kjøringer).
    step = max(1, len(urls) // SAMPLE_N)
    sample = urls[::step][:SAMPLE_N]

    n_fetched = n_blob = n_records = n_sizes = n_eans = n_instock_sizes = 0
    brands = {}
    errors = []

    for url in sample:
        st, html = get(url)
        if not html:
            errors.append((url, "HTTP %s" % st))
            continue
        n_fetched += 1
        blob = osl._extract_blob(html)
        if blob:
            n_blob += 1
        try:
            records = osl.parse(html, url)
        except Exception as e:
            errors.append((url, "parse-feil: %s" % e))
            continue
        print("-" * 74)
        print(url)
        print("  blob funnet: %s, records: %d" % (bool(blob), len(records)))
        for rec in records:
            n_records += 1
            brands[rec["brand"]] = brands.get(rec["brand"], 0) + 1
            sizes = rec["sizes"]
            n_sizes += len(sizes)
            n_eans += sum(1 for s in sizes if s.get("ean"))
            n_instock_sizes += sum(1 for s in sizes if s.get("in_stock"))
            print("   %-10s %-30s %-6s farge=%-6s pris=%s kr, %d størrelser (%d m/EAN, %d på lager)"
                  % (rec["brand"], rec["model"], rec["gender"], rec["color"],
                     rec["price"], len(sizes),
                     sum(1 for s in sizes if s.get("ean")),
                     sum(1 for s in sizes if s.get("in_stock"))))
        if blob and not records:
            print("   (blob funnet, men 0 records — sjekk om Header ble tolket som ikke-sko/barn/uten merke)")
            hdr = None
            for p in (blob.get("Product") or []):
                hdr = p.get("Header")
            print("   Header var:", repr(hdr))

    print("\n" + "=" * 74)
    print("OPPSUMMERING (%d/%d sider hentet OK):" % (n_fetched, len(sample)))
    print("  blob funnet på:      %d/%d" % (n_blob, n_fetched))
    print("  OfferRecords totalt: %d" % n_records)
    print("  størrelser totalt:   %d (%d med EAN, %d på lager)" % (n_sizes, n_eans, n_instock_sizes))
    print("  merker sett:", brands)
    if errors:
        print("  FEIL (%d):" % len(errors))
        for u, e in errors[:10]:
            print("   ", u, "->", e)
    if n_records and n_eans:
        print("\n=> Parseren fungerer i skala mot ekte sider: bro-data (EAN+lager) kommer ut.")
    else:
        print("\n=> Noe stemmer ikke — se rå Header-dump over for produkter med 0 records.")


if __name__ == "__main__":
    main()
