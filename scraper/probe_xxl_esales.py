#!/usr/bin/env python3
"""
probe_xxl_esales.py

Formaal: avgjoere om XXLs Elevate/eSales-API (samme API som discovery/
kategorisidene bruker for produktlister) leverer KORREKTE per-artikkel-priser
naar det kalles fra US-runneren (GitHub Actions), i motsetning til
price-information-api som allerede er bevist geo-gated (probe v4/v5,
10. juli).

Fasit (Norge, nettleser, privat modus):
    1244055 = 1519 kr   (svart #1)
    1253876 = 1399 kr   (svart #2, "kun i butikk")
    <hvit>  = 1749 kr   (artikkelnummer ukjent enna -- fyll inn under)

Bruk:
    1. Aapne en XXL-produktside i nettleser (devtools -> Network).
       Filtrer paa "esales" ELLER "elevate" (IKKE "price" -- det fanger
       price-information-api, som allerede er bevist stale/geo-gated og
       IKKE er det vi tester her).
       Se etter et request mot noe sant som:
         *.cluster.elevate.apptus.cloud/api/v2/...
         *.esales.apptus.cloud/api/...
         storefront.elevate.apptus.cloud/...
       Noter (a) full host/cluster-URL og (b) evt. clusterId/market/locale
       som sendes i requesten (query-param eller JSON-body).
    2. Fyll inn ELEVATE_ENDPOINT og CLUSTER_ID under.
    3. Fyll inn ARTICLE_HVIT (artikkelnummer for hvit fargevei) hvis kjent
       -- ellers kjoer scriptet uten, det hopper da over den sjekken og
       sier ifra.
    4. Kjoer: python probe_xxl_esales.py
       (lokalt: samme resultat forventes uansett hvor du kjoerer fra,
       DERSOM hypotesen stemmer -- det er akkurat det vi tester.)

Output: PASS/FAIL per artikkel + raadata for manuell inspeksjon.
Endrer INGENTING i databasen. Ren lesing.
"""

import json
import sys
import argparse

try:
    import requests
except ImportError:
    print("Mangler 'requests'. Kjoer: pip install requests")
    sys.exit(1)

# ---------------------------------------------------------------------------
# KONFIG -- fyll inn etter devtools-funn (steg 1-3 i docstringen over)
# ---------------------------------------------------------------------------

ELEVATE_ENDPOINT = "FYLL_INN_FRA_DEVTOOLS"   # f.eks. "https://xxx.cluster.elevate.apptus.cloud"
CLUSTER_ID = "FYLL_INN_FRA_DEVTOOLS"          # f.eks. "wABCD1234" -- se etter i request-URL/body
MARKET = "NO"
LOCALE = "nb-NO"

TEST_ARTICLES = {
    "1244055": {"expected": 1519, "note": "svart #1"},
    "1253876": {"expected": 1399, "note": "svart #2, kun i butikk"},
}

ARTICLE_HVIT = None   # fyll inn artikkelnummer for hvit fargevei naar kjent
EXPECTED_HVIT = 1749

if ARTICLE_HVIT:
    TEST_ARTICLES[ARTICLE_HVIT] = {"expected": EXPECTED_HVIT, "note": "hvit"}


# ---------------------------------------------------------------------------
# Kandidat-endepunkter -- forsoeksvis auto-discovery hvis ELEVATE_ENDPOINT
# ikke er fylt inn. Dette er BESTE GJETNING basert paa offentlig
# Apptus/Elevate-dokumentasjon (@apptus/esales-api, Elevate Storefront API v3)
# og er IKKE garantert aa treffe XXLs faktiske cluster. Devtools-funnet
# (steg 1-2 over) er den paalitelige veien -- ikke stol blindt paa disse.
# ---------------------------------------------------------------------------

