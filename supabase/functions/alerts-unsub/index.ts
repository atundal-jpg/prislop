// alerts-unsub v2: avmelding fra prisvarsel-e-post (6. juli).
// Token = varselets UUID (122-bit tilfeldig; besittelse = kom fra e-posten).
// Åpen (verify_jwt=false) — e-postklikk har ingen JWT; kan kun DEAKTIVERE.
// Går via public.unsub_alert-RPC (prislop-skjemaet er ikke PostgREST-eksponert).
import { createClient } from "jsr:@supabase/supabase-js@2";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function page(title: string, body: string): Response {
  return new Response(
    `<!doctype html><html lang="nb"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>${title} — Prisløp</title>
<body style="font-family:sans-serif;max-width:480px;margin:60px auto;padding:0 20px;color:#2b332f">
<h2>${title}</h2><p>${body}</p>
<p><a href="https://xn--prislp-fya.no" style="color:#1f4f4a">Tilbake til Prisløp →</a></p>
</body></html>`,
    { headers: { "Content-Type": "text/html; charset=utf-8" } });
}

Deno.serve(async (req) => {
  const url = new URL(req.url);
  const id = url.searchParams.get("id") ?? "";
  const all = url.searchParams.get("all") === "1";
  if (!UUID_RE.test(id)) {
    return page("Ugyldig lenke", "Avmeldingslenken er ikke gyldig. Prøv lenken fra e-posten på nytt.");
  }
  const db = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);
  const { data, error } = await db.rpc("unsub_alert", { p_alert_id: id, p_all: all });
  if (error) {
    return page("Noe gikk galt", "Klarte ikke å stoppe varselet akkurat nå. Prøv igjen om litt.");
  }
  if (data === "not_found") {
    return page("Fant ikke varselet", "Varselet er allerede fjernet, eller lenken er utløpt.");
  }
  if (data === "all_stopped") {
    return page("Alle varsler stoppet",
      "Du får ingen flere prisvarsler fra Prisløp. Du kan melde deg på igjen når som helst.");
  }
  return page("Varselet er stoppet",
    "Du følger ikke lenger prisen på denne skoen. Andre varsler du har, løper som før.");
});
