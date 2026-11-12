-- Adds social/contact link fields to profile, rendered in the Contact
-- section alongside email and phone. Run this once in the Supabase SQL
-- editor, then reload the PostgREST schema cache.

alter table profile
  add column linkedin_url text,
  add column github_url text,
  add column whatsapp_url text,
  add column facebook_url text,
  add column instagram_url text,
  add column twitter_url text;
