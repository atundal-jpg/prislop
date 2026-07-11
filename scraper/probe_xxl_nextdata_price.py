#!/usr/bin/env python3
"""
probe_xxl_nextdata_price.py

Formaal: verifisere det EKSAKTE feltet xxl_parser.py bruker for pris
(__NEXT_DATA__ -> initialElevateProductPageData.baseProduct.products[]
 .price.selling.range.min.value), IKKE JSON-LD-feltet probe_xxl_jsonld_price.py
testet. Dette er to forskjellige datablokker i samme HTML-dokument, og
10. juli-funnet sa at begge var stale den gangen -- saa JSON-LD-testen
(PASS 11. juli) beviser ikke automatisk at NEXT_DATA ogsaa er frisk.

Bruker KUN Python stdlib -- ingen pip install noedvendig.

Fasit (bekreftet i nettleser 10.-11. juli):
    1253876 = 1519 kr  (svart)
    1244055 = 1399 kr  (svart, "kun i butikk")

Merk: begge artiklene ligger som separate "colorway"-entries i products-
listen naar man henter EN av de to URL-ene (samme mekanisme som gjorde at
Supabase fikk identisk 1229 paa begge fra én harvest). Vi henter derfor
KUN 1253876-siden og sjekker at BEGGE colorways faar riktig, ULIK pris
fra samme respons -- det er den skarpeste testen.

Kjoer: python probe_xxl_nextdata_price.py
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

# Vi henter bare denne ene siden -- baseProduct.products bør inneholde
# BEGGE style-kodene under (samme mekanisme som ga identisk 1229 i DB).
FETCH_URL = "https://www.xxl.no/nike-vomero-18-lopesko-herre-svart/p/1253876_1_Style"

EXPECTED = {
    "1253876": 1519,
    "1244055": 1399,
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


def extract_next_data(html):
    m = NEXT_RE.search(html)
    if not m:
        return None, "Fant ikke __NEXT_DATA__ i HTML"
    try:
        return json.loads(m.group(1)), None
    except json.JSONDecodeError as e:
        return None, f"Klarte ikke parse __NEXT_DATA__ som JSON: {e}"


def colorway_price(product):
    try:
        return product["price"]["selling"]["range"]["min"]["value"]
    except (KeyError, TypeError):
        return None


def main():
    print("=" * 70)
    print("probe_xxl_nextdata_price.py -- tester EKSAKT parser-felt")
    print(f"Henter: {FETCH_URL}")
    print("=" * 70)

    html, err = fetch_html(FETCH_URL)
    if err:
        print(f"[FEIL] Kunne ikke hente side -- {err}")
        sys.exit(1)

    nd, err = extract_next_data(html)
    if err:
        print(f"[FEIL] {err}")
        sys.exit(1)

    try:
        products = (
            nd["props"]["pageProps"]["newPdpProps"]
            ["initialElevateProductPageData"]["baseProduct"]["products"]
        )
    except (KeyError, TypeError) as e:
        print(f"[FEIL] Fant ikke products-listen paa forventet sti "
              f"(strukturen kan ha endret seg): {e}")
        sys.exit(1)

    found = {}
    for p in products:
        style = str(p.get("code", ""))
        for target_id in EXPECTED:
            if target_id in style:
                found[target_id] = colorway_price(p)

    print(f"\nFant {len(products)} colorway(s) i products-listen totalt.\n")
    print("RESULTAT\n" + "-" * 70)
    all_pass = True
    for pid, expected in EXPECTED.items():
        price = found.get(pid)
        ok = price is not None and float(price) == float(expected)
        all_pass = all_pass and ok
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {pid}: forventet={expected}  fikk={price}")

    print("-" * 70)
    if all_pass:
        print("ALLE PASS -- xxl_parser.py sitt EKSAKTE prisfelt "
              "(NEXT_DATA -> price.selling.range.min.value) er friskt og "
              "gir riktig, ulik pris per fargevariant akkurat naa. "
              "Ingen kodeendring i xxl_parser.py ser ut til aa vaere "
              "noedvendig -- trigg full harvest og verifiser DB, reverser "
              "0012 hvis harvest bekrefter friske, varierte priser.")
    else:
        print("MINST EN FEIL/AVVIK i det faktiske parser-feltet -- selv om "
              "JSON-LD var friskt i gaar, er NEXT_DATA (som parseren "
              "faktisk bruker) fortsatt stale/feil. Da trengs enten en "
              "kildeendring i xxl_parser.py (les fra JSON-LD i staden) "
              "eller norsk proxy-utgang.")

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
