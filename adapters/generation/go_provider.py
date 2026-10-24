"""Closed rebuilt Go protocol negotiation, separate from runtime admission."""

import json
from typing import Any

PROFILE = "go-source-v1"
PROTOCOLS = {"schema_version": 1, "kind": "otelc.go.protocols", "profile": PROFILE,
             "build": 2, "request": 1, "plan": 1, "prepared": 1, "command": 1,
             "execution": 1, "health": 3, "embedded_sdk": True, "source_complete": False}


def require(condition: bool, reason: str) -> None:
    """Missing or contradictory evidence cannot select an older Go launcher."""
    if not condition:
        raise ValueError("Go prepared provider: " + reason)


def same(value: Any, expected: Any) -> bool:
    """Protocol numbers, booleans and floating values remain distinct."""
    return json.dumps(value, sort_keys=True, allow_nan=False) == json.dumps(expected, sort_keys=True, allow_nan=False)


def verify_protocols(value: object) -> dict:
    """The caller selects the one supported profile before reading metadata."""
    require(type(value) is dict and same(value, PROTOCOLS), "unsupported public Go protocols")
    return value
