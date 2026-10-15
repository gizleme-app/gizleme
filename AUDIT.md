# Internal security audit — October 2026

Scope: the whole system as deployed at gizleme.com — the protocol and client state machine (`app.js`,
`sw.js`), the server side (five Supabase Edge Functions, Postgres schema and RLS, storage bucket,
Realtime) and the client application (lock, storage at rest, deep links, media, headers).

Method: three independent reviews, each by a reviewer who had not written the code and did not see the
other reviews, working from the source and from the live project (functions, policies and bucket
settings were verified live, not from documentation). Findings were then fixed in one pass and the
regression suite (Playwright, 15 end-to-end scenarios against an emulated relay and mailbox) was extended
to cover each fix. This is an internal audit: it is not an independent one, and it does not replace one.

Severity: **Critical** = a stranger or the relay can read or impersonate a contact; **High** = key
material or sender identity at risk under a realistic assumption; **Medium** = metadata, abuse or
consent issues; **Low** = hardening.

## Protocol and client state machine

| # | Sev. | Finding | Status |
|---|------|---------|--------|
| F1 | Critical | A pending invite (v2 or v3 before the hello) could be "authenticated" by anyone who saw the victim's session public key in presence: the fallback check derived a candidate key from the presented public key itself, so the relay could pair itself with an inviter. | **Fixed.** The forgeable check is gone. A peer who has rotated (v2) proves it by a second HMAC under the link key (`tagp`), which the relay never holds. A v3 invite that has not been helloed accepts nobody on the link key at all (the ECDH agreement in the hello is the only way in). |
| F2 | High | Ordinary messages left in a retired v3 link mailbox were shown as the contact's for 14 days: anyone with a copy of the link could inject into both sides' chats. | **Fixed.** A v3 link mailbox carries nothing but hellos and `used` notes; anything else there is dropped. The inviter's own pre-hello writes wait on the device and go out under the agreed key. |
| F3 | High | `legacyLinkFallback`: a plain message under the link key silently downgraded a v3 pending invite to a bearer-key contact (re-opening the v2 weakness v3 was built to close). | **Fixed.** Removed. An older app (or a link holder) signing with the link key is not paired with, its messages are not shown, and the inviter is told to ask them to update. |
| F4 | High | Long-term contact keys were written to disk in clear as identifiers: the IndexedDB history index, the per-chat expiry map and the unread map were keyed by the contact key itself. | **Fixed.** Every local identifier is now an opaque per-chat id (HKDF of the contact key, 16 bytes); existing stores are migrated at unlock and after a vault pull. Mailbox cursors and nudge timestamps moved from `localStorage` into the encrypted local store. |
| F5 | Medium | Presence fields other than the public key (name, account marker, call announcement) are not covered by the HMAC. | **Open (documented).** Names shown from presence are those the contact chose and are not authenticated; the pairing decision never depends on them. Signing the whole presence payload is on the roadmap with the group-authentication work. |
| F6 | Medium | The mailbox "written by my own other device" decision trusted the relay-visible `from_user`. | **Fixed.** The account marker is sealed inside the ciphertext (`a`); nothing is sent in clear. The client never acks its own deposits. |
| F7 | Medium | A forged `used` note could tell the real invitee their link was taken; reuse alarms could fire on the same hello seen twice. | **Mitigated.** `used` is addressed to the late opener's ephemeral key and only honoured when it matches the contact's own hello; a hello already bound (`he`) never raises an alarm. A member of the link mailbox (i.e. a link holder) can still send a matching `used` only if they know the victim's ephemeral key, which the mailbox does reveal to a link holder — the note is a warning, the contact is kept. |
| F8 | Medium | v2 reconciliation keeps depositing under the retired link key while the peer has not rotated. | **Documented trade-off.** Only applies to invitations created by pre-v3 builds; it is what keeps the not-yet-rotated friend reachable (the "both offline to each other" bug). v3 links never write under the link key. |
| F9 | Medium | Any group member could ring any member with a forged 1:1 call invite; group calls are member-level (no per-member authentication). | **Fixed / documented.** A 1:1 `invite` inside a group room is ignored; group calls are announced and joined only (`gstart`/`gjoin`), mesh capped at 4. Member-level trust in groups is documented. |
| F10 | Medium | The account marker (presence `u`, mailbox `from_user`) lets the relay map which rooms an account is in. | **Partly fixed / documented.** Removed from the mailbox (sealed). It remains in presence — it is how one's own devices tell each other apart in a room — and the privacy page now says so. |
| F11 | Low | Live counter advanced before authentication; counter reset after a one-sided unpair. | Open (hardening). |
| F12 | Low | Mailbox replay into closed chats; single-page polling (300 items). | Open (hardening). |
| F13 | Low | No vault rollback protection (the server could serve an older vault blob). | Open; the vault is versioned (`cver`) but a rollback by the server is not detected. |
| F14 | Low | Direction string ambiguity; message `id` not under the tag. | Open (hardening). |
| F15 | Low | A link whose pre-key was damaged fell back silently to the bearer path. | **Fixed.** A damaged or unusable pre-key refuses the link ("ask for a new one"). |
| F16 | Low | Verification wording overstated what a bearer-link pairing proves. | **Fixed.** The first-pairing line on a legacy link now says "authenticated with your invite link". |
| F17 | Low | Envelope type visible to the relay in some paths. | Open; live broadcast payloads now carry only `{from,dir,i,iv,ct,mid}`. |
| F18 | Low | Disappearing messages are a local, best-effort sweep. | **Documented** (privacy page, SECURITY.md). |
| F19 | Info | Calls and push plumbing notes. | Addressed where it mattered (see server M4/M5). |

