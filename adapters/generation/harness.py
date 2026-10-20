"""Deterministic scalar corpora and diagnostic harness materialisation."""
import json
import ctypes
import math
import posixpath
from pathlib import Path
import random
import struct

import domains
import go_project
import node_receivers
import java_receivers
import python_project
import sequences

NATIVE_INTEGERS = {
    "int", "long", "short", "signed", "signed int", "long long", "unsigned", "unsigned int",
    "unsigned long", "unsigned short", "unsigned long long", "char", "signed char", "unsigned char",
}
INTEGERS = NATIVE_INTEGERS | {
    "int8", "int16", "int32", "int64", "uint", "uint8", "uint16", "uint32", "uint64", "byte",
    "i8", "i16", "i32", "i64", "i128", "isize", "u8", "u16", "u32", "u64", "u128", "usize",
}
FLOATS = {"float", "double", "f32", "f64", "float32", "float64", "number"}
STRINGS = {"str", "string", "String", "java.lang.String"}
BOOLS = {"bool", "boolean", "_Bool"}
VOIDS = {"void", "()", "None", "NoneType"}


def native_scalar_types(language: str) -> set[str]:
    """Native spellings only; aliases need canonical compiler type resolution."""
    boolean = "_Bool" if language == "c" else "bool"
    return NATIVE_INTEGERS | {"float", "double", boolean}


def scalar_type(name):
    return name.replace("const ", "").strip()


def values(name, language):
    name = scalar_type(name)
    if language in ("c", "cpp") and name not in native_scalar_types(language):
        return None
    if name in BOOLS:
        return [False, True]
    if name in INTEGERS:
        return [0, 1, 2] if name.startswith(("u", "unsigned")) or name in ("byte", "char") else [0, 1, -1]
    if name in FLOATS:
        return [0.0, 1.0, -1.0]
    if name in STRINGS and language not in ("c", "cpp", "rust"):
        return ["", "a", "edge\nvalue"]
    if name in ("dynamic", "unknown") and language in ("python", "javascript", "typescript"):
        return [0, 1, -1, "", True, None]
    return None


def float_width(name: str, language: str) -> int:
    """Resolve the primitive floating representation used by this caller."""
    return 32 if name in ("f32", "float32") or name == "float" and language in ("c", "cpp", "java") else 64


def finite_number(value: object) -> bool:
    """Recognise finite scalar numbers without overflowing an implicit conversion."""
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def validate_arguments(entry, arguments):
    """Reject a fixture which would be narrowed or passed to an unsupported type."""
    if len(arguments) != len(entry["parameters"]):
        raise ValueError("configured fixture argument count differs from the callable")
    for value, parameter in zip(arguments, entry["parameters"]):
        validate_argument(value, scalar_type(parameter), entry["language"])


def validate_argument(value: object, name: str, language: str) -> None:
    """Apply the scalar domain contract before generating source literals."""
    if values(name, language) is None:
        raise ValueError("argument type requires an object or buffer fixture: " + name)
    if name in INTEGERS:
        validate_integer(value, name, language)
        return
    if name in FLOATS:
        validate_float(value, name, language)
        return
    for names, expected, label in ((BOOLS, bool, "boolean"), (STRINGS, str, "string")):
        if name in names and type(value) is not expected:
            raise ValueError("configured " + label + " argument requires a " + label)


def validate_integer(value: object, name: str, language: str) -> None:
    """Check exact integer type and the qualified representable range."""
    if type(value) is not int:
        raise ValueError("configured integer argument requires an integer")
    low, high = integer_range(name, language)
    if low is not None and not low <= value <= high:
        raise ValueError("configured integer argument exceeds its qualified type range: " + name)


def validate_float(value: object, name: str, language: str) -> None:
    """Keep non-finite and overflowing requests outside the finite scalar corpus."""
    if not finite_number(value):
        raise ValueError("configured floating argument requires a finite number")
    if float_width(name, language) == 32 and abs(value) > 3.4028234663852886e38:
        raise ValueError("configured floating argument exceeds its target type")


