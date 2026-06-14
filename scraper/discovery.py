"""
discovery.py — finner produkt-URL-er per butikk, og adapterer parser-output.

For hver (butikk, modell): søk på "asics <modell>", hent søkeresultatsiden, og
plukk ut produktlenkene. Resultatet mates videre til riktig parser.

⚠️  VERIFISER MOT LIVE SIDE: søke-URL-malene (`search_url`) og produktlenke-
    markørene (`marker_re`) er kvalifiserte gjetninger. De kan ikke testes uten
    å nå butikkene, så dette er det første som må finjusteres når pipelinen
    kjører i Actions. Alt annet (henting, parsing, lasting) er testet.
"""

from __future__ import annotations
import re
from urllib.parse import quote_plus, urljoin

import xxl_parser, torshov_parser, intersport_parser
from loader import xxl_to_offers


# --- Parser-adaptere: (html, url) -> list[OfferRecord] ---------------------
def _xxl(html, url):
    return xxl_to_offers(xxl_parser.parse_xxl(html))

def _torshov(html, url):
    return [torshov_parser.parse_torshov(html, url)]

def _intersport(html, url):
    return [intersport_parser.parse_intersport(html, url)]


# --- Butikk-konfig ----------------------------------------------------------
STORES = {
    "xxl": {
        "name": "XXL",
        "base": "https://www.xxl.no",
        # VERIFISER: XXL sin søke-URL
        "search_url": lambda q: f"https://www.xxl.no/search?query={quote_plus(q)}",
        # Sterk produktmarkør: XXL-produkt-URL-er slutter på /p/<id>_<n>_Style
        "marker_re": re.compile(r"/p/\d+_\d+_Style", re.I),
        "adapter": _xxl,
    },
    "torshov": {
        "name": "Torshov Sport",
        "base": "https://www.torshovsport.no",
        # VERIFISER: Torshov (Jetshop) søke-URL
        "search_url": lambda q: f"https://www.torshovsport.no/search?q={quote_plus(q)}",
        "marker_re": None,   # ingen ren markør -> faller tilbake på token-filter
        "adapter": _torshov,
    },
    "intersport": {
        "name": "Intersport",
        "base": "https://www.intersport.no",
        # VERIFISER: Intersport (SportHolding) søke-URL
        "search_url": lambda q: f"https://www.intersport.no/sok?q={quote_plus(q)}",
        # SportHolding-produkt-slug slutter på Asics-stammen, f.eks. ...-1011b958
        "marker_re": re.compile(r"/[a-z0-9-]+-\d{4}[a-z]\d{3}/?($|\?)", re.I),
        "adapter": _intersport,
    },
}

HREF_RE = re.compile(r'href="([^"#]+)"', re.I)


def _model_tokens(model: str) -> list[str]:
    return [t for t in re.split(r"[\s\-/]+", model.lower()) if t]


def _looks_like_product(href: str, brand: str, model: str) -> bool:
    """Fallback-filter når butikken mangler en ren produktmarkør:
    slug må inneholde merket + minst ett modell-ord + et evt. tall."""
    s = href.lower()
    if brand.lower() not in s:
        return False
    toks = _model_tokens(model)
    words = [t for t in toks if not t.isdigit()]
    nums = [t for t in toks if t.isdigit()]
    word_ok = any(w in s for w in words) if words else True
    num_ok = any(n in s for n in nums) if nums else True
    return word_ok and num_ok


def discover(fetcher, store_slug: str, brand: str, model: str, limit: int = 8) -> list[str]:
    cfg = STORES[store_slug]
    html = fetcher.get(cfg["search_url"](f"{brand} {model}"))
    if not html:
        return []
    out, seen = [], set()
    for href in HREF_RE.findall(html):
        url = urljoin(cfg["base"], href)
        if not url.startswith(cfg["base"]):
            continue
        marker = cfg.get("marker_re")
        ok = marker.search(url) if marker else _looks_like_product(url, brand, model)
        if ok and url not in seen:
            seen.add(url)
            out.append(url)
            if len(out) >= limit:
                break
    return out
