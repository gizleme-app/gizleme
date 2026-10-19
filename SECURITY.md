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

- **Forward secrecy for mailbox messages: weekly, not per message.** The live channel is forward secret
  (fresh ECDH per connection). Mailbox messages for a contact added through a v3 link are encrypted under
  a **one-way key chain**: its root is derived from the ECDH secret of the link opening (`HKDF(secret,
  "gz-chain/v1")`, never from the contact key `ck`, which stays in the vault), moves forward every week
  (`root_{n+1} = HKDF(root_n, "gz-chain/next")`, `key_n = HKDF(root_n, "gz-mbox-key/v2")`), and each
  device keeps only the root of the week two before the current one — the oldest the relay can still hold
  (14 days). Each mailbox item carries its week number in clear (`ep`). Nothing a device or vault holds
  can derive a discarded root, so ciphertext the relay captured earlier than three weeks before a later
  compromise stays unreadable. The chain is used only when both builds support it (link flag `f`, hello
  flag `fs`). A contact that predates the chain gets one at the next live meeting: each side announces in
  presence that it holds no chain for this contact (`fsu`), and when both are live, authenticated under the
  contact key and both still without one, each derives the same root from that session's ECDH secret
  (`HKDF(secret, "gz-chain/live|ck")`) — never sent; the offer stays up for that session so the slower side
  takes the same root, and a device that already got the chain from the account vault no longer offers, so
  two devices of one account normally cannot seed two different chains; should two device pairs still seed
  one in the same moment, both accounts converge on the smaller root at that epoch (the same rule on both
  sides), and a mailbox message that does not decrypt under the chain a device holds is left in the
  mailbox for up to 48 h rather than skipped, so it is read once the vault converges. Until that meeting, such contacts keep the
  static key. What remains: a compromised device
  reads what is still waiting for it (inherent), and a compromise reveals the current three weeks. Per-
  message forward secrecy with per-device ephemeral keys (the Signal model) would end "any device of the
  account reads the mailbox" and stays a separate project. Groups keep a static key (see below).
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
  check for that. Three controls narrow that window: links carry an expiry (`x`, 24 h by default, 1 h to
  7 days — the opener refuses an expired link, the inviter ignores a late hello); an optional 4-digit code
  said by voice (`c`): the hello carries `HKDF(secret, "gz-pin/v1|code")`, which the inviter recomputes —
  the code never appears in the link and cannot be tested offline (it needs the ECDH secret), a wrong code
  is answered with a `nopin` note to that opener and three wrong codes cancel the link; and an in-person QR
  code (generated locally, scanned with the phone camera or the in-app scanner) so the link never transits. A v3 link opened by an older app (one that ignores the public key and signs with the
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
  an offline contact gets a push ("X is calling you"), sent again every 7 seconds while the call rings
  (under one notification tag, so each alert replaces the last) and replaced by "Missed call" if nobody
  answers; the call connects when they open the chat.
- **Groups: signed messages, creator-controlled key rotation.** Every account holds an identity key pair
  (ECDSA P-256 for signatures, an ECDH half for key delivery) that follows it across devices in the vault.
  Group messages are signed (`pk`, `ek`, `sig` inside the ciphertext; the signature covers the group id and
  the whole inner object); members learn each other's keys from the first signed message or the silent
  `hi` sent on joining (trust on first use), show ✓ on messages signed with a member's usual key and flag
  a name that signs with a different key or a broken signature. The relay holds no group key, so it can
  forge nothing; a member impersonating another is flagged. The group's creator is its admin (its identity
  key rides in the group link): it can remove a member or renew the key — a fresh key is sent in the
  group, wrapped for each remaining member under that member's ECDH key; whoever is left out cannot derive
  it, and the room name and mailbox follow the key, so they see nothing more (old invite links die too).
  The previous key stays readable for 14 days so late writers are not lost; messages from removed members
  are dropped. Limits: trust on first use (a member's very first key is not verified against anything);
  groups created before this build have no admin and cannot rotate (create a new one); a member who never
  announced a key (older app) would be locked out by a renewal until they reopen the group; group calls
  are a mesh capped at 4; a 1:1 ring inside a group room is ignored; a group invitation received in a
  chat is joined only when tapped.
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
  WhatsApp (its own `whatsapp://` link on a phone, wa.me on a computer); the v3 design is what limits what a
  copied link gives (see above), but the link itself is seen by that channel like any message you send there.
- **Merging two chats** is a local, user-confirmed step: the earlier chat's history is re-filed under this
  chat's history id on your devices, and its key stays (hidden) only so that what still arrives on it is read.
  No keys are combined, nothing is sent, the other side is not told, and verification marks are not carried
  over as proof of anything — Gizleme never merges on its own, because a matching name proves nothing.
- **Server functions accept calls only from gizleme.com** (CORS), TURN credentials only with a session, and
  the per-account login limit counts wrong passwords only (10 in 15 min pause logins for that name; existing
  devices unlock locally, so a stranger can at most delay a new-device login).
- **Muted chats and the unread count.** Whether a chat is muted (and until when) is stored with the contact or
  group in the encrypted vault. For notifications, the service worker's cache holds — next to the names it
  already kept — the end time of each muted chat, keyed by a hash of its notification key, and the unread
  count. Numbers and times only; the count shown in the tab title and on the app icon is a number, never a name.
- **Reactions and replies** add nothing for the relay to see: a reaction is an encrypted envelope
  `{t:"react", m, e}` and a reply an encrypted text carrying the quoted message id and a snippet of at most
  160 characters, both sent like any message (signed in groups; a group reaction with a broken signature is
  ignored). The snippet is a copy of text the recipient already has; it disappears with the reply.
- **Edits** are an encrypted envelope `{t:"edit", m, x}` sent the same way. A device applies one only to a
  text message from the same author, within 24 hours of it: in a two-person chat, to a message received
  from that contact (or, coming from one of your own devices, to one you sent); in a group, only when it is
  signed by the key that signed the original. The newest edit wins. An edit is a correction, not an unsend:
  the original stays in each device's encrypted local history until the chat's messages expire, and an app
  older than v29 shows the edit as a new message ("✏️ …").
- **Typing indicators** ("typing…", "recording a voice message…") are live-only encrypted signals
  `{t:"typ", s}`, never left in the mailbox: in a two-person chat under the contact's mailbox key and on the
  same relay event as delivery receipts, in a group under the group key. The relay can neither read them nor
  tell them from receipts, but it does see small encrypted events every few seconds while someone types —
  timing metadata that Settings → Privacy → Typing indicators (off: neither sent nor shown) removes. In a group the
  name shown comes from the signal itself, which only members can produce; it is not signed.
- **View-once and disappearing messages are best effort.** They are enforced by the recipient's device;
  nothing stops a screenshot or a modified client. Voice messages are encrypted like a photo (a random key
  inside the message); the ciphertext blob stays on the relay for 14 days, so every member of a group and
  each of your devices can fetch it, and each device keeps its own encrypted copy for replay. A view-once
  photo in a two-person chat is deleted from the relay once it has been viewed.
- **Documents, polls, events.** A document is encrypted on the device under a random key that only travels
  inside the message, split in pieces of at most 1.8 MB (10 MB in all) that the relay stores like photos — it
  sees sizes, never names or contents; the name, type and key are inside the encrypted message. Polls and
  events are ordinary encrypted messages; a vote (or "going / can't go") is a quiet encrypted envelope
  `{t:"vote", m, c}` like a reaction — signed in groups, the newest one per person counts. "Add to calendar"
  builds the .ics file on the device.
- **A chat's timer** is set from its header and applies to both sides: the choice travels as an encrypted
  `{t:"exp", v}` envelope (quiet, like a reaction; signed in groups) and every device applies the newest one.
  A photo is view-once while the timer runs; with the timer off it is sent as a kept photo (`once:false`):
  each device fetches it once and keeps it in its local store, encrypted under the same master key as the
  history, so it stays after the relay's 14-day sweep. A kept photo can be saved (to the gallery, through the
  browser's download or the iPhone share sheet — outside Gizleme's encryption from then on) or forwarded,
  which re-encrypts it under a new key for the other chat. Since either side can turn the timer off, "view
  once" is a shared setting of the chat, not a promise the sender alone controls.
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
  12 alerts per notification key per 10 minutes for messages and 40 for call alerts (a call rings every
  7 seconds; a ringing alert expires after 45 s), fixed bodies ("New message", "Incoming call", "Missed
  call", "A contact wants to chat") — the name is added by the receiving device from a cache keyed by
  hashed notification keys, cleared on log-out.
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
