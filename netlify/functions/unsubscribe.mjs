// Unsubscribe. Reached three ways, all of which must work:
//   * the link in the body of an email          (GET, shows a page)
//   * a mail client's own unsubscribe button    (POST, List-Unsubscribe-Post)
//   * someone pasting the link into a browser   (GET)
//
// The token is an HMAC of the address rather than a stored secret, so it keeps
// working after a database restore and cannot be enumerated. notify.py builds
// the identical value with the same UNSUB_SECRET.
//
// Unsubscribing DELETES the row. A suppression list would mean keeping the
// address of someone who asked to be gone; deletion is what they asked for,
// and the honeypot-free signup makes re-subscription trivial if it was a
// mistake.

import { createHmac, timingSafeEqual } from "node:crypto";

const env = (k) => {
  const v = process.env[k];
  if (!v) throw new Error(`missing environment variable: ${k}`);
  return v;
};

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

const expected = (email) =>
  createHmac("sha256", env("UNSUB_SECRET"))
    .update(email.toLowerCase()).digest("hex").slice(0, 32);

function valid(email, token) {
  const a = Buffer.from(expected(email));
  const b = Buffer.from(String(token || ""));
  return a.length === b.length && timingSafeEqual(a, b);
}

async function remove(email) {
  const key = env("SUPABASE_SERVICE_KEY");
  const url = `${env("SUPABASE_URL")}/rest/v1/subscribers` +
              `?email_norm=eq.${encodeURIComponent(email.toLowerCase())}`;
  const res = await fetch(url, {
    method: "DELETE",
    headers: { apikey: key, Authorization: `Bearer ${key}`, Prefer: "return=minimal" },
  });
  if (!res.ok) throw new Error(`supabase ${res.status}: ${await res.text()}`);
}

export default async (req) => {
  const url = new URL(req.url);
  let email = url.searchParams.get("e") || "";
  let token = url.searchParams.get("t") || "";

  // One-click unsubscribe posts an empty body to the same URL, so the query
  // string still carries both values -- but accept form fields too, because
  // some clients send them that way.
  if (req.method === "POST" && !email) {
    try {
      const form = await req.formData();
      email = form.get("e") || "";
      token = form.get("t") || "";
    } catch { /* empty body is normal for one-click */ }
  }

  if (!email || !valid(email, token)) {
    // 200, not 4xx: a mail client that gets an error may retry or warn the
    // person, and there is nothing they can do about a malformed link.
    return page("Link not recognised",
      "<p>That unsubscribe link is not valid — it may have been broken across " +
      "two lines by your mail client. Reply to any alert and it will be " +
      "handled by hand.</p>");
  }

  try {
    await remove(email);
  } catch (err) {
    console.error("unsubscribe failed", err);
    return page("Something went wrong",
      "<p>That did not work just now. Try again in a few minutes — and if it " +
      "still fails, reply to any alert and it will be handled by hand.</p>", 500);
  }

  if (req.method === "POST") return new Response(null, { status: 204 });

  return page("Unsubscribed",
    "<p>Done. Your address has been deleted, not merely flagged, so nothing " +
    "further will be sent.</p>" +
    "<p><a href='/'>Back to the map</a> &middot; " +
    "<a href='/alerts.html'>Sign up again</a></p>");
};
