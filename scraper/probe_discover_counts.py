#!/usr/bin/env python3
"""
probe_discover_counts.py

Formaal: bekrefte at discovery.discover() for XXL faktisk returnerer det
FULLE settet unike produkt-URL-er per merke (~142 for Nike), og ikke et
dedup-kollapset lavere tall. Hvis den gjor det, er "794 -> 229"-krympingen
IKKE et discovery-problem -- den maa da komme fra parser-spredning +
last-write-wins i loader/DB. Det avgjor at isSelected-fiksen er trygg og
ikke koster dekning.

Importerer prosjektets EKTE discovery.py. Endrer ingenting. Ren telling.

Kjoer i repo-roten (samme mappe som discovery.py):
    python probe_discover_counts.py
"""

import sys

try:
    import discovery
except Exception as e:
    print(f"Kunne ikke importere discovery.py: {e}")
    print("Kjor scriptet fra samme mappe som discovery.py ligger i.")
    sys.exit(1)


class _Fetcher:
    """Minimal fetcher med .get(url) -- discovery bruker den kun for
    fallback-stien; eSales-API-et kalles direkte uten fetcher."""
    import urllib.request

    def get(self, url):
        try:
            req = self.urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0 (prislop)"})
            with self.urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            print(f"  [fetcher] feil {url}: {e}")
            return ""


def main():
    fetcher = _Fetcher()
    brands = ["asics", "adidas", "nike", "puma", "mizuno"]
    print("XXL discover()-tellinger per merke (unike produkt-URL-er):")
    print("-" * 60)
    grand_total = 0
    all_urls = set()
    for brand in brands:
        try:
            urls = discovery.discover(fetcher, "xxl", brand, "", limit=8)
        except Exception as e:
            print(f"  {brand:<10} FEIL: {e}")
            continue
        n = len(urls)
        grand_total += n
        all_urls.update(urls)
        # tell hvor mange distinkte produktnr (…/p/NR_…) som er representert
        import re
        nrs = set()
        for u in urls:
            m = re.search(r"/p/(\d+)_", u)
            if m:
                nrs.add(m.group(1))
        print(f"  {brand:<10} {n:>4} url-er   {len(nrs):>4} distinkte produktnr")
    print("-" * 60)
    print(f"  SUM (m/ dobbelttelling): {grand_total}")
    print(f"  SUM unike url-er totalt: {len(all_urls)}")
    print()
    print("Tolkning: hvis SUM unike url-er ~= 700-800, besoker discovery "
          "allerede hver fargevariant sin egen side, og krympingen til ~229/440 "
          "skjer NEDSTROMS (parser-spredning + last-write-wins). Da gjenoppretter "
          "isSelected-fiksen full dekning MED riktig pris, uten flere kall.")


if __name__ == "__main__":
    main()
