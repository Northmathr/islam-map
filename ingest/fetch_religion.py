"""Religion at local authority district, 2011 and 2021 -- the map's core feed.

Produces both denominator bases for every share. Per DESIGN.md the respondent
basis (excluding "not answered") drives the map scale, and the all-residents
basis is carried alongside because it is the one that reconciles with every
published ONS figure. The two diverge most in the highest-share districts, so
neither is ever shown without the other.

The 2011 table is only published on pre-2015 boundaries, so it is summed onto
2023 successors via lgr.py before the change series is computed.

Usage:
    python3 ingest/fetch_religion.py
"""

import collections
import csv
import os
import sys

import lgr
import nomis

PERIOD_NOW, PERIOD_PREV = 2021, 2011

# Districts too small for a meaningful rate; counts still published. See DESIGN.md.
RATE_SUPPRESSED = {
    "E06000053": "Isles of Scilly",
    "E09000001": "City of London",
}

# 2011 KS209EW cell labels -> 2021 TS030 category labels.
CELL_2011 = {
    "Christian": "Christian",
    "Buddhist": "Buddhist",
    "Hindu": "Hindu",
    "Jewish": "Jewish",
    "Muslim": "Muslim",
    "Sikh": "Sikh",
    "Other religion": "Other religion",
    "No religion": "No religion",
    "Religion not stated": "Not answered",
}
TOTAL = "Total: All usual residents"
NOT_ANSWERED = "Not answered"

OUT_DIR = os.path.join(os.path.dirname(__file__), os.pardir, "data")


def fetch_2021():
    rows = nomis.table(
        nomis.TS030_RELIGION,
        nomis.LAD_2023,
        ["geography_name", "geography_code", "c2021_religion_10_name", "obs_value"],
    )
    by_area = collections.defaultdict(dict)
    names = {}
    for r in rows:
        code = r["GEOGRAPHY_CODE"]
        names[code] = r["GEOGRAPHY_NAME"]
        by_area[code][r["C2021_RELIGION_10_NAME"]] = int(r["OBS_VALUE"])
    return by_area, names


def fetch_2011():
    """2011 religion, summed onto 2023 boundaries."""
    rows = nomis.table(
        nomis.KS209EW_RELIGION_2011,
        nomis.LAD_PRE2015,
        ["geography_name", "geography_code", "cell_name", "obs_value"],
        rural_urban=0,
    )
    by_area = collections.defaultdict(lambda: collections.defaultdict(int))
    merged = set()
    for r in rows:
        label = r["CELL_NAME"]
        if label == "All categories: Religion":
            key = TOTAL
        elif label in CELL_2011:
            key = CELL_2011[label]
        else:
            continue  # "Has religion" is a derived subtotal; skip to avoid double count
        old = r["GEOGRAPHY_CODE"]
        new = lgr.resolve(old)
        if new != old:
            merged.add(old)
        by_area[new][key] += int(r["OBS_VALUE"])
    return by_area, merged


def summarise(a21, names, a11, faith="Muslim"):
    rows = []
    for code in sorted(a21):
        cur, prev = a21[code], a11.get(code, {})
        pop = cur.get(TOTAL, 0)
        na = cur.get(NOT_ANSWERED, 0)
        resp = pop - na
        n = cur.get(faith, 0)

        pop11 = prev.get(TOTAL, 0)
        na11 = prev.get(NOT_ANSWERED, 0)
        resp11 = pop11 - na11
        n11 = prev.get(faith, 0)

        pct = lambda num, den: round(num / den * 100, 3) if den else ""
        share_resp = pct(n, resp)
        share_resp11 = pct(n11, resp11)

        rows.append(
            {
                "area_code": code,
                "area_name": names[code],
                "faith_category": faith,
                "population": pop,
                "not_answered": na,
                "respondents": resp,
                "nonresponse_pct": pct(na, pop),
                "count": n,
                "share_all_pct": pct(n, pop),
                "share_resp_pct": share_resp,
                "per_10k_resp": round(n / resp * 1e4, 1) if resp else "",
                "population_2011": pop11 or "",
                "count_2011": n11 or "",
                "share_resp_2011_pct": share_resp11,
                "change_pp": round(share_resp - share_resp11, 3)
                if share_resp != "" and share_resp11 != ""
                else "",
                "change_rel_pct": round((n / n11 - 1) * 100, 1) if n11 else "",
                "rate_suppressed": "small population" if code in RATE_SUPPRESSED else "",
            }
        )
    return rows


def write(path, rows):
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {os.path.relpath(path)} ({len(rows)} rows)")


def main():
    a21, names = fetch_2021()
    a11, merged = fetch_2011()
    print(f"2021: {len(a21)} districts | 2011: {len(a11)} districts after LGR merge "
          f"({len(merged)} abolished codes mapped)")

    missing = sorted(set(a21) - set(a11))
    if missing:
        print(f"WARNING: no 2011 match for {len(missing)}: {missing[:6]}")

    os.makedirs(OUT_DIR, exist_ok=True)

    # Long format, all faith categories -- schema stays faith-agnostic.
    long_rows = [
        {
            "area_code": code,
            "area_name": names[code],
            "area_type": nomis.LAD_2023,
            "period": PERIOD_NOW,
            "faith_category": faith,
            "count": n,
        }
        for code in sorted(a21)
        for faith, n in sorted(a21[code].items())
    ]
    write(os.path.join(OUT_DIR, "religion_ltla23_long.csv"), long_rows)

    summary = summarise(a21, names, a11)
    write(os.path.join(OUT_DIR, "religion_ltla23.csv"), summary)

    # Reconciliation: national totals on both bases, against published ONS figures.
    pop = sum(r["population"] for r in summary)
    mus = sum(r["count"] for r in summary)
    na = sum(r["not_answered"] for r in summary)
    mus11 = sum(r["count_2011"] or 0 for r in summary)
    pop11 = sum(r["population_2011"] or 0 for r in summary)
    print(f"\n{PERIOD_NOW}: population {pop:,} | Muslim {mus:,} "
          f"| all-residents {mus/pop*100:.2f}% | respondent {mus/(pop-na)*100:.2f}%")
    print(f"{PERIOD_PREV}: population {pop11:,} | Muslim {mus11:,} "
          f"| all-residents {mus11/pop11*100:.2f}%")
    print(f"change: {mus - mus11:+,} ({(mus/mus11-1)*100:+.1f}%)")

    if abs(pop - 59_597_540) > 500:
        sys.exit(f"FAIL: 2021 population {pop:,} off published 59,597,540")
    if abs(pop11 - 56_075_912) > 5000:
        print(f"NOTE: 2011 population {pop11:,} vs published E&W 56,075,912 "
              f"(diff {pop11 - 56_075_912:+,}) -- check LGR coverage")


if __name__ == "__main__":
    main()
