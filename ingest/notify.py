"""Email subscribers about planning applications new to their council.

Run after fetch_planning.py. Diffs the freshly written snapshot against the one
previously committed, and sends a digest per subscriber.

Four guards stand between the diff and the outbox, each for a failure this
pipeline has actually shown:

  Backfill gate     PlanIt backfills. The 2023 figure in the snapshot is 248
                    against roughly 50 a year either side, which is
                    record-keeping rather than activity. "New to our snapshot"
                    therefore does not mean "newly lodged", and without a
                    recency window one backfill would mail every subscriber
                    about applications from years ago.

  Short-fetch gate  PlanIt rate-limits and 500s routinely. A run that comes
                    back materially short is not evidence that applications
                    vanished, and worse, the next full run would then read as a
                    flood of new ones. Below the floor, nothing sends.

  Already-sent gate sent_alerts is keyed on (subscriber, ref). Whatever the
                    diff believes, nobody is told about the same application
                    twice.

  Confidence gate   226 of 1,668 applications matched on the address rather
                    than the description -- a mosque named as a landmark near
                    an unrelated development. Those are excluded by default.

Nothing sends without --send. The default is a dry run that prints what would
go out, which is also how this is tested before any account exists.

Environment:
    SUPABASE_URL           https://<project>.supabase.co
    SUPABASE_SERVICE_KEY   service role key (never the anon key)
    POSTMARK_TOKEN         server token
    POSTMARK_FROM          verified sender address
    UNSUB_SECRET           HMAC key, shared with the unsubscribe function
    SITE_URL               https://<site> (for links)

Usage:
    python3 ingest/notify.py --dry-run
    python3 ingest/notify.py --send
"""

import argparse
import collections
import csv
import datetime as dt
import hashlib
import hmac
import itertools
import json
import os
import subprocess
import sys
import urllib.parse

from http_util import get, post_json

ROOT = os.path.join(os.path.dirname(__file__), os.pardir)
DATA = os.path.join(ROOT, "data")
SNAPSHOT = "data/planning_applications.csv"

# An application older than this is history, not news, whenever it first
# appeared in our snapshot.
RECENCY_DAYS = 60
# Refuse to send if the new snapshot has fallen below this share of the old one.
SHORT_FETCH_FLOOR = 0.90
# Conditions and amendments are follow-ups to a permission that already exists;
# telling someone about them reads as a new application when it is paperwork.
SKIP_KINDS = {"admin"}

KIND_LABEL = {
    "new_build": "New build or replacement",
    "use_to": "Change of use to a mosque",
    "extension": "Extension or alteration",
    "use_away": "Change of use away from worship",
    "demolition": "Demolition without replacement",
    "other": "Other",
}
STATUS_LABEL = {"approved": "Approved", "refused": "Refused",
                "withdrawn": "Withdrawn", "pending": "Awaiting a decision"}


def env(name, required=True):
    v = os.environ.get(name)
    if required and not v:
        sys.exit(f"missing environment variable: {name}")
    return v


# ---------------------------------------------------------------- the diff

def previous_snapshot():
    """The committed snapshot, read from git rather than from a copy on disk.

    Using git means the comparison point is whatever was last published, so a
    failed or interrupted run cannot leave a stale sidecar file behind that
    silently changes what counts as new.
    """
    try:
        blob = subprocess.run(
            ["git", "show", f"HEAD:{SNAPSHOT}"],
            cwd=ROOT, capture_output=True, check=True).stdout
    except subprocess.CalledProcessError:
        return None
    return list(csv.DictReader(blob.decode("utf-8").splitlines()))


def current_snapshot():
    with open(os.path.join(DATA, "planning_applications.csv")) as fh:
        return list(csv.DictReader(fh))


