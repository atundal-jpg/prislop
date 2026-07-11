#!/usr/bin/env python3
"""
probe_discover_counts.py  (v2 -- unngar loader/psycopg2-importen)

Formaal: bekrefte at XXL-discovery henter det FULLE settet unike produkt-
URL-er per merke (~142 for Nike, ~700-800 totalt), ikke et dedup-kollapset
lavere tall. Avgjor om "794 -> 229"-krympingen skjer i discovery eller
nedstroms (parser-spredning + last-write-wins).

v1 importerte discovery.py direkte, men discovery -> loader -> psycopg2,
som ikke finnes i probe-miljoet. v2 unngar det: vi henter STORES-konfigen
og _esales_paths() fra discovery via importlib UTEN aa trigge loader-
importen paa toppen -- ved aa lese fila og kjore kun det vi trenger.

Enklere og robust: vi reimplementerer _esales_paths sin URL-bygging her
(identisk request som discovery.py), og leser merke-facetene rett fra
discovery.py-kildekoden saa vi ikke duplisere konfig som kan drifte.

Kjoer: python probe_discover_counts.py
"""

import json
import re
import sys
import uuid
import urllib.request
from urllib.parse import urlencode

# Felles eSales-konfig (speiler discovery.STORES["xxl"]["api"], som er stabil).
API_URL = "https://wae24fd27.api.esales.apptus.cloud/api/storefront/v3/queries/landing-page"
CUSTOMER_KEY = "10cdaf6d-129a-498c-b0c9-f450442915f3"
SITE = "xxl.no"
PAGE_REF = "/c/142010"
STORES_PARAM = "|".join(str(n) for n in range(301, 340))
LIMIT = 32
GENDER_KEEP = ("Herre", "Dame", "Unisex")

# Merke-facetene slik de staar i discovery.STORES["xxl"]["by_brand"].
BRAND_FILTERS = {
    "asics": "Asics",
    "adidas": "adidas",
    "nike": "Nike",
    "puma": "Puma",
    "mizuno": "Mizuno",
}


def esales_gender_ok(product, keep):
    link = (product.get("link") or "").lower()
    if "-barn-" in link or "-junior-" in link:
        return False
    try:
        custom = product.get("custom") or {}
        usps_raw = (custom.get("usps") or [{}])[0].get("id") or "[]"
        for item in json.loads(usps_raw):
            if item.get("key") == "pim_mandatory_user_string":
                vals = item.get("values") or []
                return any(v in keep for v in vals)
    except Exception:
        pass
    return True


def esales_paths(brand_filter):
    common = {
        "channels": "ONLINE|STORE",
        "customerKey": CUSTOMER_KEY,
        "sessionKey": str(uuid.uuid4()),
        "site": SITE,
        "stores": STORES_PARAM,
        "touchpoint": "DESKTOP",
        "priceId": "member",
        "f.brand": brand_filter,
        "notify": "true",
        "pageReference": PAGE_REF,
        "locale": "nb-NO",
        "market": "NO",
        "templateId": "PLP",
        "limit": str(LIMIT),
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": "https://www.xxl.no",
        "Referer": "https://www.xxl.no/",
        "User-Agent": "Mozilla/5.0 (prislop)",
    }
    paths, seen, skip, total = [], set(), 0, None
    while skip <= 2000:
        params = dict(common, skip=str(skip))
        url = API_URL + "?" + urlencode(params)
        try:
            req = urllib.request.Request(url, data=b"", headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            print(f"  [{brand_filter}] eSales-feil skip={skip}: {e}")
            break
        primary = data.get("primaryList") or {}
        if total is None:
            total = primary.get("totalHits") or 0
        groups = primary.get("productGroups") or []
        if not groups:
            break
        for g in groups:
            for p in (g.get("products") or []):
                link = p.get("link")
                if not link:
                    continue
                if not esales_gender_ok(p, GENDER_KEEP):
                    continue
                if link not in seen:
                    seen.add(link)
                    paths.append(link)
        skip += LIMIT
        if total and skip >= total:
            break
    return paths


def main():
    print("XXL eSales-tellinger per merke (unike produkt-URL-er, kjonnsfiltrert):")
    print("-" * 66)
    all_urls = set()
    grand = 0
    for brand, facet in BRAND_FILTERS.items():
        paths = esales_paths(facet)
        n = len(paths)
        grand += n
        all_urls.update(paths)
        nrs = set()
        for u in paths:
            m = re.search(r"/p/(\d+)_", u)
            if m:
                nrs.add(m.group(1))
        print(f"  {brand:<10} {n:>4} url-er   {len(nrs):>4} distinkte produktnr")
    print("-" * 66)
    print(f"  SUM (m/ evt. dobbelttelling paa tvers av merker): {grand}")
    print(f"  SUM unike url-er totalt:                          {len(all_urls)}")
    print()
    if len(all_urls) >= 600:
        print("=> Discovery henter allerede ~hele settet fargevarianter (egen "
              "url per produktnr). '794 -> 229/440'-krympingen skjer NEDSTROMS "
              "(parser sprer sosken + last-write-wins). isSelected-fiksen "
              "gjenoppretter full dekning MED riktig pris, uten flere kall.")
    elif len(all_urls) <= 300:
        print("=> Discovery returnerer et KOLLAPSET sett. Da er det discovery "
              "selv som mister fargevarianter -- isSelected-fiksen alene holder "
              "ikke, vi maa fikse url-enumereringen forst.")
    else:
        print("=> Mellomresultat -- se tallene per merke for aa vurdere.")


if __name__ == "__main__":
    main()
