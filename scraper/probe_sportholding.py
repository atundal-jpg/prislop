#!/usr/bin/env python3
"""
probe_sportholding.py — ENGANGS-DIAGNOSE.

Spørsmål: er Intersport / Sport 1 / Löplabbet samme data-form, slik at ÉN delt
parser (dagens parse_intersport) holder for alle tre?

Kjøres i GitHub Actions (butikkdomenene er nåbare der, ikke fra Claudes sandkasse).
Skriver INGENTING til databasen — ren lesing. Ingen ekstra avhengigheter utover
stdlib + intersport_parser fra repoet (krever derfor ikke SUPABASE_DB_URL).

Per butikk:
  A) LISTING — henter kandidat-URL-er og teller hvor mange produkt-slug-lenker
     (slug som ender på Asics-stilkode, f.eks. ...-1012b765) hver gir. Forteller
     hvilken discovery-URL som funker, og om den server-rendrer mange eller få.
  B) PDP — kjører parse_intersport på én produktside og rapporterer hva som ble
     trukket ut: JSON-LD, RSC-variants, videoly/colorway, pris, størrelser + EAN.

Tolkning:
  - Hvis B gir brand/model/price + #sizes>0 på ALLE tre  -> delt parser holder, ship.
  - Hvis videoly-match=False, men slug-stilkode finnes   -> trenger kun slug-fallback
                                                            for code/color (lett fiks).
  - Hvis RSC variants=False                              -> størrelser ligger annet sted
                                                            på den butikken (egen gren).
"""
from __future__ import annotations
import re
import urllib.request

import intersport_parser as P

UA = "Mozilla/5.0 (prislop-probe)"

# Slug som ender på en Asics-stilkode: 4 siffer + bokstav + 3 siffer (f.eks. 1012b765).
SLUG_RE = re.compile(r"/[a-z0-9-]+-\d{4}[a-z]\d{3}\b", re.I)
HREF_RE = re.compile(r'href="([^"#]+)"', re.I)
LD_PRODUCT_RE = re.compile(r'"@type"\s*:\s*"Product"')

STORES = {
    "intersport (referanse, kjent-god)": {
        "listing": [
            "https://www.intersport.no/search?query=asics%20novablast&tab=products",
            "https://www.intersport.no/asics?Gender=Herre",
            "https://www.intersport.no/merker/asics",
        ],
        "pdp": "https://www.intersport.no/asics-novablast-5-whitefawn-dame-1012b765",
    },
    "sport1": {
        "listing": [
            "https://www.sport1.no/asics",
            "https://www.sport1.no/search?query=asics%20novablast&tab=products",
        ],
        "pdp": "https://www.sport1.no/asics-novablast-5-bluebelllilac-hint-dame-1012b765",
    },
    "loplabbet": {
        "listing": [
            "https://loplabbet.no/lopesko?Brand=ASICS",
            "https://loplabbet.no/search?query=asics%20novablast",
        ],
        "pdp": "https://loplabbet.no/asics-gel-nimbus-28-energy-aquamidnight-herre-1011c127",
    },
}


def get(url: str) -> str:
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept-Language": "nb-NO,nb;q=0.9"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def probe_listing(url: str) -> str:
    try:
        html = get(url)
    except Exception as e:
        return f"      -> FEIL: {e}"
    hits = sorted({h for h in HREF_RE.findall(html) if SLUG_RE.search(h)})
    ex = hits[0] if hits else "-"
    return f"      -> {len(html):>7} B   produkt-lenker = {len(hits):>3}   ex: {ex}"


def probe_pdp(url: str) -> None:
    try:
        html = get(url)
    except Exception as e:
        print(f"      -> FEIL henting: {e}")
        return

    esc = "variants\\\":[" in html          # samme literal som parse_intersport leter etter
    plain = '"variants":[' in html          # ueskapet JSON-variant
    m = P.VIDEOLY_ID_RE.search(html)
    sm = SLUG_RE.search(url)
    slug_code = sm.group(0).rsplit("-", 1)[-1].upper() if sm else "-"

    print(f"      lengde:            {len(html)} B")
    print(f"      ld+json blokk:     {'JA' if 'application/ld+json' in html else 'NEI'}")
    print(f"      @type Product:     {'JA' if LD_PRODUCT_RE.search(html) else 'NEI'}")
    print(f"      RSC variants:      escaped={esc}  plain={plain}")
    print(f"      videoly-id div:    {'JA' if 'videoly-product-id' in html else 'NEI'}")
    print(f"      videoly-regex:     {'MATCH ' + str(m.groups()) if m else 'INGEN MATCH'}")
    print(f"      slug-stilkode:     {slug_code}")

    rec = P.parse_intersport(html, url)
    print(f"      -> parse_intersport():")
    print(f"         brand={rec['brand']!r}  model={rec['model']!r}  gender={rec['gender']!r}")
    print(f"         color={rec['color']!r}  code={rec['manufacturer_code']!r}")
    print(f"         price={rec['price']!r} {rec['currency']}  #sizes={len(rec['sizes'])}")
    for s in rec["sizes"][:5]:
        print(f"           {str(s['size_label']):>6}  EAN={s['ean']}  qty={s['stock_count']}  in_stock={s['in_stock']}")

    ok = bool(rec["brand"] and rec["model"] and rec["price"]) and len(rec["sizes"]) > 0
    code_ok = bool(rec["manufacturer_code"])
    verdict = "PASS" if (ok and code_ok) else ("DELVIS" if ok else "FEIL")
    note = "" if code_ok else "  (code/color mangler -> trenger slug-fallback)"
    print(f"      VERDIKT: {verdict}{note}")


def main() -> None:
    print("probe_sportholding — sjekker om én delt parser holder for konsernet\n")
    for name, cfg in STORES.items():
        print(f"===== {name} =====")
        print("  A) LISTING (hvilken URL gir produkt-lenker, og hvor mange?):")
        for u in cfg["listing"]:
            print(f"    {u}")
            print(probe_listing(u))
        print(f"  B) PDP: {cfg['pdp']}")
        probe_pdp(cfg["pdp"])
        print()


if __name__ == "__main__":
    main()
