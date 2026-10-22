// Gizleme — Copyright (C) 2026 Oğuz Seran — SPDX-License-Identifier: AGPL-3.0-only — see LICENSE
// deno-lint-ignore-file no-explicit-any
// Three assertions, so the Edge Function tests need nothing fetched (they run offline, like the e2e suite).
function same(a: any, b: any): boolean {
  if (Object.is(a, b)) return true;
  if (typeof a !== "object" || typeof b !== "object" || !a || !b) return false;
  if (Array.isArray(a) !== Array.isArray(b)) return false;
  const ka = Object.keys(a).filter(k => a[k] !== undefined), kb = Object.keys(b).filter(k => b[k] !== undefined);
  if (ka.length !== kb.length) return false;
  return ka.every(k => same(a[k], b[k]));
}
export function assert(cond: unknown, msg = "assertion failed"): asserts cond { if (!cond) throw new Error(msg); }
export function assertEquals(actual: unknown, expected: unknown, msg?: string) {
  if (!same(actual, expected)) throw new Error((msg ? msg + ": " : "") + "expected " + JSON.stringify(expected) + ", got " + JSON.stringify(actual));
}
export function assertMatch(actual: string, re: RegExp, msg?: string) { if (!re.test(actual)) throw new Error((msg ? msg + ": " : "") + JSON.stringify(actual) + " does not match " + re); }
