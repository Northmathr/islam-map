"""Local government reorganisation: abolished district codes -> successor.

Lifted from mer2-scatter-map/ingest/fetch_support_data.py (LGR_SUCCESSORS),
which built and checked this map against Home Office quarterly data. Kept as
its own module here because two ingest paths need it.

Why it is needed: Nomis serves the 2021 religion table on April-2023
boundaries but the 2011 table only on pre-2015 boundaries, so the 2011->2021
change series has to be reconciled. Every change in this window is a merge of
districts into a unitary, or a straight recode -- no splits -- so reconciling
is a sum over the successor, with no apportionment and no estimation.

The Scottish recodes are inert for this project (the 2011/2021 tables here are
England & Wales; Scotland comes from NRS separately) but are retained so the
map stays identical to the sibling project's.
"""

SUCCESSORS = {
    # Buckinghamshire (2020)
    "E07000004": "E06000060", "E07000005": "E06000060",
    "E07000006": "E06000060", "E07000007": "E06000060",
    # Dorset / BCP (2019)
    "E07000049": "E06000059", "E07000050": "E06000059", "E07000051": "E06000059",
    "E07000052": "E06000059", "E07000053": "E06000059",
    "E06000028": "E06000058", "E06000029": "E06000058", "E07000048": "E06000058",
    # Suffolk (2019)
    "E07000201": "E07000245", "E07000204": "E07000245",
    "E07000205": "E07000244", "E07000206": "E07000244",
    # Somerset (2019 interim + 2023 unitary)
    "E07000190": "E06000066", "E07000191": "E06000066", "E07000246": "E06000066",
    "E07000187": "E06000066", "E07000188": "E06000066", "E07000189": "E06000066",
    # North Yorkshire (2023)
    "E07000163": "E06000065", "E07000164": "E06000065", "E07000165": "E06000065",
    "E07000166": "E06000065", "E07000167": "E06000065", "E07000168": "E06000065",
    "E07000169": "E06000065",
    # Cumbria (2023)
    "E07000026": "E06000063", "E07000028": "E06000063", "E07000029": "E06000063",
    "E07000027": "E06000064", "E07000030": "E06000064", "E07000031": "E06000064",
    # Northamptonshire (2021)
    "E07000150": "E06000061", "E07000152": "E06000061", "E07000153": "E06000061",
    "E07000156": "E06000061",
    "E07000151": "E06000062", "E07000154": "E06000062", "E07000155": "E06000062",
    # Straight ONS recodings (same geography, new code)
    "S12000046": "S12000049",  # Glasgow City
    "S12000044": "S12000050",  # North Lanarkshire
    "S12000015": "S12000047",  # Fife
    "S12000024": "S12000048",  # Perth and Kinross
    "E08000038": "E08000016",  # Barnsley
    "E08000039": "E08000019",  # Sheffield
}


def resolve(code: str) -> str:
    """Map an abolished district code onto its current successor."""
    return SUCCESSORS.get(code, code)