def new_applications(today, days=RECENCY_DAYS):
    prev = previous_snapshot()
    cur = current_snapshot()

    if prev is None:
        print("no committed snapshot to compare against -- treating as a "
              "baseline run, nothing will be sent")
        return [], cur

    if len(cur) < len(prev) * SHORT_FETCH_FLOOR:
        sys.exit(f"short fetch: {len(cur):,} rows against {len(prev):,} "
                 f"previously ({len(cur)/len(prev):.0%}). Refusing to diff -- "
                 f"a partial fetch now becomes a flood of false alerts later.")

    seen = {r["ref"] for r in prev}
    cutoff = (today - dt.timedelta(days=days)).isoformat()

    fresh, stale, low, skipped = [], 0, 0, 0
    for r in cur:
        if r["ref"] in seen:
            continue
        if r["kind"] in SKIP_KINDS:
            skipped += 1
            continue
        if r["confidence"] != "high":
            low += 1
            continue
        # `date` is consulted_date falling back to last_changed, so it moves
        # when a record is updated. It is a recency gate and nothing more --
        # never present it as the date an application was lodged.
        if not r["date"] or r["date"] < cutoff:
            stale += 1
            continue
        fresh.append(r)

    print(f"snapshot: {len(prev):,} -> {len(cur):,} rows")
    print(f"  new refs: {sum(1 for r in cur if r['ref'] not in seen):,}")
    print(f"  dropped: {stale:,} older than {days} days, "
          f"{low:,} low confidence, {skipped:,} administrative")
    print(f"  to notify on: {len(fresh):,}")
    return fresh, cur


# ------------------------------------------------------------- subscribers

def rest(path, params=""):
    url = f"{env('SUPABASE_URL')}/rest/v1/{path}{params}"
    key = env("SUPABASE_SERVICE_KEY")
    return json.loads(get_with_key(url, key))


def get_with_key(url, key):
    import urllib.request
    from http_util import _CTX, UA
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "apikey": key, "Authorization": f"Bearer {key}",
        "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60, context=_CTX) as resp:
        return resp.read()


def subscribers():
    rows = rest("subscribers",
                "?select=id,email,areas&confirmed=eq.true&unsubscribed_at=is.null")
    print(f"confirmed subscribers: {len(rows):,}")
    return rows


def already_sent(subscriber_id, refs):
    if not refs:
        return set()
    quoted = ",".join(f'"{r}"' for r in refs)
    rows = rest("sent_alerts",
                f"?select=ref&subscriber_id=eq.{subscriber_id}"
                f"&ref=in.({urllib.parse.quote(quoted)})")
    return {r["ref"] for r in rows}


def record_sent(subscriber_id, refs, area, provider_id, ok, error=None):
    key = env("SUPABASE_SERVICE_KEY")
    headers = {"apikey": key, "Authorization": f"Bearer {key}",
               "Prefer": "resolution=ignore-duplicates,return=minimal"}
    if refs:
        post_json(f"{env('SUPABASE_URL')}/rest/v1/sent_alerts",
                  [{"subscriber_id": subscriber_id, "ref": r} for r in refs],
                  headers)
    post_json(f"{env('SUPABASE_URL')}/rest/v1/send_log",
              [{"subscriber_id": subscriber_id, "area_code": area,
                "n_refs": len(refs), "provider_id": provider_id,
                "ok": ok, "error": error}], headers)


# ------------------------------------------------------------------ email

def unsub_link(email):
    secret = env("UNSUB_SECRET").encode()
    sig = hmac.new(secret, email.lower().encode(), hashlib.sha256).hexdigest()[:32]
    q = urllib.parse.urlencode({"e": email, "t": sig})
    return f"{env('SITE_URL')}/.netlify/functions/unsubscribe?{q}"


