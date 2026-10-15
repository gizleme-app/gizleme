-- Gizleme — Copyright (C) 2026 Oğuz Seran — SPDX-License-Identifier: AGPL-3.0-only — see LICENSE
--
-- The whole server-side schema. Every table is reachable only through the Edge Functions (service role):
-- RLS is on with no policies, and the API roles (anon, authenticated) hold no table privileges at all.
-- The relay stores ciphertext, opaque identifiers and timestamps — nothing it can read (see SECURITY.md).

create table public.gizleme_accounts (
  username_lc text primary key,               -- lowercase username (3–20 chars)
  display text not null,                      -- display name shown to contacts (chosen by the user)
  salt text not null,                         -- PBKDF2 salt (base64)
  verifier text not null,                     -- SHA-256 of the client-side password proof
  created_at timestamptz not null default now()
);
create table public.gizleme_sessions (
  token_hash text primary key,                -- SHA-256 of the session token (the token itself is never stored)
  username_lc text not null references public.gizleme_accounts(username_lc) on delete cascade,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null
);
create index gizleme_sessions_user on public.gizleme_sessions(username_lc);
create table public.gizleme_vault (
  username_lc text primary key references public.gizleme_accounts(username_lc) on delete cascade,
  abk jsonb,                                  -- account backup key, wrapped under the password-derived key (set once)
  contacts jsonb,                             -- contacts, groups and identity key, encrypted under the ABK
  cver integer not null default 0,            -- optimistic concurrency version
  updated_at timestamptz not null default now()
);
create table public.gizleme_mbox (
  id bigint generated always as identity primary key,
  mbox text not null,                         -- mailbox id: HKDF of a secret shared by the two parties (opaque)
  mid text not null,                          -- random message id chosen by the sender
  from_user text,                             -- unused since v4 (the sender marker is sealed in the ciphertext)
  data jsonb not null,                        -- {iv, ct[, ep]} — AES-GCM ciphertext; ep = which week's chain key
  ts timestamptz not null default now(),
  delivered_at timestamptz                    -- set by "ack": a device of the account fetched it; swept 48 h later
);
create index gizleme_mbox_box on public.gizleme_mbox(mbox, ts);
create unique index gizleme_mbox_uniq on public.gizleme_mbox(mbox, mid);
create index gizleme_mbox_delivered_idx on public.gizleme_mbox(delivered_at) where delivered_at is not null;
create table public.gizleme_push_subs (
  notify_key text not null,                   -- per-contact notification key (HKDF of the contact key)
  owner text not null,                        -- random per-device id
  sub jsonb not null,                         -- Web Push subscription (endpoint restricted to browser push services)
  name text,                                  -- unused since v5 (names are never sent)
  updated_at timestamptz not null default now(),
  acct text,                                  -- opaque per-account marker (so a sender's own devices are not woken)
  primary key (notify_key, owner)
);
create index gizleme_push_subs_nk on public.gizleme_push_subs(notify_key);
create table public.gizleme_config (
  key text primary key,                       -- "vapid" (keypair, generated on first push), "authsecret", "turn", "mediasweep"
  value jsonb not null,
  updated_at timestamptz not null default now()
);
create table public.gizleme_rl (
  k text primary key,                         -- rate-limit counter key ("auth:loginip:<ip>", "mbox:put:<mbox>", …)
  n integer not null default 0,
  ws timestamptz not null default now()
);
alter table public.gizleme_accounts enable row level security;
alter table public.gizleme_sessions enable row level security;
alter table public.gizleme_vault enable row level security;
alter table public.gizleme_mbox enable row level security;
alter table public.gizleme_push_subs enable row level security;
alter table public.gizleme_config enable row level security;
alter table public.gizleme_rl enable row level security;
revoke all on public.gizleme_accounts, public.gizleme_sessions, public.gizleme_vault, public.gizleme_mbox,
  public.gizleme_push_subs, public.gizleme_config, public.gizleme_rl from anon, authenticated;

-- fixed-window rate limiter, callable by the service role only
create or replace function public.gz_rl_hit(p_key text, p_limit integer, p_window_s integer)
 returns boolean language plpgsql security definer set search_path to 'public' as $$
declare v int;
begin
  insert into gizleme_rl(k, n, ws) values (p_key, 1, now())
  on conflict (k) do update set
    n  = case when gizleme_rl.ws < now() - make_interval(secs => p_window_s) then 1 else gizleme_rl.n + 1 end,
    ws = case when gizleme_rl.ws < now() - make_interval(secs => p_window_s) then now() else gizleme_rl.ws end
  returning n into v;
  if random() < 0.01 then delete from gizleme_rl where ws < now() - interval '1 day'; end if;
  return v <= p_limit;
end $$;
-- a successful login gives one failed-attempt unit back (so a stranger cannot lock an account's owner out)
create or replace function public.gz_rl_undo(p_key text)
 returns void language plpgsql security definer set search_path to 'public' as $$
begin
  update gizleme_rl set n = greatest(n - 1, 0) where k = p_key;
end $$;
revoke all on function public.gz_rl_hit(text,integer,integer) from public, anon, authenticated;
revoke all on function public.gz_rl_undo(text) from public, anon, authenticated;
grant execute on function public.gz_rl_hit(text,integer,integer) to service_role;
grant execute on function public.gz_rl_undo(text) to service_role;

-- Realtime: private channels "ratchet-<room>" (presence + broadcast) for the public key; messages are
-- end-to-end encrypted by the clients, the relay only forwards them
create policy ratchet_select on realtime.messages for select to anon, authenticated using (realtime.topic() like 'ratchet-%');
create policy ratchet_insert on realtime.messages for insert to anon, authenticated with check (realtime.topic() like 'ratchet-%');

-- Storage: encrypted media blobs (photos, voice messages) under random names. Public-read by URL (the name
-- only travels inside the encrypted message); the API roles cannot list, upload or delete — uploads and
-- deletions go through the rate-limited mailbox function
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('vesper-media', 'vesper-media', true, 8388608, array['application/octet-stream']);
create policy vesper_media_select on storage.objects for select to anon, authenticated using (false);
create policy vesper_media_insert on storage.objects for insert to anon, authenticated with check (false);
create policy vesper_media_delete on storage.objects for delete to anon, authenticated using (false);
