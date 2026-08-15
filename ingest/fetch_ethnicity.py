"""Ethnic composition within each faith group, by district, Census 2021.

Answers "which communities make up this area's Muslim population" -- a question
the headline share cannot, and one where the national picture and the local
picture differ sharply (Bradford and Newham have similar Muslim shares and very
different compositions).

Uses the custom-dataset API rather than Nomis RM031 so the granularity can be
checked against disclosure control the same way as the other cross-tabs.

Usage:
    python3 ingest/fetch_ethnicity.py
"""

import collections
import csv
import os

import ons_api

AREA_TYPE = "ltla23"
ETH_DIM = "ethnic_group_tb_20b"
FAITH_DIM = "religion_tb"
PERIOD = 2021
FOCUS = "Muslim"

OUT_DIR = os.path.join(os.path.dirname(__file__), os.pardir, "data")


def main():
    obs, meta = ons_api.observations(AREA_TYPE, [FAITH_DIM, ETH_DIM])
    print(f"areas {meta['total_areas']} | blocked {meta['blocked_areas']} "
          f"| observations {meta['total_observations']}")
    records = ons_api.flatten(obs, AREA_TYPE)

    tab = collections.defaultdict(lambda: collections.defaultdict(int))
    names = {}
    for r in records:
        if r[ETH_DIM] == "Does not apply":
            continue
        tab[(r["area_code"], r[FAITH_DIM])][r[ETH_DIM]] += r["count"]
        names[r["area_code"]] = r["area_name"]

    rows = []
    for (code, faith), by_eth in sorted(tab.items()):
        total = sum(by_eth.values())
        for eth, n in sorted(by_eth.items(), key=lambda kv: -kv[1]):
            rows.append(
                {
                    "area_code": code, "area_name": names[code],
                    "area_type": AREA_TYPE, "period": PERIOD,
                    "faith_category": faith, "ethnic_group": eth, "count": n,
                    "pct_of_faith": round(n / total * 100, 2) if total >= 1000 else "",
                }
            )

    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, f"ethnicity_by_religion_{AREA_TYPE}.csv")
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {os.path.relpath(path)} ({len(rows)} rows)")

    nat = collections.defaultdict(int)
    for (code, faith), by_eth in tab.items():
        if faith != FOCUS:
            continue
        for eth, n in by_eth.items():
            nat[eth] += n
    total = sum(nat.values())
    print(f"\n{FOCUS} population of E&W by ethnic group:")
    for eth, n in sorted(nat.items(), key=lambda kv: -kv[1])[:6]:
        print(f"  {eth:<46} {n:>9,}  {n/total*100:5.1f}%")


if __name__ == "__main__":
    main()
