"""Merge three sources into one mosque register, with provenance per location.

Why this exists: OpenStreetMap on its own reports 1,314 mosques in England and
Wales, which is well short of the ~1,800 "actual masjids" the MuslimsInBritain
directory lists. Two independent checks show why, and both are reproducible from
this repo:

  * Of 608 planning applications approved to build or convert a mosque, only
    73% have an OSM mosque within 250 m.
  * Of the mosque-charity locations on the Charity Commission register, only
    58% have an OSM mosque within 300 m.

Widening the Overpass query barely helps (+55 elements), so the gap is OSM's
coverage rather than the query. The fix is triangulation: take the union of
three sources that miss different things, dedupe on proximity, and record which
sources vouch for each location so any entry can be checked.

None of the three is a census of mosques:

  osm               precise coordinates, incomplete, no dates
  charity_register  official and citable, but a *contact* address that is
                    sometimes a trustee or accountant rather than the building
  planning          official and dated, but only covers premises that needed
                    permission, and approval is not completion

A location confirmed by two or more sources is materially stronger than one
seen once, so `sources` and `n_sources` travel with every row and the front-end
can report a confident count and a broader count separately.

Usage:
    python3 ingest/build_mosque_register.py
"""

import collections
import csv
import json
import math
import os

import geo

ROOT = os.path.join(os.path.dirname(__file__), os.pardir)
DATA = os.path.join(ROOT, "data")
WEB = os.path.join(ROOT, "web", "data")

# Postcode centroids are good to roughly 100 m, so anything tighter than this
# would split one mosque into several. Anything much looser starts merging
# genuinely separate mosques in dense inner-city areas.
MERGE_M = 150


def read(name):
    with open(os.path.join(DATA, name)) as fh:
        return list(csv.DictReader(fh))


def load_sources():
    pts = []
    for r in read("places_of_worship.csv"):
        if r["faith"] == "Muslim":
            pts.append((float(r["lon"]), float(r["lat"]), "osm", r["name"], ""))
    for r in read("mosque_charities.csv"):
        pts.append((float(r["lon"]), float(r["lat"]), "charity_register",
                    r["name"], r["charity_no"]))
    for r in read("planning_applications.csv"):
        if r["status"] == "approved" and r["kind"] in ("new_build", "use_to"):
            pts.append((float(r["lon"]), float(r["lat"]), "planning",
                        r["address"][:80], r["ref"]))
    return pts


def cluster(points, metres=MERGE_M):
    """Grid-hashed proximity merge, so this stays linear rather than quadratic."""
    dlat = metres / 111000
    grid, out = {}, []
    for lon, lat, src, name, ref in points:
        dlon = dlat / max(math.cos(math.radians(lat)), .3)
        gx, gy = int(lon / dlon), int(lat / dlat)
        found = None
        for a in (gx - 1, gx, gx + 1):
            for b in (gy - 1, gy, gy + 1):
                for idx in grid.get((a, b), ()):
                    c = out[idx]
                    if abs(c["lon"] - lon) < dlon and abs(c["lat"] - lat) < dlat:
                        found = idx
                        break
                if found is not None:
                    break
            if found is not None:
                break
        if found is None:
            grid.setdefault((gx, gy), []).append(len(out))
            out.append({"lon": lon, "lat": lat, "sources": {src},
                        "names": [name] if name else [], "refs": [ref] if ref else []})
        else:
            c = out[found]
            c["sources"].add(src)
            if name and name not in c["names"]:
                c["names"].append(name)
            if ref:
                c["refs"].append(ref)
            # prefer OSM geometry: it is a mapped building, not a postcode centroid
            if src == "osm":
                c["lon"], c["lat"] = lon, lat
    return out


def main():
    pts = load_sources()
    per_source = collections.Counter(s for _, _, s, _, _ in pts)
    print("input locations:")
    for k, v in per_source.most_common():
        print(f"  {k:<18}{v:>6,}")

    merged = cluster(pts)
    print(f"\nmerged at {MERGE_M} m: {len(merged):,} distinct locations")

    combos = collections.Counter("+".join(sorted(c["sources"])) for c in merged)
    for k, v in combos.most_common():
        print(f"  {k:<34}{v:>5}")

    d = geo.Districts()
    rows, outside, out_of_scope = [], 0, 0
    for c in merged:
        code, name = d.assign(c["lon"], c["lat"])
        if not code:
            outside += 1
            continue
        # The boundary file covers the whole UK and the Overpass query was
        # UK-wide, so Scottish and Northern Irish mosques get assigned a real
        # district. This map is England and Wales -- the census tables behind it
        # are E&W only -- so they are dropped here rather than inflating a
        # headline the rest of the pipeline cannot account for.
        if code[0] not in ("E", "W"):
            out_of_scope += 1
            continue
        rows.append({
            "area_code": code, "area_name": name,
            "name": (c["names"][0] if c["names"] else ""),
            "lon": round(c["lon"], 5), "lat": round(c["lat"], 5),
            "sources": "+".join(sorted(c["sources"])),
            "n_sources": len(c["sources"]),
            "refs": ";".join(c["refs"][:4]),
        })
    print(f"\nplaced in England & Wales: {len(rows):,} "
          f"({out_of_scope} in Scotland or NI, {outside} outside any district)")

    confirmed = sum(1 for r in rows if r["n_sources"] >= 2)
    print(f"  corroborated by 2+ sources: {confirmed:,}")

    os.makedirs(DATA, exist_ok=True); os.makedirs(WEB, exist_ok=True)
    path = os.path.join(DATA, "mosque_register.csv")
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    print(f"wrote {os.path.relpath(path)}")

    # per-district counts, split by how well corroborated
    by = collections.defaultdict(lambda: {"n": 0, "confirmed": 0})
    for r in rows:
        by[r["area_code"]]["n"] += 1
        if r["n_sources"] >= 2:
            by[r["area_code"]]["confirmed"] += 1
    path = os.path.join(DATA, "mosque_counts_ltla23.csv")
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["area_code", "mosques", "corroborated"])
        for code, o in sorted(by.items()):
            w.writerow([code, o["n"], o["confirmed"]])
    print(f"wrote {os.path.relpath(path)} ({len(by)} districts)")

    # map payload: coordinates plus a source count for styling
    path = os.path.join(WEB, "mosques.json")
    with open(path, "w") as fh:
        json.dump({"tier": "merged",
                   "sources": ["osm", "charity_register", "planning"],
                   "points": [[r["lon"], r["lat"], r["name"], r["n_sources"]] for r in rows]},
                  fh, separators=(",", ":"))
    print(f"wrote {os.path.relpath(path)} ({len(rows)} points)")


if __name__ == "__main__":
    main()
