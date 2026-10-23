<!-- Gizleme — Copyright (C) 2026 Oğuz Seran — SPDX-License-Identifier: AGPL-3.0-only — see LICENSE -->
# Gizleme threat model

Status: v48, October 2026. Written by the author (with an AI assistant) from the code; **not independently
reviewed**. Companion documents: [PROTOCOL.md](PROTOCOL.md) (what the protocol does, exactly),
[../SECURITY.md](../SECURITY.md) (design rationale and per-feature limitations), [../AUDIT.md](../AUDIT.md)
(the internal audit's findings and fixes).

This document answers four questions: *what are we protecting, from whom, how, and what is still exposed.*
It is deliberately blunt about the last one. Gizleme is a small project: it does not claim the strength of
Signal, and a reader should come away knowing exactly where it is weaker.

## 1. System and trust boundaries

```
 ┌───────────── user device ─────────────┐        ┌──────────────── Cloudflare ───────────────┐
 │ browser / installed PWA               │  TLS   │ Workers static assets: index.html, app.min.js│
 │  • all cryptography (WebCrypto)       │◀───────│ i18n.js, sw.js …   (the code that runs     │
 │  • keys in memory while unlocked      │        │ on the device is delivered from here)      │
 │  • local data encrypted under MK      │        └────────────────────────────────────────────┘
 └───┬───────────────┬───────────────┬───┘
     │ TLS           │ TLS/WebSocket │ TLS (DTLS-SRTP media)
     ▼               ▼               ▼
 ┌─────────────── Supabase project ──────────────┐   ┌───── Cloudflare TURN ─────┐   ┌─ browser push ─┐
 │ Edge Functions: auth, vault, mbox, push, turn │   │ relays call media         │   │ FCM / APNs /   │
 │ Postgres (ciphertext, verifiers, hashes)      │   │ (ciphertext only)         │   │ Mozilla push   │
 │ Storage (encrypted blobs)                     │   └───────────────────────────┘   └────────────────┘
 │ Realtime (presence + broadcast)               │
 └───────────────────────────────────────────────┘
```

Boundaries that matter:

- **B1 — device ↔ everything else.** The device is the only place plaintext and keys exist.
- **B2 — the code's origin.** The device runs whatever Cloudflare serves at load time. Everything below
  assumes that code is the published one (§6, W1).
- **B3 — the relay (Supabase).** Treated as *fully untrusted for confidentiality*, and as *semi-trusted for
  availability and metadata hygiene*. It holds ciphertext, password verifiers and salts, session-token hashes,
  usernames and display names, the opaque account marker, push endpoints and keys, and delivery timestamps —
  never a key or a plaintext — and it can see who connects when.
- **B4 — the other party.** A contact is trusted with what you send them, and with nothing else.

## 2. Assets

| # | Asset | Where it lives | Why it matters |
|---|---|---|---|
| A1 | Message and media **content** | device (plaintext); relay and local history (ciphertext) | the point of the app |
| A2 | **Contact keys** `ck`, chain roots `kc`, group keys `gk`, identity private keys | vault (ciphertext), device memory when unlocked | whoever holds them reads (and can write as) the conversation |
| A3 | **Account backup key** ABK | wrapped by the password on the server; cached under MK on devices | unlocks A2 |
| A4 | **Password** and `AK` | the user's head; never leave the device (`av` is derived from `AK`) | unlocks A3 |
| A5 | **Device master key** MK | wrapped by password/PIN/biometric | unlocks local history and cached A3 |
| A6 | **Session token** | `localStorage` (clear), hash on server | calls authenticated functions as the user |
| A7 | **Social graph and activity metadata** | relay logs, presence, mailbox ids, push table | who talks to whom, when, how much |
| A8 | **Server secrets** | `gizleme_config`: auth secret, VAPID private key; the TURN token (function secrets, or `gizleme_config` as a fallback) | impersonation of the push sender; relay-minute theft |
| A9 | **Integrity of the delivered code** | Cloudflare origin | compromises everything above |
| A10 | **Availability** | all of it | an unreachable app delivers nothing |

## 3. Actors

| Actor | Capability assumed |
|---|---|
| **N1 passive network observer** | sees TLS metadata (IP, timing, sizes) |
| **N2 active network attacker** | can drop/delay/replay traffic; **cannot break TLS** |
| **R1 curious relay operator** | reads everything the Supabase project stores or sees, including logs, including the service-role key |
| **R2 compromised relay** | R1 plus: writes arbitrary rows, injects/replays/reorders/withholds ciphertext, answers any function call as it likes |
| **H1 compromised or coerced host** | can ship different JavaScript to some or all users (Cloudflare account takeover, malicious deploy, legal order) |
| **P1 push service** | sees device endpoint, timing, fixed-text payloads |
| **C1 malicious contact** | holds the shared keys of a conversation; controls their own client |
| **C2 group member / removed member** | holds `gk` (current or former); can send signed messages as themselves |
| **L1 link interceptor** | obtains an invite link or group link (chat history of another app, shoulder-surfing, a leaked screenshot) |
| **D1 finder of a locked device** | physical access, device locked, app locked |
| **D2 malware / unlocked-device thief** | code execution or unlocked-device access on the user's device |
| **U1 abusive stranger** | unauthenticated, uses the public endpoints (spam, enumeration, resource abuse, guessing) |
| **T1 TURN operator** | sees call endpoints and DTLS-SRTP ciphertext |

Out of scope: a compromised OS or browser, hardware side channels, a global passive adversary correlating
traffic at both ends, rubber-hose attacks, breaks in AES/SHA-2/P-256/WebCrypto implementations, and the
operators of Supabase, Cloudflare, Google, Apple or Mozilla beyond the capabilities listed above.

## 4. Security goals, and where each stands

| Goal | Against | Status |
|---|---|---|
| G1 Message and media **confidentiality** | N1, N2, R1, R2, P1, T1 | Met, subject to H1/W1 and to the key-custody limits below. |
| G2 Message **integrity and authenticity** (1:1) | N2, R2 | Met for live and mailbox traffic *once contacts are authenticated* (AES-GCM, direction + counter + sealed id). A contact is authenticated by the invite flow; the impostor-first-opener window is narrowed, not closed (T6). Manual room-code contacts are *not* authenticated until the fingerprint is compared by the users. |
| G3 **Sender authentication in groups** | C2, R2 | Signed messages; members' keys learned on first use (TOFU). |
| G4 **Forward secrecy** | later compromise of a device or the vault | **Partial.** Live traffic: yes (fresh ECDH per join). Mailbox, v3 contacts: weekly (a captured ciphertext older than three weeks is unreadable after a later key compromise). Mailbox, pre-chain contacts: none. Groups: none. |
| G5 **Post-compromise security** | an attacker who once held a key | **None** on the mailbox path and in groups; live traffic recovers at the next join. |
| G6 **Account takeover resistance** | U1, R1/R2 with a DB copy | Online guessing: rate-limited. Offline guessing from a leaked verifier: **PBKDF2-200k only** (T1-class gap, §6 W2). |
| G7 **Metadata minimisation** | R1, P1 | Partial: opaque ids, fixed-text push, no usernames in presence; but stable mailbox ids, display names in presence, IP/timing. |
| G8 **Deniability** | — | Not a goal. Group messages are signed (non-repudiable by design); 1:1 uses symmetric keys. |
| G9 **Availability / abuse resistance** | U1 | Best-effort rate limits; fail-open if the limiter errors (W9). |

## 5. Threat register

Legend — **Status**: *Mitigated* (a control exists and is tested), *Partial* (control narrows it),
*Accepted* (known, documented, not planned), *Open* (planned or unaddressed).
Test references are to `tests/` scenarios and `tests/edge/`.

### 5.1 Relay and network

| ID | Threat | Actor | Control | Residual / status |
|---|---|---|---|---|
| T1 | Read message or photo content | R1, R2, N1 | E2E AES-GCM; keys never on server; blobs encrypted client-side with a per-blob key sent inside the message | Mitigated |
| T2 | Replay, reflection or reorder of live messages | R2, N2 | `dir`, monotonic counter `i`, sealed `mid` equal to outer `mid`, `seen` set | Mitigated (live). Mailbox: dedupe by `mid`; ordering is by relay timestamp (Accepted) |
| T3 | Replay of an old signed group message or old key rotation | C2, R2 | `sts` window 16 days; rotation number + `fpSeen` (every key the group has used) | Mitigated; clock-based (W11). The previous-key fingerprint `p` in a rotation is signed but not checked by receivers |
| T4 | Inject messages into a mailbox | R2, anyone with the mailbox id | writing needs the mailbox *key* to produce a message that decrypts; id alone lets one add junk rows | Partial: junk/DoS possible (120/min per mailbox), forged content not |
| T5 | Man-in-the-middle at live pairing | R2, N2 | HMAC over `pub` under `HKDF(ck,…)`; unverified entries are not paired with (a peer already paired in the session is kept if its tag later goes missing) | Mitigated for contacts. Not for manual rooms (§4 G2) |
| T6 | Impostor opens an invite link first | L1 | link carries only a one-time public key; expiry (default 24 h); optional spoken 4-digit code (3 tries); first hello wins and later ones are reported; in-person QR; safety code bound to the agreement | Partial: an interceptor who is faster than the invitee and knows the code becomes the contact; only the safety-code comparison detects it |
| T7 | Downgrade of the invite hello (strip forward-secrecy offer or code tag) | R2 | hello tag `h` binds `fs`, `ke`, `m` to the ECDH secret; **enforced only from 2026-12-15** — until then a hello without `h` is accepted | Partial until that date, Mitigated after |
| T8 | Username enumeration | U1 | `salt` returns deterministic fake salts; `check` is rate-limited (20/min/IP) | Partial: `check` reveals availability by design |
| T9 | Online password guessing | U1 | 10 failed attempts / 15 min per account (success refunds), 60 logins / 15 min per IP | Mitigated (limits are per-IP/per-account, not distributed-guessing-proof) |
| T10 | Spam wake-ups via push | U1 | notification key is a secret derived from `ck`; 12/10 min per key; fixed text; ≤ 8 devices per key; endpoint allow-list | Mitigated |
| T11 | Storage abuse | U1 | blobs only through `putblob`; 30/min/IP, 150/h/account; ≤ 2 MB; 14-day sweep | Partial: until 2026-12-15 a request with no session token is still served and skips the per-account limit; no storage quota (Accepted) |
| T12 | Join or inject on a Realtime channel | U1, R2 | none at the channel level (policy only checks `ratchet-%`); end-to-end tags and encryption | Partial: an attacker who learns a topic name can join presence and see names/markers; cannot pair or read (§6 W6) |
| T13 | Call media interception | R2, T1 | DTLS-SRTP; fingerprints exchanged inside the E2E session | Mitigated for 1:1; in groups an `unsigned` call envelope is still processed, so the SDP is authenticated to a holder of the group key; TURN and the peer see IPs |

### 5.2 Account and device

| ID | Threat | Actor | Control | Residual / status |
|---|---|---|---|---|
| T14 | Offline cracking of the password from a DB leak, then reading the vault | R1, R2 | PBKDF2-200k; verifier = SHA-256(SHA-256(AK)) | **Open** (W2): a weak password falls; Argon2id/OPAQUE planned |
| T15 | Replay of a captured login proof `av` | N2 with broken TLS | TLS only | **Open** (W3), with OPAQUE |
| T16 | Steal the session token from the device | D2 | token is server-revocable (a password change or account deletion deletes the others; `logout` deletes the presented one; each unlock validates the session and wipes the device if it was revoked). There is no “sign out everywhere” action | Accepted: stored in clear in `localStorage`; it grants function access (vault ciphertext, TURN, blob upload, acks), **not** key material |
| T17 | Read local data on a locked/found device | D1 | MK wraps all local data; unwrapped only by password/PIN (PBKDF2) or biometric PRF; keys out of memory on lock; opaque DB ids | Mitigated up to PIN/password strength; the PIN path is as weak as the PIN (200k PBKDF2) |
| T18 | Malware or an unlocked-device thief | D2 | none beyond OS | Out of scope: keys are in memory while unlocked |
| T19 | Cross-account leakage on a shared browser | — | vault-owner check, full wipe on logout | Mitigated |
| T20 | Takeover by an attacker who has the *password* | any | none; a new device logs in and unwraps the ABK | By design: password = full custody of the account. Contact keys do not rotate on password change (planned) |

### 5.3 Contacts and groups

| ID | Threat | Actor | Control | Residual / status |
|---|---|---|---|---|
| T21 | Removed member keeps reading | C2 | admin rotates `gk` and wraps it to the remaining members only; room and mailbox follow the key; old key readable 14 days for late writers | Mitigated for new messages; the removed member keeps what they already have |
| T22 | Removed member forces the group back to an old key | C2 | rotation number (when numeric) and `fpSeen` | Mitigated |
| T23 | Member impersonates another | C2 | ECDSA signatures over `rid` + object; name↔key binding learned on first use | Partial: TOFU; a member's first key is unverified |
| T24 | Non-admin rotates or removes | C2 | `gk2` honoured only if signed by `adm` | Mitigated. Groups created before admin keys cannot rotate |
| T25 | Malicious contact lies (fake read receipts, ignores deletes/timers) | C1 | disappearing/view-once/delete are advisory | Accepted: enforced by the recipient's client only |
| T26 | A group/room code is leaked | L1 | group link = `gk`: leak = compromise until rotated | Accepted; admin can rotate |

### 5.4 Software supply chain and delivery

| ID | Threat | Actor | Control | Residual / status |
|---|---|---|---|---|
| T27 | Malicious JavaScript served to users | H1 | CSP `script-src 'self'`, HSTS, no third-party scripts, public source, README procedure to compare the served bundle's hash with the source | **Open** (W1): a compromised origin can ship different code; no signed/reproducible build, no second-channel verification in the app |
| T28 | Malicious dependency | — | the only third-party runtime code is vendored and version-pinned: supabase-js 2.117.2 (≈218 KB, all function, Realtime and storage calls) and `qrcode.js` 1.4.4 (57 KB, loaded on first QR) | Mitigated by vendoring, not eliminated: supabase-js sits on the path of every request; see `THIRD_PARTY.md` |
| T29 | Service worker keeps an old, vulnerable version | — | cache name = version; update offer when a newer one is detected | Partial: users on a stale tab keep old code until reload |
| T30 | Server secret leakage (VAPID key, TURN token, auth secret) | R1, R2 | secrets in a service-role-only table or function secrets, never in source or client | Accepted: a Supabase compromise includes them (the VAPID key lets an attacker send fixed-looking pushes; the TURN token spends relay minutes) |

## 6. Known weaknesses, ranked

Ranked by what they would cost a user, not by effort to fix.

**W1 — The code you run is whatever the host serves.** A web app cannot prove its own integrity to itself.
A compromised Cloudflare account, a malicious deploy or a legal order could ship JavaScript that exfiltrates
keys. *Controls:* strict CSP; public source; `app.min.js` carries the SHA-256 of `app.js` in its header, and
the README shows how to compare it with a clean build. *Gap:* nothing in the app checks it; there is no
signed or reproducible release channel. *Direction:* packaged apps (Play/App Store) move the code root of
trust to the store signature; a published release hash and a bundle-verification page are cheap steps.

**W2 — The password is the whole account.** `AK = PBKDF2(password, salt, 200 000)` unwraps the ABK, which
unwraps the vault (all contact keys, group keys, the identity key). The server stores
`SHA-256(SHA-256(AK))`, so a copy of `gizleme_accounts` (or a malicious function) allows an offline attack at
PBKDF2-200k speed. Current guidance for this construction is substantially higher. *Direction:* a
memory-hard KDF (Argon2id) and/or an aPAKE (OPAQUE) so the server learns nothing guessable; this also fixes
W3.

**W3 — The login proof is replayable.** `av` is static. *Direction:* OPAQUE.

**W4 — No post-compromise security, and only weekly forward secrecy offline.** See PROTOCOL §14. A device
compromise reveals the three weeks of mailbox traffic still on the relay and **every later week** — an
existing chain is never re-seeded — and, for pre-chain contacts and all groups, the whole retained history
and the future, until keys are rotated. *Direction:* per-device ephemeral keys and a real
ratchet for the mailbox (a separate project); rotating contact keys on password change.

**W5 — The vault concentrates every secret.** One AES key (the ABK) protects all contact keys, group keys,
chain roots and the identity private key; it is protected by W2's password. A leaked vault *plus* the password
is total for that account's conversations. Contacts' vaults hold the same `ck`, so the weakest of the two
parties' passwords bounds the pair.

**W6 — Realtime topics are protected by obscurity.** The Realtime policy lets any holder of the public anon
key subscribe to and publish on any `ratchet-%` topic. 1:1 topics are 35-bit codes derived from `ck` and the
day; manual room codes are chosen by users. A guesser who lands on a live topic sees presence (display names,
account markers, public keys) but cannot pair (needs the tag) or read. *Direction:* longer topic names;
Realtime authorization tied to a session claim.

**W7 — Metadata.** The relay sees: IP and timing of every connection; mailbox ids that are **stable per
contact** (so all messages of a pair are linkable over time); co-presence in rooms; display names and the
account marker in presence; ciphertext sizes (no padding); the set of mailbox ids a device polls (one request
per pass); push endpoints linked to notification keys. Not hidden: this is a hosted relay, not a mixnet.

**W8 — The pairing proof is thin.** `tag = HMAC(HKDF(ck,"gz-auth/v1"), pub)` covers only the sender's own
public key: not the room/day, the peer's key, or the sender/receiver role; and `root = HKDF(secret,"root")`
does not bind the two public keys. An attacker cannot turn this into a decryption (the ECDH private half is
needed), but it is the first place a protocol reviewer should look for misbinding or reflection issues.

**W9 — Rate limiting fails open and relies on IP.** If the `gz_rl_hit` call errors, the request is allowed.
Limits keyed on IP are weak behind shared NATs and bypassable with many addresses. Acceptable for a small
service, inadequate against a determined abuser.

**W10 — Session token in clear in `localStorage`.** See T16. It cannot decrypt anything but it is a
credential for the relay for up to a year (revocable).

**W11 — Clock dependence.** Invite expiry, `sts` windows and weekly epochs rely on client clocks (with
stated tolerances). A wrong clock causes refusals or, in the worst case, a longer replay window.

**W12 — Server errors may echo database messages** (no secrets, but not generic).

**W13 — Advisory controls.** Disappearing messages, view-once, delete-for-everyone and edit windows are
honoured by a *cooperating* client. They protect against accidents and the relay, not against a hostile
recipient.

**W14 — Leftovers after logout (fixed in v49).** Up to v48, logout cleared `gz-exp-rooms` but left `gz-exp-ts`
and `gz-exp-global` in `localStorage` (account deletion too): per-chat timer choices keyed by the opaque
history id, or by the group id for groups — no keys or content. Both are now removed at logout and deletion.
The push device id `gz-devid` stays after a plain logout by design (see PROTOCOL §9).

## 7. What a reviewer should look at first

Ordered by expected return.

1. **Key agreement and authentication** — PROTOCOL §5 and §6: the v3 invite agreement (`processHello`,
   `v3Agree`), the pairing proof (`authTag`, `verifyPeerTag`, `establish`), the KDF inputs (W8). Questions:
   can a relay or a late opener cause a misbinding, a reflection, a downgrade, or a pairing with a key the
   honest party does not hold?
2. **Account crypto and the vault** — PROTOCOL §4: `pbkdf2bits`, `recoverABK`, `rewrapAbk`, `changepw`,
   `pushContacts` merge/conflict logic (`mergeContacts`: can a stale or malicious device write back a key it
   should not, e.g. resurrect a retired `ck` or roll the chain backwards?).
3. **The mailbox chain** — PROTOCOL §7.3: `chainRootAt`, `advanceChains`, the live re-seed (`fsu`), the
   convergence rule on concurrent seeds, and the 48-hour holding of unreadable items. Is any key reused with a
   repeated IV? Can an attacker force a chain reset?
4. **Groups** — PROTOCOL §8: signature coverage (`gsigData`), `verifyGroupEnv`, rotation handling (`onGk2`),
   removal detection, TOFU handling.
5. **Edge Functions** — authentication of each action, rate limiting, error handling, queries (all go through
   the supabase-js query builder or the fixed `gz_*` Postgres functions in `supabase/migrations/`; the one
   place a filter string is assembled, push `register`, only joins values that match `^[A-Za-z0-9_-]+$`),
   CORS, input validation (`MBOX_RE`, `MID_RE`, path regexes), service-role key handling.
6. **Web delivery** — `_headers` (CSP), service worker (`sw.js`) caching and update logic, `#` fragment
   handling (links stripped from the address bar), `postMessage` and `Notification` URL handling.
7. **Local storage** — MK wrapping (PIN/password/PRF), what stays in clear, wipe on logout/lock, IndexedDB
   ids.

Useful starting points: the 44 browser scenarios and 31 function tests (`tests/`), which encode the
intended behaviour; `AUDIT.md`, which lists what has already been found and fixed.

## 8. Planned improvements (not promises)

| Item | Addresses |
|---|---|
| Argon2id and/or OPAQUE for login; verifier not guessable by the server | W2, W3 |
| Rotate contact keys when the password changes or a device is revoked | W4, T20 |
| Per-device ephemeral keys and a ratchet for the offline path | W4 |
| Longer, authorised Realtime topics | W6 |
| Published release hashes and a bundle verification page; store-signed apps | W1 |
| Independent audit (scope: PROTOCOL §4–§8 and the five Edge Functions) | all |
| Fail-closed limiter on sensitive actions; per-account storage quota | W9, T11 |
| Bind both public keys and roles into the pairing proof and the KDF | W8 |

## 9. Reporting and maintenance

Vulnerability reports: see [../SECURITY.md](../SECURITY.md) (admin@gizleme.com). This document is updated
with each version that changes the protocol or the server; a change that moves a row of §5 or a weakness of
§6 should say so in its commit message. Corrections from reviewers are welcome as issues or pull requests.
