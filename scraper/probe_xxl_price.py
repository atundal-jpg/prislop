#!/usr/bin/env python3
"""
probe_xxl_price.py — hvilket prisfelt i XXLs __NEXT_DATA__ er «XXL-Pris»?

Bakgrunn (10. juli): xxl_parser leser price.selling.range.min — for
Vomero 18 herre ga det 1229 på alle 4 artikler, mens XXL-siden viser
1519 (svart, «Få igjen») og 1749 (hvit). Hypotese: range.min er laveste
størrelses-/restpris, ikke gjeldende hovedpris. Proben dumper HELE
price-objektet (og per-størrelse-priser om de finnes) for de fire
artiklene, så feltvalget kan rettes på fakta.

Kjøres via probe.yml (script=probe_xxl_price.py). psycopg2 stubbes.
"""
from __future__ import annotations
import json, re, sys, types, urllib.request

if "psycopg2" not in sys.modules:
    _pg = types.ModuleType("psycopg2"); _pg.extras = types.ModuleType("psycopg2.extras")
    _pg.connect = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("stub"))
    sys.modules["psycopg2"] = _pg; sys.modules["psycopg2.extras"] = _pg.extras

try:
    from fetch import Fetcher
except Exception:
    class Fetcher:
        def get(self, url):
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (prislop-probe)",
                                                       "Accept-Language": "nb-NO"})
            try:
                with urllib.request.urlopen(req, timeout=40) as r:
                    return r.read().decode("utf-8", "replace")
            except Exception as e:
                print("    fetch-feil %s: %s" % (url, e)); return None

# Fasit fra bruker 10. juli: svart = 1519 («Få igjen»), hvit = 1749.
# Vi lagret 1229 for alle fire.
URLS = [
    "https://www.xxl.no/nike-vomero-18-lopesko-herre-svart/p/1244055_1_Style",
    "https://www.xxl.no/nike-vomero-18-lopesko-herre-svart/p/1253876_1_Style",
    "https://www.xxl.no/nike-vomero-18-lopesko-herre-hvit/p/1240624_1_Style",
    "https://www.xxl.no/nike-vomero-18-lopesko-herre-hvit/p/1247272_1_Style",
]

NEXT_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def walk(node, path, out):
    """Samle alle sub-objekter der nøkkelen heter price/prices/pricing e.l."""
    if isinstance(node, dict):
        for k, v in node.items():
            p = path + "." + k
            if re.search(r"price|pricing", k, re.I) and isinstance(v, (dict, list, int, float, str)):
                out.append((p, v))
            else:
                walk(v, p, out)
    elif isinstance(node, list):
        for i, v in enumerate(node[:12]):
            walk(v, f"{path}[{i}]", out)


def main():
    f = Fetcher()
    for url in URLS:
        print("=" * 78)
        print("URL:", url)
        html = f.get(url)
        if not html:
            continue
        m = NEXT_RE.search(html)
        if not m:
            print("  FANT IKKE __NEXT_DATA__ (endret sidestruktur?)")
            # nødløsning: kontekst rundt fasit-tall i rå HTML
            for tall in ("1519", "1749", "1229", "1 519", "1 749", "1 229"):
                for mm in list(re.finditer(re.escape(tall), html))[:2]:
                    s = re.sub(r"\s+", " ", html[max(0, mm.start()-180):mm.end()+180])
                    print(f"  «{tall}»: {s}")
            continue
        try:
            data = json.loads(m.group(1))
        except Exception as e:
            print("  JSON-feil:", e)
            continue
        found = []
        walk(data, "$", found)
        print(f"  {len(found)} pris-noder funnet; skriver de 10 første (dedup på innhold):")
        seen = set()
        n = 0
        for p, v in found:
            blob = json.dumps(v, ensure_ascii=False)
            if blob in seen:
                continue
            seen.add(blob)
            print(f"  [{n}] {p}")
            print("      " + blob[:700])
            n += 1
            if n >= 10:
                break
    print("=" * 78)
    print("Les av: hvilket felt matcher fasit (svart 1519 / hvit 1749), og hva")
    print("inneholder range.min (dagens feilkilde, 1229)? Fiks xxl_parser deretter.")


if __name__ == "__main__":
    main()
