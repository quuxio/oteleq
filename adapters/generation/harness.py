"""Deterministic scalar corpora and diagnostic harness materialisation."""
import json
import ctypes
import math
from pathlib import Path
import random
import struct

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
        return "new String(new char[]{" + ",".join(units) + "})"
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
        if type_ in ("float32", "float64"):
            width = float_width(type_, language)
            bits = struct.pack(">f" if width == 32 else ">d", value).hex()
            return f"__oteleq_math.Float{width}frombits(0x{bits})"
        return type_ + "(" + json.dumps(value) + ")"
    return json.dumps(value)


def global_gaps(entry):
    if entry["language"] in ("python", "javascript", "typescript"):
        return [g["name"] for g in entry["globals"] if g["name"].startswith("<")]
    scalar = INTEGERS | FLOATS | BOOLS
    if entry["language"] in ("c", "cpp"):
        scalar = native_scalar_types(entry["language"])
    if entry["language"] in ("go", "java"):
        scalar |= STRINGS
    return [g["name"] for g in entry["globals"]
            if scalar_type(g["type"]) not in scalar or g.get("private") or g.get("inaccessible")]


def python_driver(entry, args):
    globals_ = [g["name"] for g in entry["globals"]]
    return f'''# Generated by oteleq. Boilerplate is MIT licensed.
import importlib.util, json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _oteleq_observe import graph, MISSING, function_code, bound_function
target = Path({entry['path']!r})
expected_code = function_code(target, {entry['name']!r}, {entry['line']!r})
sys.path.insert(0, str(target.parent))
spec = importlib.util.spec_from_file_location("_oteleq_target", target)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
arguments = {args!r}
function = bound_function(module, {entry['name']!r}, expected_code)
def roots():
    return {{**{{"global:" + name: vars(module).get(name, MISSING) for name in {globals_!r}}}, "arguments": arguments}}
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


JS_OBSERVER = '''
const __oteleqIsProxy=(await import('node:util')).types.isProxy;
// Labels come from known prototype identities, never application getters.
const __oteleqErrorPrototypes=new Map([
  [Error.prototype,'Error'],[TypeError.prototype,'TypeError'],
  [RangeError.prototype,'RangeError'],[SyntaxError.prototype,'SyntaxError'],
  [ReferenceError.prototype,'ReferenceError'],[URIError.prototype,'URIError'],
  [EvalError.prototype,'EvalError'],[AggregateError.prototype,'AggregateError']
]);
function __oteleqGraph(roots) {
  const seen = new Map(), nodes = [];
  function value(v, depth=0) {
    if(depth>32 || nodes.length>=512) throw new Error('observation graph limit');
    if(v===null) return {type:'null'};
    if(typeof v==='number') { const b=Buffer.alloc(8); b.writeDoubleBE(v); return {type:'float64',bits:b.toString('hex')}; }
    if(['boolean','string','undefined','bigint'].includes(typeof v)) return {type:typeof v,value:typeof v==='bigint'?v.toString():v};
    if(typeof v!=='object') throw new Error('opaque value: '+typeof v);
    if(__oteleqIsProxy(v)) throw new Error('proxy state requires a fixture');
    if(seen.has(v)) return {ref:seen.get(v)};
    const id=nodes.length; seen.set(v,id);
    const prototype=Object.getPrototypeOf(v);
    const errorType=__oteleqErrorPrototypes.get(prototype);
    const isError=errorType!==undefined;
    if(![Object.prototype,Array.prototype,null].includes(prototype) && !isError) throw new Error('opaque object prototype');
    const n={type:isError?errorType:Array.isArray(v)?'array':'object',fields:[]}; nodes.push(n);
    for(const key of Reflect.ownKeys(v)) {
      if(isError && key==='stack') continue;
      if(typeof key!=='string') throw new Error('symbol state requires a fixture');
      const d=Object.getOwnPropertyDescriptor(v,key);
      if(!Object.hasOwn(d,'value')) throw new Error('accessor state requires a fixture');
      n.fields.push([key,value(d.value,depth+1),d.writable,d.enumerable,d.configurable]);
    }
    return {ref:id};
  }
  return {roots:Object.fromEntries(Object.keys(roots).sort().map(k=>[k,value(roots[k])])),nodes};
}
'''


def js_driver(entry, args, source):
    roots = "".join(json.dumps("global:" + g["name"]) + ":" + g["name"] + "," for g in entry["globals"])
    call = "__oteleqSelected(...__oteleqArguments)"
    if entry.get("async"):
        call = "await " + call
    # Capture the hoisted declaration before application statements can rebind
    # it, retaining hashbang/directive syntax at the parser-selected position.
    raw = source.encode()
    position = entry.get("binding_capture_offset", 0)
    capture = (";const __oteleqSelected=" + entry["name"] + ";\n").encode()
    source = (raw[:position] + capture + raw[position:]).decode()
    return source + JS_OBSERVER + f'''
