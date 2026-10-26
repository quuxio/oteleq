"""The live-example checker must refuse plausible, equal-but-wrong evidence."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from google.protobuf.json_format import MessageToDict
from google.protobuf.message import DecodeError
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import ExportMetricsServiceRequest
import oracle

ROOT = Path(__file__).resolve().parent


class OracleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='oteleq-java-oracle-')
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name) / 'live'
        shutil.copytree(ROOT / 'live-v3/live', self.folder)

    def metadata(self, mutate):
        path = self.folder / 'phases.json'
        data = json.loads(path.read_text())
        mutate(data)
        path.write_text(json.dumps(data))

    def expect_failure(self):
        with self.assertRaises((AssertionError, DecodeError)):
            oracle.check_case(self.folder)

    def test_current_retained_case_passes_all_oracles(self):
        self.assertEqual(oracle.check_case(self.folder)['spans'], 204)

    def test_equal_wrong_checksums_and_numeric_types_refuse(self):
        original = json.loads((self.folder / 'phases.json').read_text())
        for value in (0, 41284864.0):
            data = copy.deepcopy(original)
            for phase in data:
                phase['outputs'][0]['checksum'] = value
            (self.folder / 'phases.json').write_text(json.dumps(data))
            (self.folder / 'stdout').write_text(''.join(json.dumps(row) + '\n' for phase in data for row in phase['outputs']))
            with self.subTest(value=value):
                self.expect_failure()

    def test_pid_restarts_rebuilds_socket_modes_and_loss_refuse(self):
        original = json.loads((self.folder / 'phases.json').read_text())
        for kind in ('pid', 'rebuild', 'socket', 'loss', 'boolean_counter'):
            data = copy.deepcopy(original)
            phase = data[1]
            if kind == 'pid':
                phase['process']['application_pid'] += 1
            elif kind == 'rebuild':
                next(iter(phase['build'].values()))['mtime_ns'] += 1
            elif kind == 'socket':
                phase['socket']['mode'] = 0o666
            elif kind == 'loss':
                phase['status']['lifetime_lost'] = 1
            else:
                phase['status']['completed'] = True
            (self.folder / 'phases.json').write_text(json.dumps(data))
            with self.subTest(kind=kind):
                self.expect_failure()

    def test_changed_raw_protobuf_cannot_use_the_unmodified_decoded_cache(self):
        record = json.loads((self.folder / 'http-capture.json').read_text())['bodies'][0]
        path = self.folder / record['file']
        path.write_bytes(path.read_bytes() + b'\x80')
        self.expect_failure()

    def test_forged_raw_and_decoded_function_counts_still_refuse(self):
        manifest = json.loads((self.folder / 'http-capture.json').read_text())
        decoded = json.loads((self.folder / 'decoded-otlp.json').read_text())
        changed = 0
        for index, record in enumerate(manifest['bodies']):
            if record['path'] != '/v1/metrics':
                continue
            path = self.folder / record['file']
            message = ExportMetricsServiceRequest()
            message.ParseFromString(path.read_bytes())
            for resource in message.resource_metrics:
                for scope in resource.scope_metrics:
                    for metric in scope.metrics:
                        if metric.name == 'otelc.function.calls':
                            for point in metric.sum.data_points:
                                point.as_int += 100
                                changed += 1
            path.write_bytes(message.SerializeToString())
            decoded[index]['message'] = MessageToDict(message, preserving_proto_field_name=True)
        self.assertGreater(changed, 0)
        (self.folder / 'decoded-otlp.json').write_text(json.dumps(decoded))
        self.expect_failure()

    def test_unexpected_application_stderr_never_becomes_an_agent_diagnostic(self):
        with (self.folder / 'stderr').open('a') as stream:
            stream.write('Unexpected application message\n')
        self.expect_failure()


if __name__ == '__main__':
    unittest.main()
