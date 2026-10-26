"""Independent fixed native workloads, schedules and complete scalar expectations."""

import json
import os
from pathlib import Path
import sys

from qualify_project_tests import toml

STATES = ((True, True), (False, True), (True, False), (False, False))
STARTS = ('11', '01', '10', '00')
MODES = {'c': ('normal', 'transient', 'recursive'),
         'cpp': ('normal', 'transient', 'recursive', 'error')}
SDK_HEAD = 'acb13d7735526448209df37b7e6b98e5717befdb'


def validate(language: str, mode: str, start: str) -> None:
    if language not in MODES or mode not in MODES[language] or start not in STARTS:
        raise ValueError('native metric corpus requires a named language, mode and startup state')


def schedule(start: str) -> list[dict]:
    if start not in STARTS:
        raise ValueError('unknown native metric startup state')
    offset = STARTS.index(start)
    return [{'collection': collection, 'emission': emission}
            for collection, emission in (STATES[(offset + index) % 4] for index in range(4))]


def function(language: str, name: str = 'selected') -> str:
    if language not in MODES or name not in ('selected', 'selected_extra'):
        raise ValueError('unknown native corpus function')
    return name + ('(int)' if language == 'cpp' else '')


def source(language: str, mode: str, *, changed: bool = False) -> str:
    validate(language, mode, '11')
    if type(changed) is not bool:
        raise ValueError('changed-source selection must be boolean')
    prefix = '#include <stdlib.h>\n' + ('#include <stdexcept>\n' if language == 'cpp' else '')
    prefix += ('static_assert' if language == 'cpp' else '_Static_assert') + '(sizeof(int)==4,"int32 corpus");\n'
    prefix += 'int state=7;int calls=0;int depth=0;\n'
    if mode == 'recursive':
        prefix += 'void keep_depth(int *value);\n'

    def body(name: str, version: int) -> str:
        if mode == 'recursive':
            code = ('++depth;keep_depth(&depth);int result=amount>0?' + name + '(amount-1)+1:' + str(version) + ';'
                    'if(amount==0)++state;--depth;keep_depth(&depth);if(depth==0)calls=(calls+1)%4;return result;')
        else:
            code = 'calls=(calls+1)%4;state+=amount;'
            if mode == 'transient':
                code += 'if(getenv("OTELC_NATIVE_PLAN_FD")){if(calls==2)++state;if(calls==0)--state;}'
            if mode == 'error':
                code += 'if(calls==2)throw std::runtime_error("failure-' + str(version) + '\\nafter");'
            code += 'return ' + str(version) + ';'
        return 'int ' + name + '(int amount){' + code + '}\n'

    return prefix + body('selected', 43 if changed else 42) + (body('selected_extra', 44) if changed else '')


def configuration(language: str, mode: str, start: str, sdk: Path) -> dict:
    validate(language, mode, start)
    steps = [{'action': 'call', 'arguments': 'case', 'metrics': flags,
              'expected_baseline': ({'kind': 'error', 'category': 'exception', 'type': 'cpp.std::runtime_error'}
                                    if mode == 'error' and index == 1 else {'kind': 'return'})}
             for index, flags in enumerate(schedule(start))]
    value = {'schema_version': 1, 'languages': [language],
        'limits': {'case_timeout_ms': 30000}, 'functions': {'include': ['selected*']},
        'fixtures': [{'language': language, 'source': 'app.' + ('cpp' if language == 'cpp' else 'c'),
            'function': 'selected*', 'cases': [[5]],
            'domains': [{'kind': 'integer', 'minimum': 0, 'maximum': 5}], 'sequence': steps}],
        'adapters': {language: {'backend': 'prepared', 'sdk_build': str(sdk), 'sdk_source_profile': 'resource-v1'}}}
    if mode == 'recursive':
        extension = 'cpp' if language == 'cpp' else 'c'
        value['adapters'][language].update(compilation_database='build/compile_commands.json',
            targets=[{'name': 'application', 'units': [{'source': name + '.' + extension} for name in ('app', 'keep')],
                      'link_flags': ['-pthread']}])
    return value


def fixture(folder: Path, language: str, mode: str, start: str, sdk: Path) -> tuple[Path, Path]:
    application = folder / 'application'
    application.mkdir(mode=0o700)
    (application / ('app.cpp' if language == 'cpp' else 'app.c')).write_text(source(language, mode))
    if mode == 'recursive':
        extension = 'cpp' if language == 'cpp' else 'c'
        (application / ('keep.' + extension)).write_text('void keep_depth(int *value){volatile int sample=*value;(void)sample;}\n')
        build = application / 'build'; build.mkdir()
        compiler = os.environ.get('OTELC_CLANGXX' if language == 'cpp' else 'OTELC_CLANG')
        if compiler is None:
            prefix = '/opt/homebrew/opt/llvm@22/bin/' if sys.platform == 'darwin' else '/usr/lib/llvm-22/bin/'
            compiler = prefix + ('clang++' if language == 'cpp' else 'clang')
        commands = [{'directory': str(build), 'file': '../' + name + '.' + extension,
            'arguments': [compiler, '-O2', '-fexceptions', '-pthread', '-std=c++17' if language == 'cpp' else '-std=c11',
                          '-c', '../' + name + '.' + extension, '-o', name + '.o']} for name in ('app', 'keep')]
        (build / 'compile_commands.json').write_text(json.dumps(commands, indent=2) + '\n')
    config = folder / 'generation.toml'
    config.write_text('\n'.join(key + '=' + toml(value)
                                for key, value in configuration(language, mode, start, sdk).items()) + '\n')
    return application, config


def scalar(language: str, value: int) -> dict:
    return {'kind': 'integer', 'type': language + '.int', 'bits': 32, 'signed': True, 'value': str(value)}


def expected(language: str, mode: str, amount: int, *, instrumented: bool, version: int = 42) -> list[dict]:
    validate(language, mode, '11')
    if type(amount) is not int or not 0 <= amount <= 5 or type(instrumented) is not bool or version not in (42, 43, 44):
        raise ValueError('invalid independent native metric observation request')
    state, calls, steps = 7, 0, []
    def graph():
        return {'roots': {'global:state': scalar(language, state), 'global:calls': scalar(language, calls),
                          'global:depth': scalar(language, 0)}, 'nodes': []}
    for index in range(4):
        before = graph()
        state += 1 if mode == 'recursive' else amount
        calls = (calls + 1) % 4
        if instrumented and mode == 'transient':
            state += int(calls == 2) - int(calls == 0)
        after = graph()
        outcome_graph = {'roots': dict(after['roots']), 'nodes': []}
        if mode == 'error' and index == 1:
            outcome_graph['roots']['error'] = {'kind': 'reference', 'node_id': 'n0'}
            outcome_graph['nodes'].append({'id': 'n0', 'type': 'cpp.std::runtime_error', 'fields': {
                'message': {'kind': 'bytes', 'type': 'cpp.what', 'hex': ('failure-' + str(version) + '\nafter').encode().hex()}}})
            outcome = {'kind': 'error', 'category': 'exception', 'graph': outcome_graph}
        else:
            outcome_graph['roots']['result'] = scalar(language, version + (amount if mode == 'recursive' else 0))
            outcome = {'kind': 'return', 'graph': outcome_graph}
        steps.append({'id': 'step-' + str(index), 'action': 'call', 'gaps': [],
                      'before': before, 'outcome': outcome, 'after': after})
    return steps
