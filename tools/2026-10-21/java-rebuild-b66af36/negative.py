"""Require visible capacity loss and prelaunch refusal for unavailable adapters."""
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

import live
from java_process import App


def main() -> None:
    if sys.flags.optimize:
        raise ValueError('Qualification requires assertions')
    folder = live.ROOT / 'capacity-v1'
    folder.mkdir(mode=0o700)
    server = live.capture.CaptureServer(max_requests=128)
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    policy = live.policy(folder, server, 'capacity')
    policy.write_text(policy.read_text().replace('max_live = 1000000', 'max_live = 1'))
    app = App(folder, live.PROVIDER, policy)
    try:
        control = live.control_path(app)
        initial = live.raw_status(control)
        identity = live.process_identity(app, initial['pid'])
        frozen = live.products()
        result = app.exchange('10')
        assert type(result['checksum']) is int and result['checksum'] == 41284864
        assert type(result['calls']) is int and result['calls'] == 10
        value = live.raw_status(control)
        assert type(value['lifetime_lost']) is int and value['lifetime_lost'] > 0
        without_loss = {**value, 'lifetime_lost': 0}
        live.check_status(without_loss, collection=False, emission=False, completed=0, require_lifetime=True)
        try:
            live.check_status(value, collection=False, emission=False, completed=0, require_lifetime=True)
        except AssertionError:
            pass
        else:
            raise AssertionError('Capacity loss incorrectly qualified as complete')
        assert app.exchange('gc') == {'gc_requested': True}
        time.sleep(.2)
        assert live.products() == frozen and live.process_identity(app, value['pid']) == identity
        live.write(folder / 'negative-result.json', {'expected_verdict': 'incomplete_observation',
            'reason': 'lifetime_capacity_loss', 'actual_status': value,
            'result': result, 'process': identity, 'build': frozen,
            'socket': live.socket_identity(control), 'complete_qualification_refused': True})
        app.close()
        assert len([span for span in live.app_spans(server) if span['name'] == 'BenchmarkApp.workload']) == 10
        assert not any(path == '/v1/metrics' for path, _ in server.bodies)
        server.require_complete()
        before = live.products()
        plan = app.cli(['--config', str(policy), 'plan'])
        assert plan['implemented'] == ['java']
        assert set(plan['remaining']) == {'typescript', 'javascript', 'python', 'go', 'c', 'cpp', 'rust'}
        refusals = []
        for language in plan['remaining']:
            command = [sys.executable, '-m', 'otelc', '--config', str(policy), 'example', language]
            output = subprocess.run(command, cwd=live.PROVIDER, env=app.env, stdin=subprocess.DEVNULL,
                                    capture_output=True, text=True, timeout=8, check=False)
            (folder / (language + '.stdout')).write_text(output.stdout)
            (folder / (language + '.stderr')).write_text(output.stderr)
            assert output.returncode == 1 and not output.stdout
            assert language + ' is not implemented in the rebuild yet' in output.stderr
            assert 'Control socket:' not in output.stderr and live.products() == before
            refusals.append(language)
        live.write(folder / 'refusals.json', {'unavailable_languages': refusals, 'class_build_unchanged': True})
    finally:
        app.stop()
        server.shutdown()
        server.server_close()
        serving.join(timeout=2)
        live.capture.retain_http(folder, server.bodies, server.errors, server.requests)
        live.write(folder / 'decoded-otlp.json', live.frames(server))


if __name__ == '__main__':
    main()
