"""Age structure by religion at local authority district, Census 2021.

Age is the primary explanatory variable in DESIGN.md, so it is worth taking
from the best available source rather than the obvious one. Nomis RM118 offers
9 age bands; the custom-dataset API offers 23 at the same coverage (317/318
districts), with an exact break at 15/16. Single-year age (resident_age_101a)
is rejected on row count at LAD, not on disclosure -- it would need per-area
batching, which is not worth it for a median.

So: under-16 share is exact, and median age is interpolated within the band
that contains it. Both are labelled as banded-derived in the output, because a
median from 23 bands is close but not the same thing as ONS's own median.

Usage:
    python3 ingest/fetch_age.py
"""

import collections
import csv
import os
import re

import ons_api

AREA_TYPE = "ltla23"
AGE_DIM = "resident_age_23a"
FAITH_DIM = "religion_tb"
PERIOD = 2021
OPEN_TOP = 100  # assumed upper bound for the "85 and over" band

OUT_DIR = os.path.join(os.path.dirname(__file__), os.pardir, "data")


def band_range(label: str):
    """'Aged 10 to 14 years' -> (10, 14). Returns None for non-age labels."""
    if m := re.match(r"Aged (\d+) to (\d+) years", label):
        return int(m.group(1)), int(m.group(2))
    if m := re.match(r"Aged (\d+) years? and over", label):
        return int(m.group(1)), OPEN_TOP
    if m := re.match(r"Aged (\d+) years? and under", label):
        return 0, int(m.group(1))
    if m := re.match(r"Aged (\d+) years?$", label):
        return int(m.group(1)), int(m.group(1))
    return None


def median_from_bands(bands):
    """Grouped median. bands: [((lo, hi), count)] in age order."""
    total = sum(c for _, c in bands)
    if not total:
        return None
    target = total / 2
    cum = 0
    for (lo, hi), count in bands:
        if cum + count >= target and count:
            return round(lo + (target - cum) / count * (hi - lo + 1), 1)
        cum += count
    return None


def main():
    obs, meta = ons_api.observations(AREA_TYPE, [FAITH_DIM, AGE_DIM])
    print(f"areas {meta['total_areas']} | blocked {meta['blocked_areas']} "
          f"| observations {meta['total_observations']}")
    records = ons_api.flatten(obs, AREA_TYPE)

    tab = collections.defaultdict(dict)
    names = {}
    for r in records:
        rng = band_range(r[AGE_DIM])
        if rng is None:
            continue  # "Does not apply"
        names[r["area_code"]] = r["area_name"]
        tab[(r["area_code"], r[FAITH_DIM])][rng] = r["count"]

    rows = []
    for (code, faith), by_band in sorted(tab.items()):
        bands = sorted(by_band.items())
        pop = sum(c for _, c in bands)
        under16 = sum(c for (lo, hi), c in bands if hi <= 15)
        rows.append(
            {
                "area_code": code,
                "area_name": names[code],
                "area_type": AREA_TYPE,
                "period": PERIOD,
                "faith_category": faith,
                "population": pop,
                "under_16": under16,
                "under_16_pct": round(under16 / pop * 100, 2) if pop >= 1000 else "",
                "median_age_banded": median_from_bands(bands) if pop >= 1000 else "",
                "suppressed": "" if pop >= 1000 else "n<1000",
            }
        )

    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"age_by_religion_{AREA_TYPE}.csv")
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {os.path.relpath(path)} ({len(rows)} rows)")

    # National figures, as a sanity check and because they are the panel baselines.
    nat = collections.defaultdict(lambda: collections.defaultdict(int))
    for (code, faith), by_band in tab.items():
        for rng, c in by_band.items():
            nat[faith][rng] += c
    print()
    for faith in ("Muslim", "Christian", "No religion"):
        bands = sorted(nat[faith].items())
        pop = sum(c for _, c in bands)
        u16 = sum(c for (lo, hi), c in bands if hi <= 15)
        print(f"{faith:<14} median {median_from_bands(bands):>5} "
              f"| under-16 {u16/pop*100:4.1f}% | n {pop:,}")


if __name__ == "__main__":
    main()
