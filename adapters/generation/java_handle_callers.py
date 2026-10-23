"""Ordinary typed JDK callers for an explicitly declared private handle route."""

import json
import unicodedata

import java_action
import java_action_bindings as bindings
import java_witness as witness

PRIMITIVES = {"boolean": "Z", "byte": "B", "char": "C", "short": "S", "int": "I",
              "long": "J", "float": "F", "double": "D", "void": "V"}
REFERENCES = {name: "java.lang." + name for name in
              ("String", "Object", "Boolean", "Byte", "Character", "Short", "Integer", "Long", "Float", "Double")}
ROLE_NAMES = {"envelope": "oteleqEnvelope", "rendezvous": "oteleqRendezvous", "wrapper": "oteleqWrapper"}


def identifier(value: object) -> bool:
    """Reject source delimiters while retaining Java letters and currency names."""
    if type(value) is not str or not value:
        return False
    categories = [unicodedata.category(char) for char in value]
    def starts(char, category):
        return char in "_$" or category.startswith("L") or category in ("Nl", "Sc", "Pc")
    return starts(value[0], categories[0]) and all(starts(char, category) or category in ("Nd", "Mc", "Mn")
                                               for char, category in zip(value[1:], categories[1:]))


def source_name(value: object) -> bool:
    return type(value) is str and all(identifier(part) for part in value.split("."))


def type_name(value: str, *, output: bool = False) -> tuple[str, str]:
    """Keep source types and JVM descriptors exact without adapting arguments."""
    witness.require(type(value) is str, "caller type must be explicit")
    dimensions = 0
    while value.endswith("[]"):
        dimensions += 1;value = value[:-2]
    witness.require(dimensions <= 32 and (value != "void" or output and dimensions == 0),
                    "unsupported caller array or void type")
    if value in PRIMITIVES:
        name, descriptor = value, PRIMITIVES[value]
    else:
        short = value.removeprefix("java.lang.")
        witness.require(short in REFERENCES and value in (short, REFERENCES[short]), "unsupported caller reference type")
        name = REFERENCES[short];descriptor = "L" + name.replace(".", "/") + ";"
    return name + "[]" * dimensions, "[" * dimensions + descriptor


def helper_source(package: str) -> str:
    """Relocate only the matched ordinary JDK helper's package declaration."""
    witness.require(package == "" or source_name(package), "invalid private helper package")
    return ("package " + package + ";\n" if package else "") + java_action.HELPER.read_text()


def members(source_owner: str, binary_owner: str, method: str, parameters: list[str], output: str,
            *, caller_owner: str, instance: bool) -> tuple[str, dict, bindings.HandleRoute]:
    """Return SDK-free members plus independent role declarations and intent.

    Source and binary owner names are separate compiler identities. The caller
    constructs fixtures and observes state outside these envelope/wrapper bodies.
    """
    witness.require(source_name(source_owner) and identifier(method) and type(instance) is bool
                    and type(binary_owner) is str and type(caller_owner) is str
                    and type(parameters) is list and len(parameters) <= 254, "invalid typed caller declaration")
    arguments = [type_name(value) for value in parameters]
    returned, result_descriptor = type_name(output, output=True)
    target_descriptor = "(" + "".join(item[1] for item in arguments) + ")" + result_descriptor
    invocation = "(L" + binary_owner + ";" + target_descriptor[1:] if instance else target_descriptor
    expected = {"target": {"owner": binary_owner, "name": method, "descriptor": target_descriptor}}
    for role, name in ROLE_NAMES.items():
        expected[role] = {"owner": caller_owner, "name": name,
                          "descriptor": "()V" if role == "rendezvous" else invocation}
    expected = bindings.declarations(expected)
    slots = bindings.descriptor_slots(invocation)
    witness.require(slots is not None and slots <= 254, "handle invocation exceeds the JVM slot bound")
    route = bindings.HandleRoute("OTELEQ_HANDLE", 5 if instance else 6)
    names = ["p" + str(index) for index in range(len(arguments))]
    declarations = [name + " " + variable for (name, _), variable in zip(arguments, names)]
    if instance:
        declarations.insert(0, source_owner + " receiver");names.insert(0, "receiver")
    signature, actual = ",".join(declarations), ",".join(names)
    classes = ",".join([returned + ".class", *(name + ".class" for name, _ in arguments)])
    invoke = "OTELEQ_HANDLE.invokeExact(" + actual + ")"
    body = invoke + ";" if returned == "void" else "return (" + returned + ")" + invoke + ";"
    forward = "oteleqWrapper(" + actual + ");"
    if returned != "void":forward = "return " + forward
    source = '''private static final java.lang.invoke.MethodHandle OTELEQ_HANDLE=oteleqHandle();
private static int OTELEQ_ACTION_POSITION;
private static java.lang.invoke.MethodHandle oteleqHandle(){
 try{return java.lang.invoke.MethodHandles.privateLookupIn(@OWNER@.class,java.lang.invoke.MethodHandles.lookup())
   .@FIND@(@OWNER@.class,@METHOD@,java.lang.invoke.MethodType.methodType(@CLASSES@));}
 catch(java.lang.ReflectiveOperationException failure){throw new java.lang.AssertionError("private caller handle unavailable");}
}
private static void oteleqRendezvous() throws java.io.IOException {
 java.lang.String actions=java.lang.System.getenv("OTELEQ_ACTION_IDS");
 if(actions==null)throw new java.lang.AssertionError("missing private action plan");
 OteleqRendezvous.awaitRelease(actions.split(",",-1)[OTELEQ_ACTION_POSITION++]);
}
private static @OUTPUT@ oteleqWrapper(@SIGNATURE@) throws java.lang.Throwable {@BODY@}
private static @OUTPUT@ oteleqEnvelope(@SIGNATURE@) throws java.lang.Throwable {oteleqRendezvous();@FORWARD@}
'''
    values = {"OWNER": source_owner, "FIND": "findVirtual" if instance else "findStatic", "METHOD": json.dumps(method),
              "CLASSES": classes, "OUTPUT": returned, "SIGNATURE": signature, "BODY": body, "FORWARD": forward}
    for key, value in values.items():source = source.replace("@" + key + "@", value)
    return source, expected, route
