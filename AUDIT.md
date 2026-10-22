# Internal security audit — October 2026

Scope: the whole system as deployed at gizleme.com — the protocol and client state machine (`app.js`,
`sw.js`), the server side (five Supabase Edge Functions, Postgres schema and RLS, storage bucket,
Realtime) and the client application (lock, storage at rest, deep links, media, headers).

Method: three independent reviews, each by a reviewer who had not written the code and did not see the
other reviews, working from the source and from the live project (functions, policies and bucket
settings were verified live, not from documentation). Findings were then fixed in one pass and the
regression suite (Playwright, 15 end-to-end scenarios against an emulated relay and mailbox) was extended
to cover each fix (a second pass on 17 October is recorded below). This is an internal audit: it is not an independent one, and it does not replace one.

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
| M8 | Medium | Gizleme shared its Supabase project with an unrelated application (one service-role key, one database, one storage account), plus two obsolete functions. | **Fixed (15 Oct 2026).** Gizleme now runs in a project of its own (schema recreated with the API roles holding no table privileges at all; data and media copied server-to-server and verified by digest; same VAPID key, so existing push subscriptions kept working). The old project's `gizleme-*` functions were removed; its tables are kept for a week as a fallback, then dropped; rotating the old project's service-role key is on the owner. |
| L1 | Low | Set-once ABK / `cver` are check-then-write races. | **Fixed** (R7: conditional updates). |
| L2 | Low | Password change is two non-atomic calls. | **Fixed** (R6: one SQL transaction). |
| L3 | Low | Error responses may echo backend error strings. | Open (no secrets involved). |
| L4 | Low | Sweeps run on every request. | Open (cheap; indexed). |
| L5 | Low | Input normalisation accepts anything; login skips the username regex. | Open (the lookup is by exact lowercase key; no injection path). |
| L6 | Low | Push text was free text from the sender when the receiver did not know the key. | **Fixed** (fixed bodies). |
| L7 | Low | One member can jam a shared mailbox (rate limit is per mailbox). | Open (documented with the group model). |
| L8 | Low | Account deletion relies on client-supplied device ids to clean push registrations. | Open (the account marker also deletes by `acct`). |
| L9 | Low | "Deleted when viewed" blobs may survive briefly in the CDN cache. | Open (documented as "at the latest after 14 days"). |
| L10 | Low | `check` reveals whether a username is taken. | **Documented** (needed for sign-up; rate-limited; `salt` does not reveal it). |
| L11 | Medium | Found during publication prep (15 Oct): the deploy uploaded the whole checkout, so gizleme.com served `/.git/` (config, index, objects) and `wrangler.jsonc`. No credential was in them (plain remote URL; the history holds no secret — checked), but the source and history were readable before publication. | **Fixed.** `.assetsignore` excludes `.git`, the docs, tests, server code and config; verified 404 live. |

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

## Second pass — 17 October 2026

Six parallel reviews of the code as deployed that morning (invites and key chain; mailbox and history; UI,
media and calls; sessions, vault and lock; service worker and page; server functions), each by a reviewer
who had not written the code. Everything below was fixed the same day and is covered by test47 (and
updated test20/test33); the suite is now 30 scenarios.

