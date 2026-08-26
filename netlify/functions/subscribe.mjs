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

async function sendConfirmation(email, token, areaCount) {
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
      Subject: "Confirm your planning alerts",
      MessageStream: "outbound",
      TextBody:
        `You asked for an email when a mosque planning application appears in ` +
        `${areaCount} council area${areaCount === 1 ? "" : "s"}.\n\n` +
        `Confirm here:\n${url}\n\n` +
        `If this was not you, ignore this message. Nothing is sent until the ` +
        `link above is used, and the request is deleted after seven days.\n`,
      HtmlBody:
        `<p>You asked for an email when a mosque planning application appears ` +
        `in ${areaCount} council area${areaCount === 1 ? "" : "s"}.</p>` +
        `<p><a href="${url}">Confirm your alerts</a></p>` +
        `<p style="font-size:12px;color:#8b96a2">If this was not you, ignore ` +
        `this message. Nothing is sent until that link is used, and the ` +
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
  const now = new Date().toISOString();

  const row = {
    email,
    email_norm: email.toLowerCase(),
    areas,
    confirmed: false,
    confirm_token: token,
    confirm_sent_at: now,
    // The consent record. Kept because UK GDPR asks you to show when and how
    // consent was given, and deleted with the subscriber on unsubscribe.
    consent_ip: req.headers.get("x-nf-client-connection-ip") || null,
    consent_ua: (req.headers.get("user-agent") || "").slice(0, 300),
    unsubscribed_at: null,
  };

  try {
    // An existing address re-subscribing updates its councils and gets a fresh
    // confirmation, rather than erroring -- which would otherwise let anyone
    // probe whether a given address is on the list.
    await rest("subscribers?on_conflict=email_norm", {
      method: "POST",
      body: [row],
      prefer: "resolution=merge-duplicates,return=minimal",
    });
    await sendConfirmation(email, token, areas.length);
  } catch (err) {
    console.error("subscribe failed", err);
    return json(500, { error: "Could not save that just now. Try again shortly." });
  }

  // The same answer whether or not the address was already known.
  return json(200, {
    ok: true,
    message: "Check your inbox for a confirmation link. Nothing is sent until you use it.",
  });
};
