-- The CV selection of a package (headline, summary, picked bullets, rewrites). The German package
-- is the master: an English version is a translation of the stored selection and letter.
alter table applications add column selection jsonb;
