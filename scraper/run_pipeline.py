"""
run_pipeline.py — orkestrerer høstingen av løpesko inn i prislop-basen.

For hver butikk × målmodell: discovery -> produkt-URL-er -> hent -> parse ->
samle OfferRecords -> last via loader. Robust per butikk (én butikk som feiler
velter ikke resten) og per produkt (én side som feiler hopper vi over).

Kjøres i GitHub Actions med SUPABASE_DB_URL som hemmelig miljøvariabel.

Ytelse (to nivåer av parallellitet, begge I/O-bundet):
  1) PÅ TVERS av butikker — hver butikk i sin egen tråd med sin egen Fetcher,
     så uavhengige domener treffes samtidig.
  2) INNE i hver butikk — produktsidene hentes+parses i en avgrenset trådpool
     (PER_STORE_WORKERS, per domene). Med per-tråd-throttle i Fetcher blir
     effektiv rate ≈ workers × (1/delay) — det høflige samtidighets-taket.
Vegg-tida går fra «summen av alle sider sekvensielt» til «tregeste butikk /
samtidighets-tak». Lastingen holdes SEKVENSIELL (i STORES-rekkefølge): den er
rask DB-jobb, og loaderens EAN-bro + select-så-insert-variant ville
duplisert/splittet ved samtidige skriv. Brukås lastes sist (broer på de andre).
NB: Intersport/Sport 1/Löplabbet deler SportHolding-backend — får de 429/503,
senk STORE_FETCH_WORKERS eller HARVEST_WORKERS.

Skalerings-notat: dette gjør discovery + prisinnhenting i samme kjøring. Når
katalogen vokser, splitt gjerne i to jobber — sjelden discovery (finn nye
produkter) og hyppig prisoppdatering (kun kjente URL-er) — for å spare kall.
"""

from __future__ import annotations
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import discovery
import loader
from brands import BRANDS
from fetch import Fetcher

# Merker × modeller vi jakter på. Butikker som ikke fører et merke gir [] fra
# discovery (by_brand-gate) og hopper stille videre.
# NB: Alle 9 aktive butikker kjører take-all/cachede discovery-moduser, så
# MODELS-listene er i praksis INERTE for discovery (hele merkekatalogen hentes
# uansett). De er seed-lister for ev. fremtidige søkebaserte butikker + dok.
# BRANDS er definert i brands.py (delt med discovery.py/oslosportslager_parser.py
# sin merke-gate for Oslo Sportslager — se den fila for hvorfor).
STORES = ["xxl", "torshov", "intersport", "sport1", "loplabbet", "bull", "brukas", "foss",
          "oslosportslager"]   # de feed-løse butikkene

