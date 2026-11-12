-- Converts the single-tenant schema (supabase_schema.sql) to multi-tenant:
-- every table gets a user_id owner column, and profile gets a unique
-- username (the slug used in the public URL, e.g. /u/<username>).
-- Paste into the Supabase SQL Editor and run it once.

alter table public.profile add column if not exists user_id uuid references auth.users(id);
alter table public.profile add column if not exists username text;

alter table public.skills add column if not exists user_id uuid references auth.users(id);
alter table public.education add column if not exists user_id uuid references auth.users(id);
alter table public.certifications add column if not exists user_id uuid references auth.users(id);
alter table public.internships add column if not exists user_id uuid references auth.users(id);
alter table public.projects add column if not exists user_id uuid references auth.users(id);

-- Backfill pre-migration rows onto the existing admin account.
-- Replace the email below if your admin account uses a different address.
do $$
declare
  admin_id uuid;
begin
  select id into admin_id from auth.users where email = 'oussamamethnani321@gmail.com';

  if admin_id is not null then
    update public.profile set user_id = admin_id where user_id is null;
    update public.profile set username = 'oussama' where username is null;
    update public.skills set user_id = admin_id where user_id is null;
    update public.education set user_id = admin_id where user_id is null;
    update public.certifications set user_id = admin_id where user_id is null;
    update public.internships set user_id = admin_id where user_id is null;
    update public.projects set user_id = admin_id where user_id is null;
  end if;
end $$;

alter table public.profile
  add constraint profile_username_format check (username ~ '^[a-z0-9-]{3,30}$');

alter table public.profile alter column user_id set not null;
alter table public.profile alter column username set not null;
alter table public.profile add constraint profile_username_unique unique (username);

alter table public.skills alter column user_id set not null;
alter table public.education alter column user_id set not null;
alter table public.certifications alter column user_id set not null;
alter table public.internships alter column user_id set not null;
alter table public.projects alter column user_id set not null;
