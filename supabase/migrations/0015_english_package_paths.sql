-- Paths of the English PDFs (translation of the German package), shown in the app.
alter table applications add column en_cv_pdf_path text;
alter table applications add column en_letter_pdf_path text;
