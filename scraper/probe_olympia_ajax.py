#!/usr/bin/env python3
"""
probe_olympia_ajax.py — følger Olympias per-størrelse-mekanikk (RenderProductDetails)
for å sjekke om EAN/GTIN dukker opp der v6 (probe_olympia.py) ikke fant EAN i den
statiske PDP-HTML-en.

v6-funn: Adidas (22) og Saucony (58) er de eneste av de ti katalogmerkene som finnes
i løpekategoriene. På 6 stikkprøve-PDP-er (3 hver) var det INGEN JSON-LD Product og
INGEN EAN i rå HTML — størrelser vises som knapper (`Velg variant :`) med hver sin
`data-productid` og `onclick="RenderProductDetails(id)"`, som tyder på at pris/lager/
EAN for valgt størrelse lastes via AJAX og bytter ut noe i DOM-en først ved klikk.

Denne proben er bevisst bred/diagnostisk (vi vet ikke ennå om dette er en JS-attributt-
platform vi kjenner igjen fra andre butikker):
  1. Henter én Adidas- og én Saucony-PDP (fersk oppdagelse fra kategori-side 1).
  2. Skanner rå HTML for ean/gtin/strekkode/varenummer/artikkelnummer/sku-tokens
     UTENFOR EAN_RE sitt strenge \\d{13}-mønster, med kontekst — i tilfelle Olympia
     bruker en annen feltnavn- eller formatkonvensjon enn de andre butikkene.
  3. Leter etter innebygde JSON-blobber (`var xxx = {...}`) i inline <script>.
  4. Finner `RenderProductDetails`-funksjonsdefinisjonen — inline først, ellers i
     hver lenkede <script src>-fil — og skriver ut kildekoden rundt den.
  5. Trekker ut kandidat-AJAX-URL-er fra funksjonskroppen ($.ajax/$.get/$.post/
     fetch/XMLHttpRequest/.ashx/.asmx) og prøver de mest sannsynlige mot en ekte
     data-productid fra siden, og skanner RESPONSEN for EAN/gtin/lager.

GO = EAN dukker opp i AJAX-responsen (eller andre steder vi finner) -> Adidas/Saucony
re-evalueres til GO, resten av de ti forblir NO-GO (0 treff i kategoriene, jf. v6).
NO-GO = broen mangler også her -> Olympia strykes helt, Oslo Sportslager rykker opp.
Stdlib only. probe.yml (script=probe_olympia_ajax.py).
"""
from __future__ import annotations
import json
import re
import urllib.request
import urllib.error
import urllib.parse

UA = "Mozilla/5.0 (prislop-probe)"
BASE = "https://www.olympiasport.no"

TILE = re.compile(
    r'class="product-item"[^>]*data-productid="\d+">\s*'
    r'<div class="picture">\s*<a\s+href="([^"#?]+)"\s+title="([^"]*)"', re.I)
TILE_LOOSE = re.compile(
    r'data-productid="\d+">(?:(?!</a>).)*?<a\s+href="(/[^"#?]+)"\s+title="([^"]*)"', re.I | re.S)
PRODUCTID = re.compile(r'data-productid="(\d+)"', re.I)
SCRIPT_SRC = re.compile(r'<script[^>]+src="([^"]+)"', re.I)
INLINE_JS_VAR = re.compile(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', re.S | re.I)
TOKENS = ["ean", "gtin", "strekkode", "barcode", "varenummer", "artikkelnummer", "sku"]


def get(path, is_json=False):
    url = path if path.startswith("http") else BASE + path
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept-Language": "nb-NO",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01" if is_json else "*/*",
    })
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, (e.read().decode("utf-8", "replace") if e.fp else "")
    except Exception as e:
        return None, "FEIL %s" % e


def tiles(html):
    t = TILE.findall(html) or TILE_LOOSE.findall(html)
    out = []
    for h, ti in t:
        if (h, ti) not in out:
            out.append((h, ti))
    return out


def find_brand_pdp(brand_slug, cats=("/asfaltsko", "/terrengsko", "/joggesko-herre", "/joggesko-dame")):
    for cat in cats:
        st, html = get(cat)
        for h, ti in tiles(html or ""):
            if h.lower().startswith(f"/{brand_slug}-"):
                return h, ti
    return None, None


def scan_tokens(html, label):
    print("  -- token-skann (%s) --" % label)
    any_hit = False
    for tok in TOKENS:
        for m in re.finditer(tok, html, re.I):
            any_hit = True
            i = m.start()
            ctx = re.sub(r"\s+", " ", html[max(0, i - 60):i + 120])
            print("    [%s] ...%s..." % (tok, ctx))
            break  # første treff per token er nok her
    if not any_hit:
        print("    ingen av %s funnet" % ", ".join(TOKENS))


def find_json_blobs(html):
    print("  -- innebygde JS-objekter (var x = {...}) --")
    found = 0
    for blk in INLINE_JS_VAR.findall(html):
        for m in re.finditer(r'\b(var|let|const)\s+(\w+)\s*=\s*(\{.*?\});', blk, re.S):
            name, body = m.group(2), m.group(3)
            if len(body) < 40:
                continue
            found += 1
            print("    %s = {...} (%d B) — nøkler: %s" % (
                name, len(body), ", ".join(re.findall(r'"?(\w+)"?\s*:', body)[:12])))
            if found >= 8:
                return
    if not found:
        print("    ingen funnet")