MODELS = {
    "Asics": [
    "Gel-Nimbus 27", "Nimbus 28", "Nimbus 28 ATC",
    "Glideride Max", "Glideride Max 2",
    "Sonicblast", "Megablast", "Superblast 2", "Superblast 3",
    "Gel-Kayano 32", "Gel-Kayano 33",
    "Magic Speed 4", "Magic Speed 5",
    "Fujispeed 4", "MetaFuji Trail",
    "Trabuco MT GTX", "Trabuco Max 4", "Trabuco Max 5",
    "Trabuco 13 GTX", "Trabuco 14 GTX",
    "GT-2000 14", "GT-2000 14 TR",
    "Novablast 5", "Novablast 5 ATC",
    "MetaSpeed Edge Tokyo", "MetaSpeed Sky Tokyo",
    "Gel-FujiSetsu 3 GTX", "FujiSetsu Max GTX", "Fuji Lite 6",
],
    "Adidas": [
        "Adizero SL 2", "Adizero SL 3",
        "Adizero Boston 13", "Adizero Adios 9",
        "Adizero Adios Pro 4", "Adizero Adios Pro Evo 2",
        "Adizero Evo SL", "Adizero Takumi Sen 11",
        "Ultraboost 5", "Ultraboost 5X",
        "Supernova Rise 2", "Supernova Prima", "Supernova Solution",
        "Terrex Agravic 3", "Terrex Agravic Speed", "Terrex Soulstride 2",
    ],
    "Saucony": [
        "Endorphin Speed 5", "Endorphin Pro 5", "Endorphin Elite 2",
        "Ride 18", "Guide 18", "Triumph 23", "Kinvara 16", "Tempus 2",
        "Peregrine 15", "Hurricane 25", "Xodus Ultra 4",
    ],
    "Nike": [
        "Pegasus 42", "Pegasus Premium", "Pegasus Plus",
        "Vomero 18", "Vomero Plus", "Structure 26", "Invincible 4",
        "Alphafly 3", "Vaporfly 4", "Streakfly 2",
        "Pegasus Trail 5", "Zegama 2",
    ],
    "Hoka": [
        "Clifton 10", "Bondi 9", "Mach 6", "Mach X 2", "Arahi 8",
        "Rincon 5", "Skyward X", "Rocket X 3", "Cielo X1 2.0",
        "Speedgoat 6", "Challenger 8", "Tecton X 3", "Torrent 4",
    ],
    "Puma": [
        "Deviate Nitro 3", "Velocity Nitro 4", "ForeverRun Nitro 2",
        "Magnify Nitro 2", "Fast-R Nitro Elite 3", "Voyage Nitro 4",
    ],
    "Kiprun": [
        "KD900X", "KS900", "KD800", "KS500 2", "KD500 3",
    ],
    # New Balance: Foss (skrudd på 9. juli) + Torshov (probe_brands 9. juli:
    # 30 treff). Take-all begge steder, så listen er inert, ren dok/seed.
    "New Balance": [
        "1080v14", "880v15", "Rebel v5", "Fresh Foam X More v5",
        "FuelCell SuperComp Elite 4", "FuelCell Propel v5", "Vongo v6",
    ],
    # Brooks: Torshov + Brukås (probe_brands 9. juli). Take-all begge steder.
    "Brooks": [
        "Ghost 17", "Ghost Max 2", "Glycerin Max 2", "Glycerin GTS",
        "Hyperion Elite 4", "Adrenaline GTS 24", "Cascadia 19",
    ],
    # Mizuno: Torshov + Intersport + Sport 1 + Löplabbet + XXL (probe_brands
    # 9. juli — desidert bredest dekning av dagens funn). Take-all overalt.
    "Mizuno": [
        "Wave Rider 30", "Wave Rider 29", "Wave Rebellion Flash 3",
        "Wave Sky 8", "Wave Horizon 9", "Wave Duel 4", "Wave Inspire 21",
    ],
}

PRODUCTS_PER_MODEL = 6          # tak på fargevarianter per modell per butikk

# Antall butikker som høstes samtidig. Standard = alle (de er I/O-bundet og
# uavhengige). Kan overstyres i Actions via env HARVEST_WORKERS.
MAX_WORKERS = max(1, int(os.environ.get("HARVEST_WORKERS", len(STORES))))

# Antall samtidige produktside-hentinger INNE i hver butikk (per domene). Med
# per-tråd-throttle i Fetcher blir effektiv rate ≈ workers × (1/delay), så
# dette er det høflige samtidighets-taket. Senk for butikker som gir 429/503.
PER_STORE_WORKERS = max(1, int(os.environ.get("STORE_FETCH_WORKERS", "6")))


