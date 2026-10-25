"""Native schedules preserve intermediate state, arbitrary error bytes and fixed input intent."""

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'adapters/generation'), str(ROOT / 'examples')]

import native_inputs
import native_sequence as sequence
import native_source
import native_workers
import policy
import sequences
import typed_capture
from test_generation_native_rendezvous import private

ABI = b'abi:{"byte_order":"little","char_signed":true,"char_bits":8,"bits":{"int":32}}\n'


def entry(language='cpp', flags=((False, True), (True, False), (True, True))):
    value = {'language': language, 'native_backend': 'prepared', 'native_options': {},
        'name': 'selected', 'path': 'selected.' + ('cpp' if language == 'cpp' else 'c'),
        'otelc_function': 'selected', 'parameters': ['int'], 'output': 'int',
        'globals': [{'name': 'g', 'type': 'int'}], 'expected_baseline': {'kind': 'return'}}
    value['sequence_configuration'] = [{'action': 'call', 'arguments': 'case',
        'metrics': {'collection': collection, 'emission': emission}} for collection, emission in flags]
    return value


def frame(before=10, after=11, result=7, error=None):
    integer = lambda value: int(value).to_bytes(4, 'little', signed=True).hex().encode()
    outcome = b'return:int:' + integer(result) if error is None else b'error:std::runtime_error\t' + error
    return ABI + b'before\ng:int:' + integer(before) + b'\n' + outcome + b'\nafter\ng:int:' + integer(after) + b'\n'


def payload(frames):
    return json.dumps({'schema_version': 1, 'kind': sequence.KIND,
        'frames': [{'id': 'step-' + str(index), 'raw_hex': raw.hex()} for index, raw in enumerate(frames)]}).encode()


