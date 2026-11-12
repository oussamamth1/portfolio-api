-- Allows the logged-in admin (any authenticated Supabase user) to upload and
-- overwrite files in the portfolio-images bucket. Public reads already work
-- because the bucket itself was created with public: true.

create policy "Allow authenticated uploads to portfolio-images"
on storage.objects for insert
to authenticated
with check (bucket_id = 'portfolio-images');

create policy "Allow authenticated updates to portfolio-images"
on storage.objects for update
to authenticated
using (bucket_id = 'portfolio-images');
