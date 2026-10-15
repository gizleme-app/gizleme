#!/usr/bin/env python3
# Gizleme — Copyright (C) 2026 Oğuz Seran — SPDX-License-Identifier: AGPL-3.0-only — see LICENSE
"""Runs every end-to-end scenario and fails if any check is False or any page error was recorded.

Each testNN.py serves the app from the repository root with a mock in place of supabase-js (an in-process
relay/mailbox emulator), drives real Chromium instances with Playwright and prints a RESULTS block of
"name: True/False" lines. Known-platform checks that can only pass on iOS are listed in EXPECTED_FALSE.

    pip install playwright pillow numpy && playwright install --with-deps chromium
    python3 tests/run.py            # all
    python3 tests/run.py 32 36      # a selection
"""
import pathlib, re, subprocess, sys, time

HERE = pathlib.Path(__file__).resolve().parent
EXPECTED_FALSE = {"safariIos_"}          # prefixes of checks that are documented as platform-only
TIMEOUT = 600

def run(name: str):
    t0 = time.time()
    p = subprocess.run([sys.executable, str(HERE / name)], capture_output=True, text=True, timeout=TIMEOUT)
    out = p.stdout + p.stderr
    body = out.split("RESULTS", 1)[1] if "RESULTS" in out else ""
    falses = [m.group(1) for m in re.finditer(r"^\s+([A-Za-z0-9_]+): False\s*$", body, re.M)
              if not any(m.group(1).startswith(x) for x in EXPECTED_FALSE)]
    errs = re.search(r"^\s+errors: (\[.*\])\s*$", body, re.M)
    errs = errs.group(1) if errs else "[]"
    exc = bool(re.search(r"^\s+exception:", body, re.M)) or ("RESULTS" not in out)   # the scenario itself crashed
    ok = "RESULTS" in out and not falses and errs == "[]" and not exc
    return ok, falses, errs, exc, round(time.time() - t0, 1), out

def main():
    sel = sys.argv[1:]
    names = sorted(x.name for x in HERE.glob("test*.py"))
    if sel: names = [n for n in names if re.sub(r"\D", "", n) in sel]
    bad = 0
    for n in names:
        ok, falses, errs, exc, dt, out = run(n)
        print(f"{'ok ' if ok else 'FAIL'} {n:12s} {dt:6.1f}s" + ("" if ok else f"  false={falses} errors={errs}" + (" exception" if exc else "")))
        if not ok:
            bad += 1
            tail = "\n".join(out.strip().splitlines()[-25:])
            print(re.sub(r"[A-Za-z0-9+/=_-]{40,}", "<…>", tail))
    print(f"\n{len(names) - bad}/{len(names)} scenarios passed")
    sys.exit(1 if bad else 0)

if __name__ == "__main__":
    main()
