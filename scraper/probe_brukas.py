#!/usr/bin/env python3
"""
probe_brukas.py — kartlegg Brukas Sport (nopCommerce) for Prislop.

nopCommerce, server-rendret HTML. Proben svarer pa:
  A) DISCOVERY — finnes en produsentside /asics som lister alle Asics paginert?
     Hvis ikke: kategori (/joggesko-herre osv.) + ?manufacturerids=<asics-id>.
     Finner produktlenke-monster, ?pagenumber=N-paginering, og Asics-produsent-id
     fra kategori-filteret.
  B) PARSE — pa en Asics-produktside: pris, SKU/GTIN, STORRELSER m/ per-storrelse
     lager, farge, produsent-kode (Asics colorway), merke.

Kjores i GitHub Actions. Skriver ingenting til DB.
"""
from __future__ import annotations
import re
import urllib.request
import urllib.error
from urllib.parse import urljoin

UA = "Mozilla/5.0 (prislop-probe)"
BASE = "https://www.brukas.no"

# nopCommerce produkt-tittel-anker i lister: <h2 class="product-title"><a href=...>
PROD_TITLE = re.compile(r'class="product-title"[^>]*>\s*<a[^>]*href="([^"#?]+)"', re.I)
PAGENUM = re.compile(r'[?&]pagenumber=(\d+)', re.I)
MANUF_ID = re.compile(r'manufacturerids?=(\d+)', re.I)
HREF = re.compile(r'href="([^"#]+)"', re.I)


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "nb-NO"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return None, "FEIL %s" % e


def prod_links(html):
    out = []
    seen = set()
    for m in PROD_TITLE.finditer(html):
        u = urljoin(BASE, m.group(1))
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def windows(html, needle, n=3, pad=110):
    out, start = [], 0
    low = html.lower()
    for _ in range(n):
        i = low.find(needle.lower(), start)
        if i < 0:
            break
        out.append(re.sub(r"\s+", " ", html[max(0, i - pad):i + len(needle) + pad]))
        start = i + len(needle)
    return out


def main():
    print("probe_brukas — nopCommerce-kartlegging\n")

    print("== A1) produsentside-kandidater ==")
    asics_listing = None
    for path in ["/asics", "/merker/asics", "/produsent/asics", "/manufacturer/asics", "/brands/asics"]:
        st, html = get(BASE + path)
        links = prod_links(html) if html else []
        pages = sorted(set(int(x) for x in PAGENUM.findall(html))) if html else []
        print("   %-22s -> %s  produkt-lenker=%d  pagenumber=%s" %
              (path, st, len(links), pages[-3:] if pages else "ingen"))
        if st == 200 and links and asics_listing is None:
            asics_listing = (path, html, links)

    print("\n== A2) kategori /joggesko-herre: produkter + Asics-filter ==")
    st, cat = get(BASE + "/joggesko-herre")
    cat_links = prod_links(cat)
    pages = sorted(set(int(x) for x in PAGENUM.findall(cat)))
    mids = sorted(set(MANUF_ID.findall(cat)))
    print("   status=%s  produkt-lenker=%d  pagenumber=%s  manufacturerids=%s" %
          (st, len(cat_links), pages[-3:] if pages else "ingen", mids))
    print("   eksempel-produktlenker:", [u.replace(BASE, "") for u in cat_links[:4]])
    print("   'Asics' i filter-markup:")
    for w in windows(cat, "asics", n=3):
        print("      ...%s..." % w)

    # finn en Asics-produktside a parse
    sample = None
    if asics_listing:
        sample = asics_listing[2][0]
    else:
        for u in cat_links:
            if "asics" in u.lower():
                sample = u
                break
    if not sample and mids:
        # prov manufacturerids-filter pa kategorien
        st, f = get("%s/joggesko-herre?manufacturerids=%s" % (BASE, mids[0]))
        fl = prod_links(f)
        print("\n   /joggesko-herre?manufacturerids=%s -> %d produkter %s" %
              (mids[0], len(fl), [u.replace(BASE, "") for u in fl[:3]]))
        if fl:
            sample = fl[0]

    print("\n== B) parse-mal pa produktside ==")
    if not sample:
        print("   fant ingen Asics-produktside a teste")
        return
    print("   sample:", sample)
    st, p = get(sample)
    print("   status=%s  lengde=%d" % (st, len(p)))
    # pris
    price = re.search(r'class="[^"]*price[^"]*"[^>]*>\s*([\d  .\u00a0]+,-|\d[\d  .\u00a0]*kr)', p, re.I)
    print("   pris:", price.group(1).strip() if price else "?")
    # SKU / GTIN / produsent-kode
    for label in ["sku", "gtin", "produktnr", "varenr", "manufacturer-part", "mpn"]:
        for w in windows(p, label, n=1, pad=70):
            print("   [%s] ...%s..." % (label, w))
    # merke / produsent
    man = re.search(r'href="([^"]*)"[^>]*>\s*Asics', p, re.I)
    print("   produsent-lenke:", man.group(1) if man else "?")
    # farge
    for w in windows(p, "farge", n=1, pad=80):
        print("   [farge] ...%s..." % w)
    # storrelser: <select> + opsjoner, og lager-markorer
    sel = re.search(r"<select[^>]*>(.*?)</select>", p, re.S | re.I)
    if sel:
        opts = re.findall(r"<option[^>]*>([^<]+)</option>", sel.group(1))
        print("   <select>-opsjoner:", [o.strip() for o in opts][:16])
    else:
        print("   <select>: ingen (storrelser ligger kanskje som attributt-knapper/JS)")
    for w in windows(p, "ikke pa lager", n=2, pad=60) or []:
        print("   [utsolgt-markor] ...%s..." % w)
    for w in windows(p, "stockquantity", n=1, pad=60):
        print("   [stockquantity] ...%s..." % w)


if __name__ == "__main__":
    main()
