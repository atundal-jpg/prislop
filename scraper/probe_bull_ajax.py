#!/usr/bin/env python3
"""
probe_bull_ajax.py — hvorfor ga Bull-discovery 0 treff?

Kjører nøyaktig samme AJAX-kall som _bull_ajax_paths, av-escaper `insert`-dataen,
og dumper den FAKTISKE lenke-strukturen i griden, så vi kan rette markøren.
Sammenligner også med/uten in_stock og med/uten &page=0.
"""
from __future__ import annotations
import json
import re
import urllib.request
import urllib.error

UA = "Mozilla/5.0 (prislop-probe)"
HREF_RE = re.compile(r'href="([^"]+)"', re.I)

URLS = {
    "discovery (vendor, page=0)":
        "https://bull-ski-kajakk.no/sko/lopesko?product_vendor%5B0%5D=13524&query="
        "&_wrapper_format=drupal_ajax&_drupal_ajax=1&page=0",
    "discovery uten page":
        "https://bull-ski-kajakk.no/sko/lopesko?product_vendor%5B0%5D=13524&query="
        "&_wrapper_format=drupal_ajax&_drupal_ajax=1",
    "probe-varianten (in_stock+vendor)":
        "https://bull-ski-kajakk.no/sko/lopesko?in_stock%5B0%5D=1&product_vendor%5B0%5D=13524&query="
        "&_wrapper_format=drupal_ajax&_drupal_ajax=1",
}


def get(url: str) -> tuple[int | None, str]:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Referer": "https://bull-ski-kajakk.no/sko/lopesko",
    })
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return None, f"FEIL {e}"


def insert_html(body: str) -> str:
    try:
        cmds = json.loads(body)
    except json.JSONDecodeError:
        return ""
    return "".join(c.get("data", "") for c in cmds
                   if isinstance(c, dict) and c.get("command") == "insert" and isinstance(c.get("data"), str))


def main() -> None:
    for label, url in URLS.items():
        print(f"\n===== {label} =====")
        st, body = get(url)
        print(f"  HTTP {st}, body={len(body)}B")
        if not body or not body.startswith("["):
            print(f"  (ikke AJAX-array) starter: {body[:160]!r}")
            continue
        cmds = json.loads(body)
        print(f"  kommandoer: {[c.get('command') for c in cmds if isinstance(c, dict)]}")
        html = insert_html(body)
        print(f"  insert-data: {len(html)}B")
        hrefs = HREF_RE.findall(html)
        sko = [h for h in hrefs if "/sko/" in h]
        asics = [h for h in hrefs if "asics" in h.lower()]
        print(f"  hrefs totalt={len(hrefs)}  /sko/={len(sko)}  inneholder 'asics'={len(asics)}")
        # vis de mest produkt-lignende (dypest path under /sko/)
        deep = sorted({h for h in sko if h.count("/") >= 3})
        print(f"  /sko/-lenker (dybde>=3), {len(deep)} unike, eksempler:")
        for h in deep[:8]:
            print(f"      {h}")
        if not deep and sko:
            print(f"  alle /sko/-lenker (eksempler): {sorted(set(sko))[:8]}")
        # rå utdrag av griden for å se kort-markup
        i = html.find("/sko/")
        if i >= 0:
            print(f"  råutdrag rundt første /sko/: {html[max(0,i-120):i+160]!r}")


if __name__ == "__main__":
    main()
