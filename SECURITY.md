# Security

Gizleme is an end-to-end encrypted messaging web app. This document describes how it is built, what it
protects against, what it does not, and how to report a problem.

## Reporting a vulnerability

Email **admin@gizleme.com**. Please include steps to reproduce. We aim to acknowledge within 72 hours and
to fix confirmed issues before any public disclosure. There is no bug bounty programme at this time.

## Architecture in one paragraph

A single-page web app (`index.html`, `app.js`, no third-party scripts, served with a strict CSP) talks to
four Supabase Edge Functions (`gizleme-auth`, `gizleme-vault`, `gizleme-mbox`, `gizleme-push`) and to
Supabase Realtime for live presence/broadcast. All cryptography runs in the browser with WebCrypto. The
server only ever stores ciphertext, password verifiers, session-token hashes, push subscriptions and
rate-limit counters.

## Cryptography

| Purpose | Primitive |
|---|---|
| Live key agreement | ECDH P-256, fresh key pair per session |
| Key derivation | HKDF-SHA-256 (salt `vesper/v1`, versioned `info` labels per purpose) |
| Message encryption | AES-256-GCM, random 96-bit IV, message id sealed inside the ciphertext |
| Per-message live keys | HKDF(root, `msg|<direction>|<counter>`) — counter must increase, direction must match the paired peer |
| Contact key `ck` | HKDF(first ECDH secret) for room-code contacts. Invite links (v3): the link carries a one-time ECDH public key `p` whose private half stays with the inviter; the opener's device agrees `ck = HKDF(ECDH(eph, p), gz-contact/v3\|ckLink)` at once and leaves a `hello` (its ephemeral public key) in the link's mailbox / presence; the inviter derives the same key. The link key `ckLink = HKDF(secret, gz-invite/v1)` only names that mailbox, the first rendezvous room and a push key — nothing else is ever encrypted under it. Older links (no `p`) still take the v2 path: HKDF(secret) until the first live pairing, then HKDF(session secret, `gz-contact/v2`). Never sent to a server |
| Pairing authentication | HMAC-SHA-256 under HKDF(ck, `gz-auth/v1`) over the session public key; unverified presence entries are never paired with |
| Mailbox | id = HKDF(ck, `gz-mbox/v1`); contents AES-GCM under HKDF(ck, `gz-mbox-key/v1`); sender name and message id inside the ciphertext |
| Receipts | AES-GCM under the mailbox key, 1:1 only |
| Groups | random 256-bit group key `gk` in the invite link fragment; messages AES-GCM under HKDF(gk) |
| Password | PBKDF2-SHA-256, 200,000 iterations, 16-byte random salt → `AK`; server stores `SHA-256(SHA-256(AK))` |
| Account backup | random ABK wrapped with AES-GCM under HKDF(AK, `gz-abk-wrap/v1`); contacts blob AES-GCM under HKDF(ABK, `gz-contacts/v1`) |
| Local storage | contacts/groups/meta blob and message history AES-GCM under a random device master key, itself wrapped by the password (PBKDF2) and optionally by a WebAuthn PRF output (Face ID / fingerprint) |
| Account marker | HKDF(ABK, `gz-acct/v1`) — opaque, replaces the username in presence, mailbox and push records |

## Threat model

**Protected against**

- A passive or active relay/server (including a compromised Supabase project) reading message or photo
  content, or the contact list.
- A relay replaying, reflecting or re-labelling live messages (direction, counter and sealed id checks).
- Someone who merely reaches a room (relay, leaked daily room code) being paired with an existing contact
  (HMAC pairing check with the shared key).
- Online password guessing (per-account and per-IP rate limits), username enumeration via the salt
  endpoint (deterministic fake salts), notification phishing (notification URLs pinned to gizleme.com
  server- and worker-side), push endpoint abuse (allow-listed push services), anonymous storage access
  (bucket closed to the public key; uploads/deletes through a rate-limited function).