if(typeof __oteleqSelected!=='function' || {entry['name']}!==__oteleqSelected) throw new Error('selected function binding differs from its frozen declaration');
const __oteleqArguments={json.dumps(args)};
const __oteleqRoots=()=>({{{roots}arguments:__oteleqArguments}});
const __oteleqBefore=__oteleqGraph(__oteleqRoots());
let __oteleqOutcome, __oteleqResult, __oteleqFailed=false;
try {{ __oteleqResult={call}; }}
catch(error) {{ __oteleqFailed=true; __oteleqOutcome={{kind:'error',value:__oteleqGraph({{error,...__oteleqRoots()}})}}; }}
if(!__oteleqFailed) __oteleqOutcome={{kind:'return',value:__oteleqGraph({{result:__oteleqResult,...__oteleqRoots()}})}};
const __oteleqAfter=__oteleqGraph(__oteleqRoots());
const __oteleqFs=await import('node:fs');
__oteleqFs.writeFileSync(process.env.OTELEQ_OBSERVATION,JSON.stringify({{before:__oteleqBefore,outcome:__oteleqOutcome,after:__oteleqAfter}}));
'''


def native_guards(language: str) -> str:
    """Resolve source aliases through the compiler before any raw scalar read."""
    if language == "cpp":
        return r'''
#include <type_traits>
template<class T> using __oteleq_type = std::remove_cv_t<std::remove_reference_t<T>>;
template<class T> constexpr bool __oteleq_scalar =
  (std::is_integral_v<__oteleq_type<T>> && sizeof(T)<=8) ||
  std::is_same_v<__oteleq_type<T>,float> ||
  std::is_same_v<__oteleq_type<T>,double>;
#define __oteleq_assert_scalar(T) static_assert(__oteleq_scalar<T>, "native type requires a scalar fixture")
#define __oteleq_assert_value(v) __oteleq_assert_scalar(decltype(v))
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


def native_driver(entry, args):
    parameters = ", ".join(literal(v, t, entry["language"]) for v, t in zip(args, entry["parameters"]))
    output = scalar_type(entry["output"])
    call = entry["name"] + "(" + parameters + ")"
    returned = call + "; fputs(\"return:void\\n\", out);" if output == "void" else output + " result=" + call + '; __oteleq_bytes(out,"return:' + output + '",&result,sizeof(result));'
    state = "\n".join('__oteleq_bytes(out,' + json.dumps(g["name"] + ":" + g["type"]) + ',&' + g["name"] + ',sizeof(' + g["name"] + '));' for g in entry["globals"])
    invocation = returned
    if entry["language"] == "cpp":
        invocation = 'try {' + returned + '} catch(const std::exception& e){fprintf(out,"error:%s:%s\\n",typeid(e).name(),e.what());} catch(...){fclose(out);return 91;}'
    headers = '#include <exception>\n#include <typeinfo>\n' if entry["language"] == "cpp" else ''
    arguments_checked = "\n".join("__oteleq_assert_scalar(" + type_ + ");" for type_ in entry["parameters"])
    return headers + '''#include <stdio.h>
#include <stdlib.h>
''' + native_guards(entry["language"]) + '''
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
    output = scalar_type(entry["output"])
    formatted = 'format!("{:x}",v.to_bits())' if output in ("f32", "f64") else 'format!("{:?}",v)'
    state_lines = []
    for global_ in entry["globals"]:
        floating = scalar_type(global_["type"]) in ("f32", "f64")
        expression = "unsafe {" + global_["name"] + "}"
        if floating:
            expression = "(" + expression + ").to_bits()"
        pattern = ":{:x}\n" if floating else ":{:?}\n"
        state_lines.append('s.push_str(&format!(' + json.dumps(global_["name"] + ':' + global_["type"] + pattern) + ',' + expression + '));')
    state = "\n".join(state_lines)
    return rename_main(source, entry["file_functions"], "rust") + f'''
