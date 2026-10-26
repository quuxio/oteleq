"""Bounded public-CLI sessions for the fixed Java provider acceptance check."""
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading
from otelc_capture import strict_json


class App:
    def __init__(self, folder: Path, provider: Path, policy: Path, *, plain: bool = False):
        self.folder, self.provider = folder, provider
        self.stdout, self.stderr, self.errors = [], [], []
        self.lines, self.diagnostics = queue.Queue(), queue.Queue()
        for name in ('home', 'scratch'):
            (folder / name).mkdir()
        self.env = {'PATH': '/opt/homebrew/opt/openjdk@21/bin:/opt/homebrew/bin:/usr/bin:/bin',
                    'JAVA_HOME': '/opt/homebrew/opt/openjdk@21', 'PYTHONPATH': str(provider),
                    'PYTHONDONTWRITEBYTECODE': '1', 'HOME': str(folder / 'home'),
                    'TMPDIR': str(folder / 'scratch'), 'LANG': 'C.UTF-8', 'TZ': 'UTC'}
        command = [sys.executable, '-m', 'otelc', '--config', str(policy), 'example', 'java']
        if plain:
            command.append('--plain')
        (folder / 'command.json').write_text(json.dumps(command, indent=2) + '\n')
        self.process = subprocess.Popen(command, cwd=provider, env=self.env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1, start_new_session=True)
        self.readers = []
        for stream, rows, channel in ((self.process.stdout, self.stdout, self.lines),
                                      (self.process.stderr, self.stderr, self.diagnostics)):
            reader = threading.Thread(target=self.read, args=(stream, rows, channel), daemon=True)
            reader.start()
            self.readers.append(reader)

    def read(self, stream, rows: list, channel: queue.Queue) -> None:
        size = 0
        while line := stream.readline(65537):
            size += len(line.encode())
            rows.append(line)
            if len(line) > 65536 or size > 1024 * 1024:
                self.errors.append('application output limit')
                channel.put(RuntimeError(self.errors[-1]))
                return
            channel.put(line)

    @staticmethod
    def receive(channel: queue.Queue) -> str:
        line = channel.get(timeout=25)
        if isinstance(line, Exception):
            raise line
        return line

    def exchange(self, command: str) -> dict:
        self.process.stdin.write(command + '\n')
        self.process.stdin.flush()
        value = strict_json(self.receive(self.lines))
        if self.errors:
            raise RuntimeError(self.errors)
        return value

    def cli(self, arguments: list[str]) -> dict:
        result = subprocess.run([sys.executable, '-m', 'otelc', *arguments], cwd=self.provider,
            env=self.env, capture_output=True, text=True, timeout=8, check=True)
        if result.stderr:
            raise RuntimeError(result.stderr)
        return strict_json(result.stdout)

    def persist(self) -> None:
        (self.folder / 'stdout').write_text(''.join(self.stdout))
        (self.folder / 'stderr').write_text(''.join(self.stderr))

    def close(self) -> None:
        self.process.stdin.write('quit\n')
        self.process.stdin.flush()
        result = self.process.wait(timeout=20)
        for reader in self.readers:
            reader.join(timeout=2)
        self.persist()
        if result != 0 or self.errors or any(reader.is_alive() for reader in self.readers):
            raise RuntimeError('Incomplete application exit: ' + repr((result, self.errors)))

    def stop(self) -> None:
        if self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGTERM)
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait(timeout=5)
        for reader in self.readers:
            reader.join(timeout=1)
        self.persist()
