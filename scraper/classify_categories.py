#!/usr/bin/env python3
"""classify_categories.py — setter brukskategori + attributt-flagg (spor 4).

Kjøres i pipelinen ETTER lasting. Idempotent: samme regelverk som init-
klassifiseringen 8. juli (én SQL-UPDATE over alle produkter), så nye modeller
fra harvest fanges automatisk, og manuelle datafikser i reglene rulles ut ved
neste kjøring. Regler bor HER (én kilde til sannhet) — endres taksonomien,
endres denne fila.

Logger løpesko som IKKE traff noen regel (ekskl. kjent ikke-løpesko-liste),
så nye umatchede modeller er synlige i Actions-loggen. Feiler ALDRI jobben —
en umatchet modell er et datakvalitetsvarsel, ikke en pipeline-feil.
"""
import os
import sys

import psycopg2

# Kjente ikke-løpesko i katalogen — bevisst ukategorisert, skal ikke varsles.
KNOWN_NON_RUNNING = "(netburner|metcon|fritidssko|initiator|max ltd)"

CLASSIFY_SQL = r"""
update prislop.products set subcategory =
  case
    when model ~* '(dragonfly|maxfly|victory 2|superfly elite|high jump|long jump|triple jump|lj elite|javelin|zoom sd|zoom rival|evospeed|prime sp|sinister|berserker|avanti|ambition)' then 'bane'
    when model ~* '(trail|terrex|trabuco|speedgoat|torrent|zinal|mafate|tecton|peregrine|pergrine|xodus|zegama|wildhorse|ultrafly|juniper|acg|kipsummit|metafuji|fuji|sonoma|endorphin rift|\matr\M|cascadia|caldera|catamount|wave daichi|wave ibuki|hierro)'
      or (brand = 'Hoka' and model ~* 'challenger') then 'terreng'
    when model ~* '(vaporfly|alphafly|adios|prime x|metaspeed|endorphin pro|endorphin elite|endorphin edge|fast-r|fast-fwd|fast-rb|nitro elite|cielo|rocket x|carbon x|takumi|streakfly|kipstorm (elite|lab|challenger)|hyperion elite|fuelcell supercomp elite)' then 'konkurranse'
    when model ~* '(zoom fly|magic speed|boston|endorphin speed|mach x|evo sl|adizero sl|kinvara|superblast|megablast|sonicblast|endorphin trainer|pegasus turbo|deviate|liberate|kipstorm tempo|noosa|hyperion|wave rebellion|fuelcell rebel|fuelcell supercomp)' then 'tempo'
    when model ~* '(kayano|gt-1000|gt-2000|structure|guide|arahi|gaviota|omni|hurricane|tempus|foreverrun|infinity|solar ?control|phoenix|wave horizon|wave inspire|wave equate|adrenaline gts|glycerin gts|fortrush|\mariel\M|\mbeast\M)' then 'stabilitet'
    when model ~* '(nimbus|bondi|triumph|vomero|invincible|magmax|magnify|glideride|kinsei|skyward|stinson|ultraboost|kipride max|endorphin shift|adistar|hyperboost|supernova prima|comfortglide|tide|4dfwd|switch fwd|ghost max|glycerin|hyperwarp|wave sky|wave serene|wave skyrise|1080v|revel max|neo zen)' then 'demping'
    when model ~* '(pegasus|cumulus|novablast|dynablast|clifton|mach|ride|velocity|winflo|supernova|kipride|skyflow|rincon|endorphin azura|run xx|solarglide|solar glide|propio|ghost|wave kizuna|neo vista|neo accera|revel)' then 'daily'
    when model ~* '(runfalcon|galaxy|duramo|questar|response|revolution|downshifter|quest|run defy|interact|journey|excite|flux|pulse|flare|axon|lancer|surge|versablast|kawana|kinjo|skyrocket)' then 'mosjon'
    else null
  end;
update prislop.products set carbon_plate =
  model ~* '(vaporfly|alphafly|adios pro|prime x|metaspeed|endorphin pro|endorphin elite|endorphin edge|fast-r|nitro elite|cielo|rocket x|carbon x|zoom fly|magic speed|deviate|tecton|metafuji|kipstorm (elite|lab|challenger)|hyperion elite|fuelcell supercomp elite|wave rebellion)';
update prislop.products set waterproof =
  model ~* '(gtx|gore-tex|\mwtr\M|runshield|rain\.rdy|cold\.rdy|waterproof)';
update prislop.products set wide = model ~* '\mwide\M';
"""


def main() -> int:
    conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"])
    with conn:
        with conn.cursor() as cur:
            cur.execute(CLASSIFY_SQL)
            cur.execute(
                "select subcategory, count(*) from prislop.products "
                "group by 1 order by 2 desc"
            )
            dist = cur.fetchall()
            cur.execute(
                "select brand, model from prislop.products "
                "where subcategory is null and model !~* %s order by brand, model",
                (KNOWN_NON_RUNNING,),
            )
            unmatched = cur.fetchall()
    conn.close()

    print("Kategorifordeling:", ", ".join(f"{k or 'ukat'}={n}" for k, n in dist))
    if unmatched:
        print(f"::warning::{len(unmatched)} løpesko uten kategori — vurder regeljustering:")
        for b, m in unmatched:
            print(f"  UMATCHET: {b} {m}")
    else:
        print("Alle løpesko klassifisert (kun kjent ikke-løpesko-liste står ukategorisert).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
