"""Mosque planning applications by district — Phase 3 activity layer.

Source is PlanIt, which aggregates most UK local planning authorities. Its API
is unreliable enough that DESIGN.md keeps it out of the render path entirely:
this script writes a snapshot and the map reads the snapshot, so a bad day at
PlanIt degrades the layer to stale rather than breaking the page.

Two honesty constraints, both from DESIGN.md:

  * Applications are applications. Refused and withdrawn stay in the data, and
    an approval is not a building. Status is carried on every record.
  * Direction matters. Change of use *away* from worship and demolition are
    first-class categories, not an afterthought -- a feed that only counts
    mosques appearing measures one direction of a two-directional process.

Full-text search also matches applications that merely cite a mosque as an
address landmark, so `confidence` records whether the match was in the
description (high) or only the address (medium). The front-end shows it.

Usage:
    python3 ingest/fetch_planning.py [--since YYYY-MM-DD]
"""

import argparse
import collections
import csv
import json
import os
import re
import time
import urllib.parse

import geo
from http_util import get_json

API = "https://www.planit.org.uk/api/applics/json"
TERMS = ["mosque", "masjid", "islamic centre", "muslim prayer", "jamia"]
PAGE = 200
SINCE_DEFAULT = "2014-01-01"

ROOT = os.path.join(os.path.dirname(__file__), os.pardir)
OUT_DATA = os.path.join(ROOT, "data")
OUT_WEB = os.path.join(ROOT, "web", "data")

KIND_LABEL = {
    "new_build": "New build or replacement",
    "use_to": "Change of use to worship",
    "extension": "Extension / alteration",
    "use_away": "Change of use away from worship",
    "demolition": "Demolition without replacement",
    "admin": "Conditions / amendments",
    "other": "Other / unclassified",
}
KIND_ORDER = list(KIND_LABEL)

# Administrative follow-ups to a permission that already exists. They are not
# new proposals and counting them would double-count the original application.
RE_ADMIN = re.compile(
    r"discharge of condition|approval of details|reserved matters|"
    r"non[- ]material amendment|minor material amendment|certificate of lawful|"
    r"prior approval|variation of condition|s\.?73\b", re.I)
RE_DEMOLISH = re.compile(r"\bdemoli", re.I)
RE_BUILD = re.compile(
    r"\b(erection|erect|construction of|new build|rebuild|replacement|"
    r"redevelop|development of)\b", re.I)
RE_USE = re.compile(r"change of use|conversion", re.I)
RE_TO_WORSHIP = re.compile(
    r"(to|into)\b.{0,60}?(mosque|masjid|place of worship|islamic|prayer|"
    r"religious|f\.?1|d1)", re.I)
RE_FROM_WORSHIP = re.compile(
    r"(to|into)\b.{0,60}?(dwelling|residential|flat|apartment|hous|office|"
    r"retail|shop|nursery|school|warehouse|gym)", re.I)
RE_EXTEND = re.compile(
    r"\b(extension|extend|alteration|storey|dormer|porch|canopy|refurbish|"
    r"internal|external works|elevation|fenestration|roof|car park)\b", re.I)
# Erecting something ONTO a mosque that is already there. Without this, every
# "erection of single storey extension to mosque" matched RE_BUILD first and was
# counted as a brand new mosque, inflating the running total of gains.
RE_ADDITION = re.compile(
    r"\b(to|at)\b[^.;]{0,60}?\b(the\s+)?(existing\s+)?"
    r"(mosque|masjid|islamic cent\w*|prayer hall)\b", re.I)

STATUS = {
    "permitted": "approved", "conditions": "approved", "approved": "approved",
    "rejected": "refused", "refused": "refused",
    "withdrawn": "withdrawn", "undecided": "pending", "unresolved": "pending",
    "referred": "pending", "insufficient": "pending",
}

TERM_RE = re.compile("|".join(re.escape(t) for t in TERMS), re.I)