def render(area_name, apps, email):
    """Plain text and HTML for one council's digest.

    Deliberately the same register as the map: reference, council, description,
    and a link to the authority's own record. The planning authority is the
    authority on its own applications -- this only says one exists.
    """
    n = len(apps)
    subject = (f"{n} new mosque planning applications in {area_name}" if n > 1
               else f"New mosque planning application in {area_name}")

    lines = [f"{n} planning application{'s' if n > 1 else ''} relating to a "
             f"mosque {'have' if n > 1 else 'has'} appeared in the public "
             f"register for {area_name}.", ""]
    html = [f"<p>{n} planning application{'s' if n > 1 else ''} relating to a "
            f"mosque {'have' if n > 1 else 'has'} appeared in the public "
            f"register for <strong>{esc(area_name)}</strong>.</p>"]

    for a in apps:
        kind = KIND_LABEL.get(a["kind"], a["kind"])
        status = STATUS_LABEL.get(a["status"], a["status"])
        lines += [f"* {kind} — {status}",
                  f"  {a['description'][:300]}",
                  f"  Reference {a['ref']}",
                  f"  {a['url']}" if a["url"] else "", ""]
        html.append(
            f'<div style="margin:0 0 18px;padding:12px 14px;border:1px solid #e2ded6;'
            f'border-radius:8px"><div style="font-size:13px;color:#55616e">'
            f'{esc(kind)} &middot; {esc(status)}</div>'
            f'<div style="margin:6px 0">{esc(a["description"][:300])}</div>'
            f'<div style="font-size:12px;color:#8b96a2">Reference {esc(a["ref"])}</div>'
            + (f'<div style="margin-top:6px"><a href="{esc(a["url"])}">'
               f'See the planning record</a></div>' if a["url"] else "")
            + "</div>")

    site = env("SITE_URL")
    lines += ["Dates shown by the source are when a record was last updated, "
              "not when an application was lodged.",
              f"Map and method: {site}",
              "",
              f"Unsubscribe: {unsub_link(email)}"]
    html.append(
        f'<p style="font-size:12px;color:#8b96a2">Dates shown by the source are '
        f'when a record was last updated, not when an application was lodged. '
        f'<a href="{esc(site)}">Map and method</a>.</p>'
        f'<p style="font-size:12px;color:#8b96a2">'
        f'<a href="{esc(unsub_link(email))}">Unsubscribe</a></p>')

    return subject, "\n".join(lines), "".join(html)


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def send(email, subject, text, html):
    """Postmark. One-click unsubscribe headers as well as the in-body link,
    because a mail client's own unsubscribe button is the one people use."""
    res = post_json(
        "https://api.postmarkapp.com/email",
        {"From": env("POSTMARK_FROM"), "To": email, "Subject": subject,
         "TextBody": text, "HtmlBody": html,
         "MessageStream": "broadcast",
         "Headers": [
             {"Name": "List-Unsubscribe",
              "Value": f"<{unsub_link(email)}>"},
             {"Name": "List-Unsubscribe-Post",
              "Value": "List-Unsubscribe=One-Click"},
         ]},
        {"X-Postmark-Server-Token": env("POSTMARK_TOKEN")})
    return res.get("MessageID") if res else None


# ------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true",
                   help="print what would be sent, touch nothing")
    g.add_argument("--send", action="store_true")
    ap.add_argument("--days", type=int, default=RECENCY_DAYS,
                    help=f"recency window in days (default {RECENCY_DAYS})")
    args = ap.parse_args()

    fresh, _ = new_applications(dt.date.today(), args.days)
    if not fresh:
        print("nothing to send")
        return

    by_area = collections.defaultdict(list)
    for r in fresh:
        by_area[r["area_code"]].append(r)
    names = {r["area_code"]: r["area_name"] for r in fresh}

    if args.dry_run and not os.environ.get("SUPABASE_URL"):
        print("\n--- dry run, no database configured ---")
        for code, apps in sorted(by_area.items()):
            print(f"\n{names[code]} ({code}) — {len(apps)} application(s)")
            subject, text, _ = render(names[code], apps, "someone@example.com") \
                if os.environ.get("SITE_URL") else (
                    f"New mosque planning application in {names[code]}", "", "")
            print(f"  subject: {subject}")
            for a in apps:
                print(f"    [{a['status']}] {KIND_LABEL.get(a['kind'], a['kind'])}"
                      f" — {a['description'][:90]}")
        print(f"\n{len(by_area)} council(s) affected, {len(fresh)} application(s).")
        print("Set SUPABASE_URL and the rest to dry-run against real subscribers.")
        return

    subs = subscribers()
    sent_total = 0
    for s in subs:
        wanted = [r for code in s["areas"] for r in by_area.get(code, [])]
        if not wanted:
            continue
        refs = [r["ref"] for r in wanted]
        seen = already_sent(s["id"], refs)
        wanted = [r for r in wanted if r["ref"] not in seen]
        if not wanted:
            continue
        # one message per council, so a subscriber to three councils with news
        # in two gets two clearly-scoped emails rather than one muddled digest
        for code, apps in itertools.groupby(
                sorted(wanted, key=lambda r: r["area_code"]),
                key=lambda r: r["area_code"]):
            apps = list(apps)
            subject, text, html = render(names[code], apps, s["email"])
            if args.dry_run:
                print(f"  would send to {s['email']}: {subject} "
                      f"({len(apps)} application(s))")
                continue
            try:
                mid = send(s["email"], subject, text, html)
                record_sent(s["id"], [a["ref"] for a in apps], code, mid, True)
                sent_total += 1
            except Exception as exc:                      # noqa: BLE001
                print(f"  FAILED {s['email']}: {exc}")
                record_sent(s["id"], [], code, None, False, str(exc))

    print(f"{'would send' if args.dry_run else 'sent'} {sent_total} message(s)")


if __name__ == "__main__":
    main()
