"""Religion x country of birth at local authority district, Census 2021 (E&W).

Resolves the Phase 1 gap recorded in DESIGN.md: the 2021 census publishes no
standard RM table crossing religion by country of birth (2011 had DC2207EW).
The custom-dataset API does serve it, and at LAD the disclosure controls allow
the 8-category world-region breakdown, not just the UK/non-UK binary.

Granularity was established empirically -- blocked districts out of 318:

    country_of_birth_3a  (UK / non-UK)       1 blocked
    country_of_birth_8a  (world regions)     1 blocked   <- used here
    country_of_birth_13a                   169 blocked
    country_of_birth_60a                   258 blocked

The single blocked district in both viable variants is the Isles of Scilly,
which DESIGN.md already suppresses on population grounds.

Usage:
    python3 ingest/fetch_religion_cob.py
"""

import collections
import csv
import os
import sys

import nomis
import ons_api

AREA_TYPE = "ltla23"
COB_DIM = "country_of_birth_8a"
FAITH_DIM = "religion_tb"
UK_BORN = "Europe: United Kingdom"
PERIOD = 2021

OUT_DIR = os.path.join(os.path.dirname(__file__), os.pardir, "data")


def nomis_muslim_total() -> int:
    """Muslim total for E&W from TS030, for the reconciliation check."""
    rows = nomis.table(
        nomis.TS030_RELIGION,
        nomis.LAD_2023,
        ["geography_code", "c2021_religion_10_name", "obs_value"],
    )
    return sum(
        int(r["OBS_VALUE"]) for r in rows if r["C2021_RELIGION_10_NAME"] == "Muslim"
    )


def main():
    obs, meta = ons_api.observations(AREA_TYPE, [FAITH_DIM, COB_DIM])
    print(f"areas {meta['total_areas']} | blocked {meta['blocked_areas']} "
          f"| observations {meta['total_observations']}")
    records = ons_api.flatten(obs, AREA_TYPE)

    tab = collections.defaultdict(lambda: collections.defaultdict(int))
    names = {}
    for r in records:
        tab[(r["area_code"], r[FAITH_DIM])][r[COB_DIM]] += r["count"]
        names[r["area_code"]] = r["area_name"]

    tidy, shares = [], []
    for (code, faith), by_cob in sorted(tab.items()):
        total = sum(by_cob.values())
        uk = by_cob.get(UK_BORN, 0)
        for cob, n in sorted(by_cob.items()):
            tidy.append(
                {
                    "area_code": code, "area_name": names[code],
                    "area_type": AREA_TYPE, "period": PERIOD,
                    "faith_category": faith, "country_of_birth": cob, "count": n,
                }
            )
        shares.append(
            {
                "area_code": code, "area_name": names[code],
                "area_type": AREA_TYPE, "period": PERIOD,
                "faith_category": faith,
                "population": total,
                "uk_born": uk,
                # small denominators make the share noise; flag rather than drop
                "uk_born_pct": round(uk / total * 100, 2) if total >= 1000 else "",
                "suppressed": "" if total >= 1000 else "n<1000",
            }
        )

    os.makedirs(OUT_DIR, exist_ok=True)
    for name, rows in (
        (f"religion_cob_{AREA_TYPE}.csv", tidy),
        (f"uk_born_share_{AREA_TYPE}.csv", shares),
    ):
        path = os.path.join(OUT_DIR, name)
        with open(path, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(f"wrote {os.path.relpath(path)} ({len(rows)} rows)")

    # Reconcile against TS030. Disclosure control perturbs cells, so this is a
    # tolerance check, not equality -- observed drift is single digits.
    muslim = sum(r["population"] for r in shares if r["faith_category"] == "Muslim")
    published = nomis_muslim_total()
    drift = abs(muslim - published)
    print(f"\nreconciliation: cross-tab Muslim {muslim:,} vs TS030 {published:,} "
          f"(drift {drift})")
    if drift > 500:
        sys.exit(f"FAIL: drift {drift} exceeds tolerance - check area coverage")

    uk = sum(r["uk_born"] for r in shares if r["faith_category"] == "Muslim")
    print(f"UK-born share of Muslim population, E&W: {uk / muslim * 100:.1f}%")


if __name__ == "__main__":
    main()