def classify(desc: str) -> str:
    """Bucket an application by what it does to the estate.

    Ordering alone is not enough here. "Demolition of existing building and
    erection of a mosque" is a *replacement*, and a naive demolition-first rule
    classifies the large majority of redevelopments as losses -- which inverts
    the direction of the whole layer. So demolition only counts as demolition
    when nothing is being built in its place.
    """
    d = desc or ""
    if not d.strip():
        return "other"
    if RE_ADMIN.search(d):
        return "admin"

    demolish, build = bool(RE_DEMOLISH.search(d)), bool(RE_BUILD.search(d))
    if demolish and not build:
        return "demolition"
    if RE_USE.search(d):
        # a change of use away from worship is the loss case and is checked
        # first, because "conversion of the mosque to flats" mentions both
        if RE_FROM_WORSHIP.search(d):
            return "use_away"
        if RE_TO_WORSHIP.search(d):
            return "use_to"
    # An addition to a mosque that already exists is an extension, whatever verb
    # the description uses. Checked before the build rule because "erection of a
    # rear extension to the mosque" satisfies both, and only one of them is
    # right. Demolition-and-replace is excluded: that really is a new building.
    if build and not demolish and RE_ADDITION.search(d):
        return "extension"
    if build:
        return "new_build"
    if RE_EXTEND.search(d):
        return "extension"
    return "other"


def fetch(term, since):
    """Page through one search term. PlanIt reports `total`, `from` and `to`."""
    out, page = [], 1
    while True:
        qs = urllib.parse.urlencode({
            "search": term, "pg_sz": PAGE, "page": page, "start_date": since,
        })
        for attempt in range(4):
            try:
                d = get_json(f"{API}?{qs}", timeout=120)
                break
            except Exception as exc:
                if attempt == 3:
                    print(f"    {term}: giving up ({exc})")
                    return out
                time.sleep(5 * (attempt + 1))
        if "error" in d:
            print(f"    {term}: {d['error']}")
            return out
        recs = d.get("records", [])
        out.extend(recs)
        total = d.get("total") or 0
        if not recs or len(out) >= total:
            break
        page += 1
        time.sleep(1.5)
    return out


def from_csv():
    """Re-read the last snapshot instead of the API.

    PlanIt is the least reliable source in this pipeline, and a change to
    classify() should not need a refetch that might come back short. This
    re-runs the classifier over the stored descriptions and rebuilds every
    derived output from them.
    """
    path = os.path.join(OUT_DATA, "planning_applications.csv")
    with open(path) as fh:
        rows = list(csv.DictReader(fh))
    changed = 0
    for r in rows:
        kind = classify(r["description"])
        if kind != r["kind"]:
            changed += 1
        r["kind"] = kind
        r["lon"], r["lat"] = float(r["lon"]), float(r["lat"])
    print(f"re-read {len(rows):,} applications from {os.path.relpath(path)}")
    print(f"  reclassified: {changed:,}")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=SINCE_DEFAULT)
    ap.add_argument("--reclassify", action="store_true",
                    help="rebuild outputs from the stored snapshot, no API calls")
    args = ap.parse_args()

    if args.reclassify:
        rows = from_csv()
        return emit(rows, args.since)

    print(f"fetching planning applications since {args.since} ...")
    raw = {}
    for term in TERMS:
        recs = fetch(term, args.since)
        print(f"  {term:<16} {len(recs):>5,}")
        for r in recs:
            if r.get("name"):
                raw[r["name"]] = r          # dedupe on the application reference
        time.sleep(1)
    print(f"  {len(raw):,} unique applications after dedupe")

    d = geo.Districts()
    rows, outside, nogeo = [], 0, 0
    for ref, r in raw.items():
        lon, lat = r.get("location_x"), r.get("location_y")
        if lon is None or lat is None:
            nogeo += 1
            continue
        code, name = d.assign(lon, lat)
        if not code:
            outside += 1
            continue
        desc = r.get("description") or ""
        addr = r.get("address") or ""
        rows.append({
            "ref": ref,
            "area_code": code, "area_name": name,
            "lpa": r.get("area_name", ""),
            "kind": classify(desc),
            "status": STATUS.get((r.get("app_state") or "").strip().lower(), "pending"),
            "app_type": r.get("app_type", ""),
            "date": (r.get("consulted_date") or r.get("last_changed") or "")[:10],
            "decided": (r.get("decided_date") or "")[:10],
            # a mosque named only in the address may be a landmark, not the subject
            "confidence": "high" if TERM_RE.search(desc) else "medium",
            "description": desc[:300],
            "address": addr[:200],
            "lon": round(lon, 5), "lat": round(lat, 5),
            "url": r.get("link", ""),
        })
    print(f"  {len(rows):,} placed | {outside:,} outside any UK district | "
          f"{nogeo:,} without coordinates")
    return emit(rows, args.since)


