#!/usr/bin/env python3
"""
probe_esales_links.py

Formaal: se om XXLs eSales landing-page-query gir en EGEN, unik URL per
produktnummer (fargevariant), eller om flere sosken-farger deler samme
`link`. Dette avgjor om dekningsfiksen i discovery.py er triviell (URL-ene
finnes allerede -> slutt aa dedupe) eller om vi maa konstruere per-produkt-
nummer-URL-er selv.

Fokus: Nike Vomero 18 herre -- vi vet den har fire fargevarianter med disse
produktnumrene: 1253876, 1244055, 1247272, 1240624.

Bruker kun stdlib. Speiler _esales_paths() sin request 1:1, men dumper
raa (link, produktnr, farge, navn) i staden for aa deduplisere.

Kjoer: python probe_esales_links.py
"""

import json
import re
import sys
import uuid
import urllib.request
from urllib.parse import urlencode

API = {
    "url": "https://wae24fd27.api.esales.apptus.cloud/api/storefront/v3/queries/landing-page",
    "customerKey": "10cdaf6d-129a-498c-b0c9-f450442915f3",
    "site": "xxl.no",
    "brand_filter": "Nike",
    "pageReference": "/c/142010",
    "stores": "|".join(str(n) for n in range(301, 340)),
    "limit": 32,
}

VOMERO_NRS = {"1253876", "1244055", "1247272", "1240624"}


def esales_dump(api):
    limit = int(api["limit"])
    common = {
        "channels": "ONLINE|STORE",
        "customerKey": api["customerKey"],
        "sessionKey": str(uuid.uuid4()),
        "site": api["site"],
        "stores": api["stores"],
        "touchpoint": "DESKTOP",
        "priceId": "member",
        "f.brand": api["brand_filter"],
        "notify": "true",
        "pageReference": api["pageReference"],
        "locale": "nb-NO",
        "market": "NO",
        "templateId": "PLP",
        "limit": str(limit),
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": "https://www.xxl.no",
        "Referer": "https://www.xxl.no/",
        "User-Agent": "Mozilla/5.0 (prislop)",
    }
    rows = []
    skip, total = 0, None
    while skip <= 2000:
        params = dict(common, skip=str(skip))
        url = api["url"] + "?" + urlencode(params)
        try:
            req = urllib.request.Request(url, data=b"", headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            print(f"eSales-feil skip={skip}: {e}")
            break
        primary = data.get("primaryList") or {}
        if total is None:
            total = primary.get("totalHits") or 0
        groups = primary.get("productGroups") or []
        if not groups:
            break
        for g in groups:
            gkey = g.get("key") or g.get("id") or "?"
            for p in (g.get("products") or []):
                link = p.get("link") or ""
                # prov aa hente produktnr fra link (…/p/NNNNNNN_…) og fra felt
                nr_from_link = None
                m = re.search(r"/p/(\d+)_", link)
                if m:
                    nr_from_link = m.group(1)
                rows.append({
                    "group": gkey,
                    "link": link,
                    "nr_from_link": nr_from_link,
                    "id": p.get("id"),
                    "name": p.get("name") or p.get("title"),
                    "price": (p.get("price") or {}).get("current")
                             if isinstance(p.get("price"), dict) else p.get("price"),
                })
        skip += limit
        if total and skip >= total:
            break
    return rows, total


def main():
    rows, total = esales_dump(API)
    print(f"Totalt {len(rows)} produkt-entries hentet (totalHits={total}).\n")

    # Fokuser paa Vomero 18
    vomero = [r for r in rows if (r["name"] and "vomero 18" in r["name"].lower())
              or (r["nr_from_link"] in VOMERO_NRS)]
    print("=" * 80)
    print("VOMERO 18-entries (raatt, IKKE deduplisert):")
    print("=" * 80)
    if not vomero:
        print("  (fant ingen -- sjekk om navnet staves annerledes i eSales)")
    for r in vomero:
        print(f"  nr_link={r['nr_from_link']:<10} id={str(r['id']):<14} "
              f"pris={str(r['price']):<8} link={r['link']}")

    # Nokkelsporsmaal: hvor mange UNIKE links vs unike produktnr totalt?
    all_links = [r["link"] for r in rows if r["link"]]
    all_nrs = [r["nr_from_link"] for r in rows if r["nr_from_link"]]
    print("\n" + "=" * 80)
    print(f"Unike links:        {len(set(all_links))}")
    print(f"Unike produktnr:    {len(set(all_nrs))}")
    print(f"Totalt entries:     {len(rows)}")
    if len(set(all_links)) < len(set(all_nrs)):
        print("-> FLERE produktnr enn links: sosken-farger DELER url. "
              "Da maa discovery konstruere per-nr-url (…/p/NR_1_Style) selv.")
    elif len(set(all_links)) == len(set(all_nrs)):
        print("-> Like mange: hver fargevariant har EGEN url i link-feltet. "
              "Da er fiksen triviell: slutt aa dedupe paa gruppe, behold alle links.")


if __name__ == "__main__":
    main()
