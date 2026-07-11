#!/usr/bin/env python3
"""
probe_xxl_group_dump.py

Formaal: dumpe ALLE fargevarianter (products[]) fra ETT hent av Vomero 18
herre-gruppen, for aa se hele monsteret i price.selling.range.min.value
paa tvers av farger samtidig -- i staden for aa gjette oss frem art-for-
artikkel.

Kjente datapunkter (bekreftet i nettleser/app 11. juli):
    Svart, kun i butikk : 1244055_1_Style -> 1399 kr
    Svart, vanlig (nett): 1253876_1_Style -> 1519 kr
    Hvit,  kun i butikk : ukjent artikkelnr -> 1229 kr
    Hvit,  vanlig (nett): 1247272_1_Style -> 1749 kr

Bruker KUN Python stdlib.

Kjoer: python probe_xxl_group_dump.py
"""

import json
import re
import sys
import urllib.request
import urllib.error

TIMEOUT_SECONDS = 20
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
)

FETCH_URL = "https://www.xxl.no/nike-vomero-18-lopesko-herre-svart/p/1253876_1_Style"

KNOWN = {
    "1244055": ("Svart, kun i butikk", 1399),
    "1253876": ("Svart, vanlig (nett)", 1519),
    "1247272": ("Hvit, vanlig (nett)", 1749),
    "1240624": ("Hvit, kun i butikk", 1229),
}

NEXT_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def fetch_html(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "nb,no;q=0.9,en;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset, errors="replace"), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP-FEIL {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        return None, f"NETTVERKS-FEIL: {e.reason}"
    except Exception as e:
        return None, f"FEIL: {e}"


def find_store_only_flag(product):
    """Let etter felt som kan indikere 'kun i butikk' andre steder enn
    kjente navn -- printer raatt hvis usikkert."""
    for key in ("storeOnly", "onlineOnly", "channel", "availabilityChannels",
                "purchasable", "onlinePurchasable"):
        if key in product:
            return f"{key}={product[key]}"
    return None


def main():
    print("=" * 70)
    print("probe_xxl_group_dump.py -- full dump av produktgruppen")
    print(f"Henter: {FETCH_URL}")
    print("=" * 70)

    html, err = fetch_html(FETCH_URL)
    if err:
        print(f"[FEIL] Kunne ikke hente side -- {err}")
        sys.exit(1)

    m = NEXT_RE.search(html)
    if not m:
        print("[FEIL] Fant ikke __NEXT_DATA__ i HTML")
        sys.exit(1)

    try:
        nd = json.loads(m.group(1))
    except json.JSONDecodeError as e:
        print(f"[FEIL] Klarte ikke parse __NEXT_DATA__: {e}")
        sys.exit(1)

    try:
        products = (
            nd["props"]["pageProps"]["newPdpProps"]
            ["initialElevateProductPageData"]["baseProduct"]["products"]
        )
    except (KeyError, TypeError) as e:
        print(f"[FEIL] Fant ikke products-listen paa forventet sti: {e}")
        sys.exit(1)

    print(f"\nFant {len(products)} fargevariant(er) i gruppen.\n")
    print(f"{'code':<20} {'color':<15} {'min_price':<10} {'flagg':<30} kjent?")
    print("-" * 90)

    all_min_prices = []
    for p in products:
        code = str(p.get("code", ""))
        color = p.get("localizedColorName") or p.get("baseColor") or "?"
        try:
            price = p["price"]["selling"]["range"]["min"]["value"]
        except (KeyError, TypeError):
            price = None
        if price is not None:
            all_min_prices.append(price)
        flag = find_store_only_flag(p) or "-"

        matched = None
        for known_id, (label, expected) in KNOWN.items():
            if known_id in code:
                matched = f"{known_id} ({label}, forventet {expected})"
                break
        matched = matched or "UKJENT ARTIKKEL"

        print(f"{code:<20} {color:<15} {str(price):<10} {flag:<30} {matched}")

    print("-" * 90)
    if all_min_prices:
        group_min = min(all_min_prices)
        print(f"\nLaveste 'min_price' i hele gruppen: {group_min}")
        n_matching_group_min = sum(1 for x in all_min_prices if x == group_min)
        print(f"Antall fargevarianter som viser NØYAKTIG denne verdien: "
              f"{n_matching_group_min} av {len(all_min_prices)}")
        if n_matching_group_min > 1:
            print("-> Sterk indikasjon paa at 'min' er et GRUPPE-nivaa felt, "
                  "ikke per-fargevariant. Parseren maa i saa fall lese et "
                  "annet felt for aa faa riktig pris per farge.")

    print("\nFull raadata (for manuell inspeksjon av evt. andre prisfelt):")
    print(json.dumps(products, ensure_ascii=False, indent=2)[:6000])


if __name__ == "__main__":
    main()
