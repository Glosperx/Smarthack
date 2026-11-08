# Local data lake

The input of the maintenance model is telemetry with hundreds of columns: too wide for a
Postgres table, and easier to automate as files. The pipeline is shaped like S3 with Lambda
functions, simulated on a local folder. Each handler writes into the next bucket, and that
write is the event that starts the next handler:

```
producer ──put──▶ raw/*.csv
                    │ raw_object_created_handler          keep only what the model reads
                    ▼
                  features/*.csv                          one row per turbine, model features
                    │ features_object_created_handler     score with the maintenance model
                    ▼
                  predictions/*.json                      status, probability, lead time, 7 days
                    │ predictions_object_created_handler  run the dispatch agent per park
                    ▼
                  dispatch/*.json                         repair plan, crews, alerts, decisions

                  failed/                                 ◀── any file a step could not process
```

## Run it

```bash
pip install -e ".[wind,lake]"     # pandas and the model (wind), watchdog (lake)
make lake-watch                   # follow data/lake/ and run the handlers
make lake-sample                  # in another terminal: simulated SCADA of the seed fleet into raw/
make lake-put FILE=telemetry.csv  # or upload your own file into raw/
```

Within two seconds of `make lake-sample`, `data/lake/` holds the same key in every bucket:
`raw/samples/scada_<time>.csv`, `features/…csv`, `predictions/…json` and `dispatch/…json`.
`make lake-sample ARGS="--turbine 1=gearbox_wear --turbine 2"` picks the turbines and their
scenario (`normal`, `bearing_overheating`, `gearbox_wear`, `hydraulic_leak`,
`transformer_overheating`).

`make up` starts the watcher with the other background jobs. Dropping or copying a file into
`data/lake/raw/` by hand works too; the watcher waits until its size stops changing. A file in
a sub-folder is an object whose key has a prefix, such as `2026-11-08/park_3.csv`.

| Variable | Default | Meaning |
|---|---|---|
| `LAKE_DIR` | `data/lake` | Root of the lake: one sub-folder per bucket. Gitignored. |
| `MAINTENANCE_MODELS_DIR` | `models/maintenance` | The model the pipeline loads, and its feature list. |
| `AGENT_DATA_SOURCE` | `memory` | Where the dispatch step finds parks, crews and wind: the seed fleet or Supabase. |

Inside Docker, on a folder mounted from a macOS or Windows host, file events do not cross the
mount: use `make lake-watch ARGS=--polling`.

## The steps

### raw → features: only what the model reads

The raw file is logged (name, size, shape, first rows), then cut to the model's input: one row
per turbine with `turbine_id`, `park_id` and `as_of` when the raw file has them, then the
model's features in the model's order. Every other column is dropped.

- The turbine is named by a `turbine_id` column, or `asset_id` as in the CARE dataset.
- **The feature list is the model's** (`fault_features.json` next to the model). Nothing in the
  handler names a feature, so a model trained on other features changes the selection by
  itself.
- A file that **already has every model feature** is selected as it is, keeping each turbine's
  latest row (by `time_stamp` when there is one).
- A file of **raw SCADA sensors** (10-minute rows) has its features derived per turbine by
  `extract_maintenance_features`, over its rows in time order, and the last row is kept: the
  same window `evaluate_telemetry` scores.
- A file with neither goes to `failed/`, with the missing features and sensors named in the
  log. It is never scored on zeros.

Code: `smarthack/maintenance/model_input.py` (`build_model_input`).

### features → predictions: the maintenance model

Every row is scored with `assess_turbine_health(features_record=…)`, the same call the
maintenance job makes on the `turbine_maintenance_input` table, and the assessments are
written as one JSON document: `health_status`, `fault_probability`,
`estimated_days_to_failure`, `suspected_subsystem`, `subsystem_risks`, `daily_forecast`,
`recommended_action`, `summary_text`, with `turbine_id`, `park_id` and `as_of`.

- A features file that lacks a feature the model reads (the model changed since the file was
  cut) goes to `failed/`.
- A turbine whose scoring raises is listed under `errors`; the others are written. A file where
  no turbine scores goes to `failed/`.
- The model is loaded once per watcher process, as a warm Lambda keeps it: **restart the
  watcher after replacing the model files.**

### predictions → dispatch: the LangGraph agent

The assessments become the agent's triage items (`TurbineHealthTriage`): WARNING and CRITICAL
need a repair; a turbine with no predicted failure gets a lead time past the forecast week, so
it never makes two failures overlap. They are grouped by park, from the file's `park_id` or
else looked up (the seed fleet, or the `turbine` table with `AGENT_DATA_SOURCE=supabase`).

`run_park_dispatch_agent(park_id, triage_items)` runs once per park with at least one turbine
to repair, so the graph starts from these predictions and does not re-run the fleet cycle:

```
triage_park → check_failure_overlap → [power_prioritization, only when failures overlap]
            → schedule_repairs → choose_repair_plan → rank_and_match_crews
            → decide_and_dispatch_alerts
```

The dispatch file keeps, per park, the agent's `audit_summary`, `alert_decisions`,
`crew_assignments`, `repair_schedule`, the power model's `power_evaluations`, and, when the
local decision model is part of the graph, its records: `repair_plan_choice`,
`channel_decisions` and `decision_model_down` (`docs/decision_model.md` on the
`feature/local-decision` branch). With `DECISION_MODEL_ENABLED` off, or the server down, the
rules decide and the file says so. A park whose agent run fails is recorded with its error;
the others go on. Turbines of no known park are listed under `unassigned_turbines`.

## Real phone calls

By default the agent's voice call is simulated: the voice client records it and writes a
`EMERGENCY VOICE CALL DISPATCHED` line, and nobody is phoned. To phone for real, switch on
`VOICE_CALLS_ENABLED=true` in `.env` and install the extra (`pip install -e ".[calls]"`).

Then every CRITICAL turbine the agent calls for is also handed to the alerting module
(`experiments/alerting`, `alerting.dispatch.dispatch`): an email, then a Romanian voice call
through Twilio or Infobip, with escalation. The module's own gates apply and are not
bypassed: the number must be in `ALLOWED_PHONES`, `DRY_RUN` must be `false` (the default only
logs), an alert is dispatched once, and it gets at most three calls.

- **Who is phoned is the on-call rotation** (`oncall.json`, from `ONCALL_PHONE`), not the crew
  number of the dispatch data, which is a placeholder.
- **The spoken text is the module's**, built from the park, the turbine, its probability and
  the lead time, not the agent's English transcript.
- The module reads `SENDER_*`, `ONCALL_*`, `ALLOWED_*`, `DRY_RUN`, `TWILIO_*` and
  `CALL_PROVIDER` from the same root `.env`.
- The outcome is in the call record (`real_call`) and in the log (`REAL CALL via alerting`). A
  provider error is recorded and never stops the sweep.
- **The watcher waits for the call.** Escalation polls the call and, if nobody answers, waits
  `ESCALATION_RETRY_MINUTES` before the retry; the pipeline handles one file at a time meanwhile.
- Every run makes a new alert id, so a re-uploaded file phones again.

## When the final maintenance model arrives

The contract between the steps is the feature list and `assess_turbine_health`'s result.

- **Same kind of model, new features or weights**: replace the files in
  `MAINTENANCE_MODELS_DIR` and restart the watcher. If a new feature is not a raw column,
  teach `extract_maintenance_features` to derive it; the raw step refuses the file until then
  and names the feature.
- **The CARE CatBoost model** (`notebooks/care_catboost_baseline.md`) scores a turbine-day from
  deviations against a 120-day baseline ([t-180, t-60)) of `_avg` and `_std` columns. One raw
  file cannot carry that history: its raw step would append each file to a per-turbine history
  bucket and compute the day's features from it. Its predictor then replaces the one loaded
  by `_default_predictor`, returning the same keys (`health_status`, `fault_probability`,
  `estimated_days_to_failure`, …) so the dispatch step does not change.

## What maps to what

| AWS | Here |
|---|---|
| S3 bucket | A sub-folder of `LAKE_DIR` (`clients/object_store.py`, `LocalObjectStore`) |
| `PutObject`, `aws s3 cp` | `make lake-put`: written to a hidden `.tmp` file, then renamed |
| Event notification on `s3:ObjectCreated:*` | `HANDLERS` in `services/lake_service.py`, run by `jobs/lake_job.py` |
| Lambda functions | `raw_object_created_handler`, `features_object_created_handler`, `predictions_object_created_handler` |
| Dead-letter queue | The `failed` bucket |

The handlers receive the event S3 sends a Lambda (`schemas/lake.py`, `object_created_event`),
URL-encoded key included, and depend only on the `ObjectStore` contract. Moving to real AWS
means a boto3 store next to `LocalObjectStore` and deploying the handlers; their code stays.

## Rules a producer and a handler follow

- **Write atomically.** Write a temporary name, then rename. A file ending in `.tmp`, or
  whose name starts with `.` (`.DS_Store`), is never processed.
- **One file type per step**: `.csv` in `raw` and `features`, `.json` in `predictions`.
  UTF-8, a header line, unique column names. Values stay strings until the step that feeds the
  model types them.
- **One event per version.** Created, modified and renamed events for one write trigger the
  handler once; overwriting a key with new content triggers it again, as on S3.
- **A handler must be idempotent.** Real S3 delivers an event at least once. The raw and
  features steps give the same output for the same input. The dispatch step does not: the agent
  alerts again each time it runs. The notification clients are simulated today; before real
  calls and emails, deduplicate on the predictions key.
- Files already in a bucket when the watcher starts are not replayed, as S3 does not.
