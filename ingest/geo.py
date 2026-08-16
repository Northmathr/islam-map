"""Assign points to local authority districts by point-in-polygon.

Phases 2 and 3 both arrive as points (mosque locations, planning applications)
that have to land in a district. Joining on the name the source supplies is not
safe -- PlanIt's `area_name` is the planning authority, which is not always the
district, and names disagree between sources anyway (see nomis.py). Coordinates
are unambiguous, so every point is placed geometrically.

Ray casting with a bounding-box prefilter. 318 districts against a few thousand
points is well inside what pure Python handles, so this stays dependency-free
rather than pulling in shapely.
"""

import json
import os

BOUNDARIES = os.path.join(
    os.path.dirname(__file__), os.pardir, "web", "data", "lad_boundaries.json")
CODE_KEY, NAME_KEY = "LAD24CD", "LAD24NM"


def _rings(geom):
    """Polygon/MultiPolygon -> list of rings; ring 0 of each part is the outer."""
    if geom["type"] == "Polygon":
        return [geom["coordinates"]]
    if geom["type"] == "MultiPolygon":
        return geom["coordinates"]
    return []


def _in_ring(x, y, ring):
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y):
            if x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                inside = not inside
        j = i
    return inside


class Districts:
    def __init__(self, path=BOUNDARIES):
        with open(path) as fh:
            gj = json.load(fh)
        self.items = []
        for f in gj["features"]:
            parts = _rings(f["geometry"])
            if not parts:
                continue
            xs = [p[0] for part in parts for p in part[0]]
            ys = [p[1] for part in parts for p in part[0]]
            self.items.append({
                "code": f["properties"][CODE_KEY],
                "name": f["properties"][NAME_KEY],
                "parts": parts,
                "bbox": (min(xs), min(ys), max(xs), max(ys)),
            })

    def assign(self, lon, lat):
        """Return (code, name) for the district containing the point, or (None, None)."""
        for it in self.items:
            x0, y0, x1, y1 = it["bbox"]
            if not (x0 <= lon <= x1 and y0 <= lat <= y1):
                continue
            for part in it["parts"]:
                if not _in_ring(lon, lat, part[0]):
                    continue
                # holes: a point inside an inner ring is outside the polygon
                if any(_in_ring(lon, lat, hole) for hole in part[1:]):
                    continue
                return it["code"], it["name"]
        return None, None

    def codes(self):
        return {it["code"] for it in self.items}
