"""Mosque charities from the Charity Commission register.

OpenStreetMap alone misses roughly a quarter to a third of mosques (measured in
build_mosque_register.py). This adds an official, citable second source: almost
every mosque in England and Wales is a registered charity, and the full register
is published as a bulk extract with no API key.

Matching on the name alone does not work. An earlier version of this script
looked for "mosque", "masjid", "jamia" and similar and found 884 charities,
against the 1,179 UK charity mosques identified by the Ayaan Institute's
*Mosques in Britain* report. The shortfall is mosques that register as
"Newham North Islamic Association", "Anjuman-ul-Muslimeen" or "Gloucestershire
Islamic Trust" -- no worship word anywhere in the name. Simply widening the
pattern overshoots in both directions: "Sunninghill Parochial Charities" matches
on "sunni", and "Islamic Medical Association" is not a place of worship.

So three signals are combined, and each match records which tier caught it:

  name      the name contains mosque/masjid/musalla. Unambiguous.
  activity  the charity's own activity text says it runs a mosque. Also
            unambiguous, and catches the ones named after an association.
            Faith-neutral phrases like "place of worship" are deliberately
            excluded -- they matched churches, synagogues and mandirs.
  inferred  an Islamic-sounding name, classified under Religious Activities,
            holding land, and not an umbrella body. Weaker, so it is tiered
            separately: 73% of charities whose name says mosque hold land
            against 33% of the register at large, which is what makes the land
            flag worth using here.

Two limitations that must travel with the data:

  * The postcode is the charity's *contact* address. For most mosques that is
    the mosque, but for some it is a trustee's home or an accountant's office,
    so a location here is a lead rather than a confirmed building.
  * Postcode centroids are accurate to roughly 100 m, which is why the merge
    step dedupes at 150 m rather than anything tighter.

Every row carries its registered charity number, so any single entry can be
checked against the public register.

Usage:
    python3 ingest/fetch_charities.py
"""

import collections
import csv
import io
import json
import os
import re
import sys
import time
import urllib.request
import zipfile

from http_util import get, _CTX

BLOB = "https://ccewuksprdoneregsadata1.blob.core.windows.net/data/txt/"
REGISTER = BLOB + "publicextract.charity.zip"
CLASSIFICATION = BLOB + "publicextract.charity_classification.zip"
POSTCODES = "https://api.postcodes.io/postcodes"
BATCH = 100

# The name says place of worship. No further evidence needed.
STRONG = re.compile(r"\b(mosque|masjid|masaajid|musalla|musallah)\b", re.I)

# Islamic, but not on its own proof of a place of worship -- these names are
# also used by welfare bodies, professional associations and umbrella groups.
WEAK = re.compile(
    r"(\bjamia\b|\bjaamia\b|\bjamiah\b|\bjaame?\b|\bjamiat\b|\banjuman\b|"
    r"\bmarkaz(i|ia)?\b|\bdar[- ]?ul[- ]?uloom\b|\bdarul\s?uloom\b|\bmadrasah?\b|"
    r"\bmadressa\b|\bmaktab\b|\bbait[- ]?ul\b|\bnoor[- ]?ul\b|\bidara\b|"
    r"\bislamic\b|\bmuslim(s|een)?\b|\bahl[- ]?e[- ]?\w+|\bahmadiyya\b|"
    r"\bismaili\b|\bminhaj\b)", re.I)

# The charity describing its own work in terms only a mosque uses. Note the
# absence of "place of worship": it is faith-neutral and matched churches,
# synagogues and mandirs by the hundred.
ACTIVITY = re.compile(
    r"\b(mosque|masjid|musalla|jum[u]?\'?a[ha]?|jummah|taraweeh|"
    r"eid (prayer|salah)|madrasah?)\b", re.I)

# Islamic in name, emphatically not a place of worship.
NOT_WORSHIP = re.compile(
    r"\b(relief|famine|\baid\b|orphan|hospice|scholarship|burial|cemeter|"
    r"funeral|hajj|umrah|publish|media|\btv\b|radio|magazine|book|"
    r"housing|credit union|sports?|football|medical|doctors?|lawyers?|"
    r"students?|university|chamber of|business|finance|bank)\b", re.I)

