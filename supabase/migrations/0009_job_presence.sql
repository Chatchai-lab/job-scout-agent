-- Counts consecutive daily polls in which a stored posting was missing from its company board.
-- Two misses in a row set closed_at (see triage.update_presence).
alter table jobs add column missing_runs integer not null default 0;
