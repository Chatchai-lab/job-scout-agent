-- Workable and BambooHR join the supported job-board vendors.
alter table companies drop constraint companies_ats_check;
alter table companies add constraint companies_ats_check
    check (ats in ('greenhouse', 'greenhouse_eu', 'lever', 'ashby', 'personio', 'recruitee',
                   'smartrecruiters', 'workable', 'bamboohr', 'none'));
