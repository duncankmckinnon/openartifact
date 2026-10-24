-- Library entries use the same versioned source storage and editor as ordinary artifacts.
alter table artifacts add column preset_kind text check (preset_kind in ('template', 'style'));
create index artifacts_presets_idx on artifacts (workspace_id, preset_kind) where preset_kind is not null;