def integer_range(name, language):
    """Bounds for the current host builds; cross-target build contexts need their own ABI."""
    if language == "python" and name == "int":
        return None, None
    if language in ("javascript", "typescript"):
        return -(2**53 - 1), 2**53 - 1
    if language in ("c", "cpp") and name == "char":
        return 0, 127
    if language == "java":
        bits = {"byte": 8, "short": 16, "char": 16, "int": 32, "long": 64}[name]
        unsigned = name == "char"
    else:
        c_types = {"char": ctypes.c_byte, "signed char": ctypes.c_byte, "unsigned char": ctypes.c_ubyte,
                   "short": ctypes.c_short, "unsigned short": ctypes.c_ushort, "int": ctypes.c_int,
                   "signed": ctypes.c_int, "signed int": ctypes.c_int, "unsigned": ctypes.c_uint,
                   "unsigned int": ctypes.c_uint, "long": ctypes.c_long, "unsigned long": ctypes.c_ulong,
                   "long long": ctypes.c_longlong, "unsigned long long": ctypes.c_ulonglong}
        suffix = next((name[len(prefix):] for prefix in ("uint", "int", "u", "i")
                       if name.startswith(prefix) and name[len(prefix):].isdecimal()), "")
        if suffix.isdecimal():
            bits = int(suffix)
        elif name == "byte":
            bits = 8
        else:
            bits = ctypes.sizeof(c_types.get(name, ctypes.c_void_p)) * 8
        unsigned = name.startswith(("u", "unsigned")) or name == "byte"
    return (0, 2**bits - 1) if unsigned else (-2**(bits - 1), 2**(bits - 1) - 1)


def expanded_pool(name, language, count, rng):
    """Keep deterministic edges first, then add seeded finite scalar samples."""
    pool = values(name, language)
    if pool is None or scalar_type(name) in BOOLS or scalar_type(name) in ("dynamic", "unknown"):
        return pool
    for _ in range(count * 4):
        if len(pool) >= count:
            break
        value = scalar_sample(scalar_type(name), language, rng)
        if value not in pool:
            pool.append(value)
    return pool


def scalar_sample(name: str, language: str, rng: random.Random):
    """Sample within small legal domains; explicit fixtures supply business values."""
    if name in INTEGERS:
        low, high = integer_range(name, language)
        return rng.randint(max(-127, low if low is not None else -127), min(127, high if high is not None else 127))
    if name in FLOATS:
        return rng.uniform(-128, 128)
    return "".join(rng.choice("abcXYZ0129 ") for _ in range(rng.randrange(1, 25)))


def corpus(entry, count, seed=20261008):
    if "input_cases" in entry:
        concrete = [concrete_arguments(entry, arguments) for arguments in entry["input_cases"]]
        if "input_domains" in entry:
            for arguments in concrete:
                domains.arguments(arguments, entry["input_domains"])
        if len({json.dumps(arguments) for arguments in concrete}) != len(concrete):
            raise ValueError("configured cases collapse to duplicate target representations")
        return concrete
    rng = random.Random(entry.get("generation_seed", seed))
    pools = [expanded_pool(t, entry["language"], count, rng) for t in entry["parameters"]]
    if any(pool is None for pool in pools):
        raise ValueError("argument type requires a concrete fixture")
    if not pools:
        return [[]]
    # Bounded diagonal plus shifted columns: deterministic, not exhaustive Cartesian coverage.
    candidates = [[pool[(index + column) % len(pool)] for column, pool in enumerate(pools)] for index in range(count)]
    unique = {}
    for candidate in candidates:
        candidate = concrete_arguments(entry, candidate)
        unique.setdefault(json.dumps(candidate), candidate)
    return list(unique.values())


def concrete_arguments(entry, arguments):
    """Freeze the actual target scalar representation and retain requests separately."""
    validate_arguments(entry, arguments)
    result = []
    for value, parameter in zip(arguments, entry["parameters"]):
        name, language = scalar_type(parameter), entry["language"]
        numeric_node = language in ("javascript", "typescript") and type(value) in (int, float)
        if name in FLOATS or numeric_node:
            if not finite_number(value):
                raise ValueError("configured numeric input exceeds the target representation")
            representation = ">f" if float_width(name, language) == 32 else ">d"
            value = struct.unpack(representation, struct.pack(representation, float(value)))[0]
        result.append(value)
    return result


