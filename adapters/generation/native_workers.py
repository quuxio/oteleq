"""Private scalar workers retain real native translation units and link recipes."""
import json
from pathlib import Path

import harness
import native_names
import native_project

C_LINKAGE = 'extern "C" '


def require(condition: bool, reason: str) -> None:
    """Incomplete state or an unsafe build recipe cannot become a passing case."""
    if not condition:
        raise ValueError('native worker: ' + reason)


def scalar(type_: str, language: str) -> None:
    """Only compiler-canonical primitive values have this byte observation codec."""
    require(harness.scalar_type(type_) in harness.native_scalar_types(language),
            'type requires a richer state fixture: ' + type_)


def validate(prepared: dict, entry: dict, args: list) -> dict:
    """Bind the selected call and every target-wide root before creating files."""
    language = prepared['language']
    require(entry['language'] == language, 'entry language differs from the build')
    require(not entry.get('reason'), 'call requires a fixture: ' + entry.get('reason', ''))
    targets = [item for item in prepared['targets'] if item['name'] == entry['target']]
    require(len(targets) == 1 and entry['unit'] in targets[0]['units'], 'missing target/unit binding')
    require(not entry.get('declaration_only') and not entry.get('variadic'),
            'call requires a concrete nonvariadic definition')
    binding = entry.get('cpp_function', {})
    require(not binding or binding['kind'] == 'FunctionDecl', 'member calls require a receiver fixture')
    harness.validate_arguments(entry, args)
    if entry['output'] != 'void':
        scalar(entry['output'], language)
    for item in entry['globals']:
        require(item['unit'] in targets[0]['units'], 'state root is outside the selected target')
        require(not item.get('private') and not item.get('inaccessible'),
                'unobservable state root: ' + item['name'])
        scalar(item['type'], language)
    require(len({item['name'] for item in entry['globals']}) == len(entry['globals']),
            'duplicate state labels')
    return targets[0]


def type_check(expression: str, type_: str, language: str) -> str:
    """Check the actual declaration type before evaluating the source expression."""
    if language == 'cpp':
        return 'static_assert(__is_same(decltype(' + expression + '),' + type_ + '),"root type changed");'
    return '_Static_assert(_Generic(&(' + expression + '),' + type_ + '*:1,default:0),"root type changed");'


def copied_value(expression: str, type_: str, language: str) -> str:
    """The compiler intrinsic cannot call an application-supplied memcpy symbol."""
    assertion = 'static_assert' if language == 'cpp' else '_Static_assert'
    return (assertion + '(sizeof(' + type_ + ')<=8,"scalar exceeds observation buffer");\n' +
            type_ + ' __oteleq_value=' + expression + ';\n' +
            '__builtin_memcpy_inline(__oteleq_out,&__oteleq_value,sizeof(__oteleq_value));\n' +
            'return sizeof(__oteleq_value);\n')


def declaration_prefix(language: str, unprofiled: bool) -> str:
    """Only generated accessors receive the SDK's compiler profiling exclusion."""
    require(type(unprofiled) is bool, 'invalid generated accessor profiling option')
    return (C_LINKAGE if language == 'cpp' else '') + (
        '__attribute__((no_profile_instrument_function)) ' if unprofiled else '')


def invocation(entry: dict, args: list, *, unprofiled: bool = False) -> str:
    """Freeze one exact scalar signature and its concrete invocation inputs."""
    language = entry['language']
    linkage = declaration_prefix(language, unprofiled)
    parameters = ','.join(harness.native_literal(value, harness.scalar_type(type_), language)
                          for value, type_ in zip(args, entry['parameters']))
    name = ('::' if language == 'cpp' else '') + entry['name']
    signature = entry['output'] + '(*)(' + (','.join(entry['parameters']) or 'void') + ')'
    if language == 'cpp':
        binding = 'auto __oteleq_selected=static_cast<' + signature + '>(&' + name + ');\n'
    else:
        binding = ('_Static_assert(__builtin_types_compatible_p(__typeof__(&' + name + '),' +
                   signature + '),"call type changed");\n' + entry['output'] +
                   ' (*__oteleq_selected)(' + (','.join(entry['parameters']) or 'void') + ')=&' + name + ';\n')
    call = '__oteleq_selected(' + parameters + ')'
    returned = call + ';return 0;\n' if entry['output'] == 'void' else copied_value(
        call, harness.scalar_type(entry['output']), language)
    return (linkage + 'unsigned long long __oteleq_invoke(unsigned char* __oteleq_out){\n' +
            binding + returned + '}\n')


