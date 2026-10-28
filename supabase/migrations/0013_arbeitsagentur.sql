-- Searches on the Bundesagentur fuer Arbeit job board are stored as pseudo companies:
-- ats = 'arbeitsagentur', ats_slug = 'what|where|radius_km'.
alter table companies drop constraint companies_ats_check;
alter table companies add constraint companies_ats_check
    check (ats in ('greenhouse', 'greenhouse_eu', 'lever', 'ashby', 'personio', 'recruitee',
                   'smartrecruiters', 'workable', 'bamboohr', 'arbeitsagentur', 'none'));