ROOT = os.path.join(os.path.dirname(__file__), os.pardir)
OUT = os.path.join(ROOT, "data")
CACHE = os.path.join(os.path.dirname(__file__), ".charity_cache")


def extract(url, filename, label):
    """Download and unzip one bulk extract, cached on disk."""
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, filename)
    if not os.path.exists(path):
        print(f"downloading {label} ...")
        blob = get(url, timeout=300)
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            name = next(n for n in z.namelist() if n.endswith(".txt"))
            with open(path, "wb") as fh:
                fh.write(z.read(name))
    csv.field_size_limit(sys.maxsize)
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def classify(row, classes):
    """Which tier of evidence says this charity is a mosque, if any."""
    name = row.get("charity_name") or ""
    activities = row.get("charity_activities") or ""
    if NOT_WORSHIP.search(name):
        return None
    if STRONG.search(name):
        return "name"
    on = classes.get(row["organisation_number"], ())
    religious = "Religious Activities" in on
    if ACTIVITY.search(activities) and (religious or WEAK.search(name)):
        return "activity"
    if (WEAK.search(name) and religious
            and row.get("charity_has_land") == "True"
            and "Acts As An Umbrella Or Resource Body" not in on):
        return "inferred"
    return None


def geocode(postcodes):
    """Bulk postcode lookup via postcodes.io (free, no key)."""
    out = {}
    uniq = sorted({p for p in postcodes if p})
    for i in range(0, len(uniq), BATCH):
        batch = uniq[i:i + BATCH]
        req = urllib.request.Request(
            POSTCODES, data=json.dumps({"postcodes": batch}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=90, context=_CTX) as r:
            d = json.load(r)
        for item in d.get("result", []):
            res = item.get("result")
            if res and res.get("longitude") is not None:
                out[item["query"].upper()] = (res["longitude"], res["latitude"])
        time.sleep(.4)
    return out


def main():
    rows = extract(REGISTER, "charity.txt", "Charity Commission register (~44 MB)")
    classes = collections.defaultdict(set)
    for c in extract(CLASSIFICATION, "classification.txt", "charity classifications"):
        classes[c["organisation_number"]].add(c["classification_description"])

    live = [r for r in rows
            if r.get("charity_registration_status") == "Registered"
            and (r.get("linked_charity_number") or "0").strip() == "0"]

    hits = []
    for r in live:
        tier = classify(r, classes)
        if tier:
            hits.append((r, tier))
    per_tier = collections.Counter(t for _, t in hits)
    print(f"register: {len(rows):,} rows | registered: {len(live):,} | "
          f"matched: {len(hits):,}")
    for tier in ("name", "activity", "inferred"):
        print(f"  {tier:<10}{per_tier[tier]:>6,}")

    pcs = [(r.get("charity_contact_postcode") or "").strip().upper() for r, _ in hits]
    print("geocoding postcodes ...")
    coords = geocode(pcs)
    print(f"  {len(coords):,} postcodes resolved")

    # One location per postcode. Several charities can share a building (a
    # mosque and its madrasah register separately), and the merge step would
    # collapse them anyway -- doing it here keeps the strongest tier.
    RANK = {"name": 0, "activity": 1, "inferred": 2}
    best = {}
    for (r, tier), pc in zip(hits, pcs):
        if pc not in coords:
            continue
        if pc in best and RANK[tier] >= RANK[best[pc]["evidence"]]:
            continue
        lon, lat = coords[pc]
        best[pc] = {
            "name": (r.get("charity_name") or "").strip(),
            "charity_no": r.get("registered_charity_number", ""),
            "postcode": pc,
            "lon": round(lon, 5), "lat": round(lat, 5),
            "evidence": tier,
            "source_tier": "charity_register",
        }
    out = list(best.values())

    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "mosque_charities.csv")
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0]))
        w.writeheader(); w.writerows(out)
    kept = collections.Counter(o["evidence"] for o in out)
    print(f"wrote {os.path.relpath(path)} ({len(out)} locations, one per postcode)")
    print(f"  by evidence: {dict(kept)}")


if __name__ == "__main__":
    main()
