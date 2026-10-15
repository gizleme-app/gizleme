# Server side

Gizleme's server is a Supabase project: Postgres (seven small tables), five Edge Functions, Realtime for
live presence/broadcast, and one storage bucket. It holds ciphertext, opaque identifiers and timestamps —
see [SECURITY.md](../SECURITY.md) for what it can and cannot see.

```
supabase/
  migrations/20261015000000_gizleme_schema.sql   tables, RLS, rate-limit functions, Realtime policies, bucket
  functions/gizleme-auth/     accounts: register, salt, login, change password, delete, rename, validate, logout
  functions/gizleme-vault/    encrypted account backup (ABK + contacts/groups/identity blob, versioned)
  functions/gizleme-mbox/     encrypted store-and-forward mailbox, media blob upload/delete, delivery acks, sweeps
  functions/gizleme-push/     Web Push: VAPID key (generated once, kept server-side), register/unregister/notify
  functions/gizleme-turn/     short-lived TURN credentials for calls (Cloudflare Realtime TURN)
```

## Deploying your own

1. Create a Supabase project and apply the migration (`supabase db push`, or paste the SQL in the SQL editor).
2. Deploy the functions with JWT verification **off** (the app has its own session tokens; nothing in the
   project uses Supabase Auth):
   ```
   supabase functions deploy gizleme-auth  --no-verify-jwt
   supabase functions deploy gizleme-vault --no-verify-jwt
   supabase functions deploy gizleme-mbox  --no-verify-jwt
   supabase functions deploy gizleme-push  --no-verify-jwt
   supabase functions deploy gizleme-turn  --no-verify-jwt
   ```
   The functions only need the secrets Supabase injects by default (`SUPABASE_URL`,
   `SUPABASE_SERVICE_ROLE_KEY`).
3. Push notifications: the VAPID keypair is generated on the first call to `gizleme-push` and stored in
   `gizleme_config` (key `vapid`). Nothing to configure. Keep that row: changing the key invalidates every
   existing subscription.
4. Calls behind strict NATs (optional): create a TURN key in Cloudflare (Realtime → TURN), then either set
   the function secrets `CF_TURN_KEY_ID` / `CF_TURN_KEY_TOKEN`, or insert
   `{"id": "...", "token": "..."}` as `gizleme_config` key `turn`. Without it, calls use STUN only.
5. Point the client at your project: `SB_URL` / `SB_KEY` (the project URL and its public anon/publishable
   key) at the top of `app.js`, and the `connect-src` entries in `_headers`.

The storage bucket is public-read **by URL only** (random 48-hex names that travel inside encrypted
messages); the API roles cannot list, upload or delete objects. Do not add policies to the `gizleme_*`
tables: the functions use the service role, and the absence of policies is what keeps the public key out.
