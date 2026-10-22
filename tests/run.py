#!/usr/bin/env python3
# Gizleme — Copyright (C) 2026 Oğuz Seran — SPDX-License-Identifier: AGPL-3.0-only — see LICENSE
"""Runs every end-to-end scenario and fails if any check is False or any page error was recorded.

Each testNN.py serves the app from the repository root with a mock in place of supabase-js (an in-process
relay/mailbox emulator), drives real Chromium instances with Playwright and prints a RESULTS block of
"name: True/False" lines. A check whose value is neither True nor False (a string, a list) cannot fail, so it
counts as an error of the scenario — unless its name ends in "_v" or starts with "DBG" (a value kept for the
eye) or is "errors" / "exception". Every scenario's full output is kept in $GZ_TEST_TMP/out/ (or the system
temp dir) for a look after a failure.

    pip install playwright pillow numpy opencv-python-headless && playwright install --with-deps chromium
    python3 tests/run.py            # all
    python3 tests/run.py 32 36      # a selection
"""
import os, pathlib, re, subprocess, sys, tempfile, time

HERE = pathlib.Path(__file__).resolve().parent
OUT = pathlib.Path(os.environ.get("GZ_TEST_TMP") or (tempfile.gettempdir() + "/gizleme-tests/")) / "out"
TIMEOUT = 600

def run(name: str):
    t0 = time.time()
    p = subprocess.run([sys.executable, str(HERE / name)], capture_output=True, text=True, timeout=TIMEOUT)
    out = p.stdout + p.stderr
    try: OUT.mkdir(parents=True, exist_ok=True); (OUT / (name[:-3] + ".txt")).write_text(out)
    except Exception: pass
    body = out.split("RESULTS", 1)[1] if "RESULTS" in out else ""
    falses = [m.group(1) for m in re.finditer(r"^\s+([A-Za-z0-9_]+): False\s*$", body, re.M)]
    nonbool = [m.group(1) for m in re.finditer(r"^\s+([A-Za-z0-9_]+): (.*)$", body, re.M)
               if m.group(2).strip() not in ("True", "False") and m.group(1) not in ("errors", "exception")
               and not m.group(1).endswith("_v") and not m.group(1).startswith("DBG")]
    errs = re.search(r"^\s+errors: (\[.*\])\s*$", body, re.M)
    errs = errs.group(1) if errs else "[]"
    exc = bool(re.search(r"^\s+exception:", body, re.M)) or ("RESULTS" not in out)   # the scenario itself crashed
    ok = "RESULTS" in out and not falses and not nonbool and errs == "[]" and not exc
    return ok, falses, nonbool, errs, exc, round(time.time() - t0, 1), out

def main():
    sel = sys.argv[1:]
    names = sorted(x.name for x in HERE.glob("test*.py"))
    if sel: names = [n for n in names if re.sub(r"\D", "", n) in sel]
    bad = 0
    for n in names:
        ok, falses, nonbool, errs, exc, dt, out = run(n)
        print(f"{'ok ' if ok else 'FAIL'} {n:12s} {dt:6.1f}s" + ("" if ok else f"  false={falses}" + (f" nonbool={nonbool}" if nonbool else "") + f" errors={errs}" + (" exception" if exc else "")))
        if not ok:
            bad += 1
            # the whole RESULTS block (it is what says what failed), then the last lines of the trace if the scenario crashed
            lines = out.strip().splitlines()
            i = next((k for k, l in enumerate(lines) if l.strip() == "RESULTS"), None)
            shown = lines[i:] if i is not None else lines[-25:]
            if exc and i is not None: shown = lines[max(0, i - 10):]
            print(re.sub(r"[A-Za-z0-9+/=_-]{40,}", "<…>", "\n".join(shown)))
    print(f"\n{len(names) - bad}/{len(names)} scenarios passed")
    sys.exit(1 if bad else 0)

if __name__ == "__main__":
    main()
