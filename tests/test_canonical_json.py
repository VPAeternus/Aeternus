import math

import pytest

from tradingagents.dealflow.canonical_json import CanonicalizationError, canonical_dumps, canonical_hash


def test_canonical_hash_stable_for_key_order_and_float_noise():
    payload_a = {
        "symbol": "TSLA",
        "metrics": {
            "score": 72.0,
            "confidence": 4,
            "sentiment": 0.50000000001,
        },
        "tags": ["momentum", "asymmetric-upside"],
    }
    payload_b = {
        "tags": ["momentum", "asymmetric-upside"],
        "metrics": {
            "sentiment": 0.5,
            "confidence": 4,
            "score": 72.0000000000,
        },
        "symbol": "TSLA",
    }

    assert canonical_hash(payload_a) == canonical_hash(payload_b)


def test_canonical_dumps_has_deterministic_no_whitespace_layout():
    payload = {"b": 2, "a": 1}
    assert canonical_dumps(payload) == '{"a":1,"b":2}'


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_canonical_hash_rejects_non_finite_float(value):
    with pytest.raises(CanonicalizationError):
        canonical_hash({"bad": value})
