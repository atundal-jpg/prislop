# marketing/ — sosiale-medier-kort

`prislop_cards.py` genererer 1200×1200-kort til Facebook/Instagram i sidens eget
designsystem (petrol/honey/paper + Space Grotesk). Kjøres manuelt fra maskin —
den er ikke del av scraper-pipelinen og kalles ikke fra noen workflow.

Kun egne data og egen grafikk: ingen produktbilder fra butikker eller
merkevarer, så ingen opphavsrettsproblemer.

## Oppsett

```sh
pip install -r marketing/requirements.txt

# Space Grotesk (OFL) — lastes ned én gang, committes ikke
mkdir -p marketing/fonts
for f in SpaceGrotesk-Bold SpaceGrotesk-Medium; do
  curl -sSL -o "marketing/fonts/$f.ttf" \
    "https://raw.githubusercontent.com/floriankarsten/space-grotesk/master/fonts/ttf/static/$f.ttf"
done
```

## Kjøre

```sh
cd marketing
PRISLOP_FONT_DIR=fonts python3 prislop_cards.py
```

Det lager de tre eksempelkortene (`kort-*.png`, gitignorert) og kjører
QA-sjekken på hvert av dem. Bruk `__main__`-blokka som mal for et ekte kort.

## De tre korttypene

| Funksjon | Når du bruker den |
| --- | --- |
| `price_drop_card()` | Prisen HAR falt — ekte kurve fra `v_prislop_price_series` som hovedvisual. |
| `spread_card()` | Samme sko, stor forskjell mellom butikker. Fanger sko som er billige fra dag én, der `drop14` er blind. |
| `spread_card_2panel()` | Dame og herre har ulik prisspredning og fortjener hvert sitt panel. |

## Før du poster

Kjør alltid `qa(path)` — den sjekker at ingenting kutter kanten og at
tekstblokkene ikke overlapper. Og verifiser tallene mot databasen først;
datareglene står i modulens docstring (kort fortalt: bruk
`v_prislop_price_series` framfor `drop14`/`deal_gap` alene, tell distinkte
størrelser hos den *billigste* butikken, og merk medlemspris i eyebrow-teksten
når lavprisen er det).
