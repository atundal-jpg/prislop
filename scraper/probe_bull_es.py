#!/usr/bin/env python3
"""
probe_bull_es.py — finn Bulls Elasticsearch-endepunkt UTEN DevTools.

Listing-griden fylles klient-side av elasticsearch_ui-JS-en. Den JS-fila
inneholder nesten alltid ruta/endepunktet den spør mot. Vi:
  1) henter listesida + AJAX-svaret, plukker ut alle JS-filer (særlig de med
     "elasticsearch" i navnet),
  2) henter de JS-filene og grep'er etter endepunkt/rute-mønstre,
  3) dumper full drupalSettings og leter etter endpoint/host/index-nøkler,
  4) prøver et par åpenbare endepunkt-kandidater og ser om de gir produkt-JSON.

Kjøres i GitHub Actions. Skriver ingenting til DB.
"""
from __future__ import annotations
import json
import re
import urllib.request
import urllib.error

UA = "Mozilla/5.0 (prislop-probe)"
BASE = "https://bull-ski-kajakk.no"
PAGE = BASE + "/sko/lopesko?product_vendor%5B0%5D=13524&query="
AJAX = PAGE + "&_wrapper_format=drupal_ajax&_drupal_ajax=1"

JS_SRC_RE = re.compile(r'(?:src=|"src":\s*)"([^"]+\.js[^"]*)"', re.I)
SETTINGS_RE = re.compile(
    r'data-drupal-selector="drupal-settings-json"[^>]*>(\{.*?\})</script>', re.S)
HINT_RE = re.compile(
    r'(elasticsearch[^"\x27\s]{0,40}|_search|/ajax[^"\x27\s]{0,30}|Drupal\.url\([^)]{0,60}\)|'
    r'"/[a-z0-9/_-]*(?:search|elastic|product|ajax)[a-z0-9/_-]*"|index["\x27]?\s*[:=]\s*["\x27][^"\x27]+)', re.I)


def get(url, headers=None):
    h = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "nb-NO"}
    if headers:
        h.update(headers)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=40) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return None, "FEIL %s" % e


def main():
    print("probe_bull_es\n")
    _, page = get(PAGE)
    _, ajax = get(AJAX, {"X-Requested-With": "XMLHttpRequest"})
    blob = page + "\n" + ajax

    js = sorted(set(JS_SRC_RE.findall(blob)))
    es_js = [u for u in js if "elastic" in u.lower() or "search" in u.lower()]
    print("== JS-filer: %d totalt, %d sok/elastic-relaterte ==" % (len(js), len(es_js)))
    for u in es_js[:10]:
        print("   " + u)
    if not es_js:
        cand = [u for u in js if u.startswith("/") and "/core/" not in u]
        print("   (ingen elastic-navngitt; egne moduler/temaer:)")
        for u in cand[:15]:
            print("   " + u)
        es_js = cand

    print("\n== endepunkt-hint i JS ==")
    for u in es_js[:12]:
        full = u if u.startswith("http") else BASE + u
        st, body = get(full)
        if st != 200 or not body:
            print("   %s -> %s" % (u, st))
            continue
        hints = sorted(set(h if isinstance(h, str) else h[0] for h in HINT_RE.findall(body)))
        hits = [h for h in hints if len(h) > 4][:14]
        print("   %s (%dB): %s" % (u, len(body), hits if hits else "(ingen treff)"))

    print("\n== drupalSettings-nokler ==")
    m = SETTINGS_RE.search(page)
    if m:
        try:
            s = json.loads(m.group(1))
            print("   topp:", list(s.keys()))
            for k, v in s.items():
                vs = json.dumps(v, ensure_ascii=False)
                if re.search(r"elastic|host|index|endpoint|/search|api", vs, re.I):
                    print("   * %s: %s" % (k, vs[:400]))
        except Exception as e:
            print("   parse-feil:", e)

    print("\n== endepunkt-gjetninger ==")
    for path in ["/elasticsearch_ui/product", "/elasticsearch-ui/product",
                 "/elasticsearch/product/_search",
                 "/sko/lopesko?product_vendor%5B0%5D=13524&query=&_format=json"]:
        st, body = get(BASE + path, {"X-Requested-With": "XMLHttpRequest",
                                     "Accept": "application/json"})
        snip = body[:90].replace("\n", " ")
        print("   %s -> %s  %r" % (path, st, snip))


if __name__ == "__main__":
    main()
