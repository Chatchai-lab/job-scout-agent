-- job-scout-agent: initial schema
-- RLS is enabled everywhere with no policies: only the service role
-- (pipelines, webhook) can read or write. The dashboard gets its own
-- owner-only policies in a later migration.

create extension if not exists pgcrypto;

-- Companies to poll, maintained by hand and by the discovery pipeline
create table companies (
    id              uuid primary key default gen_random_uuid(),
    name            text not null,
    ats             text not null default 'none'
                    check (ats in ('greenhouse', 'greenhouse_eu', 'lever', 'ashby',
                                   'personio', 'recruitee', 'smartrecruiters', 'none')),
    ats_slug        text,
    careers_url     text,
    source          text not null default 'manual',
    active          boolean not null default true,
    last_polled_at  timestamptz,
    created_at      timestamptz not null default now(),
    unique (ats, ats_slug)
);

-- Every job posting ever seen, normalized
create table jobs (
    id              uuid primary key default gen_random_uuid(),
    company_id      uuid references companies(id) on delete set null,
    company_name    text not null,
    source          text not null,
    external_id     text not null,
    title           text not null,
    location        text,
    remote          boolean,
    description     text,
    url             text not null,
    posted_at       timestamptz,
    dedup_key       text not null,
    first_seen_at   timestamptz not null default now(),
    closed_at       timestamptz,
    unique (source, external_id)
);
create index jobs_dedup_key_idx on jobs (dedup_key);
create index jobs_first_seen_idx on jobs (first_seen_at desc);

-- Why a job was dropped before scoring (kept for calibration)
create table prefilter_drops (
    job_id          uuid primary key references jobs(id) on delete cascade,
    reason          text not null,
    at              timestamptz not null default now()
);

-- LLM score per job
create table scores (
    job_id          uuid primary key references jobs(id) on delete cascade,
    fit             smallint not null check (fit between 0 and 10),
    reach           smallint not null check (reach between 0 and 10),
    ring            text not null check (ring in ('kern', 'nah', 'beratung', 'raus')),
    sales_share     real check (sales_share between 0 and 1),
    start_ok        boolean,
    salary          text,
    reason          text not null,
    model           text not null,
    cost_usd        numeric(10, 6) not null default 0,
    notified_at     timestamptz,
    scored_at       timestamptz not null default now()
);
create index scores_rank_idx on scores ((fit * reach) desc);

-- Clicks in the Telegram bot
create table decisions (
    id              uuid primary key default gen_random_uuid(),
    job_id          uuid not null references jobs(id) on delete cascade,
    action          text not null check (action in ('package', 'save', 'reject')),
    reason_tag      text,
    note            text,
    at              timestamptz not null default now()
);

-- Application tracker
create table applications (
    job_id          uuid primary key references jobs(id) on delete cascade,
    status          text not null default 'gemerkt'
                    check (status in ('gemerkt', 'paket', 'beworben', 'interview',
                                      'absage', 'angebot')),
    cv_pdf_path     text,
    cover_letter    text,
    gaps            jsonb,
    applied_at      timestamptz,
    updated_at      timestamptz not null default now()
);

-- Learned preference rules (feedback loop)
create table preferences (
    id              uuid primary key default gen_random_uuid(),
    rule            text not null,
    status          text not null default 'vorgeschlagen'
                    check (status in ('vorgeschlagen', 'freigegeben', 'verworfen')),
    created_at      timestamptz not null default now()
);

-- Cost control
create table llm_usage (
    id              bigint generated always as identity primary key,
    day             date not null default current_date,
    purpose         text not null check (purpose in ('match', 'package', 'feedback')),
    model           text not null,
    input_tokens    integer not null default 0,
    cache_read_tokens integer not null default 0,
    output_tokens   integer not null default 0,
    cost_usd        numeric(10, 6) not null
);
create index llm_usage_day_idx on llm_usage (day);

create view monthly_cost as
select date_trunc('month', day)::date as month, sum(cost_usd) as cost_usd
from llm_usage
group by 1;

alter table companies        enable row level security;
alter table jobs             enable row level security;
alter table prefilter_drops  enable row level security;
alter table scores           enable row level security;
alter table decisions        enable row level security;
alter table applications     enable row level security;
alter table preferences      enable row level security;
alter table llm_usage        enable row level security;