def harvest_store(fetcher, slug: str) -> list[dict]:
    # 1) Discovery (sekvensielt per modell) -> unik URL-liste. Rask: de fleste
    #    butikker cacher hele lista på første kall (resten blir no-ops via seen).
    urls, seen = [], set()
    for brand in BRANDS:
        for model in MODELS[brand]:
            try:
                found = discovery.discover(fetcher, slug, brand, model, limit=PRODUCTS_PER_MODEL)
            except Exception as e:
                print(f"  [{slug}] discovery-feil «{brand} {model}»: {e}")
                continue
            for url in found:
                if url not in seen:
                    seen.add(url)
                    urls.append(url)

    # 2) Hent + parse produktsidene PARALLELT, men med et avgrenset tak per
    #    butikk (= per domene). Throttlen i Fetcher er nå per tråd, så
    #    PER_STORE_WORKERS tråder × (1/delay) gir en høflig, tunbar rate.
    adapter = discovery.STORES[slug]["adapter"]

    def fetch_parse(url: str) -> list[dict]:
        html = fetcher.get(url)
        if not html:
            return []
        try:
            return adapter(html, url)
        except Exception as e:
            print(f"  [{slug}] parse-feil {url}: {e}")
            return []

    records: list[dict] = []
    if urls:
        workers = min(PER_STORE_WORKERS, len(urls))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for recs in pool.map(fetch_parse, urls):
                records.extend(recs)

    # 3) Noen butikker (Brukås) leverer per-størrelse-partials som må grupperes
    #    til colorways før lasting — opt-in via STORES[...]["aggregate"].
    agg = discovery.STORES[slug].get("aggregate")
    if agg:
        records = agg(records)
    return records


def _harvest_worker(slug: str) -> tuple[str, list[dict], str | None]:
    """Høster én butikk i sin egen tråd med sin EGEN Fetcher (per-domene-
    throttle bevart). Returnerer (slug, records, feilmelding-eller-None).
    En butikk som kaster skal ikke velte de andre."""
    try:
        return slug, harvest_store(Fetcher(), slug), None
    except Exception as e:
        return slug, [], f"{type(e).__name__}: {e}"


def main():
    if not os.environ.get("SUPABASE_DB_URL"):
        sys.exit("Mangler SUPABASE_DB_URL (sett den som hemmelighet i Actions).")

    grand = {"offers": 0, "sizes": 0}

    # --- Fase 1: høst alle butikker PARALLELT (nettverks-bundet) -----------
    print(f"Fase 1: høster {len(STORES)} butikker parallelt ({MAX_WORKERS} arbeidere)…")
    harvested: dict[str, list[dict]] = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(_harvest_worker, slug): slug for slug in STORES}
        for fut in as_completed(futures):
            slug, records, err = fut.result()
            name = discovery.STORES[slug]["name"]
            if err:
                print(f"  [{slug}] ❌ høsting feilet: {err}")
            produkter = len({(r.get("brand"), r.get("model"), r.get("color")) for r in records})
            print(f"  [{slug}] {name}: {len(records)} tilbud / ~{produkter} fargevarianter")
            harvested[slug] = records

    # --- Fase 2: last SEKVENSIELT, i STORES-rekkefølge --------------------
    # Bevisst sekvensiell: loaderen brokobler kodeløse butikker (Brukås) på
    # EAN-overlapp mot ALLEREDE lastede varianter, og get_or_create_variant er
    # en select-så-insert som ville duplisert varianter ved samtidig last.
    # STORES-rekkefølgen (Brukås sist) holder broen intakt.
    print("\nFase 2: laster sekvensielt…")
    for slug in STORES:
        records = harvested.get(slug, [])
        name = discovery.STORES[slug]["name"]
        if not records:
            # Null treff = nesten alltid feil søke-URL/markør (eller en
            # forbigående høste-feil over), ikke en faktisk tom butikk.
            print(f"  ⚠️  {name}: 0 tilbud — verifiser search_url/marker_re i discovery.py")
            continue
        try:
            stats = loader.load(records)
            grand["offers"] += stats["offers"]
            grand["sizes"] += stats["sizes"]
            print(f"  {name}: lastet {stats['offers']} tilbud, {stats['sizes']} størrelser")
        except Exception as e:
            print(f"  ❌ lasting feilet for {name}: {e}")

    print(f"\nTOTALT lastet: {grand['offers']} tilbud, {grand['sizes']} størrelser")


if __name__ == "__main__":
    main()
