-- Gizleme — Copyright (C) 2026 Oğuz Seran — SPDX-License-Identifier: AGPL-3.0-only — see LICENSE
--
-- 1. A password change writes the new verifier AND the account backup key re-wrapped under the new password in
--    one transaction: one without the other leaves a new device able to log in but unable to open the backup
--    (or the reverse). Callable by the service role only (gizleme-auth).
create or replace function public.gz_change_password(p_user text, p_salt text, p_verifier text, p_abk jsonb)
 returns boolean language plpgsql security definer set search_path to 'public' as $$
begin
  update gizleme_accounts set salt = p_salt, verifier = p_verifier where username_lc = p_user;
  if not found then return false; end if;
  if p_abk is not null then
    insert into gizleme_vault (username_lc, abk, updated_at) values (p_user, p_abk, now())
    on conflict (username_lc) do update set abk = excluded.abk, updated_at = now();
  end if;
  return true;
end $$;
revoke all on function public.gz_change_password(text, text, text, jsonb) from public, anon, authenticated;
grant execute on function public.gz_change_password(text, text, text, jsonb) to service_role;

-- 2. The retention sweep deletes by ts; without this index it scanned the whole mailbox table on every request.
create index if not exists gizleme_mbox_ts on public.gizleme_mbox(ts);
