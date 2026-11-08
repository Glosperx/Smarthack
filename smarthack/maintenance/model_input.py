"""
# Maintenance model input

Turns a raw telemetry table, as it lands in the lake, into the input of the maintenance model:
one row per turbine holding only the features the model was trained on, in its order.

The model's feature list is the contract (`fault_features.json` next to the model). Nothing
here names a feature: when a new model arrives with another list, the selection follows it.
A raw file is read in one of two ways:

- **It already carries every model feature** (a feature table exported elsewhere): the
  columns are selected, and the latest row of each turbine is kept.
- **It carries raw SCADA sensors** (10-minute rows, often hundreds of columns): the features
  are derived per turbine with `extract_maintenance_features`, over the turbine's rows in time
  order, and the last row is kept, the same window `evaluate_telemetry` scores.

Anything else is refused with the missing columns named, so a file that cannot feed the model
goes to the dead-letter bucket instead of being scored on zeros.

The following can be imported from this module:
- `PARK_ID_COLUMN`
- `TIMESTAMP_COLUMN`
- `TURBINE_ID_COLUMNS`
- `build_model_input`
"""

from collections.abc import Sequence

import pandas as pd

from smarthack.maintenance.features import RAW_SCADA_COLUMNS, extract_maintenance_features

#: Columns that may name the turbine of a row, in order of preference: the fleet's id, then
#: the CARE dataset's `asset_id`. The output always calls it `turbine_id`.
TURBINE_ID_COLUMNS: tuple[str, ...] = ("turbine_id", "asset_id")

#: Column with the time of a row; rows are put in time order before the window is taken.
TIMESTAMP_COLUMN = "time_stamp"

#: Optional column with the park of a turbine, carried through so the dispatch step need not
#: look it up.
PARK_ID_COLUMN = "park_id"


def _id_column(columns: Sequence[str]) -> str:
    """
    Pick the column that identifies the turbine of each row.

    :param columns: The table's columns.

    :returns name: The first of `TURBINE_ID_COLUMNS` present.
    :raises ValueError: When none is present.
    """
    for name in TURBINE_ID_COLUMNS:
        if name in columns:
            return name
    raise ValueError(f"no turbine id column: expected one of {', '.join(TURBINE_ID_COLUMNS)}")


def _as_numbers(frame: pd.DataFrame, keep: set[str]) -> pd.DataFrame:
    """
    Turn every value column into numbers; an empty or unreadable value becomes NaN.

    :param frame: The raw table, all strings.
    :param keep: Columns left as they are (ids, time, park).

    :returns frame: A copy with numeric value columns.
    """
    typed = frame.copy()
    for name in typed.columns:
        if name not in keep:
            typed[name] = pd.to_numeric(typed[name], errors="coerce")
    return typed


def _in_time_order(frame: pd.DataFrame) -> pd.DataFrame:
    """
    Sort rows by time when the table has a timestamp, keeping the file's order for ties.

    :param frame: Rows of one or more turbines.

    :returns frame: The rows in time order, or as given without a timestamp.
    """
    if TIMESTAMP_COLUMN not in frame.columns:
        return frame
    order = pd.to_datetime(frame[TIMESTAMP_COLUMN], errors="coerce", utc=True)
    return frame.assign(_order=order).sort_values("_order", kind="stable").drop(columns="_order")


def build_model_input(
    columns: Sequence[str], rows: Sequence[dict[str, str]], feature_columns: Sequence[str]
) -> pd.DataFrame:
    """
    Build the model's input from a raw table: one row per turbine, only the model's features.

    :param columns: The raw table's columns, as `parse_csv` returns them.
    :param rows: The raw table's rows, values as strings.
    :param feature_columns: The features the model reads, in its order.

    :returns table: Columns `turbine_id`, then `park_id` and `as_of` when the raw table has a
        park or a timestamp, then `feature_columns`; one row per turbine, ordered by id.
    :raises ValueError: When the table has no rows, no turbine id, or neither every model
        feature nor every raw sensor the features are derived from.
    """
    if not rows:
        raise ValueError("the file has no rows")
    id_column = _id_column(columns)
    passthrough = {id_column, TIMESTAMP_COLUMN, PARK_ID_COLUMN}
    frame = _as_numbers(pd.DataFrame(list(rows), columns=list(columns)), passthrough)
    frame[id_column] = pd.to_numeric(frame[id_column], errors="coerce")
    if frame[id_column].isna().any():
        raise ValueError(f"column {id_column} has a value that is not a number")
    frame = _in_time_order(frame)

    has_features = all(name in frame.columns for name in feature_columns)
    missing_sensors = [name for name in RAW_SCADA_COLUMNS if name not in frame.columns]
    if not has_features and missing_sensors:
        missing_features = [name for name in feature_columns if name not in frame.columns]
        raise ValueError(
            "the file cannot feed the model: missing features "
            f"{', '.join(missing_features)}; or else the raw sensors {', '.join(missing_sensors)}"
        )

    output: list[dict[str, object]] = []
    for turbine_id, turbine_rows in frame.groupby(id_column, sort=True):
        if has_features:
            features = turbine_rows[list(feature_columns)]
        else:
            features = extract_maintenance_features(turbine_rows.reset_index(drop=True))
            absent = [name for name in feature_columns if name not in features.columns]
            if absent:
                raise ValueError(f"the model reads features nothing derives: {', '.join(absent)}")
        record: dict[str, object] = {"turbine_id": int(turbine_id)}
        latest = turbine_rows.iloc[-1]
        if PARK_ID_COLUMN in frame.columns:
            record[PARK_ID_COLUMN] = latest[PARK_ID_COLUMN]
        if TIMESTAMP_COLUMN in frame.columns:
            record["as_of"] = latest[TIMESTAMP_COLUMN]
        record.update(features[list(feature_columns)].iloc[-1].to_dict())
        output.append(record)
    return pd.DataFrame(output)


__all__ = ["PARK_ID_COLUMN", "TIMESTAMP_COLUMN", "TURBINE_ID_COLUMNS", "build_model_input"]
