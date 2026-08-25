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


def year(text):
    """Leading four-digit year from a date string, or None."""
    head = (text or "")[:4]
    return int(head) if head.isdigit() else None


def load_sources():
    """Each point carries a first-recorded year where its source has one.

    OpenStreetMap has no dates at all. A charity registration is not an opening
    date -- congregations often register years after they start meeting -- and a
    planning approval is a decision rather than a finished building. Both are
    nonetheless real documentary evidence that a mosque existed by then, which
    is the most that can honestly be said, and it is what the year slider moves.
    """
    pts = []
    for r in read("places_of_worship.csv"):
        if r["faith"] == "Muslim":
            pts.append((float(r["lon"]), float(r["lat"]), "osm", r["name"], "", None))
    for r in read("mosque_charities.csv"):
        pts.append((float(r["lon"]), float(r["lat"]), "charity_register",
                    r["name"], r["charity_no"], year(r.get("registered"))))
    for r in read("planning_applications.csv"):
        if r["status"] == "approved" and r["kind"] in ("new_build", "use_to"):
            pts.append((float(r["lon"]), float(r["lat"]), "planning",
                        r["address"][:80], r["ref"], year(r.get("date"))))
    return pts


def cluster(points, metres=MERGE_M):
    """Grid-hashed proximity merge, so this stays linear rather than quadratic."""
    dlat = metres / 111000
    grid, out = {}, []
    for lon, lat, src, name, ref, yr in points:
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
                        "names": [name] if name else [],
                        "refs": [ref] if ref else [], "since": yr})
        else:
            c = out[found]
            c["sources"].add(src)
            # earliest evidence wins: the question is when this location is
            # first known to have been a mosque, not when we last heard of it
            if yr and (c["since"] is None or yr < c["since"]):
                c["since"] = yr
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
    per_source = collections.Counter(p[2] for p in pts)
    print("input locations:")
    for k, v in per_source.most_common():
        print(f"  {k:<18}{v:>6,}")

    merged = cluster(pts)
    print(f"\nmerged at {MERGE_M} m: {len(merged):,} distinct locations")

    combos = collections.Counter("+".join(sorted(c["sources"])) for c in merged)
    for k, v in combos.most_common():
        print(f"  {k:<34}{v:>5}")

    d = geo.Districts()
    rows, outside = [], 0
    for c in merged:
        code, name = d.assign(c["lon"], c["lat"])
        if not code:
            outside += 1
            continue
        # Kept UK-wide. Scotland and Northern Ireland have their own censuses
        # (NRS 2022, NISRA 2021), ingested by fetch_religion_devolved.py, so a
        # mosque there now has population to sit against. Northern Ireland has
        # no open charity register, so its locations rest on OSM and planning
        # alone -- recorded in the register's own source column rather than
        # asserted as equivalent coverage.
        rows.append({
            "area_code": code, "area_name": name,
            "name": (c["names"][0] if c["names"] else ""),
            "lon": round(c["lon"], 5), "lat": round(c["lat"], 5),
            "sources": "+".join(sorted(c["sources"])),
            "n_sources": len(c["sources"]),
            "since": c["since"] or "",
            "refs": ";".join(c["refs"][:4]),
        })
    nations = collections.Counter(r["area_code"][0] for r in rows)
    print(f"\nplaced in UK districts: {len(rows):,} "
          f"({outside} outside any district)")
    for k, label in (("E", "England"), ("W", "Wales"),
                     ("S", "Scotland"), ("N", "Northern Ireland")):
        print(f"  {label:<18}{nations.get(k, 0):>5}")
    dated = sum(1 for r in rows if r["since"])
    print(f"  with a dated record: {dated:,} of {len(rows):,}")

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
                   # lon, lat, name, source count, first recorded year (0 = none)
                   "points": [[r["lon"], r["lat"], r["name"], r["n_sources"],
                               r["since"] or 0] for r in rows]},
                  fh, separators=(",", ":"))
    print(f"wrote {os.path.relpath(path)} ({len(rows)} points)")


if __name__ == "__main__":
    main()
