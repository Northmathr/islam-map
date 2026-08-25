"""Merge the ingested CSVs into the single JSON the map front-end reads.

Run after the fetch_* scripts. Keys are short because this file ships to the
browser; the mapping is documented below and mirrored in web/app.js.

Every district carries both share bases. Per DESIGN.md the respondent basis
drives the map scale and the all-residents basis is what the panel leads with,
so both have to be present in the payload -- the front-end is not allowed to
derive one from the other and quietly show a single number.

Usage:
    python3 ingest/build_web_data.py
"""

import collections
import csv
import json
import os

ROOT = os.path.join(os.path.dirname(__file__), os.pardir)
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(ROOT, "web", "data")

FOCUS = "Muslim"
COMPARISON = ["Christian", "No religion", "Hindu", "Sikh", "Jewish", "Buddhist"]


def read(name):
    with open(os.path.join(DATA, name)) as fh:
        return list(csv.DictReader(fh))


def num(v, cast=float):
    return cast(v) if v not in ("", None) else None


def main():
    religion = read("religion_ltla23.csv")
    # Scotland (NRS 2022) and Northern Ireland (NISRA 2021) come from their own
    # censuses and carry no 2011 comparison here, so they are merged in as a
    # second block rather than pretending to be rows of the E&W table.
    devolved = read("religion_devolved.csv")
    long_rows = read("religion_ltla23_long.csv")
    age = read("age_by_religion_ltla23.csv")
    cob = read("uk_born_share_ltla23.csv")
    eth = read("ethnicity_by_religion_ltla23.csv")
    prov = {r["area_code"]: r for r in read("provision_ltla23.csv")}
    # merged three-source register supersedes the OSM-only count
    mreg = {r["area_code"]: r for r in read("mosque_counts_ltla23.csv")}

    age_idx = {(r["area_code"], r["faith_category"]): r for r in age}
    cob_idx = {(r["area_code"], r["faith_category"]): r for r in cob}

    faiths = collections.defaultdict(dict)
    for r in long_rows:
        faiths[r["area_code"]][r["faith_category"]] = int(r["count"])

    eth_idx = collections.defaultdict(list)
    for r in eth:
        if r["faith_category"] == FOCUS and r["pct_of_faith"]:
            eth_idx[r["area_code"]].append(
                [r["ethnic_group"], float(r["pct_of_faith"])]
            )

    districts = {}
    for r in religion:
        code = r["area_code"]
        a = age_idx.get((code, FOCUS), {})
        c = cob_idx.get((code, FOCUS), {})
        p = prov.get(code, {})
        mr = mreg.get(code, {})
        n_mq = int(mr.get("mosques", 0) or 0)
        n_conf = int(mr.get("corroborated", 0) or 0)
        n_ch = int(p.get("n_christian", 0) or 0)
        muslims = int(r["count"])
        districts[code] = {
            "n": r["area_name"],
            "pop": int(r["population"]),
            "resp": int(r["respondents"]),
            "na": int(r["not_answered"]),
            "nrp": num(r["nonresponse_pct"]),
            # focus faith
            "c": int(r["count"]),
            "sa": num(r["share_all_pct"]),        # share, all residents
            "sr": num(r["share_resp_pct"]),       # share, respondents
            "k": num(r["per_10k_resp"]),
            "c11": num(r["count_2011"], int),
            "p11": num(r["population_2011"], int),
            "sr11": num(r["share_resp_2011_pct"]),
            "dpp": num(r["change_pp"]),
            "drel": num(r["change_rel_pct"]),
            "med": num(a.get("median_age_banded", "")),
            "u16": num(a.get("under_16_pct", "")),
            "ukb": num(c.get("uk_born_pct", "")),
            "eth": sorted(eth_idx.get(code, []), key=lambda x: -x[1])[:6],
            "sup": r["rate_suppressed"],
            "f": faiths.get(code, {}),
            # provision. Counts are an OSM floor, not a register census, so the
            # ratio is suppressed on tiny denominators rather than shown precise.
            "mq": n_mq,
            "mqc": n_conf,
            "mqch": n_ch,
            "ratio": round(muslims / n_mq) if n_mq else None,
            "mq100": round(n_mq / muslims * 1e5, 1) if muslims >= 1000 else None,
            "chratio": round(int(faiths.get(code, {}).get("Christian", 0)) / n_ch)
                       if n_ch else None,
        }

    for r in devolved:
        code = r["area_code"]
        mr = mreg.get(code, {})
        n_mq = int(mr.get("mosques", 0) or 0)
        muslims = int(r["count"])
        districts[code] = {
            "n": r["area_name"],
            "pop": int(r["population"]),
            "resp": int(r["respondents"]),
            "na": int(r["not_answered"]),
            "nrp": num(r["nonresponse_pct"]),
            "c": muslims,
            "sa": num(r["share_all_pct"]),
            "sr": num(r["share_resp_pct"]),
            "k": num(r["per_10k_resp"]),
            # no 2011 comparison: a different census on a different timetable
            "c11": None, "p11": None, "sr11": None, "dpp": None, "drel": None,
            "med": None, "u16": None, "ukb": None, "eth": [],
            "sup": r["rate_suppressed"],
            "f": {},
            "yr": int(r["census_year"]),   # 2022 for Scotland, 2021 for NI
            "mq": n_mq,
            "mqc": int(mr.get("corroborated", 0) or 0),
            "mqch": 0,
            "ratio": round(muslims / n_mq) if n_mq else None,
            "mq100": round(n_mq / muslims * 1e5, 1) if muslims >= 1000 else None,
            "chratio": None,
        }

    # National baselines. A rate is uninterpretable without one, so the panel
    # shows these beside every district figure.
    ew = [d for code, d in districts.items() if code[0] in ("E", "W")]
    tot_pop = sum(d["pop"] for d in ew)
    tot_na = sum(d["na"] for d in ew)
    tot_focus = sum(d["c"] for d in ew)
    tot_focus11 = sum(d["c11"] or 0 for d in ew)
    tot_pop11 = sum(d["p11"] or 0 for d in ew)

    def national(faith):
        a = [r for r in age if r["area_code"] and r["faith_category"] == faith]
        c = [r for r in cob if r["faith_category"] == faith]
        pop = sum(int(r["population"]) for r in a)
        u16 = sum(int(r["under_16"]) for r in a)
        ukb = sum(int(r["uk_born"]) for r in c)
        cpop = sum(int(r["population"]) for r in c)
        return {
            "pop": pop,
            "u16": round(u16 / pop * 100, 1) if pop else None,
            "ukb": round(ukb / cpop * 100, 1) if cpop else None,
        }

    baselines = {
        "pop": tot_pop,
        "resp": tot_pop - tot_na,
        "nrp": round(tot_na / tot_pop * 100, 2),
        "sa": round(tot_focus / tot_pop * 100, 2),
        "sr": round(tot_focus / (tot_pop - tot_na) * 100, 2),
        "c": tot_focus,
        "c11": tot_focus11,
        "pop11": tot_pop11,
        "drel": round((tot_focus / tot_focus11 - 1) * 100, 1),
        "faiths": {f: national(f) for f in [FOCUS] + COMPARISON},
    }
    # Mosque totals are UK-wide because the register now is; the church ratio
    # stays on E&W, where the census religion breakdown behind it exists.
    tot_mq = sum(d["mq"] for d in districts.values())
    tot_conf = sum(d["mqc"] for d in districts.values())
    tot_ch = sum(d["mqch"] for d in ew)
    tot_christian = sum(int(d["f"].get("Christian", 0)) for d in ew)
    uk_pop = sum(d["pop"] for d in districts.values())
    uk_focus = sum(d["c"] for d in districts.values())
    baselines["uk"] = {"pop": uk_pop, "c": uk_focus,
                       "sa": round(uk_focus / uk_pop * 100, 2)}
    baselines["prov"] = {
        "mq": tot_mq,
        "mqc": tot_conf,
        "ratio": round(uk_focus / tot_mq) if tot_mq else None,
        "ch": tot_ch,
        "chratio": round(tot_christian / tot_ch) if tot_ch else None,
        "tier": "merged",
    }
    # Median age is banded-derived; recompute nationally from the district file
    # would double-count, so take it from the focus faith's national age run.
    baselines["faiths"][FOCUS]["med"] = 27.8

    payload = {
        "meta": {
            "focus": FOCUS,
            "period": 2021,
            "period_prev": 2011,
            "area_type": "ltla23",
            "geography": "Local authority district (April 2023), England & Wales",
            "source": "ONS Census 2021 TS030 / KS209EW 2011 / custom-dataset API",
            "note": (
                "Religion is the census's only voluntary question. Shares are "
                "shown on both bases: all residents, and respondents only."
            ),
        },
        "baselines": baselines,
        "districts": districts,
    }

    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "districts.json")
    with open(path, "w") as fh:
        json.dump(payload, fh, separators=(",", ":"))
    print(f"wrote {os.path.relpath(path)} "
          f"({len(districts)} districts, {os.path.getsize(path)/1e6:.2f} MB)")
    print(f"national: {FOCUS} {tot_focus:,} | all-residents {baselines['sa']}% "
          f"| respondents {baselines['sr']}%")


if __name__ == "__main__":
    main()
