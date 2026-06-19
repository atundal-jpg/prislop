#!/usr/bin/env python3
"""
probe_bull_api.py — finn Bulls produkt-enumererings-vei.

Sitemap finnes ikke; listing rendres via Drupal `elasticsearch_ui`
(use_rendered=true) gjennom en AJAX-rute. Vi tester to veier:
  1) Drupal JSON:API (/jsonapi/...) — reneste hvis aktivert (paginert, filtrerbar).
  2) elasticsearch_ui-AJAX — facet-URL med drupal_ajax-wrapper + XHR-header,
     ser om svaret inneholder rendrede produkt-lenker.
Asics-facet (fra GA-referrer): product_vendor=13524.

Kjøres i GitHub Actions. Skriver ingenting til DB.
"""
from __future__ import annotations
import json
import re
import urllib.request
import urllib.error

UA = "Mozilla/5.0 (prislop-probe)"
BASE = "https://bull-ski-kajakk.no"
ASICS_SKO = re.compile(r"/sko/[a-z0-9/_-]*asics-[a-z0-9-]+", re.I)


def fetch(url: str, headers: dict | None = None):
    h = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "nb-NO"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return None, f"FEIL {e}"


def section_jsonapi() -> None:
    print("== 1) JSON:API ==")
    st, body = fetch(BASE + "/jsonapi")
    print(f"  /jsonapi -> {st}, {len(body)}B")
    bundles = []
    if st == 200:
        try:
            links = json.loads(body).get("links", {})
            bundles = [k.split("--", 1)[1] for k in links if k.startswith("commerce_product--")]
            print(f"  commerce_product-bundles: {bundles or '(ingen i links)'}")
        except Exception as e:
            print(f"  parse-feil: {e}")
    # prøv funne bundles, ellers vanlige gjettinger
    for b in (bundles or ["default", "sko", "shoe", "product", "clothing", "vare"]):
        st, body = fetch(BASE + f"/jsonapi/commerce_product/{b}?page%5Blimit%5D=3")
        if st != 200 or not body.strip().startswith("{"):
            print(f"  commerce_product/{b} -> {st}")
            continue
        try:
            d = json.loads(body)
            data = d.get("data") or []
            total = ((d.get("meta") or {}).get("count"))
            ex = data[0].get("attributes", {}) if data else {}
            print(f"  commerce_product/{b} -> {st}, treff={len(data)} total={total}")
            print(f"      attrs: {list(ex.keys())[:14]}")
            print(f"      path: {ex.get('path')}  title: {ex.get('title')}")
        except Exception as e:
            print(f"  commerce_product/{b} parse-feil: {e}")


def section_ajax() -> None:
    print("\n== 2) elasticsearch_ui AJAX (Asics-facet) ==")
    facet = (BASE + "/sko/lopesko?in_stock%5B0%5D=1&product_vendor%5B0%5D=13524&query="
             "&_wrapper_format=drupal_ajax&_drupal_ajax=1")
    st, body = fetch(facet, headers={"X-Requested-With": "XMLHttpRequest"})
    print(f"  ajax-facet -> {st}, {len(body)}B, starter: {body[:100]!r}")
    if st == 200 and body:
        links = sorted({m.group(0) for m in ASICS_SKO.finditer(body)})
        print(f"      asics-sko-lenker i svar: {len(links)}  ex={links[:3]}")
        # er det en AJAX-kommando-array?
        try:
            cmds = json.loads(body)
            if isinstance(cmds, list):
                print(f"      AJAX-kommandoer: {[c.get('command') for c in cmds if isinstance(c, dict)][:8]}")
        except Exception:
            pass


def main() -> None:
    print("probe_bull_api\n")
    section_jsonapi()
    section_ajax()


if __name__ == "__main__":
    main()