## Server (Edge Functions, database, storage, Realtime)

| # | Sev. | Finding | Status |
|---|------|---------|--------|
| H1 | High | "Opaque identities" overstated: display names travelled in clear in broadcast payloads and push requests, and presence carries the display name and account marker. | **Partly fixed.** Names removed from broadcast payloads and from push requests (fixed bodies; the receiving device adds the name from a hashed-key cache). Presence still carries the chosen display name — documented. |
| H2 | High | Mailbox sender identity (`from_user`) was unauthenticated: the relay could re-label a message as "from your other device". | **Fixed** (see F6). |
| M1 | Medium | The login proof `av` is a static, server-replayable credential. | **Open (documented).** aPAKE (OPAQUE) planned with the KDF upgrade. |
| M2 | Medium | Anyone could lock any username by failing logins against it (and block its password change/deletion). | **Fixed.** Per-account budget counts failed attempts only and is given back on success (`gz_rl_undo`); change/delete have their own budget; per-IP limit on every attempt. |
| M3 | Medium | Anonymous flooding of the mailbox table and the bucket (free 14-day file host). | **Partly mitigated.** Size caps (400 kB per message, 2 MB per blob), per-IP and per-mailbox rate limits on every write, delivered messages deleted after 48 h. No per-account quota (the relay does not know accounts on the mailbox path by design). |
| M4 | Medium | TURN credentials valid 1 h, minted once per function instance and shared by all callers. | **Fixed.** 15-minute credentials, re-minted every 2 minutes, 40 fetches/10 min per IP. |
| M5 | Medium | Push fan-out amplification (unbounded devices per key) and attacker-controlled text. | **Fixed.** At most 8 devices per notification key, fixed bodies, subscription key validation, sequential sends. |
| M6 | Medium | A device acking its own deposits could delete a message before the recipient fetched it. | **Fixed.** Own deposits are recognised by the sealed marker and never acked. |
| M7 | Medium | Rate limiter fails open on DB error and depends on proxy IP headers. | **Open (documented).** Fails open by choice (availability); the IP comes from `cf-connecting-ip` first. |
| M8 | Medium | Gizleme shares its Supabase project with an unrelated application (one service-role key, one database, one storage account), plus two obsolete functions. | **Open — decision for the owner.** Recommended before any public release: move Gizleme to its own project, delete the obsolete functions, rotate the service-role key. |
| L1 | Low | Set-once ABK / `cver` are check-then-write races. | Open. |
| L2 | Low | Password change is two non-atomic calls. | Open. |
| L3 | Low | Error responses may echo backend error strings. | Open (no secrets involved). |
| L4 | Low | Sweeps run on every request. | Open (cheap; indexed). |
| L5 | Low | Input normalisation accepts anything; login skips the username regex. | Open (the lookup is by exact lowercase key; no injection path). |
| L6 | Low | Push text was free text from the sender when the receiver did not know the key. | **Fixed** (fixed bodies). |
| L7 | Low | One member can jam a shared mailbox (rate limit is per mailbox). | Open (documented with the group model). |
| L8 | Low | Account deletion relies on client-supplied device ids to clean push registrations. | Open (the account marker also deletes by `acct`). |
| L9 | Low | "Deleted when viewed" blobs may survive briefly in the CDN cache. | Open (documented as "at the latest after 14 days"). |
| L10 | Low | `check` reveals whether a username is taken. | **Documented** (needed for sign-up; rate-limited; `salt` does not reveal it). |