def application_helpers(entry: dict, args: list, key: str, *, unprofiled: bool = False) -> str:
    """Append header-free accessors after the original application bytes."""
    language = entry['language']
    linkage = declaration_prefix(language, unprofiled)
    functions = []
    for index, item in enumerate(entry['globals']):
        if item['unit'] != key:
            continue
        expression = ('::' if language == 'cpp' else '') + item['expression']
        functions.append(linkage + 'unsigned long long __oteleq_root_' + str(index) +
                         '(unsigned char* __oteleq_out){\n' +
                         type_check(expression, item['type'], language) + '\n' +
                         copied_value(expression, item['type'], language) + '}\n')
    if key == entry['unit']:
        functions.append(invocation(entry, args, unprofiled=unprofiled))
    code = ''.join(functions)
    names = [entry['name'], *(item['expression'] for item in entry['globals']),
             *entry['parameters'], entry['output'], *(item['type'] for item in entry['globals'])]
    return '\n' + native_names.undefinitions(code, names, cpp=language == 'cpp') + code


def driver(entry: dict) -> str:
    """One clean translation unit frames the complete before/return/after record."""
    cpp = entry['language'] == 'cpp'
    linkage = C_LINKAGE if cpp else ''
    names = ['__oteleq_root_' + str(index) for index in range(len(entry['globals']))] + ['__oteleq_invoke']
    declarations = ''.join(linkage + 'unsigned long long ' + name + '(unsigned char*);\n' for name in names)
    state = ''.join('if(!__oteleq_read(out,' + name + ',' + json.dumps(item['name'] + ':' + item['type']) +
                    ',sizeof(' + item['type'] + ')))return 92;\n'
                    for name, item in zip(names, entry['globals']))
    result_type = harness.scalar_type(entry['output'])
    if result_type == 'void':
        invoke = 'if(__oteleq_invoke(buffer)!=0)return 92;fputs("return:void\\n",out);'
    else:
        invoke = ('if(!__oteleq_read(out,__oteleq_invoke,' + json.dumps('return:' + result_type) +
                  ',sizeof(' + result_type + ')))return 92;')
    if cpp:
        invoke = ('try{' + invoke + '}catch(const std::exception& error){' +
                  'if(!__oteleq_error(out,error))return 91;}catch(...){return 91;}')
    support = '#include <stdio.h>\n#include <stdlib.h>\n'
    if cpp:
        support += '#include <exception>\n#include <typeinfo>\n' + harness.native_guards('cpp')
    support += harness.native_abi() + r'''
static int __oteleq_read(FILE* out,unsigned long long (*read)(unsigned char*),const char* label,size_t size){
  unsigned char buffer[8];
  if(size>8 || read(buffer)!=size)return 0;
  fprintf(out,"%s:",label);
  for(size_t i=0;i<size;i++)fprintf(out,"%02x",buffer[i]);
  fputc('\n',out);return 1;
}
'''
    if 'sequence_configuration' in entry:
        return controlled_driver(entry, support, declarations, state, invoke)
    return (support + declarations + 'int main(void){\n' +
            'const char* path=getenv("OTELEQ_OBSERVATION");if(!path)return 90;\n' +
            'FILE* out=fopen(path,"wb");if(!out)return 90;unsigned char buffer[8];\n' +
            '__oteleq_abi(out);fputs("before\\n",out);\n' + state + invoke +
            '\nfputs("after\\n",out);\n' + state + 'return fclose(out)!=0;}\n')


def controlled_driver(entry: dict, support: str, declarations: str, state: str, invoke: str) -> str:
    """Keep each call's original scalar frame private until its after checkpoint."""
    import native_sequence

    native_sequence.configuration(entry, entry['sequence_configuration'])
    header = Path(__file__).with_name('native_rendezvous.h').read_text()
    # Preserve errno across observer output, checkpoints and frame publication.
    support = support.replace('read(buffer)!=size)return 0;',
                              'read(buffer)!=size)return 0;int saved=errno;')
    support = support.replace("fputc('\\n',out);return 1;", "fputc('\\n',out);errno=saved;return 1;")
    invoke = invoke.replace('if(!__oteleq_error(out,error))return 91;',
                            'int saved=errno;if(!__oteleq_error(out,error))return 91;errno=saved;')
    buffer = 'unsigned char buffer[8];' if harness.scalar_type(entry['output']) == 'void' else ''
    frame = ('static int __oteleq_frame(FILE* out){\n' + buffer + 'int initial=errno;\n' +
             '__oteleq_abi(out);fputs("before\\n",out);\n' + state + '\nerrno=initial;\n' + invoke +
             '\nint ended=errno;fputs("after\\n",out);\n' + state + '\nerrno=ended;return 0;}\n')
    calls = []
    for index in range(len(entry['sequence_configuration'])):
        text = str(index)
        calls.append('if(!__oteleq_native_checkpoint("before-' + text + '"))return 93;\n' +
                     '{FILE* out=__oteleq_native_frame(' + text + ');if(!out)return 90;\n' +
                     'int result=__oteleq_frame(out);int saved=errno;int closed=fclose(out);errno=saved;\n' +
                     'if(result)return result;if(closed)return 90;}\n' +
                     'if(!__oteleq_native_checkpoint("after-' + text + '"))return 93;\n')
    return header + '\n' + support + declarations + frame + 'int main(void){\n' + ''.join(calls) + \
        'return __oteleq_native_checkpoint("finish")?0:93;}\n'


