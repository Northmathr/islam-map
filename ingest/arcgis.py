"""ONS Open Geography Portal (ArcGIS FeatureServer) helpers.

Every layer caps a single response at maxRecordCount (1000-2000 depending on
the service), so anything national has to be paged with resultOffset. The
server does not tell you it truncated -- it just returns fewer rows and
`exceededTransferLimit: true` -- so page until a short page comes back.
"""

import urllib.parse

from http_util import get_json

BASE = "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services"


def query(service: str, out_fields: str = "*", geometry: bool = False,
          page: int = 1000, out_sr: int = 4326):
    """Page through a FeatureServer layer. Returns a list of features."""
    params = {
        "where": "1=1",
        "outFields": out_fields,
        "returnGeometry": "true" if geometry else "false",
        "f": "json",
        "resultRecordCount": page,
    }
    if geometry:
        params["outSR"] = out_sr

    features, offset = [], 0
    while True:
        params["resultOffset"] = offset
        url = f"{BASE}/{service}/FeatureServer/0/query?" + urllib.parse.urlencode(params)
        data = get_json(url)
        if "error" in data:
            raise RuntimeError(f"{service}: {data['error']}")
        batch = data.get("features", [])
        features.extend(batch)
        if len(batch) < page:
            break
        offset += len(batch)
    return features
