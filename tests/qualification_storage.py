"""Stop new qualification commands before their output volume loses headroom."""

from contextlib import contextmanager
from contextvars import ContextVar
import json
from pathlib import Path
import shutil
from collections.abc import Iterator

MIN_FREE_BYTES = 8 * 1024 ** 3
_minimum: ContextVar[int] = ContextVar('qualification_minimum_free_bytes', default=0)


@contextmanager
def budget(minimum: int) -> Iterator[None]:
    """Select a free-space floor for this run and restore its caller's setting."""
    if type(minimum) is not int or minimum < 0:
        raise ValueError('qualification storage floor must be a nonnegative integer')
    token = _minimum.set(minimum)
    try:
        yield
    finally:
        _minimum.reset(token)


def check(folder: Path, operation: str) -> None:
    """Refuse before process launch, preserving a separate prelaunch receipt."""
    minimum = _minimum.get()
    if not minimum:
        return
    free = shutil.disk_usage(folder).free
    if free >= minimum:
        return
    value = {'schema_version': 1, 'kind': 'oteleq.qualification.storage-refusal',
             'operation': operation, 'folder': str(folder.resolve()),
             'minimum_free_bytes': minimum, 'observed_free_bytes': free,
             'applications_started_by_operation': 0}
    with (folder / (operation + '.storage-refusal.json')).open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')
    raise ValueError('qualification storage headroom exhausted before ' + operation
                     + '; preserve this incomplete attempt and free space before a new run')
