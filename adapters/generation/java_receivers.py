"""Bind declared Java receivers to ordinary source classes and scalar factories."""
from collections.abc import Callable
import json
from pathlib import Path
import java_live


PRIMITIVES = {"boolean", "byte", "short", "int", "long", "char", "float", "double"}
BOXES = {"Boolean", "Byte", "Short", "Integer", "Long", "Character", "Float", "Double", "String", "Object"}
CLASS_LITERAL = ".class"
OBSERVER = Path(__file__).with_name("OteleqGraph.java").read_text()


def supported_type(name: str, models: list[dict], package: str, *, void: bool = False) -> bool:
    """Type spelling is checked again by javac and exact runtime field binding."""
    dimensions = 0
    while name.endswith("[]"):
        name = name[:-2]
        dimensions += 1
    classes = {model["name"] for model in models}
    qualified = {package + "." + item for item in classes} if package else classes
    return (dimensions <= 32 and (name in PRIMITIVES | BOXES | classes | qualified
                                  or name in {"java.lang." + item for item in BOXES}
                                  or void and not dimensions and name == "void"))


def factory(entry: dict, discovered: dict, declaration: dict) -> tuple[dict, str]:
    """Resolve one source constructor or same-class static factory without guessing."""
    owner, name = entry["java_receiver_class"], declaration["factory"]
    constructor = owner == name
    qualified = owner + (".<init>" if constructor else "." + name)
    matches = [item for item in discovered["functions"] if item["name"] == qualified]
    if constructor and not matches:
        return {"factory": owner, "line": 0, "source_function": None, "parameters": [], "private": False}, "constructor"
    if len(matches) != 1:
        raise ValueError("Java receiver factory requires one unique source constructor or method")
    source = matches[0]
    if source.get("java_receiver_reason"):
        raise ValueError(source["java_receiver_reason"])
    allowed = {"constructor needs an object fixture"} if constructor else {"", "private method needs an access fixture"}
    if source["reason"] not in allowed or not constructor and not source.get("java_static"):
        raise ValueError("Java receiver factory requires an ordinary source constructor or static method")
    return {"factory": name, "line": source["line"], "source_function": qualified,
            "parameters": source["parameters"], "private": source.get("java_private", False)}, "constructor" if constructor else "function"


def bind(entry: dict, discovered: dict, declaration: dict, concrete: Callable) -> None:
    """Freeze source storage and independently reconstructed construction inputs."""
    owner = entry.get("java_receiver_class")
    if (not owner or entry.get("java_static") or entry.get("java_constructor")
            or entry["reason"] not in ("", "instance method needs an object fixture", "private method needs an access fixture")):
        raise ValueError("Java receiver fixture requires an ordinary source instance method")
    if entry.get("java_receiver_reason"):
        raise ValueError(entry["java_receiver_reason"])
    models = [model for model in discovered.get("classes", []) if not model["reason"]]
    selected = [model for model in models if model["name"] == owner]
    if any(model["name"] in ("OteleqDriver", "OteleqGraph") for model in discovered.get("classes", [])):
        raise ValueError("generated Java observer name collides with application source")
    if len(selected) != 1 or len(models) > 64:
        raise ValueError("Java receiver class storage is unavailable or exceeds its bound")
    for model in models:
        if len(model["fields"]) > 256 or any(not supported_type(field["type"], models, entry["package"]) for field in model["fields"]):
            raise ValueError("Java source fields require a supported bounded storage fixture")
    foreign_globals = [item for item in entry["globals"] if not item["name"].startswith(owner + ".")]
    if foreign_globals:
        raise ValueError("other Java class statics require an explicit initialization fixture")
    source, kind = factory(entry, discovered, declaration)
    arguments = concrete({"language": "java", "parameters": source["parameters"]}, declaration["arguments"])
    entry.update(receiver_class=owner, java_models=models,
                 java_class_roots=[field for field in selected[0]["fields"] if field["modifiers"] & 8],
                 receiver_fixture={**source, "kind": kind, "arguments": arguments,
                                   "arguments_requested": declaration["arguments"], "argument_types": source["parameters"]},
                 receiver_configuration=declaration, globals=[], reason="")


