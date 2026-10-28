-- Small key/value store for switches that must live outside the code.
-- notifications_paused = 'true': scheduled digests, reminders and instant pushes stay silent
-- (manual workflow runs still send, for testing).
create table app_state (
    key         text primary key,
    value       text not null,
    updated_at  timestamptz not null default now()
);

alter table app_state enable row level security;

insert into app_state (key, value) values ('notifications_paused', 'true');
