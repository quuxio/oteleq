"""Offline health consumer controls; these tests launch no application JVM."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import check_worker

ROOT = Path(__file__).resolve().parent


class ConsumerCheckerTests(unittest.TestCase):
    def test_complete_fixtures_pass_independent_value_and_transport_oracles(self):
        for name, stderr in (('clean-v1', 0), ('stderr-v1', 282)):
            result = check_worker.check(ROOT / name)
            self.assertEqual(result['selected_spans'], 1)
            self.assertEqual(result['recorded_calls'], 1)
            self.assertEqual(result['metric_points'], 12)
            self.assertEqual(result['stderr_bytes_per_lane'], stderr)

    def test_nine_altered_health_identity_state_and_return_controls_refuse(self):
        with tempfile.TemporaryDirectory(prefix='oteleq-health-checker-') as temporary:
            for fault in ('pid', 'policy', 'selection', 'phase', 'pending', 'drop', 'failed', 'metric-points', 'return'):
                folder = Path(temporary) / fault
                shutil.copytree(ROOT / 'clean-v1', folder)
                path = folder / 'instrumented/runtime/health.json'
                data = json.loads(path.read_text())
                if fault == 'pid': data['pid'] += 1
                elif fault == 'policy': data['policy_sha256'] = '0' * 64
                elif fault == 'selection': data['selection_sha256'] = '0' * 64
                elif fault == 'phase': data['phase'] = 'running'
                elif fault == 'pending': data['span_accounting']['queue_pending'] = None
                elif fault == 'drop': data['span_accounting']['queue_dropped'] = '1'
                elif fault == 'failed': data['trace_exports']['batches_failed'] = '1'
                elif fault == 'metric-points': data['metric_exports']['units_succeeded'] = '11'
                else:
                    for lane in ('baseline', 'instrumented'):
                        raw = folder / lane / 'observation'
                        value = json.loads(raw.read_text())
                        value['outcome']['value']['roots']['result']['value'] = '99'
                        raw.write_text(json.dumps(value))
                        typed = folder / lane / 'typed-observation.json'
                        value = json.loads(typed.read_text())
                        value['outcome']['graph']['roots']['result']['value'] = '99'
                        typed.write_text(json.dumps(value))
                path.write_text(json.dumps(data))
                with self.subTest(fault=fault), self.assertRaises(AssertionError):
                    check_worker.check(folder, source_root=ROOT / 'clean-v1')


if __name__ == '__main__':
    unittest.main()
