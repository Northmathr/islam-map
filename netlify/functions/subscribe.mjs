// Sign-up endpoint for planning alerts.
//
// Deliberately dependency-free: Supabase is reached over PostgREST with fetch,
// and Postmark the same way, so there is no package.json, no install step and
// nothing to keep patched. The service role key is used here and must never
// reach the browser -- the table has row level security on with no policy for
// anon, so a leaked anon key would still read nothing.
//
// Double opt-in: this writes an unconfirmed row and emails a link. An
// unconfirmed row is an intent, not a subscriber, and notify.py never reads it.

const CORS = { "Content-Type": "application/json" };

const env = (k) => {
  const v = process.env[k];
  if (!v) throw new Error(`missing environment variable: ${k}`);
  return v;
};

// Deliberately permissive. Address validation beyond this rejects real
// addresses; the confirmation email is what actually proves deliverability.
const EMAIL_RE = /^[^@\s]+@[^@\s.]+\.[^@\s]{2,}$/;
const AREA_RE = /^[ENSWK]\d{8}$/;
const MAX_AREAS = 20;
// Minimum gap between confirmation emails to one address, whoever asked.
const COOLDOWN_MS = 10 * 60 * 1000;
const SENT_MESSAGE =
  "Check your inbox for a confirmation link. Nothing is sent until you use it.";

const json = (status, body) =>
  new Response(JSON.stringify(body), { status, headers: CORS });

async function rest(path, { method = "GET", body, prefer } = {}) {
  const key = env("SUPABASE_SERVICE_KEY");
  const headers = {
    apikey: key,
    Authorization: `Bearer ${key}`,
    "Content-Type": "application/json",
  };
  if (prefer) headers.Prefer = prefer;
  const res = await fetch(`${env("SUPABASE_URL")}/rest/v1/${path}`, {
    method, headers, body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`supabase ${res.status}: ${await res.text()}`);
  const text = await res.text();
  return text ? JSON.parse(text) : null;
}

async function sendConfirmation(email, token, areaCount, isChange) {
  const url = `${env("SITE_URL")}/.netlify/functions/confirm` +
              `?t=${encodeURIComponent(token)}`;
  const body = await fetch("https://api.postmarkapp.com/email", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Postmark-Server-Token": env("POSTMARK_TOKEN"),
    },
    body: JSON.stringify({
      From: env("POSTMARK_FROM"),
      To: email,
      Subject: isChange ? "Confirm the change to your planning alerts"
                        : "Confirm your planning alerts",
      MessageStream: "outbound",
      TextBody:
        (isChange
          ? `Someone asked to change your planning alerts to ${areaCount} ` +
            `council area${areaCount === 1 ? "" : "s"}. Your current alerts are ` +
            `unchanged until you confirm.\n\n`
          : `You asked for an email when a mosque planning application appears ` +
            `in ${areaCount} council area${areaCount === 1 ? "" : "s"}.\n\n`) +
        `Confirm here:\n${url}\n\n` +
        `If this was not you, ignore this message. Nothing changes until the ` +
        `link above is used, and the request is deleted after seven days.\n`,
      HtmlBody:
        (isChange
          ? `<p>Someone asked to change your planning alerts to ${areaCount} ` +
            `council area${areaCount === 1 ? "" : "s"}. Your current alerts are ` +
            `unchanged until you confirm.</p>`
          : `<p>You asked for an email when a mosque planning application ` +
            `appears in ${areaCount} council area` +
            `${areaCount === 1 ? "" : "s"}.</p>`) +
        `<p><a href="${url}">Confirm</a></p>` +
        `<p style="font-size:12px;color:#8b96a2">If this was not you, ignore ` +
        `this message. Nothing changes until that link is used, and the ` +
        `request is deleted after seven days.</p>`,
    }),
  });
  if (!body.ok) throw new Error(`postmark ${body.status}: ${await body.text()}`);
}

export default async (req) => {
  if (req.method !== "POST") return json(405, { error: "POST only" });

  let payload;
  try {
    payload = await req.json();
  } catch {
    return json(400, { error: "expected JSON" });
  }

  const email = String(payload.email || "").trim();
  const areas = [...new Set(payload.areas || [])].filter((a) => AREA_RE.test(a));

  if (!EMAIL_RE.test(email)) return json(400, { error: "That does not look like an email address." });
  if (!areas.length) return json(400, { error: "Choose at least one council." });
  if (areas.length > MAX_AREAS) return json(400, { error: `Choose at most ${MAX_AREAS} councils.` });
  if (payload.website) return json(200, { ok: true });   // honeypot: silently accept

  const token = crypto.randomUUID().replace(/-/g, "") + crypto.randomUUID().replace(/-/g, "");
  const now = new Date();
  const norm = email.toLowerCase();

  // `inet` rejects anything that is not a single address, and a proxy chain
  // would fail the insert rather than the validation.
  const rawIp = req.headers.get("x-nf-client-connection-ip") || "";
  const ip = /^[0-9a-f.:]+$/i.test(rawIp) && rawIp.length <= 45 ? rawIp : null;

  try {
    const existing = await rest(
      `subscribers?select=id,confirmed,confirm_sent_at&email_norm=eq.${encodeURIComponent(norm)}`);
    const row = existing?.[0];

    // Anyone can type anyone's address into a form. Re-sending a confirmation
    // on demand therefore turns this endpoint into a way to mail-bomb a
    // stranger, so an address that was written to recently is left alone --
    // and answered exactly as a new one is, so the response reveals nothing
    // about whether it is already on the list.
    if (row?.confirm_sent_at &&
        Date.now() - Date.parse(row.confirm_sent_at) < COOLDOWN_MS) {
      return json(200, { ok: true, message: SENT_MESSAGE });
    }

    if (!row) {
      await rest("subscribers", {
        method: "POST",
        prefer: "return=minimal",
        body: [{
          email, email_norm: norm, areas,
          confirmed: false, confirm_token: token,
          confirm_sent_at: now.toISOString(),
          // The consent record. UK GDPR asks you to show when and how consent
          // was given; deleted with the subscriber on unsubscribe.
          consent_ip: ip,
          consent_ua: (req.headers.get("user-agent") || "").slice(0, 300),
        }],
      });
    } else if (row.confirmed) {
      // Already a subscriber. The new councils are a REQUEST, parked until
      // confirmed from the address itself -- the live subscription is not
      // touched, so a stranger cannot rewrite or silence it.
      await rest(`subscribers?id=eq.${row.id}`, {
        method: "PATCH",
        prefer: "return=minimal",
        body: { pending_areas: areas, confirm_token: token,
                confirm_sent_at: now.toISOString() },
      });
    } else {
      // Unconfirmed, so there is no subscription to protect. Replace it.
      await rest(`subscribers?id=eq.${row.id}`, {
        method: "PATCH",
        prefer: "return=minimal",
        body: { email, areas, confirm_token: token,
                confirm_sent_at: now.toISOString() },
      });
    }

    await sendConfirmation(email, token, areas.length, Boolean(row?.confirmed));
  } catch (err) {
    console.error("subscribe failed", err);
    return json(500, { error: "Could not save that just now. Try again shortly." });
  }

  // The same answer whether or not the address was already known.
  return json(200, { ok: true, message: SENT_MESSAGE });
};
