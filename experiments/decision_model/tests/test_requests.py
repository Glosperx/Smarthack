import pytest

from decision_model.requests import CHANNEL_OPTIONS, ML2_OPTIONS, ORDERS, build_request


def test_request_has_one_typed_choice_question_and_the_state_as_is() -> None:
    state = {"park_id": "p", "turbines": []}

    request = build_request("ml2", state)

    assert request["state"] == state
    assert request["state"] is not state
    question = request["questions"]["q"]
    assert question["type"] == "choice"
    assert question["criteria"] == ML2_OPTIONS
    assert "Policy" not in question["instructions"]


def test_policy_variant_adds_the_rule_of_today() -> None:
    plain = build_request("channel", {}, "fara_politica")["questions"]["q"]["instructions"]
    policy = build_request("channel", {}, "cu_politica")["questions"]["q"]["instructions"]

    assert policy.startswith(plain)
    assert "0.70" in policy and "0.30" in policy


@pytest.mark.parametrize("order_index", [0, 1, 2])
def test_orders_permute_the_same_options(order_index: int) -> None:
    criteria = build_request("channel", {}, order_index=order_index)["questions"]["q"]["criteria"]

    assert list(criteria) == ORDERS["channel"][order_index]
    assert criteria == CHANNEL_OPTIONS


def test_three_channel_orders_put_each_option_first_once() -> None:
    assert {order[0] for order in ORDERS["channel"]} == set(CHANNEL_OPTIONS)


def test_unknown_decision_or_variant() -> None:
    with pytest.raises(ValueError):
        build_request("other", {})
    with pytest.raises(ValueError):
        build_request("ml2", {}, variant="other")
