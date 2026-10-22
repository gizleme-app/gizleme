// Gizleme — Copyright (C) 2026 Oğuz Seran — SPDX-License-Identifier: AGPL-3.0-only — see LICENSE
// deno-lint-ignore-file no-explicit-any
// A stand-in for web-push: records what gizleme-push would send, and fails the endpoints a test marks dead.
export const sent: { sub: any; payload: string; opts: any }[] = [];
export const dead = new Set<string>();   // endpoints that answer 410 Gone
export function resetPush() { sent.length = 0; dead.clear(); }
export default {
  generateVAPIDKeys() { return { publicKey: "PUB" + Math.random().toString(36).slice(2), privateKey: "PRIV" }; },
  setVapidDetails(_subject: string, _pub: string, _priv: string) {},
  sendNotification(sub: any, payload: string, opts: any) {
    if (dead.has(sub?.endpoint)) { const e: any = new Error("gone"); e.statusCode = 410; return Promise.reject(e); }
    sent.push({ sub, payload, opts }); return Promise.resolve({ statusCode: 201 });
  },
};