def checked_snapshot(project: Path, prepared: dict) -> None:
    """A worker consumes an independent, unchanged copy of every project input."""
    original = Path(prepared['source_root']).resolve()
    require(not project.is_relative_to(original) and not original.is_relative_to(project),
            'application worker must be a separate private source copy')
    for name, expected in prepared['local_inputs'].items():
        path = project / name
        require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(project)
                and native_project.digest(path) == expected, 'private build input changed: ' + name)


def instrumented_command(step: dict, prefix: list[str], language: str) -> list[str]:
    """The SDK owns instrumented object transforms and their validated markers."""
    require(language in ('c', 'cpp'), 'instrumented target language must be c or cpp')
    if step['kind'] == 'rename-main':
        return [*prefix, 'object', 'rename-main', step['input'], '--output', step['output'],
                '--symbol', '__oteleq_original_main']
    require(step['kind'] in ('compile', 'driver', 'link'), 'unknown build step')
    return [*prefix, 'clang++' if language == 'cpp' else 'clang', *step['command'][1:]]


def materialise(project: Path, prepared: dict, entry: dict, args: list, directory: Path, *, unprofiled: bool = False) -> dict:
    """Create explicit VFS, compile, object-symbol rewrite and target-link recipes."""
    target = validate(prepared, entry, args)
    project, directory = project.resolve(), directory.resolve()
    checked_snapshot(project, prepared)
    require(not directory.is_relative_to(project) and not project.is_relative_to(directory),
            'helper output must be separate from application source')
    directory.mkdir(parents=True, exist_ok=False)
    compiler = prepared['compiler']['path']
    steps, objects, assets = [], [], {}
    for key in target['units']:
        unit = prepared['units'][key]
        source = project / unit['source']
        augmented = directory / (key + source.suffix)
        augmented.write_bytes(source.read_bytes() + application_helpers(entry, args, key, unprofiled=unprofiled).encode())
        overlay = directory / (key + '.vfs.json')
        overlay.write_text(json.dumps({'version': 0, 'use-external-names': False, 'roots': [
            {'type': 'file', 'name': str(source), 'external-contents': str(augmented)}]}) + '\n')
        original, renamed = directory / (key + '.original.o'), directory / (key + '.o')
        command = [compiler, *unit['flags'], '-ivfsoverlay', str(overlay), '-c', str(source), '-o', str(original)]
        steps.append({'kind': 'compile', 'unit': key, 'directory': str(project / unit['directory']),
                      'command': command, 'output': str(original)})
        steps.append({'kind': 'rename-main', 'unit': key, 'directory': str(directory), 'input': str(original),
                      'command': [str(Path(compiler).resolve().with_name('llvm-objcopy')),
                                  '--redefine-sym', 'main=__oteleq_original_main',
                                  '--redefine-sym', '_main=___oteleq_original_main', str(original), str(renamed)],
                      'output': str(renamed)})
        objects.append(str(renamed))
        assets.update({str(path): native_project.digest(path) for path in (augmented, overlay)})
    language = entry['language']
    main = directory / ('driver.cpp' if language == 'cpp' else 'driver.c')
    main.write_text(driver(entry))
    object_ = directory / 'driver.o'
    steps.append({'kind': 'driver', 'directory': str(directory), 'command': [compiler,
                  '-std=c++17' if language == 'cpp' else '-std=c11', '-O1', '-c', str(main), '-o', str(object_)],
                  'output': str(object_)})
    binary = directory / 'worker'
    steps.append({'kind': 'link', 'directory': str(directory), 'command': [compiler, *objects, str(object_),
                  *target['link_flags'], '-o', str(binary)], 'output': str(binary)})
    assets[str(main)] = native_project.digest(main)
    return {'steps': steps, 'assets': assets, 'binary': str(binary), 'project': str(project),
            'target': target['name'], 'entry_unit': entry['unit']}
