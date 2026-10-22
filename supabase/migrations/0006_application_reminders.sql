-- When the last follow-up reminder for an application was sent.
alter table applications add column reminded_at timestamptz;
