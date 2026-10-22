#!/usr/bin/env python3
# Gizleme — Copyright (C) 2026 Oğuz Seran — SPDX-License-Identifier: AGPL-3.0-only — see LICENSE
"""The release step (v43): one version number everywhere, and the app minified for the wire.

    python3 tools/build.py          # after changing APP_VERSION in app.js, or any line of app.js

- reads APP_VERSION from app.js and writes it into sw.js (CACHE name and the ?v= of every versioned shell file)
  and index.html (the ?v= of the scripts it loads), so the installed app fetches fresh files at each version and
  the CDN may cache them for a year (see _headers);
- minifies app.js into app.min.js with terser (pinned), keeping the licence header and adding the SHA-256 of
  the source it was built from — tests/test59 refuses a build that is older than app.js. The readable source
  stays app.js, served too: the minified file is only what the page loads.

Needs node (npx fetches terser the first time; CI has it). Nothing else is generated: i18n.js, boot.js and
sb.js are small enough as they are.
"""
import hashlib, pathlib, re, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
TERSER = "terser@5.44.0"

def version() -> int:
    m = re.search(r"^const APP_VERSION = (\d+);", (ROOT / "app.js").read_text(), re.M)
    if not m: sys.exit("APP_VERSION not found in app.js")
    return int(m.group(1))

def stamp(v: int) -> None:
    sw = ROOT / "sw.js"; s = sw.read_text()
    s2 = re.sub(r'const CACHE = "gizleme-v\d+";', f'const CACHE = "gizleme-v{v}";', s)
    s2 = re.sub(r'\?v=\d+"', f'?v={v}"', s2)
    if s2 != s: sw.write_text(s2); print("sw.js       →", v)
    ih = ROOT / "index.html"; s = ih.read_text()
    s2 = re.sub(r'\?v=\d+"', f'?v={v}"', s)
    if s2 != s: ih.write_text(s2); print("index.html  →", v)

def minify() -> None:
    src = ROOT / "app.js"; out = ROOT / "app.min.js"
    digest = hashlib.sha256(src.read_bytes()).hexdigest()
    if out.exists():
        m = re.search(r"sha256:([0-9a-f]{64})", out.read_text(errors="replace")[:600])
        if m and m.group(1) == digest: print("app.min.js   up to date"); return
    r = subprocess.run(["npx", "--yes", TERSER, str(src), "-c", "passes=2", "-m", "--comments", "/Copyright|SPDX|AGPL/"],
                       capture_output=True, text=True)
    if r.returncode != 0: sys.exit("terser failed:\n" + r.stderr[-2000:])
    head = (f"/* Gizleme app.min.js — built from app.js sha256:{digest} by tools/build.py ({TERSER}).\n"
            f"   The readable source is app.js, next to this file and in the repository (AGPL-3.0-only). */\n")
    out.write_text(head + r.stdout)
    print(f"app.min.js   {src.stat().st_size} → {out.stat().st_size} bytes")

if __name__ == "__main__":
    v = version(); stamp(v); minify()