- Supply-chain injection through a CDN (no third-party scripts; CSP `script-src 'self'`).
- A device picked up while the app is locked: keys are out of memory; local data is encrypted at rest
  (history, contacts, mailbox cursors and settings that name a chat live under the master key; the local
  database and its indexes use opaque per-chat ids derived from the contact key, never the key itself;
  the lock screen closes every open dialog and clears the rendered chat).
- Cross-account leakage on a shared browser (vault owner check and full wipe on log-out).

**Not protected against (known limitations)**

- **Forward secrecy for mailbox messages.** Messages that go through the mailbox (and every contact
  message does, so offline devices can collect it) are encrypted under the per-contact key. That key is
  known only to the two parties' devices and is never derivable from an invite link (v3), so the remaining
  exposure is a compromised device or account vault reading what still waits in the mailbox: a delivered
  message is deleted by the relay 48 h after any device of the account fetched it (`ack` →
  `delivered_at`, swept), an undelivered one after 14 days. Full forward secrecy — per-device ephemeral
  pre-keys destroyed after use, messages encrypted per device (the Signal model) — is a separate project
  and would end "any device of the account reads the mailbox" as it works today.
- **Invite links are tickets, not keys (v3).** The link carries a one-time public key; the first device to
  open it agrees the contact key by ECDH with the inviter's private half, which never leaves the inviter's
  devices (it rides the encrypted account vault so any of them can complete the agreement). The opener
  announces itself with a `hello` (ephemeral public key + name) in the link's mailbox and in presence; the
  inviter binds the contact to the first hello and discards the private half. Nothing but hellos is ever
  written under the link key: what the inviter writes before the link is opened waits on the inviter's
  device and is sent under the agreed key once the hello arrives. A later hello for the same link — a
  copy in other hands — is not bound: the inviter is warned once, and the late opener is told the link
  was already used (a `used` note addressed to its ephemeral key). The inviter keeps watching the link
  mailbox for 14 days for that purpose. What remains is an impostor who opens the link *before* the real
  invitee: they become the contact, and the in-person safety code (now bound to the v3 agreement) is the
  check for that. A v3 link opened by an older app (one that ignores the public key and signs with the
  link key itself) is not paired with and its messages are not shown — the inviter is told to ask them to
  update. Pending invitations created by pre-v3 builds keep the v2 path: bearer until the first live
  pairing (the peer proves the link key with a second HMAC, `tagp`), then rotated; while that rotation is
  reconciled the rotated side still deposits a copy under the link key so a peer who has not rotated yet
  stays reachable — the last remaining writes under a link key, and only for those legacy invitations.
- **Calls reveal IP addresses to the other party.** Media is peer-to-peer (DTLS-SRTP, keyed on the
  wire by the two devices; the fingerprints are exchanged inside the chat's encrypted, authenticated
  channel, so the relay cannot sit in the middle). Like any P2P call, each side learns the other's IP
  address — unless a TURN relay carries the media, which is also what makes calls work when both phones
  are behind strict (carrier-grade) NATs. TURN is on (Cloudflare): the `gizleme-turn` function holds the
  long-term TURN key server-side (function secrets `CF_TURN_KEY_ID` / `CF_TURN_KEY_TOKEN`, or the
  service-role-only `gizleme_config` row, like the VAPID key — never in source or in the client) and hands
  out short-lived credentials; the relay only ever forwards ciphertext. Group calls are a mesh (every
  participant to every other), capped at 4. A web app cannot ring while closed the way a phone app does:
  an offline contact gets a push ("X is calling you") and the call connects when they open the chat.
- **Groups have no sender authentication and no key rotation.** Any member or the relay could re-label a
  group message; leaving a group does not revoke the key. Create a new group to exclude someone. The same
  holds for group calls: any member can announce or join one (mesh, capped at 4); a 1:1 ring sent inside a
  group room is ignored. A group invitation received in a chat is a card — the group is joined only when
  the recipient taps it.
- **Login proof is replayable.** The client proves the password with a static value (`av`, the hash of the
  PBKDF2 key); the server stores its hash. Someone who captures `av` in transit (a broken TLS session) could
  replay it. Replacing it with an aPAKE (OPAQUE) is planned together with the KDF upgrade below.