fn main() {{
    let mut s=String::from("before\\n"); {state}
    match std::panic::catch_unwind(|| {call}) {{
      Ok(v)=>s.push_str(&format!("return:{output}:{{}}\\n",{formatted})),
      Err(payload)=>{{
        if let Some(v)=payload.downcast_ref::<String>() {{ s.push_str(&format!("error:string:{{:?}}\\n",v)); }}
        else if let Some(v)=payload.downcast_ref::<&str>() {{ s.push_str(&format!("error:str:{{:?}}\\n",v)); }}
        else {{ std::process::exit(91); }}
      }},
    }}
    s.push_str("after\\n"); {state}
    std::fs::write(std::env::var("OTELEQ_OBSERVATION").unwrap(),s).unwrap();
}}
'''


def go_driver(entry, args, source):
    source = rename_main(source, entry["file_functions"], "go")
    position = entry["package_end"]
    imports = '\nimport (__oteleq_fmt "fmt"; __oteleq_os "os"; __oteleq_math "math")\n'
    raw = source.encode()
    source = (raw[:position] + imports.encode() + raw[position:]).decode()
    call = entry["name"] + "(" + ",".join(literal(v, t, "go") for v, t in zip(args, entry["parameters"])) + ")"
    invoked = call + ';s+="return:void\\n"' if entry["output"] == "void" else 's+="return:"+__oteleqValue(' + call + ')+"\\n"'
    state = "\n".join('s+=' + json.dumps(g["name"] + ':') + '+__oteleqValue(' + g["name"] + ')+"\\n"' for g in entry["globals"])
    return source + f'''
func __oteleqValue(v any) string {{
 switch x:=v.(type) {{case float32: return __oteleq_fmt.Sprintf("float32:%x",__oteleq_math.Float32bits(x));case float64:return __oteleq_fmt.Sprintf("float64:%x",__oteleq_math.Float64bits(x))}}
 switch v.(type) {{case nil,bool,string,int,int8,int16,int32,int64,uint,uint8,uint16,uint32,uint64:default:panic("opaque observation requires a fixture")}}
 return __oteleq_fmt.Sprintf("%T:%#v",v,v)
}}
func main(){{
 s:="before\\n"; {state}
 func(){{defer func(){{if p:=recover();p!=nil{{s+="error:"+__oteleqValue(p)+"\\n"}}}}();{invoked}}}()
 s+="after\\n"; {state}
 if err:=__oteleq_os.WriteFile(__oteleq_os.Getenv("OTELEQ_OBSERVATION"),[]byte(s),0600);err!=nil{{panic(err)}}
}}
'''


def java_driver(entry, args):
    package = "package " + entry["package"] + ";\n" if entry["package"] else ""
    call = entry["name"] + "(" + ",".join(literal(v, t, "java") for v, t in zip(args, entry["parameters"])) + ")"
    invoked = call + ';s.append("return:void\\n");' if entry["output"] == "void" else 's.append("return:").append(value(' + call + ')).append("\\n");'
    state = "\n".join('s.append(' + json.dumps(g["name"] + ':') + ').append(value(' + g["name"] + ')).append("\\n");' for g in entry["globals"])
    return package + '''class OteleqDriver {
static String value(Object v){
 if(v==null)return "null";
 if(v instanceof Double x)return "double:"+Long.toHexString(Double.doubleToRawLongBits(x));
 if(v instanceof Float x)return "float:"+Integer.toHexString(Float.floatToRawIntBits(x));
 if(v instanceof Character x)return "char:"+Integer.toHexString(x.charValue());
 if(v instanceof String x){StringBuilder units=new StringBuilder("string:utf16:");for(int i=0;i<x.length();i++)units.append(String.format("%04x",(int)x.charAt(i)));return units.toString();}
 return v.getClass().getName()+":"+java.util.Base64.getEncoder().encodeToString(v.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));
}
public static void main(String[] args) throws Exception {
StringBuilder s=new StringBuilder("before\\n");
''' + state + '\ntry{' + invoked + '}catch(Exception e){s.append("error:").append(e.getClass().getName()).append(":").append(value(e.getMessage())).append("\\n");}\ns.append("after\\n");\n' + state + '\njava.nio.file.Files.writeString(java.nio.file.Path.of(System.getenv("OTELEQ_OBSERVATION")),s.toString());\n}}\n'


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
    else:
        driver = source
        emit = {"javascript": js_driver, "typescript": js_driver, "rust": rust_driver, "go": go_driver}[language]
        driver.write_text(emit(entry, args, original))
    return driver
