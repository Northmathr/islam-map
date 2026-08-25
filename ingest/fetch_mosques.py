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
import hashlib
import json
import os
import time
import urllib.parse

import geo
from http_util import get

# The public Overpass endpoints are free and heavily loaded; 504s are routine
# rather than exceptional, so the fetch rotates mirrors, backs off, and caches
# each faith's response. A partial run resumes instead of starting over.
# overpass.osm.jp was dropped: it serves a certificate for a different
# hostname, so every attempt against it fails verification rather than load.
MIRRORS = [
    "https://overpass.osm.ch/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
# The focus faith is mapped across the whole United Kingdom. The comparison
# faiths are not: the provision ratio they feed is computed on England and Wales,
# where the census religion breakdown behind it exists, so fetching them further
# north would download a lot of data to throw away -- and the free Overpass
# mirrors reject the UK-wide Christian query outright.
#
# The old England and Wales box cut through Scotland at 55.9N, which quietly
# admitted Glasgow but not Edinburgh. District assignment does the filtering now;
# these boxes only bound the download.
BBOX = "49.8,-8.7,60.9,2.1"          # United Kingdom
BBOX_COMPARISON = "49.8,-6.5,55.9,2.1"   # England & Wales


def box_for(faith):
    return BBOX if faith == FOCUS else BBOX_COMPARISON
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


# The UK-wide Christian query is roughly 40,000 elements and several mirrors
# answer it with an empty 200 rather than an error. Splitting the box into
# latitude bands keeps every request small enough to be served, and is gentler
# on a free endpoint than retrying a giant one.
BANDS = 4


def bands(box):
    s, w, n, e = (float(x) for x in box.split(","))
    step = (n - s) / BANDS
    return [f"{s + i * step},{w},{s + (i + 1) * step},{e}" for i in range(BANDS)]


def query(religion, box):
    q = f"""[out:json][timeout:180];
(
  node["amenity"="place_of_worship"]["religion"="{religion}"]({box});
  way["amenity"="place_of_worship"]["religion"="{religion}"]({box});
);
out center tags;"""
    last = None
    for attempt in range(8):
        url = MIRRORS[attempt % len(MIRRORS)]
        try:
            out = json.loads(get(f"{url}?data={urllib.parse.quote(q)}", timeout=300))
            # an overloaded mirror can answer 200 with nothing in it
            if not out.get("elements"):
                raise RuntimeError("empty element list")
            return out
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
    # Key the cache on the bounding box too. Keyed on faith alone, widening the
    # box silently reused the narrower result and looked like OSM having no
    # Scottish mosques.
    out = []
    for tag in FAITH:
        box = box_for(FAITH[tag])
        # England & Wales keeps the original unsuffixed cache name, so extracts
        # taken before the map went UK-wide stay valid for those faiths.
        suffix = "" if box == BBOX_COMPARISON else \
            "." + hashlib.sha1(box.encode()).hexdigest()[:8]
        cached = os.path.join(CACHE, f"{tag}{suffix}.json")
        if os.path.exists(cached):
            with open(cached) as fh:
                els = json.load(fh)
            print(f"  {tag:<10} {len(els):>6,}  (cached)")
        else:
            try:
                seen, els = set(), []
                for band in bands(box):
                    for e in query(tag, band).get("elements", []):
                        key = (e["type"], e["id"])
                        if key not in seen:     # bands share an edge
                            seen.add(key)
                            els.append(e)
                    time.sleep(3)  # be polite to a free endpoint
            except RuntimeError:
                # The focus faith is the product and must be current. The others
                # feed a secondary comparison, so when the free endpoints are
                # shedding load, fall back to any older cached extract rather
                # than failing the whole pipeline -- loudly, because an older
                # extract may be on a narrower bounding box.
                if FAITH[tag] == FOCUS:
                    raise
                stale = os.path.join(CACHE, f"{tag}.json")
                if not os.path.exists(stale):
                    print(f"  {tag:<10} {'SKIPPED':>6}  (Overpass unavailable, no cache)")
                    continue
                with open(stale) as fh:
                    els = json.load(fh)
                print(f"  {tag:<10} {len(els):>6,}  (STALE: earlier extract, "
                      f"England & Wales box)")
                for e in els:
                    e["_faith"] = FAITH[tag]
                out.extend(els)
                continue
            with open(cached, "w") as fh:
                json.dump(els, fh)
            print(f"  {tag:<10} {len(els):>6,}")
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
            outside += 1          # Isle of Man, Channel Islands, offshore, bad tag
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
    print(f"  {len(rows):,} placed | {outside:,} outside any UK district")

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
    print(f"\nplaces of worship (OSM, a floor not a census). {FOCUS} is UK-wide;"
          f"\nthe comparison faiths are England & Wales, which is where the"
          f"\nprovision ratio they feed is computed:")
    for k, v in tot.most_common():
        print(f"  {k:<12} {v:>6,}")


if __name__ == "__main__":
    main()
