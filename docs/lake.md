# Local data lake

The input of the next maintenance model is one telemetry record with hundreds of columns:
too wide for a Postgres table, and easier to automate as files. The pipeline is shaped like
S3 with Lambda functions, simulated on a local folder:

```
producer ──put──▶ data/lake/raw/      ──event──▶ raw_object_created_handler   (logs the file)
                  data/lake/failed/   ◀── files that could not be read, same key
```

Today the handler on `raw` only logs each new file: its key, size, shape and first rows.
Cutting the model's columns into a second bucket, and the handler that feeds the model from
there, come with the new model.

## Run it

```bash
pip install -e ".[lake]"          # watchdog: the only dependency
make lake-watch                   # follow data/lake/ and run the handlers
make lake-put FILE=telemetry.csv  # in another terminal: upload a file into raw/
```

`make up` starts the watcher with the other background jobs. Dropping or copying a file into
`data/lake/raw/` by hand works too; the watcher waits until its size stops changing. A file in
a sub-folder is an object whose key has a prefix, such as `2026-11-08/turbine_7.csv`.

| Variable | Default | Meaning |
|---|---|---|
| `LAKE_DIR` | `data/lake` | Root of the lake: one sub-folder per bucket. Gitignored. |

Inside Docker, on a folder mounted from a macOS or Windows host, file events do not cross the
mount: use `make lake-watch ARGS=--polling`.

## What maps to what

| AWS | Here |
|---|---|
| S3 bucket | A sub-folder of `LAKE_DIR` (`clients/object_store.py`, `LocalObjectStore`) |
| `PutObject`, `aws s3 cp` | `make lake-put`: written to a hidden `.tmp` file, then renamed |
| Event notification on `s3:ObjectCreated:*` | `HANDLERS` in `services/lake_service.py`, run by `jobs/lake_job.py` |
| Lambda function | `raw_object_created_handler(event, context)` |
| Dead-letter queue | The `failed` bucket |

The handler receives the event S3 sends a Lambda (`schemas/lake.py`, `object_created_event`),
URL-encoded key included, and depends only on the `ObjectStore` contract. Moving to real AWS
means a boto3 store next to `LocalObjectStore` and deploying the handler; its code stays.

## Rules a producer and a handler follow

- **Write atomically.** Write a temporary name, then rename. A file ending in `.tmp`, or
  whose name starts with `.` (`.DS_Store`), is never processed.
- **Only `.csv` is read** (`LAKE_OBJECT_SUFFIXES`). UTF-8, a header line, unique column names.
  Values stay strings until the step that feeds the model types them.
- **One event per version.** Created, modified and renamed events for one write trigger the
  handler once; overwriting a key with new content triggers it again, as on S3.
- **A handler must be idempotent.** Real S3 delivers an event at least once, so handling the
  same object twice must give the same result.
- Files already in `raw/` when the watcher starts are not replayed, as S3 does not.
