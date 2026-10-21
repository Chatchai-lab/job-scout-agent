-- Full master profile (with contact data) for CV and cover letter builds.
-- One row; the YAML text is entered by hand in the Supabase SQL editor, never committed.
-- RLS on, no policies: only the service role can read it.
create table profile_private (
    id          text primary key default 'main',
    yaml        text not null,
    updated_at  timestamptz not null default now()
);

alter table profile_private enable row level security;
