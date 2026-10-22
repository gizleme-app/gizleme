# Gizleme — Copyright (C) 2026 Oğuz Seran — SPDX-License-Identifier: AGPL-3.0-only — see LICENSE
"""Helpers shared by the scenarios: waits on a condition instead of a fixed delay.

A scenario keeps its own site, server and mock (they differ where the scenario needs them to); what every one of
them does the same way — wait for the app after a sign-in, wait for a condition — lives here, so a slow runner
(CI, a loaded machine) makes a scenario slower, not red.

    from harness import wait_for, entered, TZ
"""
import time

TZ = "Europe/Paris"   # the contexts' time zone: day separators and default times must not depend on the runner

def wait_for(page, js, timeout=20000, step=120):
    """True as soon as the page evaluates `js` to a truthy value, False after `timeout` ms."""
    t0 = time.time()
    while time.time() - t0 < timeout / 1000:
        try:
            if page.evaluate(js): return True
        except Exception: pass
        page.wait_for_timeout(step)
    return False

APP_SHOWN = ("()=>{ const a=document.getElementById('app'), m=document.getElementById('authMsg');"
             " return (a && a.style.display==='flex') || !!(m && m.textContent.trim()); }")

def entered(page, settle=400, timeout=20000):
    """After a click on #joinBtn (sign-up, log-in, unlock): waits until the app is shown — or the form says
    why not — then settles a moment for what follows the first paint (local load, the first mailbox pass).
    An invite link opened at sign-in pairs the two sides in the link's room and moves them to the day's room
    a couple of seconds later: scenarios that write right after pass a longer settle (2500)."""
    wait_for(page, APP_SHOWN, timeout)
    page.wait_for_timeout(settle)
