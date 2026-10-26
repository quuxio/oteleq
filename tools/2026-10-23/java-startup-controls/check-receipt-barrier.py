"""Reproduce the early acknowledgement before and after the consumer fix."""

import importlib.util
import inspect
import json
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

source = Path(sys.argv[1])
sys.path[:0] = [str(source / 'adapters/generation'), str(source / 'examples'), str(source / 'tests')]
import java_live
from test_generation_java_control_receipt import status

ON = {'collection': True, 'emission': True}
with tempfile.TemporaryDirectory(prefix='receipt-barrier-') as temporary:
    folder = Path(temporary).resolve()
    bindings = {'service': 'case', 'method': 'Counter.identity'} if 'service' in inspect.signature(java_live.Session).parameters else {}
    bodies = []
    session = java_live.Session(folder, folder / 'runtime', [], bodies, plain=False, **bindings)
    session.record['steps'] = [{'id': 'step-0', 'requested': ON,
        'before': {'cursor': 0, 'history': []}, 'after': None}]
    session.holding = {'index': 0, 'status': status(ON, 1), 'flush': status(ON, 1),
        'started_ns': time.monotonic_ns()}
    with patch.object(session, 'query', return_value=status(ON, 1)), patch.object(session, 'acknowledge') as acknowledge:
        session.settle(time.monotonic() + 1)
        premature = acknowledge.called
        if not premature:
            from java_live_fixture import metric_body
            bodies.append(('/v1/metrics', metric_body(1)))
            session.settle(time.monotonic() + 1)
            assert acknowledge.call_count == 1 and session.record['steps'][0]['after']['cursor'] == 1
        print(json.dumps({'source': str(source), 'acknowledged_before_any_metric_receipt': premature,
            'acknowledged_after_actual_metric_body': acknowledge.called if not premature else None,
            'new_application_launches': 0}))
