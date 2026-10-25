"""Keep an explicit free-space floor active during owned Go compiler commands."""

import json
from pathlib import Path
import shutil
import time


def minimum(value: object) -> int:
    """Validate a retained byte budget without accepting boolean integers."""
    if type(value) is not int or not 0 <= value <= 2 ** 63 - 1:
        raise ValueError("Go build_min_free_bytes must be an integer from 0 to 9223372036854775807")
    return value


class Guard:
    """Use the shared executor's cleanup when the output volume loses headroom."""

    def __init__(self, directory: Path, minimum_free_bytes: int):
        self.directory = directory
        self.minimum = minimum(minimum_free_bytes)
        self.next_check = 0.0
        if self.minimum:
            self.check("before_start", None)

    def check(self, phase: str, process) -> None:
        """Retain the measured refusal; never label an interrupted build as a result."""
        free = shutil.disk_usage(self.directory).free
        if free < self.minimum:
            value = {"schema_version": 1, "kind": "oteleq.go.build-storage-refusal",
                     "phase": phase, "directory": str(self.directory.resolve()),
                     "minimum_free_bytes": self.minimum, "observed_free_bytes": free,
                     "process_started": process is not None,
                     "pid": process.pid if process is not None else None}
            with (self.directory / "storage-refusal.json").open("x") as stream:
                json.dump(value, stream, sort_keys=True, indent=2)
                stream.write("\n")
            raise ValueError("Go build storage headroom exhausted; inspect retained storage-refusal.json")

    def poll(self, process, deadline: float) -> None:
        """Measure at most ten times per second while the original deadline applies."""
        now = time.monotonic()
        if self.minimum and now >= self.next_check:
            self.check("running", process)
            self.next_check = now + 0.1

    def finish(self, process) -> None:
        """Also check commands that finish between two periodic measurements."""
        if self.minimum:
            self.check("after_exit", process)
