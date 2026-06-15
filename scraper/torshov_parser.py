"""
torshov_parser.py — parser for Torshov Sport (Jetshop-plattformen).

Jetshop server-rendrer hele produktet som en Apollo-cache i sidedokumentet:
    window.__APOLLO_STATE__ = JSON.parse("...")   (JSON-streng inni JS-streng)
Så en vanlig requests.get på produktsiden gir alt — ingen eget API-kall.

Apollo-cachen er normalisert: produktet ligger som "Product:<id>", og felter
peker til andre noder via {"type":"id","id":"$Product:<id>.<felt>"} eller
{"type":"json","json":[...]}. Vi derefererer disse.

Torshov er «rosettasteinen»: hver variant har BÅDE barcode (=EAN-13) og vi
finner Asics-fargekoden i HTML — altså begge kryssnøklene.

Returnerer en OfferRecord kompatibel med loader.load().
"""

from __future__ import annotations
import json, re

ASICS_CODE_RE = re.compile(r"\b(\d{4}[A-Z]\d{3}-\d{3})\b")

# Kjønn er valgfritt: unisex-titler mangler kjønnsord helt. re.I fordi titler
# noen ganger kommer i caps (f.eks. «SUPERBLAST 3 ...»).
NAME_RE = re.compile(
    r"^(?P<model>.+?)\s+(?:Løpesko|Joggesko|Sko)"
    r"(?:\s+(?P<gender>Herre|Dame|Unisex|Barn|Junior))?"
    r"\s+(?P<color>.+)$",
    re.I,
)


def _extract_apollo(html: str) -> dict:
    i = html.find("__APOLLO_STATE__")
    idx = html.find("JSON.parse(", i)
    oq = html.find('"', idx)
    k, esc = oq + 1, False
    while k < len(html):
        c = html[k]
        if esc:
            esc = False
        elif c == "\\":
            esc = True
        elif c == '"':
            break
        k += 1
    return json.loads(json.loads(html[oq:k + 1]))


def _gender(s: str | None) -> str:
    # (s or "") gjør None -> "" -> default "unisex" i stedet for å kræsje på .lower()
    return {"herre": "herre", "dame": "dame", "unisex": "unisex",
            "barn": "barn", "junior": "barn"}.get((s or "").lower(), "unisex")


def parse_torshov(html: str, url: str) -> dict:
    state = _extract_apollo(html)

    def deref(n):
        if isinstance(n, dict):
            if n.get("type") == "id":
                return state.get(n["id"])
            if n.get("type") == "json":
                return n["json"]
        return n

    # og:title -> finn produktnoden med eksakt navn
    mt = re.search(r'property="og:title"\s+content="([^"]+)"', html)
    title = (mt.group(1) if mt else "").split(" - ")[0].strip()
    product = None
    for key, node in state.items():
        if (re.match(r"^Product:\d+$", key) and isinstance(node, dict)
                and node.get("name") == title):
            product = node
            break
    if product is None:  # fallback: første Product med varianter
        for key, node in state.items():
            if re.match(r"^Product:\d+$", key) and isinstance(node, dict) and node.get("variants"):
                product = node
                break

    brand = product.get("subName") or "Asics"
    name = product.get("name", "")
    rest = name[len(brand):].strip() if name.startswith(brand) else name
    m = NAME_RE.match(rest)
    if m:
        model = m.group("model").strip()
        gender = _gender(m.group("gender"))
        color = m.group("color").strip()
    else:
        model, gender, color = rest, "unisex", None
    product_line = re.sub(r"\s*\d+.*$", "", model).strip().lower().replace(" ", "-") or None

    code_m = ASICS_CODE_RE.search(html)
    manufacturer_code = code_m.group(1) if code_m else None

    price = deref(product["price"]).get("incVat") if product.get("price") else None
    prev = deref(product["previousPrice"]).get("incVat") if product.get("previousPrice") else None

    sizes = []
    variants = deref(product["variants"])
    for ref in variants.get("values", []):
        v = deref(ref)
        if not isinstance(v, dict):
            continue
        sv = deref(v.get("values"))
        size = sv[0] if isinstance(sv, list) and sv else None
        ss = deref(v.get("stockStatus")) or {}
        sizes.append({
            "size_label": size,
            "ean": v.get("barcode"),
            "in_stock": bool(ss.get("buyable")),
            "stock_count": None,
        })

    return {
        "store": {"slug": "torshov", "name": "Torshov Sport", "source": "scrape", "network": None},
        "brand": brand, "model": model, "gender": gender,
        "product_line": product_line, "category": "running",
        "color": color, "manufacturer_code": manufacturer_code,
        "image_url": None,
        "store_sku": str(product.get("articleNumber")) if product.get("articleNumber") else None,
        "url": url, "currency": "NOK",
        "price": price, "original_price": prev,   # original_price for fremtidig rabattvisning
        "sizes": sizes,
    }


if __name__ == "__main__":
    import sys
    html = open(sys.argv[1], encoding="utf-8", errors="replace").read()
    url = sys.argv[2] if len(sys.argv) > 2 else ""
    rec = parse_torshov(html, url)
    print(json.dumps({k: v for k, v in rec.items() if k != "sizes"}, ensure_ascii=False, indent=1))
    for s in rec["sizes"]:
        print(f"  {s['size_label']:>5}  EAN={s['ean']}  in_stock={s['in_stock']}")
