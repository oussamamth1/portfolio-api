-- Schema for the portfolio API, inferred from src/*/*.service.ts and dto/*.ts.
-- Paste this into the Supabase dashboard's SQL Editor and run it once.

create table if not exists public.profile (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  title text not null,
  tagline text,
  bio text,
  phone text,
  avatar_url text,
  resume_url text,
  updated_at timestamptz not null default now()
);

create table if not exists public.skills (
  id uuid primary key default gen_random_uuid(),
  category text not null,
  icon_key text,
  subject text not null,
  level int not null,
  sort_order int not null default 0,
  updated_at timestamptz not null default now()
);

create table if not exists public.education (
  id uuid primary key default gen_random_uuid(),
  institution text not null,
  degree text not null,
  location text,
  period text,
  status text,
  description text,
  coursework text[] not null default '{}',
  achievements text[] not null default '{}',
  sort_order int not null default 0,
  updated_at timestamptz not null default now()
);

create table if not exists public.certifications (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  issuer text not null,
  date text,
  status text,
  credential_id text,
  description text,
  skills text[] not null default '{}',
  url text,
  sort_order int not null default 0,
  updated_at timestamptz not null default now()
);

create table if not exists public.internships (
  id uuid primary key default gen_random_uuid(),
  company text not null,
  role text not null,
  period text,
  location text,
  type text,
  is_current boolean not null default false,
  description text,
  highlights text[] not null default '{}',
  techs text[] not null default '{}',
  logo_url text,
  demo_url text,
  video_id text,
  sort_order int not null default 0,
  updated_at timestamptz not null default now()
);

create table if not exists public.projects (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  company text,
  period text,
  location text,
  description text,
  icon_key text,
  category text,
  technologies text[] not null default '{}',
  highlights text[] not null default '{}',
  status text,
  github_url text,
  app_store_url text,
  play_store_url text,
  video_id text,
  image_url text,
  portrait boolean not null default false,
  sort_order int not null default 0,
  updated_at timestamptz not null default now()
);

-- The API expects exactly one profile row to already exist (PATCH-only, no create endpoint).
insert into public.profile (name, title)
select 'Oussama Methnani', 'Software Engineer'
where not exists (select 1 from public.profile);