def java_literal(value, type_):
    """Use UTF-16 code units and legal long constants without source escape loss."""
    if type_ in STRINGS and any(ord(char) < 32 or ord(char) > 126 for char in value):
        encoded = value.encode("utf-16-be", errors="surrogatepass")
        units = ["(char)0x" + encoded[index:index + 2].hex() for index in range(0, len(encoded), 2)]
        return "new java.lang.String(new char[]{" + ",".join(units) + "})"
    if type_ == "long":
        return "(long)" + str(value) + "L"
    if type_ in ("byte", "short", "char", "float"):
        return "(" + type_ + ")" + str(value).lower()
    return json.dumps(value)


def native_literal(value, type_, language):
    """Avoid implementation-defined integer literal narrowing in the native caller."""
    if type(value) is int and type_ in INTEGERS:
        suffix = "ULL" if type_.startswith(("u", "unsigned")) else "LL"
        number = "(-9223372036854775807LL-1)" if value == -(2**63) else str(value) + suffix
        return "(" + type_ + ")" + number
    if language == "c" and type(value) is bool:
        return "1" if value else "0"
    return json.dumps(value)


def go_literal(value: object, type_: str) -> str:
    """Freeze Go bits and boolean expressions independently of source bindings."""
    if type(value) is bool:
        return type_ + "(1==" + ("1" if value else "0") + ")"
    if type_ in ("float32", "float64"):
        width = float_width(type_, "go")
        bits = struct.pack(">f" if width == 32 else ">d", value).hex()
        return f"__oteleq_math.Float{width}frombits(0x{bits})"
    return type_ + "(" + json.dumps(value) + ")"


def literal(value, type_, language):
    type_ = scalar_type(type_)
    if language == "java":
        return java_literal(value, type_)
    if language in ("c", "cpp"):
        return native_literal(value, type_, language)
    if language == "rust":
        if isinstance(value, bool):
            return str(value).lower()
        return str(value) + (".0" if type_ in ("f32", "f64") and type(value) is int else "") + type_
    if language == "go":
        return go_literal(value, type_)
    return json.dumps(value)


def global_gaps(entry):
    if entry["language"] in ("python", "javascript", "typescript"):
        gaps = [g["name"] for g in entry["globals"] if g["name"].startswith("<")]
        if "receiver_fixture" in entry and entry["language"] == "python":
            gaps.extend("static:" + entry["python_receiver_class"] + "." + item["name"]
                        for item in entry.get("python_class_roots", [])
                        if item["name"].startswith("<") or item["name"].startswith("__") and not item["name"].endswith("__"))
        return gaps
    scalar = INTEGERS | FLOATS | BOOLS
    if entry["language"] in ("c", "cpp"):
        scalar = native_scalar_types(entry["language"])
    if entry["language"] in ("go", "java"):
        scalar |= STRINGS
    return [g["name"] for g in entry["globals"]
            if scalar_type(g["type"]) not in scalar or g.get("private") or g.get("inaccessible")]


def python_driver(entry, args):
    globals_ = [g["name"] for g in entry["globals"]]
    loader = python_project.loader(entry["python_import"]) if "python_import" in entry else '''sys.path.insert(0, str(target.parent))
spec = importlib.util.spec_from_file_location("_oteleq_target", target)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
'''
    setup, binding, receiver_root = "", f"function = bound_function(module, {entry['name']!r}, expected_code)", ""
    if "receiver_fixture" in entry:
        fixture = entry["receiver_fixture"]
        setup = (f"expected_factory = function_code(target, {fixture['source_function']!r}, {fixture['line']!r})"
                 if fixture["source_function"] else "expected_factory = None")
        binding = f"receiver, function = bound_receiver(module, {entry['python_receiver_class']!r}, {entry['name'].rsplit('.', 1)[-1]!r}, expected_code, {fixture!r}, expected_factory)\nreceiver_class = type(receiver)"
        names = [item["name"] for item in entry.get("python_class_roots", [])]
        prefix = "static:" + entry["python_receiver_class"] + "."
        receiver_root = f', "receiver": receiver, **{{{prefix!r} + name: class_members(receiver_class).get(name, MISSING) for name in {names!r}}}'
    return f'''# Generated by oteleq. Boilerplate is MIT licensed.
import importlib.util, json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _oteleq_observe import graph, MISSING, function_code, bound_function, bound_receiver, class_members
target = Path({entry['path']!r}).resolve()
expected_code = function_code(target, {entry['name']!r}, {entry['line']!r})
{setup}
{loader}
arguments = {args!r}
{binding}
def roots():
    return {{**{{"global:" + name: vars(module).get(name, MISSING) for name in {globals_!r}}}, "arguments": arguments{receiver_root}}}
before = graph(roots())
try:
    result = function(*arguments)
except Exception as error:
    outcome = {{"kind": "error", "value": graph({{"error": error, **roots()}})}}
else:
    outcome = {{"kind": "return", "value": graph({{"result": result, **roots()}})}}
after = graph(roots())
Path(os.environ["OTELEQ_OBSERVATION"]).write_text(json.dumps({{"before": before, "outcome": outcome, "after": after}}, sort_keys=True))
'''


