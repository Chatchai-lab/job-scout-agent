-- Private storage bucket for the CV photo and generated application PDFs.
-- No storage policies: only the service role can read or write.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('cv-assets', 'cv-assets', false, 5242880, array['image/jpeg', 'image/png', 'application/pdf'])
on conflict (id) do update
set public = false,
    file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;
