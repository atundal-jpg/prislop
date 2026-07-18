// Supabase Edge Function: ut
// Klikk-redirect-laget (P0.2 i prioritert plan, 9. juli).
//
// GET /functions/v1/ut?offer=<offer_uuid>[&src=web|email]
//   1. Én RPC (public.ut_click): logger klikket i prislop.clicks OG
//      returnerer butikk-URL + store_id. (RPC fordi prislop-skjemaet ikke
//      er PostgREST-eksponert; SECURITY DEFINER, kun service_role.)
//   2. 302 til butikkens produktside.
//
// AFFILIATE-INNBYTTEPUNKT: når en avtale lander for en butikk, legges
// omskrivingen i AFFILIATE_WRAP under — én endring her, null i frontend.
// Eksempel (Adtraction): "4": (url) =>
//   `https://track.adtraction.com/t/t?a=XXXX&as=YYYY&t=2&tk=1&url=${encodeURIComponent(url)}`
//
// Deploy: verify_jwt MÅ være av — lenkene skal fungere uten auth-header,
// også fra e-postklienter. Endepunktet lekker ingenting sensitivt (kun
// 302 til offentlige butikksider), og ugyldig/ukjent offer gir forsiden.

import { createClient } from "jsr:@supabase/supabase-js@2";

// store_id -> URL-omskriver. Tom til avtaler lander.
const AFFILIATE_WRAP: Record<string, (url: string) => string> = {};

const HOME = "https://xn--prislp-fya.no/";

Deno.serve(async (req) => {
  const u = new URL(req.url);
  const offerId = u.searchParams.get("offer");
  const src = (u.searchParams.get("src") || "web").slice(0, 16);

  if (!offerId || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(offerId)) {
    return Response.redirect(HOME, 302);
  }

  const sb = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
  );

  const { data, error } = await sb.rpc("ut_click", {
    p_offer: offerId,
    p_src: src,
    p_ua: req.headers.get("user-agent") || "",
    p_ref: req.headers.get("referer") || "",
  });
  if (error) console.error("ut_click feilet:", error.message);

  const row = Array.isArray(data) ? data[0] : data;
  if (!row?.url) {
    return Response.redirect(HOME, 302);
  }

  const wrap = AFFILIATE_WRAP[String(row.store_id)];
  return Response.redirect(wrap ? wrap(row.url) : row.url, 302);
});