class NativeSequenceTests(unittest.TestCase):
    def test_explicit_native_free_function_configuration_and_all_startup_states(self):
        for language in ('c', 'cpp'):
            for flags in ((False, False), (False, True), (True, False), (True, True)):
                value = entry(language, (flags, (True, True)))
                raw_fixture = {'function': 'selected', 'cases': [[7]], 'sequence': value['sequence_configuration']}
                frozen = policy.fixture(raw_fixture, 0)
                supplied = copy.deepcopy(value['sequence_configuration'])
                sequences.configure(value, supplied, lambda selected, args: args)
                supplied[0]['metrics']['collection'] = not flags[0]
                self.assertEqual(value['sequence_configuration'], frozen['sequence'])
                self.assertEqual({key: native_source.configuration(value, 'http://127.0.0.1:4318', 'test')['metrics'][key]
                                  for key in ('collection', 'emission')}, {'collection': flags[0], 'emission': flags[1]})
                concrete = sequences.concrete(value, [7], lambda selected, args: args)
                self.assertEqual(sequence.concrete(value, concrete, [7]), tuple(concrete))

    def test_legacy_receiver_lifetime_partial_states_and_changed_arguments_remain_refusals(self):
        mutations = [('native_backend', 'legacy'), ('language', 'rust'), ('receiver_fixture', {}),
                     ('cpp_receiver', {}), ('cpp_function', {'kind': 'CXXMethodDecl'}),
                     ('native_options', {'profile': 'native-objects-owned-v1'})]
        for key, new in mutations:
            value = entry(); value[key] = new
            with self.subTest(key=key), self.assertRaises(ValueError): sequence.configuration(value, value['sequence_configuration'])
        for kind in ('empty', 'long', 'bool', 'missing', 'release', 'arguments', 'no-positive'):
            value = entry(); steps = value['sequence_configuration']
            if kind == 'empty': steps.clear()
            elif kind == 'long': steps *= 11
            elif kind == 'bool': steps[0]['metrics']['collection'] = 0
            elif kind == 'missing': del steps[0]['metrics']
            elif kind == 'release': steps[0]['action'] = 'release'
            elif kind == 'arguments': steps[0]['arguments'] = [7]
            else:
                for step in steps: step['metrics']['collection'] = False
            with self.subTest(kind=kind), self.assertRaises(ValueError): sequence.configuration(value, steps)

    def test_concrete_inputs_step_identity_and_per_step_expectations_cannot_drift(self):
        value = entry(); value['sequence_configuration'][0]['expected_baseline'] = {'kind': 'error'}
        original = sequences.concrete(value, [7], lambda selected, args: args)
        self.assertEqual(sequence.concrete(value, original, [7])[0]['expected_baseline'], {'kind': 'error'})
        for key, new in (('id', 'step-1'), ('arguments', [8]), ('expected_baseline', {'kind': 'return'}),
                         ('metrics', {'collection': True, 'emission': True}), ('hidden', True)):
            actual = copy.deepcopy(original); actual[0][key] = new
            with self.subTest(key=key), self.assertRaises(ValueError): sequence.concrete(value, actual, [7])

    def test_same_final_state_and_return_do_not_hide_an_intermediate_mutation(self):
        value = entry(flags=((True, True), (True, True)))
        left = sequence.decode(payload([frame(10, 20), frame(20, 10)]), value)
        right = sequence.decode(payload([frame(10, 21), frame(21, 10)]), value)
        for key in ('before', 'after', 'outcome'): self.assertEqual(left[key], right[key])
        self.assertNotEqual(left['steps'], right['steps'])
        self.assertEqual(left['steps'][0]['after']['roots']['global:g']['value'], '20')
        contract = {'case_id': 'case', 'function_id': 'selected', 'fixture_sha256': 'a' * 64}
        self.assertEqual(typed_capture.observation(payload([frame(10, 20), frame(20, 10)]), value, contract)['steps'], left['steps'])

    def test_multiline_nul_exception_payload_is_decoded_inside_its_own_original_frame(self):
        value = entry(flags=((True, True),))
        raw = payload([frame(error=b'first\nafter\nlast\x00')])
        result = sequence.decode(raw, value)
        error = result['steps'][0]['outcome']
        self.assertEqual(error['kind'], 'error')
        self.assertEqual(error['graph']['nodes'][0]['fields']['message']['hex'], b'first\nafter\nlast\x00'.hex())

    def test_container_schema_order_encoding_and_denominator_refuse(self):
        value = entry(flags=((True, True),))
        original = json.loads(payload([frame()]))
        for key, new in (('schema_version', True), ('kind', 'other'), ('frames', []), ('hidden', 1)):
            changed = copy.deepcopy(original); changed[key] = new
            with self.subTest(key=key), self.assertRaises(ValueError): sequence.decode(json.dumps(changed).encode(), value)
        for key, new in (('id', 'step-1'), ('raw_hex', 'aa BB'), ('raw_hex', ''), ('raw_hex', 'ABC'), ('hidden', 1)):
            changed = copy.deepcopy(original); changed['frames'][0][key] = new
            with self.subTest(key=key, new=new), self.assertRaises(ValueError): sequence.decode(json.dumps(changed).encode(), value)
        with self.assertRaises(ValueError): sequence.decode(b'', value)

    def test_host_container_preserves_original_files_and_enforces_case_budget(self):
        value = entry(flags=((True, True),))
        concrete = tuple(sequences.concrete(value, [7], lambda selected, args: args))
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve(); source = base / 'step-0.observation'
            private(source, frame())
            held = native_inputs.capture(source, keep=True, private=True)
            raw = sequence.container((held,), concrete)
            saved = sequence.publish(base / 'observation', raw, len(raw))
            saved.verify(); held.verify()
            self.assertEqual(bytes.fromhex(json.loads(saved.content)['frames'][0]['raw_hex']), held.content)
            with self.assertRaises(ValueError): sequence.publish(base / 'small', raw, len(raw) - 1)
            self.assertFalse((base / 'small').exists())
            with self.assertRaises(FileExistsError): sequence.publish(base / 'observation', raw, len(raw))
            source.write_bytes(frame(after=999))
            with self.assertRaises(ValueError): sequence.container((held,), concrete)
        with self.assertRaises(ValueError): sequence.container((), concrete)

    def test_controlled_driver_syntax_keeps_helpers_neutral_and_has_every_checkpoint(self):
        for language in ('c', 'cpp'):
            compiler = os.environ.get('OTELC_CLANGXX' if language == 'cpp' else 'OTELC_CLANG')
            self.assertIsNotNone(compiler, 'The bounded syntax gate requires an explicitly selected compiler')
            for output in ('int', 'void'):
                value = entry(language); value['output'] = output
                raw = native_workers.driver(value)
                for phase in ('before-0', 'after-0', 'before-1', 'after-1', 'before-2', 'after-2', 'finish'):
                    self.assertIn('__oteleq_native_checkpoint("' + phase + '")', raw)
                self.assertNotIn('no_profile_instrument_function', raw)
                result = subprocess.run([compiler, '-x', 'c++' if language == 'cpp' else 'c',
                    '-std=c++17' if language == 'cpp' else '-std=c11', '-Wall', '-Wextra', '-Werror',
                    '-fsyntax-only', '-'], input=raw.encode(), capture_output=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr.decode())


if __name__ == '__main__':
    unittest.main()
