-- Migration: Add unique constraint on (turbine_id, predicted_date) to support upserts
-- and add optional rich diagnostic columns to public.turbine_mentenance.

-- 1) Deduplicate if any exist (keep newest entry_id)
delete from public.turbine_mentenance a
using public.turbine_mentenance b
where a.turbine_id = b.turbine_id
  and a.predicted_date = b.predicted_date
  and a.entry_id < b.entry_id;

-- 2) Add unique constraint
alter table public.turbine_mentenance
  add constraint turbine_mentenance_turbine_date_uniq
  unique (turbine_id, predicted_date);

-- 3) Drop non-unique index if it was created
drop index if exists public.turbine_mentenance_turbine_date_idx;

-- 4) Add rich diagnostic columns if not present
alter table public.turbine_mentenance
  add column if not exists health_score real,
  add column if not exists estimated_days_to_failure real,
  add column if not exists anomalous_sensors text[],
  add column if not exists summary_text text;
