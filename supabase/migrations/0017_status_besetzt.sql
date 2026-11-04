-- "Besetzt": an application whose position was filled, kept apart from a real rejection.
alter table applications drop constraint applications_status_check;
alter table applications add constraint applications_status_check
    check (status in ('gemerkt', 'paket', 'beworben', 'interview', 'absage', 'angebot', 'besetzt'));
