-- Companies to probe for a public job board. Filled by hand or by research; `discover`
-- tries the known ATS vendors and promotes hits into `companies`.
create table company_candidates (
    name            text primary key,
    status          text not null default 'pending'
                    check (status in ('pending', 'found', 'not_found')),
    ats             text,
    ats_slug        text,
    open_jobs       integer,
    sample_titles   text[],
    checked_at      timestamptz
);

alter table company_candidates enable row level security;
