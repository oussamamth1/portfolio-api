-- Expands theme/animation choices and adds avatar/text size controls.
-- Run this once in the Supabase SQL editor, then reload the PostgREST
-- schema cache (dashboard "Reload schema" button, or
-- `NOTIFY pgrst, 'reload schema';`).

alter table profile drop constraint if exists profile_theme_check;
alter table profile add constraint profile_theme_check
  check (theme in ('amber', 'violet', 'emerald', 'crimson', 'azure', 'rose', 'slate', 'ocean'));

alter table profile drop constraint if exists profile_animation_check;
alter table profile add constraint profile_animation_check
  check (animation in ('none', 'fade', 'particles', 'matrix', 'tilt'));

alter table profile
  add column avatar_size text not null default 'medium',
  add column text_size text not null default 'medium';

alter table profile
  add constraint profile_avatar_size_check check (avatar_size in ('small', 'medium', 'large'));

alter table profile
  add constraint profile_text_size_check check (text_size in ('small', 'medium', 'large'));
