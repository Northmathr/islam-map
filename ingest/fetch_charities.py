"""Mosque charities from the Charity Commission register.

OpenStreetMap alone misses roughly a quarter to a third of mosques (measured in
build_mosque_register.py). This adds an official, citable second source: almost
every mosque in England and Wales is a registered charity, and the full register
is published as a bulk extract with no API key.

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

REGISTER = ("https://ccewuksprdoneregsadata1.blob.core.windows.net"
            "/data/txt/publicextract.charity.zip")
POSTCODES = "https://api.postcodes.io/postcodes"
BATCH = 100

# Deliberately broad: mosques register under many names, and a name that merely
# looks Islamic is cheap to discard later but impossible to recover if excluded.
NAME_RE = re.compile(
    r"(mosque|masjid|masaajid|\bjamia\b|\bjame\b|\bjaame\b|islamic cent|"
    r"muslim (community|welfare|educational|cultural|association)|"
    r"\bidara\b|madrasah?)", re.I)

ROOT = os.path.join(os.path.dirname(__file__), os.pardir)
OUT = os.path.join(ROOT, "data")
CACHE = os.path.join(os.path.dirname(__file__), ".charity_cache")


def register_rows():
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, "charity.txt")
    if not os.path.exists(path):
        print("downloading Charity Commission bulk register (~44 MB) ...")
        blob = get(REGISTER, timeout=300)
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            name = next(n for n in z.namelist() if n.endswith(".txt"))
            with open(path, "wb") as fh:
                fh.write(z.read(name))
    csv.field_size_limit(sys.maxsize)
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


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
    rows = register_rows()
    live = [r for r in rows
            if r.get("charity_registration_status") == "Registered"
            and (r.get("linked_charity_number") or "0").strip() == "0"]
    hits = [r for r in live if NAME_RE.search(r.get("charity_name") or "")]
    print(f"register: {len(rows):,} rows | registered: {len(live):,} | "
          f"name-matched: {len(hits):,}")

    pcs = [(r.get("charity_contact_postcode") or "").strip().upper() for r in hits]
    print("geocoding postcodes ...")
    coords = geocode(pcs)
    print(f"  {len(coords):,} postcodes resolved")

    out, seen = [], set()
    for r, pc in zip(hits, pcs):
        if pc not in coords or pc in seen:
            continue
        seen.add(pc)
        lon, lat = coords[pc]
        out.append({
            "name": (r.get("charity_name") or "").strip(),
            "charity_no": r.get("registered_charity_number", ""),
            "postcode": pc,
            "lon": round(lon, 5), "lat": round(lat, 5),
            "source_tier": "charity_register",
        })

    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "mosque_charities.csv")
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0]))
        w.writeheader(); w.writerows(out)
    print(f"wrote {os.path.relpath(path)} ({len(out)} locations, one per postcode)")


if __name__ == "__main__":
    main()
