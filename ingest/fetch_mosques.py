"""Places of worship by faith and district — Phase 2 provision layer.

Source is OpenStreetMap via Overpass. It is not the official register and it
undercounts, but it is the only source that is openly licensed, machine
readable, carries coordinates, and covers every faith with the same query --
and that last point is what makes the provision ratio meaningful. Mosque
openings and church closures are the same metric moving in opposite directions
in the same district; a mosque-only source cannot show that.

The count is a floor, not a census. Small congregations in converted or shared
buildings are systematically under-mapped, and the undercount is not uniform
across faiths, so DESIGN.md requires the ratio to be presented with that stated
rather than as a precise figure. `source_tier` is carried on every row so the
front-end can label it.

Usage:
    python3 ingest/fetch_mosques.py
"""

import collections
import csv
import json
import os
import time
import urllib.parse

import geo
from http_util import get

# The public Overpass endpoints are free and heavily loaded; 504s are routine
# rather than exceptional, so the fetch rotates mirrors, backs off, and caches
# each faith's response. A partial run resumes instead of starting over.
MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.osm.jp/api/interpreter",
]
BBOX = "49.8,-6.5,55.9,2.1"  # England & Wales, trimmed at the Scottish border
SOURCE_TIER = "osm"
CACHE = os.path.join(os.path.dirname(__file__), ".overpass_cache")

# OSM religion tags -> the census faith categories, so provision joins to people
FAITH = {
    "muslim": "Muslim", "christian": "Christian", "jewish": "Jewish",
    "hindu": "Hindu", "sikh": "Sikh", "buddhist": "Buddhist",
}
FOCUS = "Muslim"

ROOT = os.path.join(os.path.dirname(__file__), os.pardir)
OUT_DATA = os.path.join(ROOT, "data")
OUT_WEB = os.path.join(ROOT, "web", "data")


def query(religion):
    q = f"""[out:json][timeout:180];
(
  node["amenity"="place_of_worship"]["religion"="{religion}"]({BBOX});
  way["amenity"="place_of_worship"]["religion"="{religion}"]({BBOX});
);
out center tags;"""
    last = None
    for attempt in range(6):
        url = MIRRORS[attempt % len(MIRRORS)]
        try:
            return json.loads(get(f"{url}?data={urllib.parse.quote(q)}", timeout=300))
        except Exception as exc:
            last = exc
            wait = min(60, 6 * 2 ** attempt)
            print(f"    {religion}: {type(exc).__name__} on mirror "
                  f"{attempt % len(MIRRORS)}, retry in {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"{religion}: all Overpass attempts failed ({last})")


def elements():
    """Fetch per faith rather than in one shot -- the unfiltered England & Wales
    query is large enough that it times out more often than it succeeds."""
    os.makedirs(CACHE, exist_ok=True)
    out = []
    for tag in FAITH:
        cached = os.path.join(CACHE, f"{tag}.json")
        if os.path.exists(cached):
            with open(cached) as fh:
                els = json.load(fh)
            print(f"  {tag:<10} {len(els):>6,}  (cached)")
        else:
            els = query(tag).get("elements", [])
            with open(cached, "w") as fh:
                json.dump(els, fh)
            print(f"  {tag:<10} {len(els):>6,}")
            time.sleep(3)  # be polite to a free endpoint
        for e in els:
            e["_faith"] = FAITH[tag]
        out.extend(els)
    return out


def main():
    print("fetching places of worship from Overpass ...")
    els = elements()

    print("assigning to districts ...")
    d = geo.Districts()
    rows, outside = [], 0
    for e in els:
        lat = e.get("lat") or (e.get("center") or {}).get("lat")
        lon = e.get("lon") or (e.get("center") or {}).get("lon")
        if lat is None or lon is None:
            continue
        code, name = d.assign(lon, lat)
        if not code:
            outside += 1          # Scotland, Isle of Man, offshore, or a bad tag
            continue
        tags = e.get("tags", {})
        rows.append({
            "area_code": code, "area_name": name,
            "faith": e["_faith"],
            "osm_type": e["type"], "osm_id": e["id"],
            "name": tags.get("name", ""),
            "denomination": tags.get("denomination", ""),
            "lon": round(lon, 5), "lat": round(lat, 5),
            "source_tier": SOURCE_TIER,
        })
    print(f"  {len(rows):,} placed | {outside:,} outside England & Wales")

    os.makedirs(OUT_DATA, exist_ok=True)
    os.makedirs(OUT_WEB, exist_ok=True)

    path = os.path.join(OUT_DATA, "places_of_worship.csv")
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    print(f"wrote {os.path.relpath(path)} ({len(rows)} rows)")

    # counts per district per faith
    counts = collections.defaultdict(lambda: collections.defaultdict(int))
    names = {}
    for r in rows:
        counts[r["area_code"]][r["faith"]] += 1
        names[r["area_code"]] = r["area_name"]

    summary = []
    for code in sorted(d.codes()):
        if not code.startswith(("E", "W")):
            continue
        by = counts.get(code, {})
        summary.append({
            "area_code": code,
            "area_name": names.get(code, ""),
            "source_tier": SOURCE_TIER,
            **{f"n_{k.lower().replace(' ', '_')}": by.get(k, 0) for k in FAITH.values()},
            "n_total": sum(by.values()),
        })
    path = os.path.join(OUT_DATA, "provision_ltla23.csv")
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(summary[0]))
        w.writeheader(); w.writerows(summary)
    print(f"wrote {os.path.relpath(path)} ({len(summary)} districts)")

    # points for the map overlay: focus faith only, to keep the payload small
    pts = [[r["lon"], r["lat"], r["name"]] for r in rows if r["faith"] == FOCUS]
    path = os.path.join(OUT_WEB, "mosques.json")
    with open(path, "w") as fh:
        json.dump({"tier": SOURCE_TIER, "points": pts}, fh, separators=(",", ":"))
    print(f"wrote {os.path.relpath(path)} ({len(pts)} points)")

    tot = collections.Counter(r["faith"] for r in rows)
    print("\nplaces of worship in England & Wales (OSM, a floor not a census):")
    for k, v in tot.most_common():
        print(f"  {k:<12} {v:>6,}")


if __name__ == "__main__":
    main()
