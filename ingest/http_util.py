"""Shared HTTP helpers for ingest scripts.

Mirrors mer2-scatter-map/ingest/http_util.py. certifi is required in practice:
the system Python on this machine has no usable CA bundle and every ONS/Nomis
fetch fails with CERTIFICATE_VERIFY_FAILED without it.
"""

import json
import ssl
import urllib.request

try:
    import certifi
    _CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:  # fall back to system trust store
    _CTX = ssl.create_default_context()

UA = "islam-census-map ingest (research tool)"


def get(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as resp:
        return resp.read()


def get_json(url: str, timeout: int = 120):
    return json.loads(get(url, timeout))


def post_json(url: str, payload, headers=None, timeout: int = 60):
    """POST JSON, return parsed JSON (or None for an empty 2xx body).

    Used for the Supabase REST API and Postmark. Both are plain JSON over
    HTTPS, so no SDK is needed and this file stays the only HTTP surface.
    """
    body = json.dumps(payload).encode()
    h = {"User-Agent": UA, "Content-Type": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=body, headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as resp:
        raw = resp.read()
    return json.loads(raw) if raw else None
