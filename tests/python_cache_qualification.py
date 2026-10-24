"""Independent literal input and file-fact checks for actual cache workflows."""

from dataclasses import dataclass
import ast
import hashlib
import os
from pathlib import Path
import re

import generation
import python_selection


def file_facts(path: Path) -> dict:
    """Record fixture facts independently of the production cache catalogue."""
    info = path.stat()
    return {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'size': info.st_size,
            'device': info.st_dev, 'inode': info.st_ino, 'mtime_ns': info.st_mtime_ns, 'mode': info.st_mode}


def check_private(path: Path, content: bytes, expected: dict) -> None:
    """Private inode identities can differ; bytes, mode and timestamp cannot."""
    assert path.is_file() and not path.is_symlink() and path == path.resolve(strict=True)
    assert path.read_bytes() == content, str(path)
    facts = file_facts(path)
    assert all(facts[key] == expected[key] for key in ('sha256', 'size', 'mtime_ns', 'mode')), str(path)


def cache_paths(root: Path, sources: dict[str, bytes]) -> set[Path]:
    """Account independently for all ordinary source-associated cache tags/optimisations."""
    result = set()
    for name in sources:
        source = root / name; directory = source.parent / '__pycache__'
        if not directory.exists() and not directory.is_symlink():
            continue
        assert directory.is_dir() and not directory.is_symlink() and directory == directory.resolve(strict=True)
        pattern = re.compile(re.escape(source.stem) + r'\.[A-Za-z0-9_-]+(?:\.opt-[0-9]+)?\.pyc')
        for path in directory.iterdir():
            if pattern.fullmatch(path.name):
                assert path.is_file() and not path.is_symlink() and path == path.resolve(strict=True)
                result.add(path)
    return result


@dataclass(frozen=True)
class CacheInputs:
    """Literal sources and stock-compiler cache files frozen before planning."""

    root: Path
    sources: dict[str, bytes]
    caches: dict[str, bytes]
    source_facts: dict[str, dict]
    cache_facts: dict[str, dict]

    @classmethod
    def capture(cls, root: Path, sources: dict[str, bytes]) -> 'CacheInputs':
        """Require literal fixture sources and use the stock runtime's cache path."""
        assert root == root.resolve(strict=True)
        assert sources and all((root / name).is_file() and not (root / name).is_symlink()
                               and (root / name).read_bytes() == raw for name, raw in sources.items())
        cached = {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(cache_paths(root, sources))}
        return cls(root, dict(sources), cached, {n: file_facts(root / n) for n in sources},
                   {n: file_facts(root / n) for n in cached})

    def receipt(self) -> dict:
        """Keep independent initial facts alongside raw qualification evidence."""
        return {'sources': self.source_facts, 'caches': self.cache_facts}

    def verify_originals(self) -> None:
        """Do not count restored bytes with changed timestamps or inodes as preserved."""
        for names, expected in ((self.sources, self.source_facts), (self.caches, self.cache_facts)):
            assert all(file_facts(self.root / name) == expected[name] for name in names)
        assert {p.relative_to(self.root).as_posix() for p in cache_paths(self.root, self.sources)} == set(self.caches)

    def verify_workspace(self, workspace: Path) -> None:
        """Check the complete sealed context against independently captured fixture facts."""
        plan = generation.read(workspace / 'plan.json')
        assert plan['configuration']['adapters']['python']['profile'] == 'python-native-cache-origins-v3'
        assert plan['source_manifest'] == {n: hashlib.sha256(raw).hexdigest() for n, raw in self.sources.items()}
        directory = workspace / 'python-cache-context'
        metadata = generation.read(directory / 'context.json')
        assert metadata == {'schema_version': 1, 'sources': self.source_facts, 'caches': self.cache_facts}
        assert set(plan['python_cache_context_manifest']) == {'context.json', *('files/' + n for n in self.caches)}
        assert generation.manifest(directory) == plan['python_cache_context_manifest']
        assert plan['source_sha256'] == generation.identity({
            'source': generation.identity(plan['source_manifest']),
            'python_cache_context': plan['python_cache_context_manifest']})
        for name, raw in self.sources.items():
            check_private(workspace / 'snapshot' / name, raw, self.source_facts[name])
        for name, raw in self.caches.items():
            check_private(directory / 'files' / name, raw, self.cache_facts[name])

    def frozen_caches(self, folder: Path, entry: dict, facts: dict) -> tuple:
        """Rebuild the caller's prelaunch cache catalogue from independent fixture bytes."""
        assert entry['python_profile'] == 'python-native-cache-origins-v3'
        project = folder / 'project'
        rows = {bytes.fromhex(row['path_hex']): row for row in facts['caches']}
        assert len(rows) == len(facts['caches']) == len(self.caches)
        assert set(rows) == {os.fsencode(project / name) for name in self.caches}
        frozen = []
        for name, raw in sorted(self.caches.items()):
            path = project / name
            check_private(path, raw, self.cache_facts[name])
            observed = file_facts(path)
            assert rows[os.fsencode(path)] == {'path_hex': os.fsencode(path).hex(),
                **{key: observed[key] for key in ('sha256', 'device', 'inode', 'mtime_ns', 'mode')}}
            frozen.append(python_selection.Source(os.fsencode(path), raw, observed['device'], observed['inode'],
                                                  observed['mtime_ns'], observed['mode']))
        for name, raw in self.sources.items():
            check_private(project / name, raw, self.source_facts[name])
        return tuple(frozen)

    def scalar_selection(self, folder: Path, entry: dict) -> tuple:
        """Bind a literal top-level scalar declaration independently of the inventory."""
        assert 'receiver_fixture' not in entry and entry['path'] in self.sources
        raw = self.sources[entry['path']]
        declarations = {node.name: node.lineno for node in ast.parse(raw).body if isinstance(node, ast.FunctionDef)}
        assert entry['line'] == declarations[entry['name']]
        facts = generation.read(folder / 'python-expected-origins.json')
        assert len(facts['selected']) == 1
        row = facts['selected'][0]
        path = folder / 'project' / entry['path']
        check_private(path, raw, self.source_facts[entry['path']])
        current = file_facts(path)
        assert row == {'path_hex': os.fsencode(path).hex(), 'qualname': entry['name'], 'line': entry['line'],
                       **{key: current[key] for key in ('sha256', 'device', 'inode', 'mtime_ns', 'mode')}}
        source = python_selection.Source(os.fsencode(path), raw, current['device'], current['inode'],
                                         current['mtime_ns'], current['mode'])
        return facts, (python_selection.Selection(source, entry['name'], entry['line']),)