GUESS_PATTERNS = [
    "https://{cluster}.cluster.elevate.apptus.cloud/api/v3/query/searchPage",
    "https://{cluster}.cluster.elevate.apptus.cloud/api/v2/query/searchPage",
    "https://storefront.elevate.apptus.cloud/api/v3/{cluster}/query/searchPage",
]


def query_elevate(session, endpoint, cluster_id, article_id):
    """Spoer eSales/Elevate for en enkelt artikkel. Returnerer (price, raw)
    eller (None, raw/feilmelding)."""
    payload = {
        "market": MARKET,
        "locale": LOCALE,
        "clusterId": cluster_id,
        "q": article_id,
        "limit": 5,
    }
    try:
        resp = session.post(endpoint, json=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return None, f"FEIL: {e}"

    # Forsoek aa finne pris i typiske Elevate-responsstrukturer.
    # Dette MAA sannsynligvis justeres naar ekte respons er sett -- json-
    # strukturen varierer med clusterkonfig. Print raadata ved mismatch.
    price = None
    try:
        products = data.get("products") or data.get("result", {}).get("products") or []
        for p in products:
            sku = str(p.get("id") or p.get("sku") or p.get("articleNumber") or "")
            if article_id in sku:
                price = (
                    p.get("price")
                    or p.get("salePrice")
                    or (p.get("prices") or {}).get("current")
                )
                break
    except Exception:
        pass

    return price, data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default=ELEVATE_ENDPOINT)
    parser.add_argument("--cluster", default=CLUSTER_ID)
    args = parser.parse_args()

    endpoint = args.endpoint
    cluster = args.cluster

    if endpoint == "FYLL_INN_FRA_DEVTOOLS" or cluster == "FYLL_INN_FRA_DEVTOOLS":
        print("=" * 70)
        print("ELEVATE_ENDPOINT / CLUSTER_ID er ikke fylt inn.")
        print("Proever gjetning-kandidater (se GUESS_PATTERNS) -- disse er")
        print("IKKE paalitelige. Bekreft ekte endepunkt via devtools foerst")
        print("(Network-fanen, filtrer 'esales' eller 'elevate', ikke 'price').")
        print("=" * 70)

    session = requests.Session()
    session.headers.update({"User-Agent": "prislop-probe/1.0"})

    results = []
    endpoints_to_try = [endpoint] if endpoint != "FYLL_INN_FRA_DEVTOOLS" else [
        p.format(cluster=cluster) for p in GUESS_PATTERNS
    ]

    for article_id, meta in TEST_ARTICLES.items():
        found_price, raw = None, None
        used_endpoint = None
        for ep in endpoints_to_try:
            price, raw = query_elevate(session, ep, cluster, article_id)
            if price is not None:
                found_price, used_endpoint = price, ep
                break
        results.append((article_id, meta, found_price, used_endpoint, raw))

    print("\nRESULTAT\n" + "-" * 70)
    all_pass = True
    for article_id, meta, price, used_endpoint, raw in results:
        expected = meta["expected"]
        ok = price is not None and float(price) == float(expected)
        all_pass = all_pass and ok
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {article_id} ({meta['note']}): "
              f"forventet={expected}  fikk={price}  endpoint={used_endpoint}")
        if not ok:
            print(f"        raadata: {json.dumps(raw, ensure_ascii=False)[:500]}")

    print("-" * 70)
    if all_pass:
        print("ALLE PASS -- Elevate/eSales leverer korrekte priser fra denne "
              "runneren. Neste steg: fiks xxl_parser til aa bruke dette "
              "endepunktet, verifiser full harvest, reverser 0012.")
    else:
        print("MINST EN FAIL (eller ukjent endepunkt) -- Elevate/eSales er "
              "enten geo-gated paa samme maate som price-information-api, "
              "eller endepunktet/clusterId over er feil. Hvis endepunktet "
              "er bekreftet riktig og det fortsatt failer: skisser norsk "
              "proxy-utgang for XXL-henting i staedet. XXL forblir i "
              "karantene (0012) til en av veiene er verifisert.")

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
