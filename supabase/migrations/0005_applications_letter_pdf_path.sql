-- Storage path of the cover letter PDF, next to cv_pdf_path.
alter table applications add column if not exists letter_pdf_path text;
