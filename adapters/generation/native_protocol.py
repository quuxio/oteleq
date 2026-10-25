"""Closed native prepared protocols and independent primitive wire identities."""

import hashlib
import json
from typing import Any

PROFILE = 'native-owned-v1'
PROTOCOLS = {'schema_version': 1, 'kind': 'otelc.native.protocols', 'profile': PROFILE,
             'build': 2, 'request': 1, 'plan': 1, 'prepared': 1, 'command': 1,
             'execution': 1, 'host_release': 1, 'gate': 1, 'embedded_sdk': True,
             'source_complete': False}


def require(condition: bool, reason: str) -> None:
    """Unsupported or contradictory native evidence has no legacy fallback."""
    if not condition:
        raise ValueError('native prepared provider: ' + reason)


def encoded(value: Any) -> str:
    """The public native protocol hashes compact sorted finite JSON."""
    return json.dumps(value, sort_keys=True, allow_nan=False, separators=(',', ':'))


def same(value: Any, expected: Any) -> bool:
    """Keep wire booleans, integers, floating values and missing fields distinct."""
    return encoded(value) == encoded(expected)


def digest(value: Any) -> str:
    """Hash the native wire representation, including exact primitive types."""
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def verify_protocols(value: object) -> dict:
    """Negotiate the complete current descriptor before any application launch."""
    require(type(value) is dict and same(value, PROTOCOLS), 'unsupported public native protocols')
    return value


def fields(value: object, names: set[str], label: str) -> dict:
    """Refuse missing and additional fields in a closed record."""
    require(type(value) is dict and set(value) == names, 'invalid ' + label + ' fields')
    return value
