"""Preserve caller-owned source/cache inputs without compiling or clearing them."""

import os
from pathlib import Path, PurePosixPath
import re
import stat

import python_journal as inputs
import python_provider as provider
import python_selection as selection

DIRECTORY = 'python-cache-context'
METADATA = 'context.json'
MAX_FILES = 4096
FIELDS = {'sha256', 'size', 'device', 'inode', 'mtime_ns', 'mode'}


def enabled(configuration: dict) -> bool:
    """Cache context is never inferred from cache files or producer metadata."""
    options = configuration.get('adapters', {}).get('python', {})
    return options.get('backend') == 'prepared' and options.get('profile') == provider.CACHE_PROFILE


def _facts(source: selection.Source) -> dict:
    return {'sha256': source.sha256, 'size': len(source.content), 'device': source.device,
            'inode': source.inode, 'mtime_ns': source.mtime_ns, 'mode': source.mode}


def _cache_name(source: str, cached: str) -> bool:
    return selection.cache_for_source(os.fsencode(Path(source).name), os.fsencode(Path('__pycache__') / cached))


def _gather(root: Path, contents: dict) -> tuple[dict, dict[str, selection.Source]]:
    """Keep unrelated build trees excluded while inspecting source-associated caches."""
    sources, caches, frozen = {}, {}, {}
    total = 0
    provider.require(root.is_absolute() and root == root.resolve(strict=True),
                     'Python cache source root must be canonical')
    for name, digest in sorted(contents.items()):
        _name(name)
        if not name.endswith('.py'):
            continue
        source = selection.freeze(root / name)
        provider.require(source.sha256 == digest, 'Python source changed before cache capture')
        sources[name] = _facts(source)
        cache = (root / name).parent / '__pycache__'
        try:
            info = cache.lstat()
        except FileNotFoundError:
            continue
        provider.require(stat.S_ISDIR(info.st_mode) and cache == cache.resolve(strict=True),
                         'Python cache directory is linked or not a directory')
        for path in sorted(cache.iterdir()):
            if not _cache_name(name, path.name):
                continue
            relative = path.relative_to(root).as_posix()
            provider.require(relative not in caches, 'ambiguous Python cache source')
            value = selection.freeze(path)
            total += len(value.content)
            provider.require(total <= inputs.MAX_BYTES and len(caches) < MAX_FILES,
                             'Python cache context exceeds its byte/file budget')
            caches[relative], frozen[relative] = _facts(value), value
    provider.require(len(sources) <= MAX_FILES, 'Python cache source context exceeds its file budget')
    return {'schema_version': 1, 'sources': sources, 'caches': caches}, frozen


def _name(name: str) -> PurePosixPath:
    provider.require(type(name) is str and bool(name) and '\0' not in name and '\\' not in name,
                     'invalid Python context path')
    path = PurePosixPath(name)
    provider.require(not path.is_absolute() and '..' not in path.parts and str(path) == name,
                     'Python context path must be canonical and source-relative')
    return path


def _context(workflow, workspace: Path) -> dict:
    value = workflow.read(workspace / DIRECTORY / METADATA)
    provider.require(type(value) is dict and set(value) == {'schema_version', 'sources', 'caches'}
                     and type(value['schema_version']) is int and value['schema_version'] == 1,
                     'invalid Python cache context schema')
    total = 0
    for section in ('sources', 'caches'):
        rows = value[section]
        provider.require(type(rows) is dict and len(rows) <= MAX_FILES, 'invalid Python context file map')
        for name, facts in rows.items():
            path = _name(name)
            provider.require(type(facts) is dict and set(facts) == FIELDS
                             and type(facts['sha256']) is str and re.fullmatch('[0-9a-f]{64}', facts['sha256'])
                             and all(type(facts[key]) is int for key in FIELDS - {'sha256'})
                             and 0 <= facts['size'] <= inputs.MAX_PAYLOAD
                             and 0 <= facts['device'] < 2**64 and 0 < facts['inode'] < 2**64
                             and 0 <= facts['mode'] <= 0xffffffff and stat.S_ISREG(facts['mode']),
                             'invalid frozen Python context file facts')
            if section == 'sources':
                provider.require(path.suffix == '.py', 'Python cache source is not a source file')
            else:
                provider.require(path.parent.name == '__pycache__'
                                 and any(path.parent.parent == PurePosixPath(source).parent
                                         and _cache_name(source, path.name) for source in value['sources']),
                                 'Python cache has no declared source file')
                total += facts['size']
    provider.require(total <= inputs.MAX_BYTES, 'Python cache context exceeds its byte budget')
    return value


