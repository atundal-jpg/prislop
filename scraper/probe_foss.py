#!/usr/bin/env python3
"""
probe_foss.py — kartlegg Foss Sport (foss-sport.no) for discovery + parser.

Plattform (alt bekreftet via web_fetch): Demonstrare/Multicase (ASP.NET),
SERVER-RENDRET. Listingen /asics viser produktene i HTML med:
  - produkt-URL `/asics/<id>/<asics-slug>`
  - lager inline på listingen (in-stock2.png + antall «20+/5/1», no-stock2.png)
  - colorway-kode synlig i bilde-filnavn (f.eks. «1013a162_101_…»)

Hva v1 må svare på (skriv IKKE parser før dette er bekreftet):
  1) PAGINERING: gir /asics alt på én side, eller må vi paginere? Test
     ?page=N / ?p=N / ?side=N og sammenlign produkt-URL-settene. Finn total-tall.
  2) PDP: har produktsida per-størrelse-lager (select/dropdown med lagerstatus)?
  3) EAN/GTIN per størrelse (broer mot XXL/Löplabbet/Brukås) — eller bare kode?
  4) JSON-LD til stede (navn/merke/pris)? Asics-stilkode (manufacturer_code)?

Stdlib only. Kjøres via .github/workflows/probe.yml (script=probe_foss.py).
"""
from __future__ import annotations
import json
import re
import urllib.request
import urllib.error

UA = "Mozilla/5.0 (prislop-probe)"
BASE = "https://www.foss-sport.no"
LISTING = "/asics"

PROD_A = re.compile(r'href="(/asics/\d+/[^"#?]+)"', re.I)
LD = re.compile(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I)
EAN_RE = re.compile(r'\b(\d{13})\b')
STOCK_IMG = re.compile(r'(in-stock2|no-stock2)\.png', re.I)
CODE_IMG = re.compile(r'/(\d{4}[a-z]\d{3})_', re.I)   # Asics-stilkode i bilde-filnavn


def get(path):
    url = path if path.startswith("http") else BASE + path
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "nb-NO"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return None, "FEIL %s" % e


def prod_urls(html):
    seen, out = set(), []
    for h in PROD_A.findall(html):
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out


def ld_products(html):
    res = []
    for blk in LD.findall(html):
        try:
            d = json.loads(blk)
        except Exception:
            continue
        for it in (d if isinstance(d, list) else [d]):
            if isinstance(it, dict) and it.get("@type") in ("Product", "ProductGroup"):
                res.append(it)
    return res


def section(html, needle, before=160, after=1800):
    i = html.lower().find(needle.lower())
    if i < 0:
        return ""
    return re.sub(r"\s+", " ", html[max(0, i - before):i + after])


def probe_pagination():
    print("=" * 78)
    print("1) PAGINERING")
    st, base_html = get(LISTING)
    base_set = set(prod_urls(base_html))
    print("  /asics -> HTTP %s, %d B, %d unike produkt-URL-er" % (st, len(base_html), len(base_set)))

    # total-tall-hint
    for needle in ["Totalt antall treff", "antall treff", "treff", "av "]:
        sec = section(base_html, needle, 40, 120)
        if sec:
            print("  total-hint («%s»): …%s…" % (needle, sec[:160]))
            break

    # test paginerings-parametre
    for param in ["page", "p", "side", "pagenumber"]:
        st2, html2 = get("%s?%s=2" % (LISTING, param))
        s2 = set(prod_urls(html2))
        new = s2 - base_set
        print("  ?%s=2 -> HTTP %s, %d URL-er, %d NYE vs side 1  %s"
              % (param, st2, len(s2), len(new), "<-- PAGINERER" if len(new) >= 3 else ""))

    # paginerings-kontroller i markup
    for needle in ["pagination", "pager", "Se hele resultatet", "vis flere", "Neste", "page=", "loadMore", "data-page"]:
        sec = section(base_html, needle, 30, 200)
        if sec:
            print("  kontroll-hint («%s»): …%s…" % (needle, sec[:200]))
    return list(base_set)[:3]


def probe_pdp(path):
    print("\n" + "-" * 78)
    print("PDP:", path)
    st, html = get(path)
    print("  HTTP %s, %d B" % (st, len(html)))
    if not html:
        return

    lds = ld_products(html)
    print("  JSON-LD Product/ProductGroup: %d" % len(lds))
    for p in lds[:1]:
        off = p.get("offers") or {}
        if isinstance(off, list):
            off = off[0] if off else {}
        print("     name=%r brand=%s gtin=%s sku/mpn=%s price=%s avail=%s"
              % (p.get("name"), p.get("brand"), p.get("gtin"),
                 p.get("sku") or p.get("mpn"), off.get("price"), off.get("availability")))

    codes = sorted(set(CODE_IMG.findall(html)))
    print("  Asics-stilkode-kandidater (fra bilder): %s" % (codes or "INGEN"))
    eans = sorted(set(EAN_RE.findall(html)))
    print("  13-sifrede tall (EAN-kandidater): %s" % (eans[:8] or "INGEN"))
    stk = STOCK_IMG.findall(html)
    print("  lager-ikoner på PDP: %s" % ({s: stk.count(s) for s in set(stk)} or "INGEN"))

    # størrelses-/variant-seksjon: dump rå markup rundt sannsynlige markører
    for needle in ["Størrelse", "St&#248;rrelse", "velg variant", "variant", "size", "På lager", "Utsolgt", "lagerstatus"]:
        sec = section(html, needle, 120, 1600)
        if sec:
            print("  --- markup rundt «%s» ---" % needle)
            print("  " + sec[:1600])
            print("  --- slutt ---")
            break
    else:
        print("  fant ingen åpenbar størrelses-markør — dump <select>-blokker:")
        for m in re.findall(r"<select\b.*?</select>", html, re.S | re.I)[:2]:
            print("  " + re.sub(r"\s+", " ", m)[:1000])


def main():
    print("probe_foss v1 — Demonstrare/Multicase (server-rendret)\n")
    pdps = probe_pagination()
    print("\n2-4) PDP-INSPEKSJON (per-størrelse-lager / EAN / kode / JSON-LD)")
    for p in pdps:
        probe_pdp(p)
    print("\nKONKLUSJON-HINT:")
    print("  * Pagineringen avgjør discovery-modus (ny: 'demonstrare_pages').")
    print("  * Har PDP per-størrelse-lager + EAN -> parser som SportHolding (EAN-bro).")
    print("  * Kun colorway-kode (ingen EAN) -> match på kode, som Bull/Intersport.")


if __name__ == "__main__":
    main()
