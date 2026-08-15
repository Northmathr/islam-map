"""Sub-district population surface, for dot placement only.

DESIGN.md commits to dot density as a render mode because a district choropleth
shades land rather than people, and English districts vary enormously in size.
For the dots to mean anything they have to fall where people actually live, not
spread evenly across the polygon -- otherwise the render reproduces exactly the
area-is-not-population distortion it exists to fix.

So: LSOA population-weighted centroids, each carrying its LSOA's total resident
population, grouped by parent district. This is a *population* surface only. No
religion data below district level is fetched, stored, or shipped -- the dots
are placed by where people live and coloured by a district-level figure.

Usage:
    python3 ingest/fetch_geography.py
"""

import collections
import json
import os

import arcgis
import nomis

LOOKUP = "LSOA21_LAD23_EW_LU"          # LSOA 2021 -> LAD 2023
CENTROIDS = "LSOA_PopCentroids_EW_2021_V4"
TS001_POPULATION = "NM_2021_1"
LSOA_TYPE = "TYPE151"
COORD_DP = 3  # ~110 m; ample for placing a dot representing hundreds of people

OUT_DIR = os.path.join(os.path.dirname(__file__), os.pardir, "web", "data")


def lsoa_to_lad():
    feats = arcgis.query(LOOKUP, out_fields="LSOA21CD,LAD23CD")
    return {f["attributes"]["LSOA21CD"]: f["attributes"]["LAD23CD"] for f in feats}


def lsoa_centroids():
    feats = arcgis.query(CENTROIDS, out_fields="LSOA21CD", geometry=True, page=2000)
    out = {}
    for f in feats:
        g = f.get("geometry") or {}
        if "x" in g and "y" in g:
            out[f["attributes"]["LSOA21CD"]] = (
                round(g["x"], COORD_DP), round(g["y"], COORD_DP)
            )
    return out


def lsoa_population():
    rows = nomis.table(
        TS001_POPULATION, LSOA_TYPE,
        ["geography_code", "c2021_restype_3_name", "obs_value"],
        c2021_restype_3=0,  # total residents, not the household/communal split
    )
    return {r["GEOGRAPHY_CODE"]: int(r["OBS_VALUE"]) for r in rows}


def main():
    print("fetching LSOA -> LAD lookup ...")
    parent = lsoa_to_lad()
    print(f"  {len(parent):,} LSOAs")

    print("fetching LSOA population-weighted centroids ...")
    coords = lsoa_centroids()
    print(f"  {len(coords):,} centroids")

    print("fetching LSOA population ...")
    pop = lsoa_population()
    print(f"  {len(pop):,} populations")

    by_lad = collections.defaultdict(lambda: {"x": [], "y": [], "p": []})
    dropped = 0
    for lsoa, lad in parent.items():
        if lsoa not in coords or lsoa not in pop:
            dropped += 1
            continue
        x, y = coords[lsoa]
        by_lad[lad]["x"].append(x)
        by_lad[lad]["y"].append(y)
        by_lad[lad]["p"].append(pop[lsoa])

    total_pop = sum(sum(v["p"]) for v in by_lad.values())
    print(f"\n{len(by_lad)} districts | {sum(len(v['p']) for v in by_lad.values()):,} "
          f"points | {dropped} LSOAs dropped for missing coord/population")
    print(f"population on the surface: {total_pop:,}")

    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, "lsoa_points.json")
    with open(path, "w") as fh:
        json.dump(by_lad, fh, separators=(",", ":"))
    size = os.path.getsize(path) / 1e6
    print(f"wrote {os.path.relpath(path)} ({size:.1f} MB)")


if __name__ == "__main__":
    main()