| # | Sev. | Finding | Status |
|---|------|---------|--------|
| R1 | High | The mailbox key chain's starting week (`kce`) was chosen by each side at its own time: an inviter reading the hello in a later week than the opener held the same root one week behind, so every chain-encrypted offline message between the two failed to decrypt (silently dropped after 48 h). | **Fixed.** The hello carries the opener's week (`ke`); the inviter counts the chain from it. |
| R2 | High | The group creator's key renewal was never wrapped for the creator's own identity: the creator's other devices were told "removed from this group" (live) or stayed on the old key (mailbox), and the vault did not carry the new key. | **Fixed.** Self-wrap; own `gk2` applied from the mailbox; `ts` bumped so the vault carries `gk/rot/rotFp/prevGk`. |
| R3 | High | A contact removed (or a group left) on one device came back from the other device at the next vault merge, and its mailbox was read again. | **Fixed.** Tombstones (`gone`, in the vault blob): a record saved before its removal stays removed; one saved after wins. |
| R4 | High | The service worker stored any navigated page as the offline shell (a visit to the privacy page replaced the app); a tapped notification did not open the chat when a window was already open (hash-only navigate). | **Fixed.** Only `/` is the shell; the worker tells the open window which chat to open. |
| R5 | High | Voice-message (and group photo) blobs were deleted from the relay by the first fetch: other group members and the recipient's or sender's other devices got "expired". | **Fixed.** The relay's 14-day sweep is the only deletion for voice and group photos; 1:1 view-once photos are still deleted by the viewer. |
| R6 | Medium | Password change was two requests (verifier, then the re-wrapped backup key) and the second's result was ignored: a new device could log in but never open the backup. | **Fixed.** One request, one SQL transaction (`gz_change_password`). |
| R7 | Medium | Vault `pushContacts` was check-then-write: two devices pushing from the same base both "won", last writer silently overwrote. Same for the set-once backup key. | **Fixed.** Conditional update on the version (and on `abk is null`). |
| R8 | Medium | TURN credentials (paid relay minutes) were minted for anyone; per-account login limit counted every attempt (a stranger could lock the owner out of new-device logins); push registrations for removed contacts were never pruned; VAPID/auth-secret first-run race; mailbox ids unvalidated; non-base64 input gave 500s; retention sweep ran unindexed on every request; `Access-Control-Allow-Origin: *`. | **Fixed.** Session required for TURN; only wrong passwords count; the registration list is authoritative per device; insert-if-absent then re-read; id shapes enforced; guarded decoding; `(ts)` index + sampled background sweep; origin pinned to gizleme.com. |
| R9 | Medium | Client: a fresh group link after a removal was ignored ("rotated key beats an old link"); a failed hello deposit was never retried; a copied invite link was not persisted; `used`/`nopin` notices read while the chat was closed were silent; removing a chat left its unread count on the icon; two readers of one mailbox could deliver a message twice; own messages read before the account marker was restored; queued invite messages never retried; lock dropped the pending save and vault push; receipts accepted from a link mailbox; auto-lock cut calls; the update check reloaded the New-chat screen; a rejoin timer outlived its room; a recording followed you to another chat; a second call start leaked a mic stream; early ICE candidates dropped; voice playback on a muted iPhone went silent after 1.5 s; peer names unbounded. | **Fixed.** |
| R10 | Low | Merge inherited the ✓ verified mark onto an unverified key; `identAdopt` left two devices with different group ECDH keys; a re-invited member stayed on the removed list; any link could name an admin on a legacy group; image envelopes unvalidated; call buttons shown in audio calls; toast under modals; duplicate SVG id; `_chainCache` survived lock. | **Fixed.** |

## Third pass — 21–22 October 2026 (full review, v41–v45)

Five parallel reviews of the whole application (security, code, UX, performance, tests and maintenance)
by reviewers who had not written the code; the plan that came out of it runs from v41 to v45. v41 took the
urgent fixes (a long chat froze the app, a photo burst could land in the wrong chat, a message written
offline was lost, the delete-account dialog's Cancel, a notification could open an invite link, docs that
no longer matched the code). v42 took the security findings below, covered by test58 (and test19, test37,
test38 updated); the suite is 41 scenarios.

| # | Sev. | Finding | Status |
|---|------|---------|--------|
| S1 | High | A group key rotation (`gk2`) carried neither a number nor a link to the key it replaced, and the ids a chat had seen were forgotten at each lock: a removed member could re-seal the admin's earlier, signed rotation under a key it still held and take the group back to it. | **Fixed.** `rc` (rotation number) and `p` (previous fingerprint) are signed into every gk2; members keep the count and every key fingerprint the group has used (vault-synced) and refuse a rotation numbered at or below theirs or naming a used key; seen ids persist 14 days (`_meta.sids`, encrypted). |
| S2 | Medium | Signed group envelopes had no sender clock; any old one could be re-deposited as new. | **Fixed.** `sts` is signed; older than 16 days (or missing, after 2026-12-15) → dropped. |
| S3 | Medium | A password change deleted the other sessions server-side but no device ever asked (`validate` was never called), so a lost device kept reading. | **Fixed.** `validate` at each unlock, on coming online and to the front; a revoked session wipes the device. The toast says what now happens. |
| S6/S8 | Medium/Low | `putblob` (an anonymous file host), `delblob` and `ack` took no session. | **Fixed.** The session token is required (grace for older builds until 2026-12-15); 150 uploads/h per account. |
| S7 | Medium | The push subscription table held one notification key under both contacts' account markers — a social graph. | **Fixed.** Per-direction keys (inviter / opener), registered by their own side only, no sender marker; v1 key kept for role-less records and registered until 2027-02-01 for older builds. |
| S10 | Low | The opener's hello was not bound to its own fields (a copy with the chain offer stripped would downgrade forward secrecy). | **Fixed.** `h = HKDF(secret, "gz-hello/v1|fs|ke|m")`; required after 2026-12-15. |
| S14 | Low | At lock, hidden dialogs kept their text (safety code, members and fingerprints, caller name, merge previews). | **Fixed.** Emptied in `lockApp`. |
| S19 | Low | A group's disappearing timer and "X is typing" were accepted unsigned. | **Fixed.** Group typing is signed; exp/react/vote/edit/del need `vf==="ok"`. |

