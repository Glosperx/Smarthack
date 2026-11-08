"""The maintenance model's input: one row per turbine, only the features the model reads."""

import pytest

from tests.conftest import skip_module_without_extra

skip_module_without_extra("wind")

from smarthack.maintenance.features import RAW_SCADA_COLUMNS  # noqa: E402
from smarthack.maintenance.model_input import build_model_input  # noqa: E402
from smarthack.maintenance.simulator import ScadaSimulator  # noqa: E402


def _table(rows: list[dict[str, object]]) -> tuple[list[str], list[dict[str, str]]]:
    """
    Turn rows into what `parse_csv` returns: the columns and string values.

    :param rows: The rows.

    :returns table: Columns and rows of strings.
    """
    columns = list(rows[0])
    return columns, [{name: str(row[name]) for name in columns} for row in rows]


def test_the_latest_row_in_time_wins_whatever_the_file_order() -> None:
    """Rows are put in time order before the last one of each turbine is taken."""
    columns, rows = _table(
        [
            {"turbine_id": 1, "time_stamp": "2026-11-08 10:20", "f": 3},
            {"turbine_id": 1, "time_stamp": "2026-11-08 10:00", "f": 1},
            {"turbine_id": 1, "time_stamp": "2026-11-08 10:10", "f": 2},
        ]
    )

    table = build_model_input(columns, rows, ["f"])

    assert table.to_dict("records") == [{"turbine_id": 1, "as_of": "2026-11-08 10:20", "f": 3.0}]


def test_an_unreadable_value_becomes_missing_not_an_error() -> None:
    """A sensor that sent text reads as NaN; the model has its own missing value."""
    columns, rows = _table([{"asset_id": 2, "f": "n/a"}])

    table = build_model_input(columns, rows, ["f"])

    assert table["turbine_id"].tolist() == [2]
    assert table["f"].isna().all()


@pytest.mark.parametrize(
    "rows, message",
    [
        ([], "no rows"),
        ([{"turbine_id": "seven", "f": 1}], "not a number"),
        ([{"name": "x", "f": 1}], "no turbine id column"),
    ],
)
def test_what_cannot_name_or_hold_a_turbine_is_refused(
    rows: list[dict[str, object]], message: str
) -> None:
    """No rows, a turbine id that is not a number, or no id column at all."""
    columns, values = _table(rows) if rows else (["turbine_id", "f"], [])

    with pytest.raises(ValueError, match=message):
        build_model_input(columns, values, ["f"])


def test_raw_sensors_are_derived_into_the_requested_features() -> None:
    """With only raw sensors, the features come from `extract_maintenance_features`."""
    frame = ScadaSimulator(seed=1).generate_stream(asset_id=5, duration_hours=4)
    columns, rows = _table(frame.to_dict("records"))
    wanted = ["rpm_deviation", "thermal_lift_bearing_de"]

    table = build_model_input(columns, rows, wanted)

    assert list(table.columns) == ["turbine_id", "as_of", *wanted]
    assert table["thermal_lift_bearing_de"].notna().all()


def test_a_feature_nothing_derives_is_named() -> None:
    """The model asks for a feature the derivation does not produce: refused, not zero-filled."""
    columns, rows = _table([{"turbine_id": 1, **{name: 20 for name in RAW_SCADA_COLUMNS}}])

    with pytest.raises(ValueError, match="nothing derives: vibration_rms"):
        build_model_input(columns, rows, ["rpm_deviation", "vibration_rms"])
