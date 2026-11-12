-- Adds: a languages table (spoken languages + proficiency, same shape as
-- skills), a cover/banner photo on profile, an email field for the new
-- Contact section, and widens section_config's recognized keys to include
-- 'languages', 'stats' (computed, no new columns needed) and 'contact'.
-- Run this once in the Supabase SQL editor, then reload the PostgREST
-- schema cache.

create table public.languages (
  id uuid not null default gen_random_uuid(),
  language text not null,
  level integer not null,
  sort_order integer not null default 0,
  updated_at timestamp with time zone not null default now(),
  user_id uuid not null references auth.users(id),
  constraint languages_pkey primary key (id)
);

alter table profile
  add column email text,
  add column cover_url text,
  add column cover_enabled boolean not null default false;
