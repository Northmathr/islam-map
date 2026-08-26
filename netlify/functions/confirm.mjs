// Confirmation endpoint. Turns an intent into a subscriber.
//
// Returns HTML rather than JSON: this is opened by a person clicking a link in
// their mail client, not by the site's own JavaScript.

const env = (k) => {
  const v = process.env[k];
  if (!v) throw new Error(`missing environment variable: ${k}`);
  return v;
};

// A confirmation link that is never used is a request nobody made or nobody
// wanted. Seven days, then it is deleted rather than left lying around.
const TOKEN_TTL_DAYS = 7;

function page(title, body, status = 200) {
  return new Response(
    `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>${title}</title>
<link rel="stylesheet" href="/style.css">
<script>document.documentElement.dataset.theme =
  localStorage.getItem("theme") ||
  (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");</script>
</head><body class="doc">
<header id="topbar"><div class="brand"><h1>${title}</h1></div>
<a class="backlink" href="/">&larr; Back to the map</a></header>
<article class="prose">${body}</article></body></html>`,
    { status, headers: { "Content-Type": "text/html; charset=utf-8" } });
}

async function rest(path, { method = "GET", body, prefer } = {}) {
  const key = env("SUPABASE_SERVICE_KEY");
  const headers = {
    apikey: key, Authorization: `Bearer ${key}`,
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

export default async (req) => {
  const token = new URL(req.url).searchParams.get("t") || "";
  if (!/^[a-f0-9]{64}$/.test(token)) {
    return page("Link not recognised",
      "<p>That confirmation link is not valid. It may have been broken across " +
      "two lines by your mail client — try copying the whole address into the " +
      "address bar.</p>", 400);
  }

  try {
    const cutoff = new Date(Date.now() - TOKEN_TTL_DAYS * 864e5).toISOString();
    const rows = await rest(
      `subscribers?select=id,confirmed,confirm_sent_at&confirm_token=eq.${token}`);

    if (!rows?.length) {
      return page("Link not recognised",
        "<p>That confirmation link has already been used, or the request was " +
        "cancelled. If you are unsure, <a href='/alerts.html'>sign up " +
        "again</a> — it is harmless to repeat.</p>", 404);
    }
    const row = rows[0];
    if (row.confirmed) {
      return page("Already confirmed",
        "<p>These alerts are already active. Nothing more to do.</p>");
    }
    if (row.confirm_sent_at && row.confirm_sent_at < cutoff) {
      await rest(`subscribers?id=eq.${row.id}`, { method: "DELETE" });
      return page("Link expired",
        `<p>Confirmation links last ${TOKEN_TTL_DAYS} days and this one has ` +
        `passed that, so the request has been deleted. ` +
        `<a href="/alerts.html">Sign up again</a> if you still want alerts.</p>`, 410);
    }

    await rest(`subscribers?id=eq.${row.id}`, {
      method: "PATCH",
      prefer: "return=minimal",
      body: {
        confirmed: true,
        confirmed_at: new Date().toISOString(),
        confirm_token: null,       // single use
      },
    });
  } catch (err) {
    console.error("confirm failed", err);
    return page("Something went wrong",
      "<p>That did not work just now. Try the link again in a few minutes.</p>", 500);
  }

  return page("Alerts confirmed",
    "<p>Done. You will get an email when a planning application relating to a " +
    "mosque appears in the public register for a council you chose.</p>" +
    "<p>Two things worth knowing:</p><ul>" +
    "<li>Planning coverage is uneven. Most applications in the source are " +
    "English — silence does not always mean nothing was lodged.</li>" +
    "<li>Every email carries an unsubscribe link, and using it deletes your " +
    "address rather than flagging it.</li></ul>" +
    "<p><a href='/'>Back to the map</a> &middot; " +
    "<a href='/privacy.html'>What is stored</a></p>");
};