JS_OBSERVER = Path(__file__).with_name("node_observe.mjs").read_text()


def js_driver(entry, args, source):
    if "receiver_fixture" in entry:
        sequence = sequences.concrete(entry, args, concrete_arguments) if "sequence_configuration" in entry else None
        return node_receivers.driver(entry, args, source, sequence)
    roots = "".join(json.dumps("global:" + g["name"]) + ":" + g["name"] + "," for g in entry["globals"])
    # Capture the hoisted declaration before application statements can rebind
    # it, retaining hashbang/directive syntax at the parser-selected position.
    raw = source.encode()
    position = entry.get("binding_capture_offset", 0)
    helper = posixpath.relpath("_oteleq_generated/node_observe.mjs", str(Path(entry["path"]).parent))
    helper = helper if helper.startswith(".") else "./" + helper
    capture = (";const __oteleqSelected=" + entry["name"] + ";\nconst __oteleqObserver=await import(" + json.dumps(helper) + ");\n").encode()
    source = (raw[:position] + capture + raw[position:]).decode()
    return source + f'''
const __oteleqArguments={json.dumps(args)};
const __oteleqRoots=()=>({{{roots}arguments:__oteleqArguments}});
await __oteleqObserver.run(__oteleqSelected,__oteleqArguments,__oteleqRoots,{str(bool(entry.get('async'))).lower()},()=>typeof __oteleqSelected==='function' && {entry['name']}===__oteleqSelected);
'''


def native_guards(language: str) -> str:
    """Resolve source aliases through the compiler before any raw scalar read."""
    if language == "cpp":
        return r'''
#include <type_traits>
#include <stdexcept>
template<class T> using __oteleq_type = std::remove_cv_t<std::remove_reference_t<T>>;
template<class T> constexpr bool __oteleq_scalar =
  (std::is_integral_v<__oteleq_type<T>> && sizeof(T)<=8) ||
  std::is_same_v<__oteleq_type<T>,float> ||
  std::is_same_v<__oteleq_type<T>,double>;
#define __oteleq_assert_scalar(T) static_assert(__oteleq_scalar<T>, "native type requires a scalar fixture")
#define __oteleq_assert_value(v) __oteleq_assert_scalar(decltype(v))
static bool __oteleq_error(FILE* out,const std::exception& error){
  const std::type_info& kind=typeid(error);
  const char* label=nullptr;
#define __oteleq_exception(T) if(kind==typeid(T)) label=#T;
  __oteleq_exception(std::exception) __oteleq_exception(std::runtime_error)
  __oteleq_exception(std::logic_error) __oteleq_exception(std::invalid_argument)
  __oteleq_exception(std::domain_error) __oteleq_exception(std::length_error)
  __oteleq_exception(std::out_of_range) __oteleq_exception(std::range_error)
  __oteleq_exception(std::overflow_error) __oteleq_exception(std::underflow_error)
#undef __oteleq_exception
  if(!label) return false;
  fprintf(out,"error:%s\t%s\n",label,error.what());
  return true;
}
'''
    return r'''
typedef _Bool __oteleq_bool;
typedef char __oteleq_char;
typedef signed char __oteleq_schar;
typedef unsigned char __oteleq_uchar;
typedef short __oteleq_short;
typedef unsigned short __oteleq_ushort;
typedef int __oteleq_int;
typedef unsigned int __oteleq_uint;
typedef long __oteleq_long;
typedef unsigned long __oteleq_ulong;
typedef long long __oteleq_llong;
typedef unsigned long long __oteleq_ullong;
typedef float __oteleq_float;
typedef double __oteleq_double;
#define __oteleq_scalar_value(v) _Generic((v), \
  __oteleq_bool:1, __oteleq_char:1, __oteleq_schar:1, __oteleq_uchar:1, \
  __oteleq_short:1, __oteleq_ushort:1, __oteleq_int:1, __oteleq_uint:1, \
  __oteleq_long:1, __oteleq_ulong:1, __oteleq_llong:1, __oteleq_ullong:1, \
  __oteleq_float:1, __oteleq_double:1, default:0)
#define __oteleq_assert_value(v) _Static_assert(__oteleq_scalar_value(v), "native type requires a scalar fixture")
#define __oteleq_assert_scalar(T) __oteleq_assert_value(*((T*)0))
'''


