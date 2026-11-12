-- Adds a per-user animation choice to the profile table: which effect (if
-- any) plays on their public /u/:username page. Run this once in the
-- Supabase SQL editor, then reload the PostgREST schema cache (either via
-- the dashboard's "Reload schema" button, or `NOTIFY pgrst, 'reload schema';`).

alter table profile
  add column animation text not null default 'none';

alter table profile
  add constraint profile_animation_check
  check (animation in ('none', 'fade', 'particles', 'matrix'));
