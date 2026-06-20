#!/usr/bin/env python3
"""
probe_bull_es.py (v2) — lås Bulls produkt-API.

JS-grepen avslorte familien /api/navigation/product/{cart,export,promote,sale}.
Vi trenger sok/liste-ruta. Denne proben:
  1) henter den store JS-bundelen og trekker ut ALLE /api/navigation/...-stier,
  2) viser kontekst rundt sokekallet (elasticsearch-ui-search / navigation/product
     / fetch/ajax/url),
  3) tester de mest sannsynlige endepunktene (GET+POST) med Asics-faceten og
     rapporterer status + om svaret inneholder produkt-lenker/JSON.

Kjores i GitHub Actions. Skriver ingenting til DB.
"""
from __future__ import annotations
import json
import re
import urllib.request
import urllib.error

UA = "Mozilla/5.0 (prislop-probe)"
BASE = "https://bull-ski-kajakk.no"
JS = "/sites/default/files/js/js_DkIfw9DxD6dSA3b1NE8hupSJ6Duar-L2jZx-yHph7Pg.js"
VENDOR = "product_vendor%5B0%5D=13524"

API_RE = re.compile(r'["\x27](/api/navigation/[a-z0-9/_-]+)["\x27]', re.I)
ASICS_RE = re.compile(r'/sko/[a-z0-9/_-]*asics-[a-z0-9-]+', re.I)


def get(url, headers=None, data=None, method=None):
    h = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "nb-NO"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            b = e.read().decode("utf-8", "replace")
        except Exception:
            b = ""
        return e.code, b
    except Exception as e:
        return None, "FEIL %s" % e


def windows(text, needle, n=2, pad=90):
    out, start = [], 0
    for _ in range(n):
        i = text.find(needle, start)
        if i < 0:
            break
        out.append(text[max(0, i - pad):i + len(needle) + pad])
        start = i + len(needle)
    return out


def main():
    print("probe_bull_es v2\n")
    st, js = get(BASE + JS)
    print("== JS %s -> %s, %dB ==" % (JS.split('/')[-1][:24], st, len(js)))

    apis = sorted(set(API_RE.findall(js)))
    print("\n== alle /api/navigation/-stier i JS ==")
    for a in apis:
        print("   " + a)

    print("\n== kontekst rundt sokekallet ==")
    for needle in ["elasticsearch-ui-search", "navigation/product", "use_rendered", "ajaxUrl", "apiUrl"]:
        for w in windows(js, needle, n=1, pad=110):
            print("   [%s] ...%s..." % (needle, w.replace("\n", " ")))

    print("\n== test endepunkter (GET + POST) med Asics-facet ==")
    paths = [
        "/api/navigation/product",
        "/api/navigation/product/search",
        "/api/navigation/product/list",
        "/api/navigation/product/index",
        "/api/navigation/product/export",
        "/api/navigation/product/sale",
    ]
    for p in paths:
        url = "%s%s?%s&query=" % (BASE, p, VENDOR)
        for method in ("GET", "POST"):
            data = b"" if method == "POST" else None
            st, body = get(url, {"X-Requested-With": "XMLHttpRequest",
                                 "Accept": "application/json, text/html, */*"},
                           data=data, method=method)
            n_asics = len(set(ASICS_RE.findall(body)))
            is_json = body[:1] in "{["
            snip = body[:80].replace("\n", " ")
            flag = "  <== PRODUKTER!" if n_asics > 2 else ("  json" if is_json else "")
            print("   %-4s %-34s -> %-4s %6dB  asics=%d%s" % (method, p, st, len(body), n_asics, flag))


if __name__ == "__main__":
    main()
