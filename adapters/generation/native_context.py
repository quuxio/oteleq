"""Bind checked native declarations and target-wide storage to actual build units."""
from dataclasses import dataclass
import hashlib
from pathlib import Path

import cpp_models
import discovery
import native_frontend
import native_project

RECORDS = {'CXXRecordDecl', 'ClassTemplateSpecializationDecl', 'ClassTemplatePartialSpecializationDecl'}
TEMPLATES = {'ClassTemplateDecl', 'FunctionTemplateDecl', 'ClassTemplateSpecializationDecl',
             'ClassTemplatePartialSpecializationDecl'}


def require(condition: bool, reason: str) -> None:
    """A missing target binding is an inventory gap rather than an empty success."""
    if not condition:
        raise ValueError('native context: ' + reason)


@dataclass(frozen=True)
class Scope:
    """Compiler declaration contexts distinguish class statics and internal names."""
    names: tuple[str, ...] = ()
    record: str = ''
    template: bool = False


def nested(node: dict, parent: Scope) -> Scope:
    """Anonymous namespaces retain internal linkage without invented C++ names."""
    kind, name = node.get('kind'), node.get('name', '')
    names, record = parent.names, parent.record
    if kind == 'NamespaceDecl':
        names = (*names, name) if name else names
        record = ''
    elif kind in RECORDS and name and not node.get('isImplicit'):
        names = (*names, name)
        record = '::'.join(names)
    return Scope(names, record, parent.template or kind in TEMPLATES)


class Storage:
    """Every source global/static is retained, including inaccessible storage."""

    def __init__(self, document: dict, root: Path, records: dict) -> None:
        self.root, self.records = root.resolve(), records
        self.contexts: dict[str, Scope] = {}
        self.items: list[dict] = []
        self.context(document)
        self.visit(document)
        self.external_references(document)

    def owned_file(self, node: dict) -> Path | None:
        """Only explicit physical compiler locations identify project declarations."""
        original = node.get('loc', {})
        location = original.get('expansionLoc', original)
        if type(location.get('file')) is not str:
            return None
        path = Path(location['file']).resolve()
        return path if path.is_relative_to(self.root) else None

    def external_references(self, document: dict) -> None:
        """A source reference to foreign storage must not silently lose its root."""
        owned, references = set(), []

        def collect(node: dict, source: Path | None = None) -> None:
            if node.get('kind', '').endswith('Decl'):
                source = self.owned_file(node)
            if node.get('kind') == 'VarDecl' and source is not None:
                owned.add(node.get('id'))
            reference = node.get('referencedDecl', {})
            if source is not None and reference.get('kind') == 'VarDecl':
                references.append((reference, source, node.get('range', {}).get('begin', {}).get('offset', 0)))
            for child in node.get('inner', []):
                collect(child, source)

        collect(document)
        seen = set()
        for reference, source, offset in references:
            identifier = reference.get('id')
            if identifier in owned or identifier in seen:
                continue
            seen.add(identifier)
            name = reference.get('name', '<anonymous>')
            type_ = reference.get('type', {}).get('qualType', 'unknown')
            self.items.append({'name': '<external-storage:' + name + '>', 'expression': name,
                'type': type_, 'symbol': identifier, 'source_file': source.relative_to(self.root).as_posix(),
                'source_offset': offset, 'internal': False, 'private': False, 'definition': False,
                'inaccessible': True, 'reason': 'referenced foreign storage requires an explicit observation fixture'})

    def context(self, node: dict, parent: Scope = Scope()) -> None:
        """Out-of-line statics use their actual compiler-owned declaration scope."""
        scope = nested(node, self.contexts.get(node.get('parentDeclContextId'), parent))
        if node.get('kind') in RECORDS | {'NamespaceDecl'} and node.get('id'):
            self.contexts[node['id']] = scope
        for child in node.get('inner', []):
            self.context(child, scope)

    def visit(self, node: dict, parent: Scope = Scope(), inside: bool = False) -> None:
        """Automatic locals are excluded; persistent locals remain explicit gaps."""
        scope = nested(node, self.contexts.get(node.get('parentDeclContextId'), parent))
        if node.get('kind') == 'VarDecl':
            self.variable(node, scope, inside)
        inside |= node.get('kind') in discovery.NATIVE_CALLABLE_KINDS
        for child in node.get('inner', []):
            self.visit(child, scope, inside)

    def variable(self, node: dict, scope: Scope, inside: bool) -> None:
        """Keep physical source, linkage and access independently of display labels."""
        original = node.get('loc', {})
        location = original.get('expansionLoc', original)
        if type(location.get('file')) is not str or type(location.get('offset')) is not int:
            return
        path = Path(location['file']).resolve()
        if not path.is_relative_to(self.root):
            return
        item = discovery.native_storage(node, scope.names, inside)
        if item is None:
            return
        require(type(node.get('oteleq_internal_linkage')) is bool,
                'compiler storage linkage is missing: ' + node.get('name', '<anonymous>'))
        expression = '::'.join((*scope.names, node.get('name', '')))
        fields = self.records.get(scope.record, {}).get('statics', [])
        field = next((value for value in fields if value['name'] == node.get('name')), None)
        item.update(expression=expression, source_file=path.relative_to(self.root).as_posix(),
                    source_offset=location['offset'], symbol=node.get('mangledName', expression),
                    internal=node['oteleq_internal_linkage'],
                    private=field is not None and field['access'] != 'public',
                    definition=(node.get('storageClass') != 'extern' or 'init' in node) and
                    (not scope.record or node.get('parentDeclContextId') is not None or node.get('inline', False)))
        if scope.template:
            item.update(inaccessible=True, reason='template storage requires a concrete compiler instance fixture')
        self.items.append(item)