- **Offline password guessing by the server.** The verifier is derived with PBKDF2-200k; a weak password
  can be brute-forced from a database leak, which would then unlock that account's backup (contact keys).
  Use a long password. A memory-hard KDF or an aPAKE is a planned upgrade.
- **Metadata.** The relay sees connection timing, IP addresses, mailbox identifiers (opaque) and traffic
  volume. Co-presence in a room reveals that two opaque identities talk. Presence also carries, in clear,
  the display name each person chose and an opaque per-account marker (how one's own devices recognise
  each other), so the relay can tell which rooms one account is present in and the name it shows there
  (not the username). Inside the mailbox that marker is sealed in the ciphertext; the relay sees only the
  mailbox id, a random message id, the timestamp and the delivery time. Push subscriptions link a device
  endpoint to the per-contact notification keys and the account marker. Presence fields other than the
  signed public key (name, marker, call announcements) are not authenticated by the contact key.
- **Invite links travel through whatever you share them with.** "Share on WhatsApp" hands the link to
  wa.me; the v3 design is what limits what a copied link gives (see above), but the link itself is seen by
  that channel like any message you send there.
- **View-once and disappearing messages are best effort.** They are enforced by the recipient's device;
  nothing stops a screenshot or a modified client. Voice messages follow the photo path (random key inside
  the message, ciphertext blob deleted from the relay after the first fetch) and are then kept encrypted
  in the recipient's local store for replay; like photos, a second device of the same account that did not
  fetch the blob first cannot play it.
- **Web delivery.** Code is delivered at each load; a compromised origin could serve malicious code. The
  CSP, HSTS and the absence of third-party scripts limit, but do not remove, this trust in the host.
- **Screenshots and the operating system.** No web app can prevent screenshots or protect against a
  compromised OS or browser.

## Server-side controls

- Five Edge Functions (`gizleme-auth`, `gizleme-vault`, `gizleme-mbox`, `gizleme-push`, `gizleme-turn`) use
  the service-role key; tables have RLS enabled with no policies (reachable only through the functions).
  Storage bucket policies deny anonymous INSERT/SELECT/DELETE through the API (uploads and deletions go
  through the rate-limited mailbox function); the bucket itself is public-read by URL, which is how the
  recipient fetches a photo: anyone holding a blob's 48-hex random name — which only travels inside the
  encrypted message — can download its ciphertext, and nothing else.
- Rate limits (Postgres counter, service-role only): login 60/15 min per IP and 10 *failed* attempts/15 min
  per account (a success gives the budget back, so a stranger cannot lock the owner out), password change
  and deletion 10/15 min per account, register 10/h per IP, salt/check 60/min per IP, notify 12/10 min
  per key + 120/10 min per IP, mailbox puts 120/min per mailbox + 300/min per IP, gets/acks 400/min per
  IP, blob uploads 30/min per IP, TURN credentials 40/10 min per IP. There are no per-account storage
  quotas beyond these.
- Push: endpoints restricted to the browser push services, at most 8 devices woken per notification key,
  fixed bodies ("New message", "Incoming call", "A contact wants to chat") — the name is added by the
  receiving device from a cache keyed by hashed notification keys, cleared on log-out.
- TURN: short-lived credentials (15 min) minted by the function from a server-side key and shared by all
  callers for 2 minutes; a credential only lets someone relay ciphertext through Cloudflare's TURN.
- Password change and account deletion require both the session token and the current password.
- The `check` action of registration reveals whether a username is taken (60/min per IP); the `salt`
  action does not.
- Server error responses may echo database error strings (no secrets, but not yet generic).
- HTTP headers: CSP (`script-src 'self'`), HSTS, X-Frame-Options DENY, Referrer-Policy no-referrer,
  Permissions-Policy, COOP same-origin.

## Data retention

See [privacy.html](https://gizleme.com/privacy.html).

## Audits

An internal audit (protocol, server, client) was carried out in October 2026 before any wider release;
findings, fixes and the open items are in [AUDIT.md](AUDIT.md). No independent audit yet.
