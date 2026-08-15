"""ONS custom-dataset API (Census 2021).

Serves cross-tabs the standard Nomis tables don't publish. Two distinct limits
apply and they fail differently:

  * disclosure control blocks individual areas -- the response still returns
    200 with a `blocked_areas` count, so a query can silently lose most of the
    country. Always check `meta['blocked_areas']`.
  * a row-count ceiling rejects the whole query with an `errors` payload.
    resident_age_101a x religion at LAD hits this; the 23-category age
    variant does not.

Coarse categorisations of a variable are NOT returned by /dimensions?q= --
only the most detailed ones are. Use categorisations() to find the usable
variants, or the API looks far more restrictive than it is.
"""

BASE = "https://api.beta.ons.gov.uk/v1"
POP_TYPE = "UR"  # all usual residents
PAGE = 2000

from http_util import get_json


class BlockedQuery(RuntimeError):
    """The API rejected the query outright (usually the row-count ceiling)."""


def categorisations(dimension: str):
    """Available categorisations of a dimension, coarsest usable first."""
    url = f"{BASE}/population-types/{POP_TYPE}/dimensions/{dimension}/categorisations?limit=100"
    return get_json(url).get("items", [])


def observations(area_type: str, dimensions: list[str]):
    """Page through a cross-tab. Returns (observations, meta)."""
    dims = ",".join(dimensions)
    url = (
        f"{BASE}/population-types/{POP_TYPE}/census-observations"
        f"?area-type={area_type}&dimensions={dims}"
    )
    rows, offset, meta = [], 0, None
    while True:
        page = get_json(f"{url}&limit={PAGE}&offset={offset}")
        if "errors" in page:
            raise BlockedQuery("; ".join(page["errors"]))
        if meta is None:
            meta = {
                "total_areas": page.get("total_areas"),
                "blocked_areas": page.get("blocked_areas") or 0,
                "total_observations": page.get("total_observations"),
            }
        obs = page.get("observations", [])
        rows.extend(obs)
        offset += len(obs)
        if not obs or offset >= meta["total_observations"]:
            break
    return rows, meta


def flatten(observations_, area_type: str):
    """API observations -> flat dicts keyed by dimension id."""
    out = []
    for o in observations_:
        dims = {d["dimension_id"]: d for d in o["dimensions"]}
        rec = {
            "area_code": dims[area_type]["option_id"],
            "area_name": dims[area_type]["option"],
            "count": o["observation"],
        }
        for did, d in dims.items():
            if did != area_type:
                rec[did] = d["option"]
        out.append(rec)
    return out
