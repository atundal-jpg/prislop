#!/usr/bin/env python3
"""
probe_xxl_jsonld_price.py

Formaal: rask, isolert sjekk av om XXLs JSON-LD (embedded i produktsiden)
leverer korrekt pris naar den hentes fra GitHub Actions-runneren -- uten
aa maatte vente paa en full scrape-kjoring.

Bakgrunn (10.-11. juli): Supabase har vist 1229 kr (identisk, uendret i
48t) for begge artiklene under, mens en manuell nettleser-sjekk og en
web-fetch fra Anthropics infrastruktur begge har vist korrekte, ULIKE
priser. Dette scriptet tester om GitHub Actions-runnerens forespoersel
gir samme (riktige) svar, eller fortsatt det stale/like tallet.

Bruker KUN Python stdlib -- ingen pip install noedvendig.

Fasit (bekreftet i nettleser 10.-11. juli):
    1253876 = 1519 kr  (svart)
    1244055 = 1399 kr  (svart, "kun i butikk")

Kjoer: python probe_xxl_jsonld_price.py
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

TEST_PRODUCTS = {
    "1253876": {
        "url": "https://www.xxl.no/nike-vomero-18-lopesko-herre-svart/p/1253876_1_Style",
        "expected": 1519,
    },
    "1244055": {
        "url": "https://www.xxl.no/nike-vomero-18-lopesko-herre-svart/p/1244055_1_Style",
        "expected": 1399,
    },
}

JSONLD_RE = re.compile(
    r'<script type="application/ld\+json"[^>]*>(.*?)</script>',
    re.DOTALL,
)


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


def extract_price(html, product_group_id):
    """Finn foerste JSON-LD-blokk med matchende productGroupId og hent
    UnitPriceSpecification-prisen fra foerste variant."""
    for match in JSONLD_RE.finditer(html):
        raw = match.group(1).strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue

        items = data if isinstance(data, list) else [data]
        for item in items:
            if str(item.get("productGroupId", "")) != product_group_id:
                continue
            variants = item.get("hasVariant", [])
            for v in variants:
                for offer in v.get("offers", []):
                    for spec in offer.get("priceSpecification", []):
                        if "price" in spec:
                            return spec["price"], None
    return None, "Fant ingen matchende productGroupId/pris i JSON-LD"


def main():
    print("=" * 70)
    print("probe_xxl_jsonld_price.py -- direkte JSON-LD-sjekk (ingen cache-tricks)")
    print("=" * 70)

    all_pass = True
    for pid, meta in TEST_PRODUCTS.items():
        html, err = fetch_html(meta["url"])
        if err:
            print(f"[FEIL] {pid}: kunne ikke hente side -- {err}")
            all_pass = False
            continue

        price, err = extract_price(html, pid)
        if err:
            print(f"[FEIL] {pid}: {err}")
            all_pass = False
            continue

        expected = meta["expected"]
        ok = float(price) == float(expected)
        all_pass = all_pass and ok
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {pid}: forventet={expected}  fikk={price}  "
              f"url={meta['url']}")

    print("-" * 70)
    if all_pass:
        print("ALLE PASS -- JSON-LD leverer korrekte, ULIKE priser fra denne "
              "runneren akkurat naa. Sannsynlig aarsak til 1229-verdien i "
              "Supabase: forbigaaende CDN-staleness paa hentetidspunktet, "
              "ikke vedvarende geo-blokkering. Kjoer full harvest og "
              "bekreft at DB oppdateres foer dere reverserer 0012.")
    else:
        print("MINST EN FEIL/AVVIK -- staleness/geo-problemet er fortsatt "
              "tilstede fra denne runneren. Da er norsk proxy-utgang "
              "fortsatt riktig vei videre.")

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
