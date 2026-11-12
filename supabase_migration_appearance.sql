-- Adds per-user appearance settings to the profile table: a curated theme
-- choice and the order/visibility of the five content sections on the
-- public /u/:username page. Run this once in the Supabase SQL editor.

alter table profile
  add column theme text not null default 'amber',
  add column section_config jsonb not null default '[
    {"key": "skills", "visible": true},
    {"key": "internships", "visible": true},
    {"key": "projects", "visible": true},
    {"key": "education", "visible": true},
    {"key": "certifications", "visible": true}
  ]'::jsonb;

alter table profile
  add constraint profile_theme_check
  check (theme in ('amber', 'violet', 'emerald', 'crimson', 'azure'));
