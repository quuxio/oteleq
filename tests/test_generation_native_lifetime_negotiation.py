"""Lifetime protocol and SDK source choices stay explicit and independently bound."""

import copy
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]
import native_inputs
import native_protocol
import native_provider_fixture as fixture
import native_sdk


DESCRIPTOR = {
    'schema_version': 1, 'kind': 'otelc.native.protocols',
    'profile': 'native-owned-v1', 'request': 1, 'plan': 1, 'prepared': 1,
    'command': 1, 'execution': 1, 'host_release': 1, 'gate': 1,
    'embedded_sdk': True, 'source_complete': False,
}
ADDITIONS = {
    2: {},
    3: {'unit_recipe': 1},
    4: {'unit_recipe': 1, 'object_inventory': 2,
        'object_probe_abi': 'otelc.object.v1'},
    5: {'unit_recipe': 1, 'resource_inventory': 1,
        'resource_resolution': 1, 'resource_probe_abi': 'otelc.resource.v1'},
}
HEADERS = {
    'function-v2': ['function_abi.h'],
    'object-v1': ['function_abi.h', 'object_abi.h'],
    'resource-v1': ['function_abi.h', 'object_abi.h', 'resource_abi.h'],
}


def descriptor(version: int) -> dict:
    """Literal fixtures do not call the producer's protocol implementation."""
    return {**DESCRIPTOR, 'build': version, **ADDITIONS[version]}


def recapture(sdk: native_sdk.SDK, profile: str) -> native_sdk.SDK:
    """Select caller-owned paths again, without using paths from its record."""
    return native_sdk.capture(
        sdk.root, sdk.directory, sdk.toolchain, cmake=sdk.cmake.path,
        ninja=sdk.ninja.path, platform='linux', source_profile=profile)


class NativeLifetimeProtocolTests(unittest.TestCase):
    def test_all_four_descriptors_require_their_explicit_version(self):
        for version in ADDITIONS:
            value = descriptor(version)
            with self.subTest(version=version):
                self.assertEqual(native_protocol.verify_protocols(
                    value, build_version=version), value)
                for other in ADDITIONS:
                    if other != version:
                        with self.assertRaises(ValueError):
                            native_protocol.verify_protocols(
                                value, build_version=other)
        self.assertEqual(native_protocol.verify_protocols(descriptor(2)),
                         descriptor(2))

    def test_each_lifetime_field_rejects_missing_extra_or_substituted_values(self):
        for version in (4, 5):
            value = descriptor(version)
            for key in value:
                missing = {name: item for name, item in value.items()
                           if name != key}
                substituted = copy.deepcopy(value)
                original = value[key]
                substituted[key] = (1 if type(original) is bool else
                                    True if type(original) is int else 'foreign')
                for changed in (missing, substituted):
                    with self.subTest(version=version, field=key), \
                            self.assertRaises(ValueError):
                        native_protocol.verify_protocols(
                            changed, build_version=version)
            with self.assertRaises(ValueError):
                native_protocol.verify_protocols(
                    {**value, 'future': 1}, build_version=version)

    def test_inventory_and_resolution_versions_are_exact_wire_integers(self):
        for version in (4, 5):
            value = descriptor(version)
            for key in ADDITIONS[version]:
                if type(value[key]) is not int:
                    continue
                for invalid in (True, float(value[key]), 0, 99, None):
                    with self.subTest(version=version, key=key, value=invalid), \
                            self.assertRaises(ValueError):
                        native_protocol.verify_protocols(
                            {**value, key: invalid}, build_version=version)

    def test_object_and_resource_claims_cannot_be_combined_or_downgraded(self):
        for version in (4, 5):
            other = 5 if version == 4 else 4
            with self.assertRaises(ValueError):
                native_protocol.verify_protocols(
                    {**descriptor(version), **ADDITIONS[other]},
                    build_version=version)

    def test_unsupported_build_version_is_refused_before_wire_interpretation(self):
        for version in (False, True, 4.0, '4', None, [], {}, 0, 1, 6):
            with self.subTest(version=version), self.assertRaises(ValueError):
                native_protocol.verify_protocols({}, build_version=version)


