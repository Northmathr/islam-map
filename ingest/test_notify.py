"""Gate tests for notify.py. No network, no database, no credentials.

The four gates in notify.py are the difference between a useful alert and
mailing strangers about a 2019 application because a source backfilled. They
are cheap to break and invisible when broken -- a silent gate looks exactly
like a quiet week -- so they are tested against the real snapshot.

Usage:
    python3 ingest/test_notify.py
"""

import copy
import datetime as dt
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("notify", os.path.join(HERE, "notify.py"))
notify = importlib.util.module_from_spec(spec)
sys.modules["notify"] = notify
spec.loader.exec_module(notify)

TODAY = dt.date(2026, 8, 26)
RECENT = (TODAY - dt.timedelta(days=10)).isoformat()
ANCIENT = (TODAY - dt.timedelta(days=400)).isoformat()

failures = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}: {got!r}")
    if not ok:
        failures.append(f"{label}: expected {want!r}, got {got!r}")


def run(prev, cur):
    notify.previous_snapshot = lambda: prev
    notify.current_snapshot = lambda: cur
    try:
        fresh, _ = notify.new_applications(TODAY)
        return [r["ref"] for r in fresh]
    except SystemExit:
        return "ABORTED"


def main():
    real = notify.current_snapshot()
    base = real[:200]

    def variant(**kw):
        row = copy.deepcopy(base[0])
        row.update(ref="TEST/1", date=RECENT, confidence="high",
                   kind="new_build", status="pending",
                   description="Erection of a new mosque")
        row.update(kw)
        return row

    print("notify.py gates")
    check("short fetch aborts", run(real, real[:1000]), "ABORTED")
    check("full fetch does not abort", run(real, real) != "ABORTED", True)
    check("new recent application notifies", run(base, base + [variant()]), ["TEST/1"])
    check("backfill suppressed", run(base, base + [variant(date=ANCIENT)]), [])
    check("blank date suppressed", run(base, base + [variant(date="")]), [])
    check("address-only match suppressed",
          run(base, base + [variant(confidence="medium")]), [])
    check("administrative follow-up suppressed",
          run(base, base + [variant(kind="admin")]), [])
    check("already-present ref not re-notified", run(base, base), [])
    check("first run sends nothing", run(None, real), [])

    if failures:
        print(f"\n{len(failures)} failure(s)")
        for f in failures:
            print("  -", f)
        sys.exit(1)
    print("\nall gates hold")


if __name__ == "__main__":
    main()