def _preserved_file(path: Path, facts: dict) -> selection.Source:
    source = selection.freeze(path)
    provider.require(source.sha256 == facts['sha256'] and len(source.content) == facts['size']
                     and source.mtime_ns == facts['mtime_ns'] and source.mode == facts['mode'],
                     'private Python context bytes, timestamps or permissions changed')
    return source


def _write_file(path: Path, source: selection.Source) -> None:
    existing = path.parent
    while not existing.exists() and not existing.is_symlink():
        existing = existing.parent
    provider.require(existing.is_dir() and existing == existing.resolve(strict=True),
                     'Python cache destination has a linked parent')
    path.parent.mkdir(parents=True, exist_ok=True)
    provider.require(not path.exists() and not path.is_symlink(), 'Python cache destination already exists')
    with path.open('xb') as output:
        output.write(source.content)
    os.chmod(path, stat.S_IMODE(source.mode))
    os.utime(path, ns=(source.mtime_ns, source.mtime_ns))


def prepare(workflow, root: Path, workspace: Path, contents: dict, configuration: dict) -> dict | None:
    """Freeze original inputs and preserve validation timestamps in the private snapshot."""
    if not enabled(configuration):
        return None
    value, caches = _gather(root, contents)
    directory = workspace / DIRECTORY
    directory.mkdir(mode=0o700)
    for name, source in caches.items():
        _write_file(directory / 'files' / name, source)
    for name, facts in value['sources'].items():
        path = workspace / 'snapshot' / name
        provider.require(selection.freeze(path).sha256 == facts['sha256'], 'Python snapshot differs from frozen source')
        os.chmod(path, stat.S_IMODE(facts['mode']))
        os.utime(path, ns=(facts['mtime_ns'], facts['mtime_ns']))
    workflow.write(directory / METADATA, value)
    provider.require(_gather(root, contents)[0] == value, 'original Python cache context changed during capture')
    return workflow.manifest(directory)


def verify(workflow, workspace: Path, data: dict) -> None:
    """Bind sealed cache files, immutable snapshots and optional original inputs."""
    expected = data.get('python_cache_context_manifest')
    provider.require((expected is not None) == enabled(data['configuration']),
                     'explicit Python cache profile/context mismatch')
    if expected is None:
        return
    provider.require(workflow.manifest(workspace / DIRECTORY) == expected, 'frozen Python cache context changed')
    value = _context(workflow, workspace)
    source_names = {name for name in data['source_manifest'] if name.endswith('.py')}
    provider.require(set(value['sources']) == source_names, 'Python source/cache context inventory differs')
    expected_files = {METADATA, *('files/' + name for name in value['caches'])}
    provider.require(set(expected) == expected_files, 'Python cache context contains unaccounted files')
    for name, facts in value['sources'].items():
        provider.require(facts['sha256'] == data['source_manifest'][name], 'Python source/cache hashes differ')
        _preserved_file(workspace / 'snapshot' / name, facts)
    for name, facts in value['caches'].items():
        _preserved_file(workspace / DIRECTORY / 'files' / name, facts)
    if 'original_source' not in data:
        provider.require(_gather(Path(data['source']), data['source_manifest'])[0] == value,
                         'original Python source/cache context changed')


def materialise(workflow, workspace: Path, data: dict, project: Path) -> tuple[selection.Source, ...]:
    """Install original cache bytes beside private sources without forcing compilation."""
    verify(workflow, workspace, data)
    value = _context(workflow, workspace)
    for name, facts in value['sources'].items():
        _preserved_file(project / name, facts)
    for name, facts in value['caches'].items():
        _write_file(project / name, _preserved_file(workspace / DIRECTORY / 'files' / name, facts))
    return freeze_attempt(workflow, workspace, project)


def freeze_attempt(workflow, workspace: Path, project: Path) -> tuple[selection.Source, ...]:
    """Retain actual private cache identities before launch and compare them after exit."""
    value = _context(workflow, workspace)
    return tuple(_preserved_file(project / name, facts) for name, facts in sorted(value['caches'].items()))
