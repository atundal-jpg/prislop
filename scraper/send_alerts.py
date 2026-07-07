#!/usr/bin/env python3
"""
send_alerts.py — varslings-løkka del 2 (6. juli): kjøres ETTER harvest.

Finner aktive prisfall-varsler der billigste ferske tilbud (på lager, riktig
størrelse via v_prislop_sizes — så UK/EU-mappingen gjelder) er <= prisgrensen,
sender e-post via Resend, og logger alert_events.

Re-arm/dedup: samme varsel re-sendes IKKE hvis det finnes en event siste 7
dager med price_at_trigger <= dagens pris — kun nytt (lavere) prisfall eller
>7 dager trigget på nytt.

Miljø: SUPABASE_DB_URL (som loader), RESEND_API_KEY (hopper stille over hvis
den mangler — pipelinen skal aldri knekke på e-post), ALERT_FROM (default
Resend-testavsender til prislop.no-domenet er DNS-verifisert), UNSUB_URL
(Edge Function-basen for avmelding).
"""
from __future__ import annotations
import json
import os
import sys
import urllib.request

import psycopg2
import psycopg2.extras

RESEND_API = "https://api.resend.com/emails"
FROM = os.environ.get("ALERT_FROM", "Prisløp <onboarding@resend.dev>")
UNSUB_URL = os.environ.get(
    "UNSUB_URL",
    "https://agmhjcskkjtnwmhzzckx.supabase.co/functions/v1/alerts-unsub")

TRIGGER_SQL = """
with best as (
  select vs.product_id,
         a.id as alert_id,
         min(vs.price) as best_price
  from prislop.alerts a
  join prislop.subscribers s on s.id = a.subscriber_id
  join public.v_prislop_sizes vs
    on vs.product_id = a.product_id
   and vs.in_stock
   and (a.size_label is null
        or vs.size = btrim(replace(a.size_label, ',', '.')))
  where a.active
    and a.max_price is not null
    and s.email_verified and s.consent_alerts and s.unsubscribed_at is null
  group by vs.product_id, a.id
)
select a.id as alert_id, s.email, a.size_label, a.max_price,
       b.best_price, p.brand, p.model, p.gender,
       (select vs2.store from public.v_prislop_sizes vs2
         where vs2.product_id = a.product_id and vs2.in_stock
           and (a.size_label is null or vs2.size = btrim(replace(a.size_label, ',', '.')))
         order by vs2.price limit 1) as store,
       (select vs2.url from public.v_prislop_sizes vs2
         where vs2.product_id = a.product_id and vs2.in_stock
           and (a.size_label is null or vs2.size = btrim(replace(a.size_label, ',', '.')))
         order by vs2.price limit 1) as url,
       (select vs2.offer_id from public.v_prislop_sizes vs2
         where vs2.product_id = a.product_id and vs2.in_stock
           and (a.size_label is null or vs2.size = btrim(replace(a.size_label, ',', '.')))
         order by vs2.price limit 1) as offer_id
from best b
join prislop.alerts a on a.id = b.alert_id
join prislop.subscribers s on s.id = a.subscriber_id
join prislop.products p on p.id = a.product_id
where b.best_price <= a.max_price
  and not exists (
    select 1 from prislop.alert_events e
    where e.alert_id = a.id
      and e.triggered_at > now() - interval '7 days'
      and e.price_at_trigger <= b.best_price
  );
"""


def send_email(api_key: str, to: str, subject: str, html: str) -> bool:
    req = urllib.request.Request(
        RESEND_API,
        data=json.dumps({"from": FROM, "to": [to],
                         "subject": subject, "html": html}).encode(),
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return 200 <= resp.status < 300
    except urllib.error.HTTPError as e:
        # 7. juli natt: bare "HTTP Error 403: Forbidden" ble logget her,
        # uten Resends faktiske feiltekst (f.eks. "API key is invalid" vs.
        # "You can only send testing emails to your own email address") —
        # umulig å diagnostisere uten å lese response-body.
        body = e.read().decode(errors="replace")
        print(f"  [alerts] sendefeil til {to}: HTTP {e.code}: {body}")
        return False
    except Exception as e:  # aldri knekk pipelinen på e-post
        print(f"  [alerts] sendefeil til {to}: {e}")
        return False


def build_html(r: dict) -> str:
    shoe = f"{r['brand']} {r['model']}"
    size = f" i str. {r['size_label']}" if r["size_label"] else ""
    return f"""
<div style="font-family:sans-serif;max-width:520px">
  <h2 style="margin:0 0 6px">Prisen falt! 🏃</h2>
  <p><strong>{shoe}</strong>{size} er nå <strong>{int(r['best_price'])} kr</strong>
     hos {r['store']} — under grensen din på {int(r['max_price'])} kr.</p>
  <p><a href="{r['url']}" style="display:inline-block;background:#1f4f4a;color:#fff;
     padding:12px 20px;border-radius:8px;text-decoration:none">Til butikken →</a></p>
  <p style="color:#777;font-size:13px">Du får denne fordi du fulgte prisen på
     <a href="https://prisløp.no">prisløp.no</a>.
     <a href="{UNSUB_URL}?id={r['alert_id']}">Stopp dette varselet</a> ·
     <a href="{UNSUB_URL}?id={r['alert_id']}&all=1">Stopp alle varsler</a></p>
</div>"""


def main() -> None:
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        print("[alerts] RESEND_API_KEY ikke satt — hopper over varsling")
        return
    conn = psycopg2.connect(os.environ["SUPABASE_DB_URL"])
    try:
        with conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(TRIGGER_SQL)
            hits = cur.fetchall()
            print(f"[alerts] {len(hits)} utløste varsler")
            sent = 0
            for r in hits:
                subject = (f"Prisfall: {r['brand']} {r['model']} "
                           f"nå {int(r['best_price'])} kr")
                if send_email(api_key, r["email"], subject, build_html(r)):
                    cur.execute(
                        "insert into prislop.alert_events "
                        "(alert_id, offer_id, price_at_trigger) values (%s, %s, %s)",
                        (r["alert_id"], r["offer_id"], r["best_price"]))
                    sent += 1
            print(f"[alerts] sendt {sent}/{len(hits)}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
