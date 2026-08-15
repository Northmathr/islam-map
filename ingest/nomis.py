"""Nomis bulk-table helpers.

Nomis serves the standard census tables (TS*/KS*/RM*). Geography vintage is
per-table and is not negotiable: the 2021 tables offer TYPE424 (April 2023
district/unitary, 318 areas) while the 2011 tables stop at TYPE464 (pre-April
2015). That mismatch is why the change series needs `lgr.py`.

District names differ between Nomis and the ONS custom API for the same GSS
codes -- Nomis writes "Bristol, City of" where the API writes "Bristol". Join
on code, never on name.
"""

import csv

from http_util import get

BASE = "https://www.nomisweb.co.uk/api/v01/dataset"

# 2021 census tables, verified against the live API.
TS030_RELIGION = "NM_2049_1"       # Religion, 2021
KS209EW_RELIGION_2011 = "NM_616_1"  # Religion, 2011
RM031_ETHNICITY = "NM_2131_1"      # Ethnic group by religion, 2021

LAD_2023 = "TYPE424"  # district / unitary as of April 2023 -- 318 areas (E&W)
LAD_PRE2015 = "TYPE464"  # district / unitary prior to April 2015


# Nomis silently truncates a response at 25,000 rows -- no error, no flag. Any
# LSOA-level query exceeds this (35,672 areas), so every fetch is paged.
PAGE = 25_000


def table(dataset: str, geography: str, select: list[str], **params) -> list[dict]:
    """Fetch a Nomis table as a list of dicts, paging until exhausted."""
    qs = [f"geography={geography}", "measures=20100", f"select={','.join(select)}"]
    qs += [f"{k}={v}" for k, v in params.items()]
    base = f"{BASE}/{dataset}.data.csv?" + "&".join(qs)

    rows, offset = [], 0
    while True:
        text = get(f"{base}&RecordLimit={PAGE}&RecordOffset={offset}").decode("utf-8")
        batch = list(csv.DictReader(text.splitlines()))
        rows.extend(batch)
        if len(batch) < PAGE:
            break
        offset += len(batch)
    return rows