## Client application

| # | Sev. | Finding | Status |
|---|------|---------|--------|
| 1 | High | Contact keys at rest in clear (IndexedDB index, `gz-exp-rooms`). | **Fixed** (see F4). |
| 2 | Medium | The lock screen could be overlaid or bypassed by elements it did not close (modals, lightbox, pending deep links). | **Fixed.** Locking closes every dialog and lightbox, clears pending invites/notifications, the rendered logs and sidebar, and password fields. |
| 3 | Medium | Deep links joined groups without consent; a group invitation in a chat silently added the group. | **Fixed.** A group link asks for confirmation unless the group is already known; a group-invitation card adds the group only when tapped. Contact links still open the chat directly (by design: the opener is the one who tapped the link). |
| 4 | Medium | Display name in clear beside ciphertext (presence) and defaults to the username. | **Partly fixed / documented.** Removed from broadcast and push; presence keeps it (documented). The display name is chosen at sign-up and can be changed in Settings. |
| 5 | Medium | EXIF/GPS metadata leaked on the "small file" photo path. | **Fixed.** Every photo is re-encoded before sending (small PNGs stay PNG, everything else JPEG). |
| 6 | Medium | Contact nicknames at rest in clear in the Cache API, keyed by notification keys. | **Mitigated / documented.** Keys are hashed (SHA-256); names remain readable in the cache (the worker needs them to compose the notification) and are cleared on log-out. |
| 7 | Medium | Privacy defaults (24 h expiry, auto-lock) applied only at registration. | **Fixed.** Applied at registration and at login; 15 min auto-lock. |
| 8 | Medium | Disappearing messages presented as a protocol feature. | **Documented** as best effort. |
| 9 | Medium | "Share on WhatsApp" sends the invite link to wa.me. | **Documented.** Inherent to sharing through WhatsApp; the v3 link design limits what the link gives. |
| 10 | Low | Lock left plaintext in hidden DOM/inputs. | **Fixed** (see 2). |
| 11 | Low | Logout/delete wipe incomplete (`gz-exp-rooms`, cursors). | **Fixed.** |
| 12 | Low | Untrusted names unbounded in native dialogs and syslines. | Open (names are text-node inserted, length-capped at 24 on the server for accounts; sysline text is never HTML). |
| 13 | Low | Recipient trusts photo envelope `mime`/`path`. | Open (`path` is validated by regex server-side on delete; the blob is decrypted locally and shown as an image blob). |
| 14 | Low | Selector built from a message id; receipt-map eviction. | Open (ids are generated locally as random strings; inbound ids are only used as map keys). |
| 15 | Low | Camera/mic lifecycle races. | Open. |
| 16 | Low | Silent group insertion via `ginv`; spoofable group-call names. | **Fixed** (consent) / documented (names). |
| 17 | Low | Plaintext identifiers in `localStorage` while locked. | **Fixed** for mailbox cursors and nudge times (moved into the encrypted store); the session username and settings remain (they are not secrets). |
| 18–22 | Info | CSP/headers, service worker, lock-screen name disclosure, accessibility, deployment hygiene. | Noted; the lock screen shows the display name by design (so you know whose account is locked). |

## What is deliberately not fixed yet (roadmap)

1. **Forward secrecy for the mailbox** — per-device ephemeral pre-keys (Signal model). Today: a delivered
   message is deleted 48 h after any device fetched it; the per-contact key never derives from a link.
2. **aPAKE login (OPAQUE) and a memory-hard KDF** — removes the replayable `av` and raises the cost of
   offline guessing from a database leak.
3. **Authenticated presence and group sender authentication / key rotation.**
4. **Own Supabase project** (M8) — an operational decision for the owner before any public release.

## Verified as sound

ECDH P-256 + HKDF + AES-GCM with per-direction counters; HMAC pairing check under the contact key; the
vault (PBKDF2-200k → account backup key → AES-GCM; no password reset by design); RLS with no policies on
every table (service role only); bucket closed to anonymous API access with uploads/deletes through the
rate-limited function; VAPID and TURN secrets held server-side only; CSP `script-src 'self'` with no
third-party scripts; push notification URLs pinned to the origin server- and worker-side.
