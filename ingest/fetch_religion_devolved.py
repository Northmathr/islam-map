"""Religion for Scotland and Northern Ireland, to extend the map beyond E&W.

Nomis carries England and Wales only. Scotland and Northern Ireland run their
own censuses, on their own timetables, with their own categories -- so this is
three censuses stitched together, not one:

    England & Wales   ONS, March 2021,  religion voluntary
    Northern Ireland  NISRA, March 2021, religion voluntary
    Scotland          NRS, March 2022,   religion voluntary

The reference dates differ by a year for Scotland, which matters for any
UK-wide total and is stated in the payload rather than quietly ignored.

Northern Ireland's headline religion table does not break Muslims out at all --
its eight-category table stops at "Other religions", because the question there
is built around the Catholic/Protestant division. The six-category aggregate
(RELIGION_BELONG_TO_AGG6) does separate Muslim, so that is the one used.

Scotland publishes council-area tables by NAME rather than code, so names are
matched against the boundary file. Any council that fails to match is a hard
error: a silent drop would look exactly like a district with no Muslims.

Usage:
    python3 ingest/fetch_religion_devolved.py
"""

import csv
import io
import json
import os
import sys

from http_util import get

SCOTLAND = ("https://ukds-ckan.s3.eu-west-1.amazonaws.com/2022/NRS/UV205/"
            "census_2022_UV205_religion_Local_authority_CA2019.csv")
NI = ("https://build.nisra.gov.uk/en/custom/table.csv"
      "?d=PEOPLE&v=LGD14&v=RELIGION_BELONG_TO_AGG6")

ROOT = os.path.join(os.path.dirname(__file__), os.pardir)
OUT = os.path.join(ROOT, "data")
BOUNDARIES = os.path.join(ROOT, "web", "data", "lad_boundaries.json")

NOT_STATED = {"Religion not stated", "Not stated"}


def council_codes():
    """Scottish council name -> S12 code, from the boundary file."""
    with open(BOUNDARIES) as fh:
        gj = json.load(fh)
    return {f["properties"]["LAD24NM"]: f["properties"]["LAD24CD"]
            for f in gj["features"]
            if f["properties"]["LAD24CD"].startswith("S")}


def scotland():
    """NRS UV205. A SuperWEB2 export: preamble, then a four-column block."""
    text = get(SCOTLAND, timeout=120).decode("utf-8-sig", errors="replace")
    lines = text.splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith('"Counting","Council Area'))
    rows = list(csv.DictReader(io.StringIO("\n".join(lines[start:]))))

    codes = council_codes()
    by_area = {}
    for r in rows:
        area = (r.get("Council Area 2019") or "").strip()
        cat = (r.get("Religion") or "").strip()
        raw = (r.get("Count") or "").strip().replace(",", "")
        if not area or not cat or not raw:
            continue
        d = by_area.setdefault(area, {"pop": 0, "muslim": 0, "not_stated": 0})
        n = int(float(raw))
        if cat == "All people":
            d["pop"] = n
        elif cat == "Muslim":
            d["muslim"] = n
        elif cat in NOT_STATED:
            d["not_stated"] = n

    out, missing = [], []
    for area, d in by_area.items():
        code = codes.get(area)
        if not code:
            missing.append(area)
            continue
        out.append((code, area, d, 2022))
    if missing:
        raise SystemExit(f"unmatched Scottish council names: {missing}")
    return out


def northern_ireland():
    """NISRA flexible table builder. Already keyed on LGD14 codes."""
    text = get(NI, timeout=120).decode("utf-8-sig", errors="replace")
    rows = list(csv.DictReader(io.StringIO(text)))
    code_k = "Local Government District 2014 Code"
    name_k = "Local Government District 2014 Label"
    cat_k = next(f for f in rows[0] if f.startswith("Religion") and f.endswith("Label"))

    by_area = {}
    for r in rows:
        d = by_area.setdefault(r[code_k], {"name": r[name_k], "pop": 0,
                                           "muslim": 0, "not_stated": 0})
        n = int(r["Count"])
        d["pop"] += n                       # no "all people" row; sum the parts
        if r[cat_k] == "Muslim":
            d["muslim"] = n
        elif r[cat_k] in NOT_STATED:
            d["not_stated"] = n
    return [(code, d["name"], d, 2021) for code, d in by_area.items()]


def main():
    print("fetching Scotland (NRS UV205, council area) ...")
    scot = scotland()
    print(f"  {len(scot)} councils")
    print("fetching Northern Ireland (NISRA MS-B19 six-category, LGD14) ...")
    ni = northern_ireland()
    print(f"  {len(ni)} districts")

    rows = []
    for code, name, d, year in scot + ni:
        pop, muslim, na = d["pop"], d["muslim"], d["not_stated"]
        resp = pop - na
        rows.append({
            "area_code": code,
            "area_name": name,
            "census_year": year,
            "population": pop,
            "respondents": resp,
            "not_answered": na,
            "nonresponse_pct": round(na / pop * 100, 2) if pop else "",
            "count": muslim,
            "share_all_pct": round(muslim / pop * 100, 2) if pop else "",
            "share_resp_pct": round(muslim / resp * 100, 2) if resp else "",
            "per_10k_resp": round(muslim / resp * 10000) if resp else "",
            # Rates on tiny populations are noise, and the same rule is applied
            # to the E&W file, so keep the threshold identical.
            "rate_suppressed": "True" if pop < 1000 else "",
        })
    rows.sort(key=lambda r: r["area_code"])

    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "religion_devolved.csv")
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)

    s_pop = sum(r["population"] for r in rows if r["area_code"][0] == "S")
    s_mus = sum(r["count"] for r in rows if r["area_code"][0] == "S")
    n_pop = sum(r["population"] for r in rows if r["area_code"][0] == "N")
    n_mus = sum(r["count"] for r in rows if r["area_code"][0] == "N")
    print(f"\nwrote {os.path.relpath(path)} ({len(rows)} areas)")
    print(f"  Scotland         population {s_pop:>10,}   Muslim {s_mus:>8,}"
          f"  ({s_mus/s_pop*100:.2f}%)")
    print(f"  Northern Ireland population {n_pop:>10,}   Muslim {n_mus:>8,}"
          f"  ({n_mus/n_pop*100:.2f}%)")

    # Published checks. NRS gives Scotland 5,436,600 and NISRA gives Northern
    # Ireland 1,903,175; both are reconciliation targets, not decoration.
    for label, got, want in (("Scotland", s_pop, 5_436_600),
                             ("Northern Ireland", n_pop, 1_903_175)):
        drift = abs(got - want) / want
        flag = "ok" if drift < 0.005 else "DRIFT"
        print(f"  {label:<17} vs published {want:>10,}  {flag}")
        if drift >= 0.005:
            sys.exit(f"{label} population is {drift:.2%} off the published figure")


if __name__ == "__main__":
    main()