def native_abi() -> str:
    """Emit actual compiler representation metadata before application macros."""
    types = sorted(NATIVE_INTEGERS | {"float", "double"})
    fields = ",".join(json.dumps(name) + ":%zu" for name in types)
    format_ = 'abi:{"byte_order":"%s","char_signed":%s,"char_bits":%d,"ieee754":%s,"bits":{' + fields + '}}\n'
    arguments = ','.join('sizeof(' + name + ')*CHAR_BIT' for name in types)
    return '#include <limits.h>\n#include <float.h>\nstatic void __oteleq_abi(FILE* out){unsigned int one=1;\nfprintf(out,' + json.dumps(format_) + ',*((unsigned char*)&one)?"little":"big",((char)-1<0)?"true":"false",CHAR_BIT,(FLT_RADIX==2 && FLT_MANT_DIG==24 && DBL_MANT_DIG==53 && FLT_MAX_EXP==128 && DBL_MAX_EXP==1024)?"true":"false",' + arguments + ');}\n'


def native_driver(entry, args):
    parameters = ", ".join(literal(v, t, entry["language"]) for v, t in zip(args, entry["parameters"]))
    output = scalar_type(entry["output"])
    call = entry["name"] + "(" + parameters + ")"
    returned = call + "; fputs(\"return:void\\n\", out);" if output == "void" else output + " result=" + call + '; __oteleq_bytes(out,"return:' + output + '",&result,sizeof(result));'
    state = "\n".join('__oteleq_bytes(out,' + json.dumps(g["name"] + ":" + g["type"]) + ',&' + g["name"] + ',sizeof(' + g["name"] + '));' for g in entry["globals"])
    invocation = returned
    if entry["language"] == "cpp":
        invocation = 'try {' + returned + '} catch(const std::exception& e){if(!__oteleq_error(out,e)){fclose(out);return 91;}} catch(...){fclose(out);return 91;}'
    headers = '#include <exception>\n#include <typeinfo>\n' if entry["language"] == "cpp" else ''
    arguments_checked = "\n".join("__oteleq_assert_scalar(" + type_ + ");" for type_ in entry["parameters"])
    return headers + '''#include <stdio.h>
#include <stdlib.h>
''' + native_guards(entry["language"]) + native_abi() + '''
static void __oteleq_raw_bytes(FILE* out,const char* label,const void* v,size_t n){
  const unsigned char* p=(const unsigned char*)v; fprintf(out,"%s:",label);
  for(size_t i=0;i<n;i++) fprintf(out,"%02x",p[i]); fputc('\\n',out);
}
#define __oteleq_bytes(out,label,value,size) do { \\
  __oteleq_assert_value(*(value)); \\
  __oteleq_raw_bytes((out),(label),(value),(size)); \\
} while(0)
#define main __oteleq_original_main
#include ''' + json.dumps(entry["path"]) + '''
#undef main
int main(void){ FILE* out=fopen(getenv("OTELEQ_OBSERVATION"),"wb"); if(!out)return 90;
__oteleq_abi(out);
fputs("before\\n",out);
''' + arguments_checked + '\n' + state + '\n' + invocation + '\nfputs("after\\n",out);\n' + state + '\nreturn fclose(out)!=0;}\n'


def rename_main(source, entries, language):
    main = next((e for e in entries if e["name"] == "main"), None)
    if not main:
        return source
    if language == "go":
        offset = main["name_offset"]
    else:
        offset = sum(len(line.encode()) for line in source.splitlines(keepends=True)[:main["line"] - 1]) + main["column"]
    encoded = source.encode()
    if encoded[offset:offset + 4] != b"main":
        raise ValueError("entrypoint source range does not match AST")
    return (encoded[:offset] + b"__oteleq_original_main" + encoded[offset + 4:]).decode()


