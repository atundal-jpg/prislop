#!/usr/bin/env python3
"""
probe_bull_es.py — finn endepunktet elasticsearch_ui-JS-en spør Elasticsearch mot.

drupal_ajax-ruta gir bare et tomt <div id="elasticsearch-ui">; JS-en fyller det
via et eget kall. Vi henter <script src> fra /sko/lopesko, leter opp JS-en som
nevner «elasticsearch», og griper URL-/rute-/fetch-mønstre + query-bygging.
Dumper også hele elasticsearchUi-settings + baseUrl.

Kjøres i GitHub Actions. Skriver ingenting til DB.
"""
from __future__ import annotations
import json
import re
import urllib.request
import urllib.error

UA = "Mozilla/5.0 (prislop-probe)"
BASE = "https://bull-ski-kajakk.no"
SRC_RE = re.compile(r'<script[^>]+src="([^"]+)"', re.I)
SETTINGS_RE = re.compile(r'data-drupal-selector="drupal-settings-json"[^>]*>(\{.*?\})</script>', re.S)
# Mønstre som kan røpe endepunktet
HINT_RE = re.compile(
    r"""(elasticsearch[\w/.\-]*|/[a-z0-9_\-/]*search[a-z0-9_\-/]*|_search|"\s*url\s*"\s*:|"""
    r"""Drupal\.url\([^)]*\)|fetch\(\s*['"][^'"]+['"]|\.ajax\(|endpoint|indexPlugin|/elasticsearch[\w\-/]*)""",
    re.I)


def get(url: str) -> tuple[int | None, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "nb-NO"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return None, f"FEIL {e}"


def main() -> None:
    st, html = get(BASE + "/sko/lopesko")
    print(f"/sko/lopesko -> {st}, {len(html)}B")

    # settings: full elasticsearchUi + baseUrl
    m = SETTINGS_RE.search(html)
    if m:
        try:
            s = json.loads(m.group(1))
            print("  baseUrl:", (s.get("path") or {}).get("baseUrl"))
            es = s.get("elasticsearchUi")
            print("  elasticsearchUi (full):", json.dumps(es, ensure_ascii=False)[:1500])
        except Exception as e:
            print("  settings parse-feil:", e)

    # JS-filer
    srcs = []
    for src in SRC_RE.findall(html):
        full = src if src.startswith("http") else BASE + (src if src.startswith("/") else "/" + src)
        if full.startswith(BASE) and full.endswith(".js"):
            srcs.append(full)
    srcs = sorted(set(srcs))
    print(f"\n  lokale JS-filer: {len(srcs)}")

    # let etter elasticsearch-relatert JS (navn eller innhold)
    checked = 0
    for u in srcs:
        st, js = get(u)
        if not js or "elasticsearch" not in js.lower():
            continue
        checked += 1
        print(f"\n  >>> {u}  ({len(js)}B)")
        seen = set()
        for mt in HINT_RE.finditer(js):
            frag = js[max(0, mt.start() - 40):mt.end() + 80]
            frag = re.sub(r"\s+", " ", frag).strip()
            if frag not in seen:
                seen.add(frag)
                print(f"      … {frag}")
            if len(seen) >= 25:
                break
        if checked >= 4:
            break
    if checked == 0:
        print("\n  Fant ingen JS som nevner 'elasticsearch' (trolig aggregert/minifisert).")
        print("  Aggregerte bundles:", [u for u in srcs if "/js/" in u][:6])


if __name__ == "__main__":
    main()
