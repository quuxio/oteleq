"""Generated ordinary JDK callers preserve exact values, aliases and failures."""

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import generation
import java_action
import java_handle_callers as callers

JAVA = os.environ.get("OTELC_JAVA") or shutil.which("java")
JAVAC = os.environ.get("OTELC_JAVAC") or shutil.which("javac")


class Release:
    def __init__(self, harness):self.harness = harness

    def poll(self, process, deadline):
        if self.harness.poll(process, deadline) is not None:self.harness.release(deadline)

    def finish(self, process):self.harness.finish(process)


class JavaHandleCallerTests(unittest.TestCase):
    def execute(self, parameters, output, work, main, *, instance=False, package="", actions=1, owner="Work", references=None):
        caller = (package.replace(".", "/") + "/" if package else "") + "OteleqDriver"
        binary = (package.replace(".", "/") + "/" if package else "") + owner
        source_owner = (package + "." if package else "") + owner
        source, declarations, route = callers.members(source_owner, binary, "target", parameters, output,
                                                     caller_owner=caller, instance=instance, references=references)
        self.assertNotIn("io.quux.otelc", source)
        self.assertNotIn("otelc.", source)
        self.assertEqual(route.reference_kind, 5 if instance else 6)
        with tempfile.TemporaryDirectory(prefix="oeqhc-", dir="/tmp") as temporary:
            root = Path(temporary).resolve();prefix = "package " + package + ";\n" if package else ""
            files = {"Work.java": prefix + work,
                     "OteleqDriver.java": prefix + "class OteleqDriver {\n" + source
                         + "public static void main(java.lang.String[] ignored) throws java.lang.Throwable {\n" + main
                         + "\njava.lang.System.out.write(new byte[]{0,(byte)255,10});java.lang.System.err.write(new byte[]{1,(byte)254,10});}\n}",
                     "OteleqRendezvous.java": callers.helper_source(package)}
            for name, text in files.items():(root / name).write_text(text)
            before = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in files}
            classes = root / "classes";classes.mkdir()
            subprocess.run([JAVAC, "-encoding", "UTF-8", "-d", str(classes),
                            *(str(root / name) for name in files)], capture_output=True, check=True, timeout=20)
            identifiers = [hashlib.sha256(str(index).encode()).hexdigest() for index in range(actions)]
            harness = java_action.Harness(root / "wire", "a" * 64, "b" * 64, identifiers)
            try:
                result = generation.execute([JAVA, "-cp", str(classes), caller.replace("/", ".")], root,
                    {**os.environ, **harness.environment()}, root / "process", timeout=15,
                    max_output_bytes=4096, record_process=True, interaction=Release(harness))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, b"\x00\xff\n");self.assertEqual(result.stderr, b"\x01\xfe\n")
                self.assertEqual([row["action_id"] for row in harness.records], identifiers)
                self.assertTrue(all(row["pid"] == harness.pid for row in harness.records))
            finally:harness.close()
            self.assertEqual(before, {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in files})
        return declarations

    def test_private_static_wide_and_utf16_values_are_not_adapted(self):
        self.execute(["long", "double", "String"], "long", r'''class Work {
private static long target(long value,double fraction,String text){
 if(value!=9007199254740993L || Double.doubleToRawLongBits(fraction)!=0x8000000000000000L
    || text.length()!=2 || text.charAt(0)!=0xd83d || text.charAt(1)!=0xde00)throw new AssertionError("argument changed");
 return value;
}}''', '''long value=oteleqEnvelope(9007199254740993L,-0.0D,new String(new char[]{0xd83d,0xde00}));
if(value!=9007199254740993L)throw new AssertionError("return changed");''')

    def test_private_instance_arrays_state_aliases_and_original_exception_identity(self):
        self.execute(["int[]", "long", "double"], "int[]", '''class Work {
static int total,getters;int calls;
static final class Problem extends RuntimeException {
 public String getMessage(){getters++;return "changed";}
 public String toString(){getters++;return "changed";}
}
static final Problem FAILURE=new Problem();
private int[] target(int[] values,long seed,double fraction){
 if(Double.doubleToRawLongBits(fraction)!=Double.doubleToRawLongBits(.25D))throw new AssertionError("fraction changed");
 if(seed<0)throw FAILURE;
 total+=seed;calls++;values[0]+=seed;return values;
}}''', '''Work receiver=new Work();int[] values={1,2};
if(oteleqEnvelope(receiver,values,7L,.25D)!=values || values[0]!=8 || receiver.calls!=1 || Work.total!=7)
 throw new AssertionError("state or alias changed");
try{oteleqEnvelope(receiver,values,-1L,.25D);throw new AssertionError("missing failure");}
catch(Work.Problem failure){if(failure!=Work.FAILURE)throw new AssertionError("exception identity changed");}
if(Work.getters!=0 || values[0]!=8 || receiver.calls!=1 || Work.total!=7)throw new AssertionError("failure state changed");''',
                     instance=True, actions=2)

    def test_void_and_packaged_unicode_owner_keep_private_access(self):
        value = self.execute([], "void", '''class W\u00f6rk\u00a3 {static int calls;
private static void target(){calls++;}}''',
                             'oteleqEnvelope();if(W\u00f6rk\u00a3.calls!=1)throw new AssertionError("missing call");',
                             package="example", owner="W\u00f6rk\u00a3")
        self.assertEqual(value["target"]["owner"], "example/W\u00f6rk\u00a3")
        self.assertEqual(value["wrapper"]["descriptor"], "()V")

    def test_each_primitive_return_has_the_exact_invoke_descriptor(self):
        for name, value in (("boolean", "true"), ("byte", "(byte)-128"), ("char", "(char)0xffff"),
                            ("short", "(short)-32768"), ("int", "-2147483648"), ("long", "Long.MIN_VALUE"),
                            ("float", "Float.intBitsToFloat(0x7fc00042)"),
                            ("double", "Double.longBitsToDouble(0x7ff8000000000042L)")):
            if name == "float":comparison = "Float.floatToRawIntBits(value)!=0x7fc00042"
            elif name == "double":comparison = "Double.doubleToRawLongBits(value)!=0x7ff8000000000042L"
            else:comparison = "value!=(" + value + ")"
            with self.subTest(type=name):
                self.execute([name], name, "class Work {private static " + name + " target(" + name + " value){return value;}}",
                             name + " value=oteleqEnvelope(" + value + ");if(" + comparison + ")throw new AssertionError(\"changed bits\");")

    def test_invalid_source_names_types_and_dispatch_refuse_before_compilation(self):
        original = {"source_owner": "Work", "binary_owner": "Work", "method": "target", "parameters": ["int"],
                    "output": "int", "caller_owner": "OteleqDriver", "instance": False}
        for key, value in (("source_owner", "Work;System.exit(0)"), ("source_owner", ""), ("source_owner", None),
                           ("binary_owner", None), ("binary_owner", "../Work"), ("caller_owner", None),
                           ("method", "<init>"), ("method", "bad\n"), ("instance", 1),
                           ("parameters", ["void"]), ("parameters", ["Unknown"]),
                           ("parameters", ["int" + "[]" * 33]), ("parameters", [None]),
                           ("parameters", ["long"] * 128), ("parameters", ["int"] * 255),
                           ("output", "void[]")):
            with self.subTest(key=key), self.assertRaises(ValueError):callers.members(**{**original, key: value})
        for package in ("..", "bad;package", None):
            with self.subTest(package=package), self.assertRaises(ValueError):callers.helper_source(package)
        self.assertEqual(callers.type_name("java.lang.Integer"), ("java.lang.Integer", "Ljava/lang/Integer;"))
        self.assertFalse(callers.identifier("2bad"))


if __name__ == "__main__":
    unittest.main()
