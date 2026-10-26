"""Closed negotiation for the reserved rebuilt Rust owned preparation API."""

from native_protocol import require, same

PROFILE = 'rust1981-owned-standalone-v1'
SOURCE_PROFILES = ('rust1981-standalone-sync-v1', 'rust1981-standalone-drop-v2')


def descriptor(source_build_version: int) -> dict:
    """Reconstruct the fixed descriptor for one caller-selected source build."""
    require(type(source_build_version) is int and source_build_version in (1, 2),
            'Rust preparation requires explicit source build version 1 or 2')
    return {'schema_version': 1, 'kind': 'otelc.rust.protocols', 'profile': PROFILE,
            'owned_build': 1, 'source_build': source_build_version,
            'source_profile': SOURCE_PROFILES[source_build_version - 1],
            'request': 1, 'plan': 1, 'prepared': 1, 'command': 1,
            'execution': 1, 'host_release': 1, 'gate': 1,
            'native_plan': 2 if source_build_version == 1 else 3,
            'health': 1 if source_build_version == 1 else 5,
            'embedded_sdk': True, 'source_complete': False}


def verify(value: dict, *, source_build_version: int) -> dict:
    """Reject extra fields, coercible versions and mixed direct/owned profiles."""
    expected = descriptor(source_build_version)
    require(type(value) is dict and same(value, expected),
            'Rust preparation descriptor differs from the selected fixed profile')
    return expected
