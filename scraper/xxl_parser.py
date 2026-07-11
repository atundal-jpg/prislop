"""
xxl_parser.py — XXL.no produktside-parser for løpesko-prisguiden.

XXL er en Next.js-app som server-rendrer all produktdata inn i HTML-dokumentet,
så en vanlig HTTP GET (requests) holder — ingen headless browser.

To kilder i dokumentet, som vi slår sammen:
  1. <script id="__NEXT_DATA__">  -> alle fargevarianter, pris, lager per størrelse,
                                     kjønn, og en base64 `ticket` per størrelse som
                                     inneholder størrelsens EAN-13.
  2. <script type="application/ld+json"> (ProductGroup) -> ren `gtin` (EAN) per størrelse,
                                     men KUN for fargevarianten som vises på siden.

EAN hentes via ticket-dekoding (fungerer for ALLE farger fra én henting) og
kryss-valideres mot JSON-LD-gtin for den viste fargen.

RETTET 11. juli (probe_xxl_group_dump.py, kveldsøkt): prisen i
__NEXT_DATA__.products[].price.selling.range.min.value er IKKE reell per
fargevariant. XXL server-rendrer kun én ekte pris per sidevisning — den til
fargevarianten som faktisk vises (products[].isSelected == true). De andre
fargevariantene i samme products[]-liste arver/kopierer den viste fargens
pris i dette feltet; det er ikke deres egen pris. Bekreftet empirisk: samme
modellgruppe (Nike Vomero 18 herre) har fire fargevarianter med fire ulike
ekte priser (1519/1399/1749/1229), men __NEXT_DATA__ fra ÉN sidevisning
viste identisk pris på alle fire.

Konsekvens: vi emitter nå KUN rader for den fargevarianten som faktisk var
isSelected på siden vi hentet. De andre fargevariantene i products[]-lista
droppes fullstendig fremfor å skrive feil pris — en pris-sammenligningsside
har ingen nytte av et tilbud med feil pris. Discovery (discovery.py) må på
sikt utvides til å besøke hver fargevariants egen URL for å gjenvinne full
fargedekning; det er IKKE gjort i denne fila.

Snublefelle: intern `Size_N` følger IKKE EU-størrelsen (Size_13 = 39, Size_3 = 40).
Bruk alltid `label`/`size`, aldri tallet i sizeCode.
"""

from __future__ import annotations
import re, json, base64
from typing import Optional

