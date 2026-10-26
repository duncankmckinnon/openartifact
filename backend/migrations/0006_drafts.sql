-- Library entries under construction are unlisted until saved.
alter table artifacts add column draft boolean not null default false;
create index artifacts_drafts_idx on artifacts (updated_at) where draft;

-- External cleanup survives deletion of the artifact row and is retried by the draft sweeper.
create table artifact_deletions (
    artifact_id uuid primary key,
    created_at timestamptz not null default now()
);