def execution(entry: dict, arguments: list, literal: Callable, sequence: list[dict] | None) -> str:
    """One receiver is retained for all calls; arguments are frozen per action."""
    def inputs(values: list) -> str:
        return "new java.lang.Object[]{" + ",".join(literal(value, type_) for value, type_ in zip(values, entry["parameters"])) + "}"

    if sequence is None:
        return 'java.lang.String capture="{\\\"java_receiver_schema_version\\\":1,"+boundaries(call(receiver,' + inputs(arguments) + ',target))+"}";'
    schedule = ",".join(inputs(step["arguments"]) for step in sequence)
    controlled = any("metrics" in step for step in sequence)
    before = 'checkpoint("before-"+index);' if controlled else ""
    after = 'checkpoint("after-"+index);' if controlled else ""
    return '''java.lang.Object[][] schedule=new java.lang.Object[][]{''' + schedule + '''};
java.lang.String[] first=null,last=null;
java.lang.StringBuilder steps=new java.lang.StringBuilder();
for(int index=0;index<schedule.length;index++){
''' + before + '''
 java.lang.String[] current=call(receiver,schedule[index],target);
 if(first==null)first=current;
 last=current;
 if(index>0)steps.append(',');
 steps.append("{\\\"id\\\":\\\"step-").append(index).append("\\\",\\\"action\\\":\\\"call\\\",").append(boundaries(current)).append('}');
''' + after + '''
}
java.lang.String capture="{\\\"java_receiver_schema_version\\\":2,\\\"before\\\":"+first[0]+",\\\"outcome\\\":"+last[1]+",\\\"after\\\":"+last[2]+",\\\"steps\\\":["+steps+"]}";'''