v43 took the performance review (measured on an iPhone-class CPU 4× slower and a slow 4G, see the review's
numbers in the plan): covered by test59, test57 updated.

| # | Sev. | Finding | Status |
|---|------|---------|--------|
| P1 | Critical | Every 20 s, one relay call per chat (two during reconciliation) and the whole history of each closed chat decrypted again: 200 chats = 201 calls and 22 s per pass; 1 contact = 8 640 calls a day. | **Fixed.** One `getmany` call per pass for all mailboxes (150 a call); the seen ids seeded once per unlock; the pace follows activity (20 s alive, 45–60 s quiet, 120 s hidden). |
| P2 | High | Nothing on screen before 800 KB of JavaScript had run (first content at 4.9 s on slow 4G). | **Fixed.** `boot.js` draws the unlock / log-in / welcome card at once from what the device holds, in its language; the password can be typed meanwhile. |
| P3 | High | Service worker network-first for everything: an installed app made ≥10 revalidation requests before showing anything (2.0 s on slow 4G vs 0.8 s offline). | **Fixed.** Versioned URLs (`?v=NN`, `tools/build.py`), cache-first for the shell files, a year of CDN cache, the page and `sw.js` revalidated; precache fetched past the HTTP cache; the install fails only on the critical files. |
| P4 | High | The chats list rebuilt every row at every render (31 call sites) and re-read every chat's last message each time; `contactFind` copied the whole list (52 call sites). | **Fixed.** Rows kept when their signature is unchanged (moved, not rebuilt); previews re-read only for chats whose history changed; an index by key. |
| P5 | Medium | A 2 000-message chat rendered 8 768 nodes at once (after v41's one-scroll fix: 3.6 s / 6.6 s). | **Fixed.** The last 150 records at once, earlier ones by pages from the top (button or scroll); a search loads the whole chat first. |
| P6 | Medium | `app.js` 400 KB unminified parsed at each start (≈80 % of start-up CPU); `qrcode.js` loaded for a rarely used button; 203 KB of PNG for 35 KB of WebP; a 21 KB favicon in the head. | **Fixed.** `app.min.js` (261 KB, 85 KB gzipped) built by `tools/build.py`, hash-checked by test59 and smoke-tested; QR library on demand; WebP logos and watermark; favicon as a link. |
| P7 | Medium | The 15-second sweep walked every bubble and ran an IndexedDB cursor over the whole chat even when nothing could expire; the welcome halos animated forever under a backdrop blur; `will-change` kept a compositing layer per big emoji. | **Fixed.** The sweep looks at the oldest bubble first and sweeps the store every 5 minutes; halos play twice then rest (none with reduced motion); `will-change` only while an emoji plays. |
| P8 | Medium | No `storage.persist()` (Safari drops the data of an uninstalled site after 7 days); `theme-color` fixed dark. | **Fixed.** Persistence asked at first unlock; the theme colour follows the scheme and the toggle (dark on the always-dark first screens, v44). |

v44 took the UX and accessibility review (WCAG 2.2 AA; axe-core, measured contrasts and targets): covered by
test60; tests 20, 21, 24, 37, 41, 46, 48, 57 updated (the browser's dialogs are gone).

| # | Sev. | Finding | Status |
|---|------|---------|--------|
| U1 | Blocking | Keyboard and screen readers could not use the app: list rows and bubbles not focusable, 15 of 17 dialogs without a role, no focus management, Escape ignored by most dialogs and the ⋮ menu. | **Fixed.** Rows are buttons with a spoken name; bubbles focusable with a keyboard menu; one keeper gives every dialog its role, name, focus in / kept / back; Escape closes the dialog or menu on top. |
| U2 | Major | Native `confirm()` / `prompt()` for twelve questions, a double confirmation to delete the account. | **Fixed.** The house dialog (`gzAsk`) with translated, named buttons and a red destructive one; the delete-account dialog is its own confirmation. |
| U3 | Major | Three meanings of pill in Settings, no `aria-pressed` / `role="switch"`. | **Fixed.** Switches with `aria-checked` for typing, previews, privacy screen, notifications; the theme pill says what it switches to. |
| U4 | Major | `#logs` entirely `aria-live` (noise); toasts, sign-in errors and the call status silent; photos without `alt`. | **Fixed.** No live region on the log; `role="status"` on the toast and the call status, `role="alert"` on the sign-in message; `alt` on photos. |
| U5 | Major | Contrast under 4.5:1: sent-bubble time and ticks, quotes, the offline banner (light), the comparison table's green, the signature tick. | **Fixed.** Sent meta at .92 with white ticks, quotes at full opacity, banner `#f59e0b` on `#111` (8.8:1), green `#15803d`; the signature tick is gone (a problem is what gets a mark). |
| U6 | Major | Targets: a 15×20 px destructive cross on every list row, 28 px header buttons, 38 px list-header buttons, 23 px reaction chips, 24 px "Remove". | **Fixed.** The cross is gone (Chat info has the action); header buttons 40×44, list header 44×44 on phones, chips ≥ 26, "Remove" ≥ 32. |
| U7 | Major | The attachments panel truncated its labels at 1.4× and in Turkish (4+2 tiles); a muted microphone was a colour only; a voice recording had no clock and sent itself at two minutes. | **Fixed.** 3×2 tiles with wrapping labels; mic-off icon, label and `aria-pressed`; clock `m:ss / 2:00` and a stop at the cap that waits for Send or Cancel. |
| U8 | Minor | Terminology: conversation/discussion, app/appli/application, vocal/audio, localisation/position; English colour names read by VoiceOver; the iOS diagnostic line shown to everyone; orphan day separators after messages expire; "Lock now [Lock]". | **Fixed.** One word each in French, two Turkish sentences reworded, colour names translated, the diagnostic line behind `?debug=1` or a long press, orphan separators removed by the sweep, "Verrouiller maintenant". |

v45 took the code review's robustness findings (the ones v41 had left): covered by test61.

| # | Sev. | Finding | Status |
|---|------|---------|--------|
| C6 | Medium | Removing a contact or leaving a group left its messages, media, timer and seen ids on the device until log-out. | **Fixed.** `histPurgeRoom`: IndexedDB records and media (by room), `gz-exp-rooms` / `gz-exp-ts`, `_meta.sids`, the preview. |
| C7 | Medium | A vault 401 (session deleted by a password change elsewhere, or expired) was swallowed: the device kept working on its cache and never said why nothing synced. | **Fixed.** `vaultFn` sees the 401, validates the session (twice before signing out, as v42) and, if the session stands, says it once. |
| C8 | Medium | A member removed, then invited back with a newer link, read the previous key's mailbox for 14 days and found the old rotation that excluded them — thrown out again. | **Fixed.** Rejoining from `left` sets no `prevGk`; a rotation read from a previous key's mailbox can't mean "removed" (`cur` flag through `fetchMailboxId`). |
| C9 | Medium | Nothing watched the UTC day change: a chat left open stayed in yesterday's rendezvous room while the other side, opening after midnight, found an empty one. | **Fixed.** A timer at 00:00 UTC (+2.5 s) and a check at each mailbox pass move every open contact chat to the day's room (`rolloverRooms`, `moveRoomSoon(R, true)`). |
| C10 | Medium | A `blob:` URL per rendered photo, never revoked (kept alive until reload); every document decrypted at render. | **Fixed.** Revoked when the bubble leaves (leave, lock, sweep); documents over 1 MB decrypted on the tap. |
| C11 | Medium | The first vault pull had no second chance: offline or a 5xx at log-in left a new device on the empty state until the next log-in. | **Fixed.** The password-derived key stays in memory until the backup opens; retried on "online" and at each pass; the empty list says so. |
| C12 | Low | A message deposited while the account marker was unknown (backup not yet opened) reached the account's other devices as the contact's. Also the pull at unlock raced the cached key: `recoverABK` found `gABK` set before `gContactsKey` was and `syncPull` skipped. | **Fixed.** Signed in and no marker → the message waits in the queue (sent once the backup opens); `setABK` exposes a promise that `syncPull` and the recover paths await. |
| C13 | Low | Composer re-enabled in a group one was removed from; one draft shared by every chat; `histLast` in insertion order (the list's preview could be an older message caught up late); `inviteT` and `_syncT` cleaned by accident of `call` / `clearTimeout`; a corrupt unlock record read as a wrong password; a pairing bumped the contact's `ts` (a removed contact could come back through the merge); a mailbox row without its chain key held the cursor forever. | **Fixed.** `composerFor` on rotation and switch; `R._draft`; DB v3 `[room, ts]` index; the interval captures its call; `localFlush`; "unlock record unreadable — log in again"; `ts` bumped only when the name changes; the hold is 48 h; a write that fails (storage full) is said once; `_meta` is flushed when the page hides. |

v46 took the tests-and-maintenance review's findings (the ones v41 had left): covered by `tests/edge/` and
the suite itself.

| # | Sev. | Finding | Status |
|---|------|---------|--------|
| T1 | High | `import cv2` in test35 with OpenCV absent from every install line: CI red by construction. | **Fixed.** `opencv-python-headless` in the workflow, CONTRIBUTING and tests/README. |
| T2 | High | No test of the Edge Functions (633 lines), no `deno check`; the scenarios' mocks never answer an error. | **Fixed.** `tests/edge/`: a stand-in for supabase-js (tables, unique keys, rpc, storage) and web-push; 31 tests drive the five handlers unchanged — accounts, sessions, limits, the batched mailbox read, blobs and acks with the session, the vault's set-once key and versioned contacts, push endpoints and targets, TURN; a CI job type-checks and runs them. Two small things they found: a renamed display name could end in a space, a malformed `av` to the vault was a 500 instead of a 401 (gizleme-auth v4, gizleme-vault v3). |
| T3 | High | The harness copied in 39 files (3 900 lines), already diverging. | **Partly.** `tests/harness.py` holds what every scenario does the same way (the conditional waits); each scenario keeps its own relay/mock where it needs its own. |
| T4 | Medium | 51 checks held a string or a list and could not fail. | **Fixed.** Equality with the expected value, or `_v` for a value kept for the eye; `run.py` counts any other non-boolean as an error of the scenario. |
| T5 | Medium | 703 s of fixed waits; under load 12 scenarios of 39 failed on timing. | **Fixed where it bit.** The sign-in waits are conditional (`entered`), the contexts run in one time zone, the pairing-then-write scenarios settle; `run.py` keeps every scenario's output and prints the whole RESULTS block on a failure. |
| T6 | Medium | 236 rules in "v36–v40" blocks at the end of the stylesheet, 20 selectors declared twice, 25 properties rewritten by the cascade. | **Fixed.** The later declarations of a selector merged into its first rule, in cascade order, only where no rule in between could contest the property (779 → 759 rules, 33 → 15 repeated selectors, the rest groups). |
| T7 | Low | `app.js` as one file with no module boundary. | **Not done** — CONTRIBUTING says the one file is on purpose, so that the whole client can be read top to bottom; a split is the owner's call. |

## What is deliberately not fixed yet (roadmap)

1. **Forward secrecy for the mailbox** — done at week granularity on 15 Oct 2026 (one-way key chain per
   contact seeded from the link-opening ECDH, advanced weekly, old roots destroyed; see SECURITY.md). Per-
   message secrecy with per-device ephemeral pre-keys (Signal model) remains the long-term option.
2. **aPAKE login (OPAQUE) and a memory-hard KDF** — removes the replayable `av` and raises the cost of
   offline guessing from a database leak.
3. ~~Group sender authentication / key rotation~~ — done 15 Oct 2026 (signed messages, creator-driven
   rotation and removal; see SECURITY.md). Authenticated presence remains open. Rotations are ordered and
   replay-proof since v42.
4. ~~Own Supabase project (M8)~~ — done 15 Oct 2026.

## Verified as sound

ECDH P-256 + HKDF + AES-GCM with per-direction counters; HMAC pairing check under the contact key; the
vault (PBKDF2-200k → account backup key → AES-GCM; no password reset by design); RLS with no policies on
every table (service role only); bucket closed to anonymous API access with uploads/deletes through the
rate-limited function; VAPID and TURN secrets held server-side only; CSP `script-src 'self'` with no
third-party scripts; push notification URLs pinned to the origin server- and worker-side.