class NativeLifetimeSDKTests(unittest.TestCase):
    def test_three_source_catalogues_bind_the_complete_fixed_header_order(self):
        for profile, headers in HEADERS.items():
            with self.subTest(profile=profile), \
                    tempfile.TemporaryDirectory() as temporary:
                sdk = fixture.sdk(Path(temporary).resolve(),
                                  source_profile=profile)
                self.assertEqual(sdk.source_profile, profile)
                self.assertEqual([held.path.name for held in sdk.sources[4:]],
                                 headers)
                self.assertEqual(len(sdk.sources), 4 + len(headers))
                self.assertEqual(sdk.expected(), sdk.record.value())
                recapture(sdk, profile).verify()

    def test_default_remains_the_original_function_catalogue(self):
        with tempfile.TemporaryDirectory() as temporary:
            sdk = fixture.sdk(Path(temporary).resolve())
            self.assertEqual(sdk.source_profile, 'function-v2')
            self.assertEqual(len(sdk.sources), 5)
            self.assertEqual(native_sdk.source_paths(sdk.root),
                             tuple(held.path for held in sdk.sources))

    def test_profile_is_not_discovered_from_producer_metadata(self):
        for profile in ('object-v1', 'resource-v1'):
            with self.subTest(profile=profile), \
                    tempfile.TemporaryDirectory() as temporary:
                sdk = fixture.sdk(Path(temporary).resolve(),
                                  source_profile=profile)
                with self.assertRaises(ValueError):
                    recapture(sdk, 'function-v2')
                with self.assertRaises(ValueError):
                    replace(sdk, source_profile='function-v2').verify()

    def test_missing_selected_abi_header_refuses_without_fallback(self):
        for profile in ('object-v1', 'resource-v1'):
            with self.subTest(profile=profile), \
                    tempfile.TemporaryDirectory() as temporary:
                sdk = fixture.sdk(Path(temporary).resolve(),
                                  source_profile=profile)
                sdk.sources[-1].path.unlink()
                with self.assertRaises((OSError, ValueError)):
                    recapture(sdk, profile)

    def test_changed_header_original_identity_cannot_be_repaired(self):
        for profile in ('object-v1', 'resource-v1'):
            with self.subTest(profile=profile), \
                    tempfile.TemporaryDirectory() as temporary:
                sdk = fixture.sdk(Path(temporary).resolve(),
                                  source_profile=profile)
                path = sdk.sources[-1].path
                path.write_bytes(path.read_bytes())
                with self.assertRaises(ValueError):
                    sdk.verify()

    def test_header_aliases_are_not_accepted_as_original_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            sdk = fixture.sdk(Path(temporary).resolve(),
                              source_profile='resource-v1')
            path = sdk.sources[-1].path
            original = sdk.root / 'foreign-header.h'
            path.rename(original)
            path.symlink_to(original)
            with self.assertRaises(ValueError):
                recapture(sdk, 'resource-v1')

    def test_rehashed_source_record_cannot_change_the_header_denominator(self):
        for change in ('omit', 'reorder', 'substitute', 'additional'):
            with self.subTest(change=change), \
                    tempfile.TemporaryDirectory() as temporary:
                sdk = fixture.sdk(Path(temporary).resolve(),
                                  source_profile='resource-v1')
                value = sdk.record.value()
                if change == 'omit':
                    value['sources'].pop()
                elif change == 'reorder':
                    value['sources'][-2:] = reversed(value['sources'][-2:])
                else:
                    foreign = sdk.root / 'foreign.h'
                    foreign.write_text('not a selected ABI input')
                    if change == 'substitute':
                        value['sources'][-1] = fixture.identity(foreign)
                    else:
                        value['sources'].append(fixture.identity(foreign))
                fixture.write(sdk.record.file.path, value)
                with self.assertRaises(ValueError):
                    recapture(sdk, 'resource-v1')

    def test_additional_held_header_cannot_extend_caller_intent(self):
        with tempfile.TemporaryDirectory() as temporary:
            sdk = fixture.sdk(Path(temporary).resolve(),
                              source_profile='object-v1')
            path = sdk.root / 'native/llvm/resource_abi.h'
            path.write_text('unselected ABI')
            with self.assertRaises(ValueError):
                replace(sdk, sources=(*sdk.sources,
                                     native_inputs.capture(path))).verify()

    def test_unknown_or_wrongly_typed_source_profiles_are_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            for profile in ('', 'automatic', 'resource-v2', None, True, [], {}):
                with self.subTest(profile=profile), self.assertRaises(ValueError):
                    native_sdk.source_paths(root, source_profile=profile)


if __name__ == '__main__':
    unittest.main()
