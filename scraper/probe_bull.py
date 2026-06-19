#!/usr/bin/env python3
"""
probe_bull.py — kartlegg Bull Ski & Kajakk (Drupal Commerce 2) for Prisløp.

Kjent: meta-Generator = "Drupal 9; Commerce 2". Faceted listing med
?product_category / ?product_department / ?in_stock / ?query, Drupal-pager
(?page=N, 0-indeksert). Produkt-slug inneholder IKKE Asics-koden (den ligger i
sidekroppen som "Produktnummer: 1011B867-101").

Proben svarer på det vi trenger for discovery + parser:
  A) LISTING — server-rendret produkt-lenker på /merker/asics og /sko/lopesko,
     antall + eksempler, og om ?page=1 paginerer (Drupal er 0-indeksert).
  B) PDP — HVOR ligger pris / farge / kode / EAN, og finnes per-STØRRELSE lager?
     Leter etter JSON-LD Product (m/ offers/hasVariant/gtin13), Drupal
     `drupalSettings`-JSON (ofte variasjoner: sku/price/attributes/stock),
     <select>/variant-attributter i HTML, og teller 13-sifrede EAN/GTIN.

Kjøres i GitHub Actions. Skriver ingenting til DB.
"""
from __future__ import annotations
import json
import re
import urllib.request

UA = "Mozilla/5.0 (prislop-probe)"
HREF_RE = re.compile(r'href="([^"#]+)"', re.I)
# Produkt-detalj-lenke: under /sko/... eller /merker/... med en asics-slug.
PROD_RE = re.compile(r"/(?:sko|merker)/[a-z0-9/_-]*asics-[a-z0-9-]+", re.I)
LD_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
SETTINGS_RE = re.compile(
    r'data-drupal-selector="drupal-settings-json"[^>]*>(\{.*?\})</script>', re.S)
EAN_RE = re.compile(r"\b\d{13}\b")
SELECT_RE = re.compile(r"<select[^>]*>(.*?)</select>", re.S | re.I)
OPTION_RE = re.compile(r"<option[^>]*>([^<]+)</option>", re.I)
CODE_RE = re.compile(r"Produktnummer[^0-9A-Za-z]*([0-9A-Za-z-]+)", re.I)

LISTINGS = {
    "merker/asics": "https://bull-ski-kajakk.no/merker/asics",
    "sko/lopesko":  "https://bull-ski-kajakk.no/sko/lopesko",
}
PDPS = [
    "https://bull-ski-kajakk.no/sko/lopesko/treningssko/asics-gel-kayano-31-lopesko-herre",
    "https://bull-ski-kajakk.no/sko/lopesko/treningssko/asics-superblast-3-unisex-1",
    "https://bull-ski-kajakk.no/sko/lopesko/vinterlopesko/asics-fujisetsu-max-gore-tex-piggsko-herre",
]


def get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "nb-NO"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def prod_links(html: str) -> list[str]:
    return sorted({m.group(0) for h in HREF_RE.findall(html) if (m := PROD_RE.search(h))})


def probe_listing() -> None:
    for name, base in LISTINGS.items():
        print(f"\n----- LISTING {name} -----")
        try:
            html = get(base)
        except Exception as e:
            print(f"  FEIL: {e}")
            continue
        p1 = prod_links(html)
        print(f"  {base}")
        print(f"    produkt-lenker={len(p1)}  ex={p1[:3]}")
        # pager (Drupal 0-indeksert): ?page=1 = side 2
        try:
            sep = "&" if "?" in base else "?"
            p2 = prod_links(get(f"{base}{sep}page=1"))
            extra = sorted(set(p2) - set(p1))
            print(f"    ?page=1: lenker={len(p2)}  nye={len(extra)}  "
                  f"{'<-- PAGINERING' if extra else '(samme/ingen)'}")
        except Exception as e:
            print(f"    ?page=1 FEIL: {e}")


def probe_pdp(url: str) -> None:
    print(f"\n----- PDP {url.rsplit('/',1)[-1]} -----")
    try:
        html = get(url)
    except Exception as e:
        print(f"  FEIL: {e}")
        return
    print(f"  lengde={len(html)}  Produktnummer={ (CODE_RE.search(html) or [None,'?'])[1] if CODE_RE.search(html) else '?'}")
    eans = sorted(set(EAN_RE.findall(html)))
    print(f"  13-sifrede EAN/GTIN i HTML: {len(eans)}  ex={eans[:6]}")

    # JSON-LD Product
    ld_found = False
    for blk in LD_RE.findall(html):
        try:
            d = json.loads(blk)
        except json.JSONDecodeError:
            continue
        items = d if isinstance(d, list) else [d]
        for it in items:
            if isinstance(it, dict) and it.get("@type") == "Product":
                ld_found = True
                off = it.get("offers") or {}
                offs = off if isinstance(off, list) else [off]
                print(f"  JSON-LD Product: name={it.get('name')!r} sku={it.get('sku')} "
                      f"gtin13={it.get('gtin13')} #offers={len(offs)} hasVariant={'ja' if it.get('hasVariant') else 'nei'}")
                for o in offs[:4]:
                    if isinstance(o, dict):
                        print(f"      offer: price={o.get('price')} {o.get('priceCurrency')} "
                              f"avail={str(o.get('availability')).split('/')[-1]} sku={o.get('sku')} gtin13={o.get('gtin13')}")
    if not ld_found:
        print("  JSON-LD Product: NEI")

    # drupalSettings
    sm = SETTINGS_RE.search(html)
    if sm:
        raw = sm.group(1)
        keys = []
        try:
            keys = list(json.loads(raw).keys())
        except json.JSONDecodeError:
            pass
        flags = {k: (k in raw.lower()) for k in
                 ["variation", "sku", "stock", "inventory", "attribute", "size", "gtin", "price"]}
        print(f"  drupalSettings: {len(raw)} tegn, toppnøkler={keys[:12]}")
        print(f"    inneholder: {[k for k,v in flags.items() if v]}")
    else:
        print("  drupalSettings: NEI")

    # variant-/størrelses-selector i rendret HTML
    sizes = []
    for sel in SELECT_RE.findall(html):
        opts = [o.strip() for o in OPTION_RE.findall(sel) if o.strip()]
        if any(re.search(r"\d{2}([.,]\d)?", o) for o in opts):   # ser ut som størrelser
            sizes = opts
            break
    print(f"  <select>-størrelser i HTML: {sizes[:14] if sizes else 'ingen/JS-rendret'}")


def main() -> None:
    print("probe_bull — Drupal Commerce 2-kartlegging")
    probe_listing()
    for u in PDPS:
        probe_pdp(u)


if __name__ == "__main__":
    main()