def rust_driver(entry, args, source):
    call = entry["name"] + "(" + ",".join(literal(v, t, "rust") for v, t in zip(args, entry["parameters"])) + ")"
    state_lines = []
    for global_ in entry["globals"]:
        expression = "unsafe {" + global_["name"] + "}"
        state_lines.append('s.push_str(&__oteleq_std::format!(' + json.dumps(global_["name"] + ':{}\n') + ',__oteleq_value(&' + expression + ')));')
    state = "\n".join(state_lines)
    return rename_main(source, entry["file_functions"], "rust") + rust_codec() + f'''
fn main() {{
    let mut s=__oteleq_std::format!("abi:{{{{\\\"pointer_bits\\\":{{}}}}}}\\nbefore\\n",__oteleq_std::mem::size_of::<__oteleq_std::primitive::usize>()*8); {state}
    match __oteleq_std::panic::catch_unwind(|| {call}) {{
      Ok(v)=>s.push_str(&__oteleq_std::format!("return:{{}}\\n",__oteleq_value(&v))),
      Err(payload)=>{{
        if let Some(v)=payload.downcast_ref::<__oteleq_std::string::String>() {{ s.push_str(&__oteleq_std::format!("error:string:{{:?}}\\n",v)); }}
        else if let Some(v)=payload.downcast_ref::<&__oteleq_std::primitive::str>() {{ s.push_str(&__oteleq_std::format!("error:str:{{:?}}\\n",v)); }}
        else {{ __oteleq_std::process::exit(91); }}
      }},
    }}
    s.push_str("after\\n"); {state}
    __oteleq_std::fs::write(__oteleq_std::env::var("OTELEQ_OBSERVATION").unwrap(),s).unwrap();
}}
'''


def rust_codec() -> str:
    """A closed implementation set prevents application Debug/to_bits callbacks."""
    return r'''
extern crate std as __oteleq_std;
#[allow(non_camel_case_types)]
trait __oteleq_Value { fn capture(&self)->__oteleq_std::string::String; }
macro_rules! __oteleq_scalar {($(($label:ident,$kind:ty)),*)=>{$(
  impl __oteleq_Value for $kind {
    fn capture(&self)->__oteleq_std::string::String {__oteleq_std::format!("{}:{:?}",__oteleq_std::stringify!($label),self)}
  }
)*}}
__oteleq_scalar!((bool,__oteleq_std::primitive::bool),(char,__oteleq_std::primitive::char),
  (i8,__oteleq_std::primitive::i8),(i16,__oteleq_std::primitive::i16),(i32,__oteleq_std::primitive::i32),
  (i64,__oteleq_std::primitive::i64),(i128,__oteleq_std::primitive::i128),(isize,__oteleq_std::primitive::isize),
  (u8,__oteleq_std::primitive::u8),(u16,__oteleq_std::primitive::u16),(u32,__oteleq_std::primitive::u32),
  (u64,__oteleq_std::primitive::u64),(u128,__oteleq_std::primitive::u128),(usize,__oteleq_std::primitive::usize),
  (String,__oteleq_std::string::String),(str,&__oteleq_std::primitive::str),(unit,()));
impl __oteleq_Value for __oteleq_std::primitive::f32 {
  fn capture(&self)->__oteleq_std::string::String {
    __oteleq_std::format!("f32:{:08x}",__oteleq_std::primitive::f32::to_bits(*self))
  }
}
impl __oteleq_Value for __oteleq_std::primitive::f64 {
  fn capture(&self)->__oteleq_std::string::String {
    __oteleq_std::format!("f64:{:016x}",__oteleq_std::primitive::f64::to_bits(*self))
  }
}
fn __oteleq_value<T:__oteleq_Value>(value:&T)->__oteleq_std::string::String {value.capture()}
'''