def driver(entry: dict, arguments: list, literal: Callable, sequence: list[dict] | None = None) -> str:
    """Emit identical SDK-free reflection/access helpers for the two lanes."""
    models, fixture = entry["java_models"], entry["receiver_fixture"]
    owner = entry["receiver_class"]
    params = ",".join(name + CLASS_LITERAL for name in entry["parameters"])
    factory_params = ",".join(name + CLASS_LITERAL for name in fixture["argument_types"])
    factory_args = ",".join(literal(value, type_) for value, type_ in zip(fixture["arguments"], fixture["argument_types"]))
    if fixture["kind"] == "constructor":
        construct = f'''java.lang.reflect.Constructor<?> factory={owner}.class.getDeclaredConstructor({factory_params});
if(!factory.trySetAccessible())throw new java.lang.AssertionError("receiver constructor access unavailable");
constructed=factory.newInstance(new java.lang.Object[]{{{factory_args}}});'''
    else:
        construct = f'''java.lang.reflect.Method factory={owner}.class.getDeclaredMethod({json.dumps(fixture['factory'])}{',' if factory_params else ''}{factory_params});
if(!java.lang.reflect.Modifier.isStatic(factory.getModifiers()) || !factory.trySetAccessible())throw new java.lang.AssertionError("receiver factory binding unavailable");
constructed=factory.invoke(null,new java.lang.Object[]{{{factory_args}}});'''
    names = ["receiver", *["argument:" + str(i) for i in range(len(arguments))],
             *["static:" + owner + "." + field["name"] for field in entry["java_class_roots"]]]
    values = ["receiver", *["arguments[" + str(i) + "]" for i in range(len(arguments))],
              *["observer.staticValue(" + owner + ".class," + json.dumps(field["name"]) + ")" for field in entry["java_class_roots"]]]
    types = [owner, *entry["parameters"], *[field["type"] for field in entry["java_class_roots"]]]
    model_fields = ",".join("new java.lang.String[]{" + ",".join(json.dumps(field["name"]) for field in model["fields"]) + "}" for model in models)
    model_types = ",".join("new java.lang.Class<?>[]{" + ",".join(field["type"] + CLASS_LITERAL for field in model["fields"]) + "}" for model in models)
    model_modifiers = ",".join("new int[]{" + ",".join(str(field["modifiers"]) for field in model["fields"]) + "}" for model in models)
    template = r'''class OteleqDriver {
@CHECKPOINT_HELPER@
static OteleqGraph observer() throws java.lang.Exception {
return new OteleqGraph(new java.lang.Class<?>[]{@MODELS@},new java.lang.String[][]{@FIELDS@},new java.lang.Class<?>[][]{@TYPES@},new int[][]{@MODIFIERS@});
}
static java.lang.String graph(@OWNER@ receiver,java.lang.Object[] arguments,java.lang.Object result,java.lang.Exception failure,boolean outcome) throws java.lang.Exception {
OteleqGraph observer=observer();
java.util.ArrayList<java.lang.String> names=new java.util.ArrayList<>(java.util.List.of(@NAMES@));
java.util.ArrayList<java.lang.Object> values=new java.util.ArrayList<>(java.util.Arrays.asList(@VALUES@));
java.util.ArrayList<java.lang.Class<?>> types=new java.util.ArrayList<>(java.util.List.of(@ROOT_TYPES@));
if(outcome){names.add(failure==null?"result":"error");values.add(failure==null?result:failure);types.add(failure==null?@OUTPUT@.class:java.lang.Exception.class);}
return observer.graph(names.toArray(new java.lang.String[0]),values.toArray(),types.toArray(new java.lang.Class<?>[0]));
}
static java.lang.String[] call(@OWNER@ receiver,java.lang.Object[] arguments,java.lang.reflect.Method target) throws java.lang.Exception {
java.lang.String before=graph(receiver,arguments,null,null,false);
java.lang.Object result=null;java.lang.Exception failure=null;
try{result=target.invoke(receiver,arguments);}catch(java.lang.reflect.InvocationTargetException invocation){
java.lang.Throwable cause=invocation.getCause();if(!(cause instanceof java.lang.Exception))throw new java.lang.AssertionError("target throwable requires another codec");failure=(java.lang.Exception)cause;}
java.lang.String outcome=graph(receiver,arguments,result,failure,true);
java.lang.String after=graph(receiver,arguments,null,null,false);
return new java.lang.String[]{before,"{\"kind\":\""+(failure==null?"return":"error")+"\",\"value\":"+outcome+"}",after};
}
static java.lang.String boundaries(java.lang.String[] capture){
return "\"before\":"+capture[0]+",\"outcome\":"+capture[1]+",\"after\":"+capture[2];
}
public static void main(java.lang.String[] ignored) throws java.lang.Exception {
if(java.lang.System.getSecurityManager()!=null)throw new java.lang.AssertionError("custom security manager requires a fixture");
java.lang.reflect.Method target=@OWNER@.class.getDeclaredMethod(@METHOD@@PARAMS@);
if(java.lang.reflect.Modifier.isStatic(target.getModifiers()) || target.isSynthetic() || target.isBridge() || target.getReturnType()!=@OUTPUT@.class || !target.trySetAccessible())throw new java.lang.AssertionError("receiver method binding unavailable");
java.lang.Object constructed;
// Construction is fixture setup. Never let JVM failure reporting format an application cause.
try{@CONSTRUCT@}catch(java.lang.Throwable failure){throw new java.lang.AssertionError("receiver construction failed");}
if(constructed==null || constructed.getClass()!=@OWNER@.class)throw new java.lang.AssertionError("receiver factory returned the wrong class");
@OWNER@ receiver=(@OWNER@)constructed;
@EXECUTION@
java.nio.file.Files.writeString(java.nio.file.Path.of(java.lang.System.getenv("OTELEQ_OBSERVATION")),capture);
@FINAL_CHECKPOINT@
}
}
'''
    substitutions = {"MODELS": ",".join(model["name"] + CLASS_LITERAL for model in models),
                     "FIELDS": model_fields, "TYPES": model_types, "MODIFIERS": model_modifiers,
                     "OWNER": owner, "NAMES": ",".join(json.dumps(name) for name in names),
                     "VALUES": ",".join(values), "ROOT_TYPES": ",".join(type_ + CLASS_LITERAL for type_ in types),
                     "OUTPUT": entry["output"], "METHOD": json.dumps(entry["name"].rsplit(".", 1)[-1]),
                     "PARAMS": ("," + params) if params else "", "CONSTRUCT": construct,
                     "EXECUTION": execution(entry, arguments, literal, sequence),
                     "CHECKPOINT_HELPER": java_live.HELPER if sequence and any("metrics" in step for step in sequence) else "",
                     "FINAL_CHECKPOINT": 'checkpoint("finish");' if sequence and any("metrics" in step for step in sequence) else ""}
    for name, value in substitutions.items():
        template = template.replace("@" + name + "@", value)
    package = "package " + entry["package"] + ";\n" if entry["package"] else ""
    return package + '@java.lang.SuppressWarnings("removal")\n' + template + OBSERVER