STORE = "xxl"
NEXT_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
LD_RE = re.compile(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', re.S)


def _extract_next_data(html: str) -> dict:
    m = NEXT_RE.search(html)
    if not m:
        raise ValueError("Fant ikke __NEXT_DATA__ i HTML")
    return json.loads(m.group(1))


def _extract_jsonld_gtins(html: str) -> dict[str, str]:
    """sizeCode/sku -> gtin, for fargevarianten som vises (kryss-validering)."""
    out: dict[str, str] = {}
    for block in LD_RE.findall(html):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        for entry in (data if isinstance(data, list) else [data]):
            if isinstance(entry, dict) and entry.get("@type") == "ProductGroup":
                for v in entry.get("hasVariant", []):
                    if v.get("sku") and v.get("gtin"):
                        out[v["sku"]] = v["gtin"]
    return out


def decode_ean_from_ticket(ticket: str) -> Optional[str]:
    """XXLs base64 `ticket` inneholder størrelsens EAN-13 som en 13-sifret streng."""
    if not ticket:
        return None
    try:
        raw = base64.b64decode(ticket + "=" * (-len(ticket) % 4)).decode("latin1")
    except Exception:
        return None
    m = re.search(r"\b(\d{13})\b", raw)
    return m.group(1) if m else None


def _gender(product: dict) -> Optional[str]:
    for c in product.get("classifications", {}).get("mandatory", []):
        if str(c.get("id", "")).endswith("|user") and c.get("values"):
            return c["values"][0]
    return None


def _online_stock(variant: dict) -> tuple[Optional[int], Optional[str]]:
    for a in variant.get("availability", []):
        if a.get("channel") == "ONLINE":
            return a.get("stockNumber"), a.get("stockStatus")
    return variant.get("stockNumber"), variant.get("stockStatus")


def _colorway_price(product: dict) -> Optional[float]:
    try:
        return product["price"]["selling"]["range"]["min"]["value"]
    except (KeyError, TypeError):
        return None


def parse_xxl(html: str) -> dict:
    """
    Returnerer:
      {
        "rows": [ {store, brand, model_title, product_line, gender, color,
                   style_code, url, size_label, size_code, ean,
                   price, currency, online_stock, online_status}, ... ],
        "ean_validation": {"checked": int, "mismatches": [ ... ]},
        "skipped_colorways": [ {style_code, color}, ... ],  # ikke-viste farger, droppet
      }
    Én rad per (fargevariant × størrelse) -- men KUN for fargevarianten som
    faktisk var isSelected på den hentede siden (se modul-docstring).
    """
    nd = _extract_next_data(html)
    products = (
        nd["props"]["pageProps"]["newPdpProps"]
        ["initialElevateProductPageData"]["baseProduct"]["products"]
    )
    jsonld_gtin = _extract_jsonld_gtins(html)

    rows = []
    checked = 0
    mismatches = []
    skipped_colorways = []

    for p in products:
        # KRITISK: kun den viste fargevarianten har en reell pris i denne
        # responsen. Søskenfargene i samme products[]-liste arver/kopierer
        # den viste fargens pris -- drop dem heller enn å skrive feil pris.
        if not p.get("isSelected"):
            skipped_colorways.append({
                "style_code": p.get("code"),
                "color": p.get("localizedColorName") or p.get("baseColor"),
            })
            continue

        brand = (p.get("brand") or {}).get("name")
        title = p.get("title")
        line = p.get("productLine")
        gender = _gender(p)
        color = p.get("localizedColorName") or p.get("baseColor")
        style = p.get("code")
        url = "https://www.xxl.no" + p.get("url", "")
        price = _colorway_price(p)

        for v in p.get("variants", []):
            size_code = v.get("sizeCode")
            ean = decode_ean_from_ticket(v.get("ticket", ""))
            # kryss-valider mot JSON-LD der vi har den (kun vist farge)
            if size_code in jsonld_gtin:
                checked += 1
                if ean != jsonld_gtin[size_code]:
                    mismatches.append((size_code, ean, jsonld_gtin[size_code]))
                    ean = jsonld_gtin[size_code]  # stol på den rene kilden
            stock_n, stock_s = _online_stock(v)
            rows.append({
                "store": STORE,
                "brand": brand,
                "model_title": title,
                "product_line": line,
                "gender": gender,
                "color": color,
                "style_code": style,
                "url": url,
                "size_label": v.get("label"),
                "size_code": size_code,
                "ean": ean,
                "price": price,
                "currency": "NOK",
                "online_stock": stock_n,
                "online_status": stock_s,
            })

    return {
        "rows": rows,
        "ean_validation": {"checked": checked, "mismatches": mismatches},
        "skipped_colorways": skipped_colorways,
    }


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "Document_-_1246154_1_Style.txt"
    html = open(path, encoding="utf-8").read()
    res = parse_xxl(html)
    rows = res["rows"]

    if not rows:
        print("Ingen rader (isSelected-fargen manglet eller hadde ingen varianter).")
        sys.exit(0)

    colors = sorted({r["color"] for r in rows})
    print(f"Produkt: {rows[0]['brand']} {rows[0]['model_title']}  ({rows[0]['gender']})")
    print(f"Farger returnert (kun isSelected): {len(colors)} -> {', '.join(colors)}")
    if res["skipped_colorways"]:
        skipped_desc = ", ".join(
            f"{c['color']} ({c['style_code']})" for c in res["skipped_colorways"]
        )
        print(f"Droppet søskenfarger (ikke isSelected, upålitelig pris): "
              f"{len(res['skipped_colorways'])} -> {skipped_desc}")
    print(f"Rader (farge×størrelse): {len(rows)}")
    val = res["ean_validation"]
    print(f"EAN kryss-validert mot JSON-LD: {val['checked']} sjekket, "
          f"{len(val['mismatches'])} avvik")
    print()
    show = [r for r in rows if r["color"] == colors[0]]
    print(f"== {colors[0]} ({show[0]['price']} {show[0]['currency']}) ==")
    print(f"{'str':>5}  {'EAN':<14} {'lager':>5}  status")
    for r in sorted(show, key=lambda r: float(str(r["size_label"]).replace(',', '.'))):
        print(f"{str(r['size_label']):>5}  {r['ean']:<14} {str(r['online_stock']):>5}  {r['online_status']}")