def go_driver(entry, args, source):
    source = (go_project.rename_entrypoint(source, entry["go_main_renames"]) if "go_main_renames" in entry
              else rename_main(source, entry["file_functions"], "go"))
    position = entry["package_end"]
    imports = '\nimport (__oteleq_fmt "fmt"; __oteleq_os "os"; __oteleq_math "math"; __oteleq_reflect "reflect")\n'
    raw = source.encode()
    source = (raw[:position] + imports.encode() + raw[position:]).decode()
    declared = entry.get("go_parameter_types", entry["parameters"])
    arguments = [literal(value, kind, "go") if kind == original else original + "(" + literal(value, kind, "go") + ")"
                 for value, kind, original in zip(args, entry["parameters"], declared)]
    call = entry["name"] + "(" + ",".join(arguments) + ")"
    invoked = call + ';s+="return:void\\n"' if entry["output"] == "void" else 's+="return:"+__oteleqValue(' + call + ')+"\\n"'
    state = "\n".join('s+=' + json.dumps(g["name"] + ':') + '+__oteleqValue(' + g["name"] + ')+"\\n"' for g in entry["globals"])
    worker = go_project.BRIDGE if entry.get("go_context", {}).get("package", "main") != "main" else "main"
    return source + f'''
func __oteleqValue(v interface{{}}) string {{
 x:=__oteleq_reflect.ValueOf(v)
 if !x.IsValid(){{return "<nil>:<nil>"}}
 kind:=x.Type().String()+":"
 if x.Type().String()!=x.Kind().String(){{kind="@"+x.Kind().String()+"|"+kind}}
 switch x.Kind() {{
 case __oteleq_reflect.Float32:
  bits:=__oteleq_reflect.ValueOf(__oteleq_math.Float32bits).Call([]__oteleq_reflect.Value{{x.Convert(__oteleq_reflect.TypeOf(__oteleq_math.Float32frombits(0)))}})[0].Uint()
  return kind+__oteleq_fmt.Sprintf("%08x",bits)
 case __oteleq_reflect.Float64:return kind+__oteleq_fmt.Sprintf("%016x",__oteleq_math.Float64bits(x.Float()))
 case __oteleq_reflect.Bool:return kind+__oteleq_fmt.Sprintf("%#v",x.Bool())
 case __oteleq_reflect.String:return kind+__oteleq_fmt.Sprintf("%#v",x.String())
 case __oteleq_reflect.Int,__oteleq_reflect.Int8,__oteleq_reflect.Int16,__oteleq_reflect.Int32,__oteleq_reflect.Int64:return kind+__oteleq_fmt.Sprintf("%#v",x.Int())
 case __oteleq_reflect.Uint,__oteleq_reflect.Uint8,__oteleq_reflect.Uint16,__oteleq_reflect.Uint32,__oteleq_reflect.Uint64:return kind+__oteleq_fmt.Sprintf("%#v",x.Uint())
 default:__oteleq_os.Exit(91);return ""
 }}
}}
func {worker}(){{
 s:=__oteleq_fmt.Sprintf(`abi:{{"pointer_bits":%d}}`+"\\nbefore\\n",__oteleq_reflect.TypeOf(0).Bits()); {state}
 func(){{defer func(){{if p:=recover();__oteleq_reflect.ValueOf(p).IsValid(){{s+="error:"+__oteleqValue(p)+"\\n"}}}}();{invoked}}}()
 s+="after\\n"; {state}
 if err:=__oteleq_os.WriteFile(__oteleq_os.Getenv("OTELEQ_OBSERVATION"),[]byte(s),0600);__oteleq_reflect.ValueOf(err).IsValid(){{panic(err)}}
}}
'''