def join_constructors(records: dict, functions: list[dict]) -> None:
    """A header constructor declaration can use its checked out-of-line body."""
    for record in records.values():
        for declared in record['constructors']:
            definitions = [item['construction'] for item in functions
                           if item['kind'] == 'CXXConstructorDecl' and item['symbol'] == declared['symbol']
                           and item['has_body']]
            if len(definitions) == 1:
                declared.update(definitions[0])


def unit_inventory(prepared: dict, key: str, evidence: Path, demangler: Path | None, execute) -> dict:
    """One real compile variant includes project headers in its actual language."""
    root, unit = Path(prepared['source_root']), prepared['units'][key]
    path = evidence / 'units' / key / 'metadata.json'
    require(path.is_file() and not path.is_symlink() and
            native_project.digest(path) == unit['metadata_sha256'], 'retained compiler metadata changed')
    document = native_frontend.document(path.read_bytes(), prepared['frontend']['clang_major'])['ast']
    files = sorted({item['source_relative'] for item in unit['dependencies'].values()
                    if item['source_relative'] is not None})
    functions, cpp_functions, records, globals_ = [], [], {}, {}
    for name in files:
        found = discovery.native_inventory(document, root / name, cpp=prepared['language'] == 'cpp')
        functions.extend({**item, 'source_file': name} for item in found['functions'])
        if prepared['language'] == 'cpp':
            for owner, record in found['cpp_records'].items():
                require(owner not in records, 'multiple source definitions of record ' + owner)
                records[owner] = {**record, 'source_file': name}
            cpp_functions.extend({**item, 'source_file': name} for item in found['cpp_functions'])
            globals_.update(found['cpp_globals'])
    if prepared['language'] == 'cpp':
        require(demangler is not None, 'matched C++ symbol resolution is required')
        # Preserve the shared function bindings when adding compiler identities.
        all_functions = []
        for item in functions:
            if 'cpp_function' in item:
                item['cpp_function']['source_file'] = item['source_file']
                all_functions.append(item['cpp_function'])
        cpp_models.bind_symbols({'cpp_functions': all_functions}, demangler, root, execute)
        identities = {(item['source_offset'], item['kind'], item['symbol'], source['source_file']): item
                      for source in functions if (item := source.get('cpp_function')) is not None}
        cpp_functions = [identities.get((item['source_offset'], item['kind'], item['symbol'], item['source_file']), item)
                         for item in cpp_functions]
        join_constructors(records, cpp_functions)
    return {'functions': functions, 'globals': Storage(document, root, records).items,
            'cpp_records': records, 'cpp_functions': cpp_functions, 'cpp_globals': globals_,
            'files': files, 'parser': 'matched Clang project inventory'}


def target_globals(target: dict, inventories: dict) -> list[dict]:
    """Internal storage is per unit; external declarations identify one linked root."""
    groups: dict[tuple, list[dict]] = {}
    for key in target['units']:
        for item in inventories[key]['globals']:
            if item.get('inaccessible'):
                identity = ('gap', key, item['source_file'], item['source_offset'])
            else:
                identity = ('internal', key, item['symbol']) if item['internal'] else ('external', item['symbol'])
            groups.setdefault(identity, []).append({**item, 'unit': key})
    result = []
    for identity, declarations in groups.items():
        require(len({item['type'] for item in declarations}) == 1,
                'linked storage has inconsistent compiler types: ' + declarations[0]['expression'])
        selected = next((item for item in declarations if item['definition']), declarations[0])
        selected = selected.copy()
        if identity[0] == 'gap':
            file_id = hashlib.sha256(selected['source_file'].encode()).hexdigest()[:16]
            selected['name'] = 'unit:' + selected['unit'] + ':' + file_id + ':' + selected['name']
        elif identity[0] == 'internal':
            selected['name'] = 'unit:' + selected['unit'] + ':' + selected['expression']
        selected['declarations'] = [{'unit': item['unit'], 'source_file': item['source_file'],
                                     'source_offset': item['source_offset']} for item in declarations]
        result.append(selected)
    require(len({item['name'] for item in result}) == len(result), 'ambiguous target storage labels')
    return result


def target_inventory(prepared: dict, evidence: Path, demangler: Path | None, execute) -> list[dict]:
    """Retain each target/unit callable variant with its complete required state."""
    inventories = {key: unit_inventory(prepared, key, evidence, demangler, execute) for key in prepared['units']}
    result = []
    for target in prepared['targets']:
        globals_ = target_globals(target, inventories)
        for key in target['units']:
            found = inventories[key]
            for function in found['functions']:
                result.append({'function': function, 'target': target['name'], 'unit': key,
                               'globals': globals_, 'models': {name: found[name] for name in
                               ('cpp_records', 'cpp_functions', 'cpp_globals', 'parser')},
                               'files': sorted({name for unit in target['units'] for name in inventories[unit]['files']})})
    return result
