-- Working-student postings (Werkstudent) near Darmstadt are scored like any other posting
-- but carry their own kind so the digest and the package can treat them differently.
alter table jobs drop constraint jobs_kind_check;
alter table jobs add constraint jobs_kind_check
    check (kind in ('posting', 'initiative', 'working_student'));