def java_driver(entry, args):
    if "receiver_fixture" in entry:
        return java_receivers.driver(entry, args, java_literal)
    package = "package " + entry["package"] + ";\n" if entry["package"] else ""
    call = entry["name"] + "(" + ",".join(literal(v, t, "java") for v, t in zip(args, entry["parameters"])) + ")"
    invoked = call + ';s.append("return:void\\n");' if entry["output"] == "void" else 'java.lang.Object result=' + call + ';s.append("return:").append(value(result)).append("\\n");'
    state = "\n".join('s.append(' + json.dumps(g["name"] + ':') + ').append(value(' + g["name"] + ')).append("\\n");' for g in entry["globals"])
    return package + '''class OteleqDriver {
static java.lang.String value(java.lang.Object v){
 if(v==null)return "null";
 if(v instanceof java.lang.Double x)return "double:"+java.lang.Long.toHexString(java.lang.Double.doubleToRawLongBits(x));
 if(v instanceof java.lang.Float x)return "float:"+java.lang.Integer.toHexString(java.lang.Float.floatToRawIntBits(x));
 if(v instanceof java.lang.Character x)return "char:"+java.lang.Integer.toHexString(x.charValue());
 if(v instanceof java.lang.String x){java.lang.StringBuilder units=new java.lang.StringBuilder("string:utf16:");for(int i=0;i<x.length();i++)units.append(java.lang.String.format("%04x",(int)x.charAt(i)));return units.toString();}
 if(v instanceof java.lang.Boolean || v instanceof java.lang.Byte || v instanceof java.lang.Short ||
    v instanceof java.lang.Integer || v instanceof java.lang.Long)
  return v.getClass().getName()+":"+java.util.Base64.getEncoder().encodeToString(v.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));
 throw new java.lang.AssertionError("opaque observation requires a fixture");
}
static java.lang.String message(java.lang.Exception error){
 java.lang.Class<?> kind=error.getClass();
 if(kind!=java.lang.Exception.class && kind!=java.lang.RuntimeException.class &&
    kind!=java.lang.IllegalArgumentException.class && kind!=java.lang.IllegalStateException.class &&
    kind!=java.lang.NullPointerException.class && kind!=java.lang.ArithmeticException.class &&
    kind!=java.lang.IndexOutOfBoundsException.class && kind!=java.lang.ArrayIndexOutOfBoundsException.class &&
    kind!=java.lang.StringIndexOutOfBoundsException.class && kind!=java.lang.UnsupportedOperationException.class &&
    kind!=java.lang.ClassCastException.class && kind!=java.lang.NumberFormatException.class)
  throw new java.lang.AssertionError("exception message requires a fixture");
 return error.getMessage();
}
public static void main(java.lang.String[] args) throws java.lang.Exception {
java.lang.StringBuilder s=new java.lang.StringBuilder("before\\n");
''' + state + '\ntry{' + invoked + '}catch(java.lang.Exception e){s.append("error:").append(e.getClass().getName()).append(":").append(value(message(e))).append("\\n");}\ns.append("after\\n");\n' + state + '\njava.nio.file.Files.writeString(java.nio.file.Path.of(java.lang.System.getenv("OTELEQ_OBSERVATION")),s.toString());\n}}\n'


def go_materialise(project, entry, args, original):
    """Keep legal package access and original main bindings in private copies."""
    context = entry["go_context"]
    (project / entry["path"]).write_text(go_driver(entry, args, original))
    for name, positions in context["main_renames"].items():
        if name != entry["path"] and positions:
            sibling = project / name
            sibling.write_text(go_project.rename_entrypoint(sibling.read_text(), positions))
    driver = project / go_project.worker_path(context)
    if context["package"] != "main":
        driver.parent.mkdir(parents=True)
        driver.write_text("package main\nimport __oteleq_target " + json.dumps(context["import_path"])
                          + "\nfunc main(){__oteleq_target." + go_project.BRIDGE + "()}\n")
    return driver


def materialise(project, entry, args):
    source = project / entry["path"]
    original = source.read_text()
    generated = project / "_oteleq_generated"
    generated.mkdir(exist_ok=True)
    language = entry["language"]
    if language == "python":
        driver = generated / "driver.py"
        driver.write_text(python_driver(entry, args))
        (generated / "_oteleq_observe.py").write_bytes(Path(__file__).with_name("observe.py").read_bytes())
    elif language in ("c", "cpp"):
        driver = project / ("_oteleq_driver.c" if language == "c" else "_oteleq_driver.cpp")
        driver.write_text(native_driver(entry, args))
    elif language == "java":
        driver = source.parent / "OteleqDriver.java"
        if driver.exists():
            raise ValueError("generated Java driver would overwrite an application file")
        driver.write_text(java_driver(entry, args))
    elif language == "go" and "go_context" in entry:
        driver = go_materialise(project, entry, args, original)
    else:
        driver = source
        emit = {"javascript": js_driver, "typescript": js_driver, "rust": rust_driver, "go": go_driver}[language]
        if language in ("javascript", "typescript"):
            (generated / "node_observe.mjs").write_text(JS_OBSERVER)
            if "sequence_configuration" in entry:
                (generated / "node_sequence.mjs").write_bytes(Path(__file__).with_name("node_sequence.mjs").read_bytes())
        driver.write_text(emit(entry, args, original))
    return driver