def emit(rows, since):
    os.makedirs(OUT_DATA, exist_ok=True)
    os.makedirs(OUT_WEB, exist_ok=True)

    rows.sort(key=lambda r: r["date"], reverse=True)
    path = os.path.join(OUT_DATA, "planning_applications.csv")
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    print(f"wrote {os.path.relpath(path)} ({len(rows)} rows)")

    # per-district rollup for the choropleth
    agg = collections.defaultdict(lambda: collections.Counter())
    for r in rows:
        a = agg[r["area_code"]]
        a["n"] += 1
        a[r["status"]] += 1
        a[r["kind"]] += 1
        if r["confidence"] == "high":
            a["high"] += 1
        # only approved outcomes move the estate; refusals and pending do not
        if r["status"] == "approved":
            if r["kind"] in ("new_build", "use_to"):
                a["net_gain"] += 1
            elif r["kind"] in ("demolition", "use_away"):
                a["net_gain"] -= 1
    summary = [{
        "area_code": code, "n": a["n"],
        "approved": a["approved"], "refused": a["refused"],
        "withdrawn": a["withdrawn"], "pending": a["pending"],
        "high_confidence": a["high"],
        **{k: a[k] for k in KIND_ORDER},
        # Net direction implied by approved outcomes: things gained minus things
        # lost. This is planning flow, never a register stock delta -- DESIGN.md.
        "net_gain": a["net_gain"],
    } for code, a in sorted(agg.items())]

    path = os.path.join(OUT_DATA, "planning_ltla23.csv")
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(summary[0]))
        w.writeheader(); w.writerows(summary)
    print(f"wrote {os.path.relpath(path)} ({len(summary)} districts)")

    # snapshot for the map: the feed is never read live
    path = os.path.join(OUT_WEB, "applications.json")
    with open(path, "w") as fh:
        json.dump({
            "fetched": time.strftime("%Y-%m-%d"),
            "since": since,
            "records": [{
                "r": r["ref"], "c": r["area_code"], "k": r["kind"],
                "s": r["status"], "d": r["date"], "q": r["confidence"],
                "x": r["lon"], "y": r["lat"],
                "t": r["description"][:160], "u": r["url"],
            } for r in rows],
        }, fh, separators=(",", ":"))
    print(f"wrote {os.path.relpath(path)} ({len(rows)} records)")

    print("\nby kind:")
    for k, n in collections.Counter(r["kind"] for r in rows).most_common():
        print(f"  {KIND_LABEL[k]:<32} {n:>5,}")
    print("by status:")
    for k, n in collections.Counter(r["status"] for r in rows).most_common():
        print(f"  {k:<32} {n:>5,}")
    hi = sum(1 for r in rows if r["confidence"] == "high")
    print(f"\nmatched in description (high confidence): {hi:,} of {len(rows):,}")


if __name__ == "__main__":
    main()