def find_render_function(html, pdp_url):
    print("  -- leter etter RenderProductDetails --")
    m = re.search(r'function\s+RenderProductDetails\s*\([^)]*\)\s*\{', html)
    if m:
        body = html[m.start():m.start() + 1500]
        print("    funnet INLINE i PDP-HTML:")
        print("    " + re.sub(r"\s+", " ", body)[:1400])
        return body
    srcs = SCRIPT_SRC.findall(html)
    print("    ikke inline — sjekker %d lenkede script-filer" % len(srcs))
    for src in srcs:
        url = src if src.startswith("http") else (src if src.startswith("/") else "/" + src)
        st, js = get(url)
        if not js or "RenderProductDetails" not in js:
            continue
        m = re.search(r'function\s+RenderProductDetails\s*\([^)]*\)\s*\{', js)
        if m:
            body = js[m.start():m.start() + 1500]
            print("    funnet i %s :" % url)
            print("    " + re.sub(r"\s+", " ", body)[:1400])
            return body
    print("    RenderProductDetails ikke funnet noe sted (verken inline eller i %d script-filer)" % len(srcs))
    return ""


URL_PATTERNS = [
    re.compile(r'\.ajax\(\s*\{[^}]*?url\s*:\s*["\']([^"\']+)["\']', re.S),
    re.compile(r'\$\.(?:get|post)\(\s*["\']([^"\']+)["\']'),
    re.compile(r'fetch\(\s*["\']([^"\']+)["\']'),
    re.compile(r'\.open\(\s*["\']\w+["\']\s*,\s*["\']([^"\']+)["\']'),
    re.compile(r'["\']([^"\']*\.(?:ashx|asmx|aspx)[^"\']*)["\']'),
]


def guess_endpoints(fn_body):
    urls = []
    for pat in URL_PATTERNS:
        for u in pat.findall(fn_body):
            if u not in urls:
                urls.append(u)
    return urls


def try_endpoint(url, productid):
    candidates = []
    if "{id}" in url or "{0}" in url:
        candidates.append(url.replace("{id}", str(productid)).replace("{0}", str(productid)))
    else:
        sep = "&" if "?" in url else "?"
        for param in ("id", "productId", "ProductId", "productid"):
            candidates.append(f"{url}{sep}{param}={productid}")
        candidates.append(url.rstrip("/") + f"/{productid}")
    seen = set()
    for cand in candidates:
        if cand in seen:
            continue
        seen.add(cand)
        st, body = get(cand, is_json=True)
        print("    -> %s" % cand)
        print("       HTTP %s, %d B" % (st, len(body) if body else 0))
        if body and st and 200 <= st < 300:
            eans = sorted(set(re.findall(r'\b(\d{13})\b', body)))
            print("       EAN-kandidater (%d): %s" % (len(eans), eans[:8] or "INGEN"))
            for tok in TOKENS:
                if re.search(tok, body, re.I):
                    i = re.search(tok, body, re.I).start()
                    print("       [%s] ...%s..." % (tok, re.sub(r"\s+", " ", body[max(0, i-60):i+120])))
            print("       snippet:", re.sub(r"\s+", " ", body)[:500])
            if eans:
                return True
    return False


def investigate(brand_slug, label):
    print("=" * 74)
    print("MERKE:", label)
    href, title = find_brand_pdp(brand_slug)
    if not href:
        print("  ingen PDP funnet for", brand_slug)
        return
    print("PDP:", href, "(%s)" % title)
    st, html = get(href)
    print("  HTTP %s, %d B" % (st, len(html or "")))
    if not html:
        return

    scan_tokens(html, "PDP-HTML")
    find_json_blobs(html)
    fn_body = find_render_function(html, href)

    pids = PRODUCTID.findall(html)
    pid = pids[0] if pids else None
    print("  første data-productid på siden:", pid)

    if fn_body and pid:
        eps = guess_endpoints(fn_body)
        print("  -- kandidat-endepunkt utledet fra funksjonskroppen --")
        if not eps:
            print("    ingen URL-mønstre funnet i funksjonskroppen")
        for ep in eps[:4]:
            print("  prøver:", ep)
            got = try_endpoint(ep, pid)
            if got:
                print("  *** EAN FUNNET via AJAX-endepunkt ***")
                return True
    return False


def main():
    print("probe_olympia_ajax — sporer RenderProductDetails for Adidas + Saucony\n")
    got_adidas = investigate("adidas", "ADIDAS")
    got_saucony = investigate("saucony", "SAUCONY")
    print("\n" + "=" * 74)
    print("KONKLUSJON:")
    print("  Adidas : %s" % ("EAN funnet via AJAX -> GO" if got_adidas else "fortsatt ingen EAN -> NO-GO"))
    print("  Saucony: %s" % ("EAN funnet via AJAX -> GO" if got_saucony else "fortsatt ingen EAN -> NO-GO"))
    if not got_adidas and not got_saucony:
        print("  Ingen bro-data funnet noe sted -> Olympia strykes for alle ti merkene,")
        print("  Oslo Sportslager rykker opp (jf. NO-GO-regelen i probe_olympia.py).")


if __name__ == "__main__":
    main()
