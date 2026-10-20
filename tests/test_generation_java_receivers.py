"""Actual JDK checks for passive, bounded source-bound receiver observations."""
import json
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
JAVA = os.environ.get("OTELC_JAVA") or shutil.which("java")
JAVAC = os.environ.get("OTELC_JAVAC") or shutil.which("javac")
sys.path[:0] = [str(REPO / "adapters/generation"), str(REPO / "examples")]
import generation as gen
import harness
import policy
import typed_capture as typed
SOURCE = r'''
class Counter {
 private int number=7;
 Counter self=this;
 java.lang.Object[] array=new java.lang.Object[2];
 java.lang.String first=new java.lang.String(new char[]{'a',0,'\ud800'});
 java.lang.String second=first;
 private static Counter global;
 public java.lang.String toString(){throw new java.lang.AssertionError("APP_CALLBACK");}
 public int hashCode(){throw new java.lang.AssertionError("APP_CALLBACK");}
 public boolean equals(java.lang.Object other){throw new java.lang.AssertionError("APP_CALLBACK");}
 int getNumber(){throw new java.lang.AssertionError("APP_CALLBACK");}
}
class Child extends Counter {}
class Foreign { int value=7; }
class Probe {
 static OteleqGraph observer() throws java.lang.Exception {
  return new OteleqGraph(new java.lang.Class<?>[]{Counter.class},
   new java.lang.String[][]{{"number","self","array","first","second","global"}},
   new java.lang.Class<?>[][]{{int.class,Counter.class,java.lang.Object[].class,java.lang.String.class,java.lang.String.class,Counter.class}},
   new int[][]{{2,0,0,0,0,10}});
 }
 static java.lang.String snapshot(Counter value) throws java.lang.Exception {
  OteleqGraph observer=observer();
  return observer.graph(new java.lang.String[]{"receiver","alias","static:Counter.global","primitive","result"},
   new java.lang.Object[]{value,value,observer.staticValue(Counter.class,"global"),7,value},
   new java.lang.Class<?>[]{Counter.class,Counter.class,Counter.class,int.class,Counter.class});
 }
 @java.lang.SuppressWarnings("removal")
 public static void main(java.lang.String[] args) throws java.lang.Exception {
  Counter value=new Counter();
  value.array[0]=value;value.array[1]=value.array;
  java.lang.reflect.Field global=Counter.class.getDeclaredField("global");global.setAccessible(true);global.set(null,value);
  java.lang.String mode=args[0];
  if(mode.equals("boundaries")) {
   java.lang.System.out.println(snapshot(value));
   java.lang.reflect.Field number=Counter.class.getDeclaredField("number");number.setAccessible(true);number.setInt(value,8);
   java.lang.System.out.println(snapshot(value));return;
  }
  if(mode.equals("duplicate")){observer().graph(new java.lang.String[]{"x","x"},new java.lang.Object[]{1,2},new java.lang.Class<?>[]{int.class,int.class});return;}
  if(mode.equals("mismatch")){new OteleqGraph(new java.lang.Class<?>[]{Counter.class},new java.lang.String[][]{{}},new java.lang.Class<?>[][]{{}},new int[][]{{}});return;}
  if(mode.equals("type")){observer().graph(new java.lang.String[]{"x"},new java.lang.Object[]{value},new java.lang.Class<?>[]{java.lang.String.class});return;}
  if(mode.equals("opaque")){value.array[0]=new Foreign();java.lang.System.out.println(snapshot(value));return;}
  if(mode.equals("inherited")){java.lang.System.out.println(snapshot(new Child()));return;}
  if(mode.equals("array")){value.array=new java.lang.Object[4097];java.lang.System.out.println(snapshot(value));return;}
  if(mode.equals("depth")){
   Counter current=value;for(int i=0;i<34;i++){current.self=new Counter();current=current.self;}
   java.lang.System.out.println(snapshot(value));return;
  }
  if(mode.equals("nodes")){
   value.array=new java.lang.Object[512];for(int i=0;i<512;i++)value.array[i]=new java.lang.Object();
   java.lang.System.out.println(snapshot(value));return;
  }
  if(mode.equals("bytes")){value.first="x".repeat(65536);java.lang.System.out.println(snapshot(value));return;}
  if(mode.equals("reuse")){
   OteleqGraph graph=observer();graph.graph(new java.lang.String[]{"x"},new java.lang.Object[]{value},new java.lang.Class<?>[]{Counter.class});
   graph.graph(new java.lang.String[]{"x"},new java.lang.Object[]{value},new java.lang.Class<?>[]{Counter.class});return;
  }
  if(mode.equals("static")){observer().staticValue(Counter.class,"number");return;}
  if(mode.equals("primitives")) {
   java.lang.Integer one=new java.lang.Integer(1000),two=new java.lang.Integer(1000);
   java.lang.System.out.println(observer().graph(new java.lang.String[]{"left","right","same","integer","negative_zero","nan","void","null"},
    new java.lang.Object[]{one,two,one,7,-0.0,java.lang.Double.longBitsToDouble(0x7ff8000000000001L),null,null},
    new java.lang.Class<?>[]{java.lang.Integer.class,java.lang.Integer.class,java.lang.Integer.class,int.class,double.class,double.class,void.class,java.lang.Object.class}));return;
  }
  if(mode.equals("types")) {
   java.lang.Object[] values={true,(byte)-128,(short)-32768,java.lang.Integer.MIN_VALUE,java.lang.Long.MIN_VALUE,(char)65535,java.lang.Float.intBitsToFloat(0x7fc00001),java.lang.Double.longBitsToDouble(0x7ff8000000000001L)};
   java.lang.Class<?>[] primitives={boolean.class,byte.class,short.class,int.class,long.class,char.class,float.class,double.class};
   java.lang.Class<?>[] boxes={java.lang.Boolean.class,java.lang.Byte.class,java.lang.Short.class,java.lang.Integer.class,java.lang.Long.class,java.lang.Character.class,java.lang.Float.class,java.lang.Double.class};
   java.lang.String[] names=new java.lang.String[16];java.lang.Object[] roots=new java.lang.Object[16];java.lang.Class<?>[] types=new java.lang.Class<?>[16];
   for(int i=0;i<8;i++){names[i]="primitive:"+i;names[i+8]="boxed:"+i;roots[i]=values[i];roots[i+8]=values[i];types[i]=primitives[i];types[i+8]=boxes[i];}
   java.lang.System.out.println(observer().graph(names,roots,types));return;
  }
  if(mode.equals("errors")) {
   java.lang.Exception failure=new java.lang.IllegalArgumentException("expected");
   java.lang.System.out.println(observer().graph(new java.lang.String[]{"error","alias"},new java.lang.Object[]{failure,failure},new java.lang.Class<?>[]{java.lang.Exception.class,java.lang.Exception.class}));return;
  }
  throw new java.lang.IllegalArgumentException("unknown mode");
 }
}
'''


class JavaReceiverObserverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if JAVA is None or JAVAC is None:
            raise RuntimeError("JDK is required for Java receiver regressions")
        cls.temporary = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.temporary.name)
        shutil.copyfile(REPO / "adapters/generation/OteleqGraph.java", cls.folder / "OteleqGraph.java")
        (cls.folder / "Probe.java").write_text(SOURCE)
        shadows = "\n".join("class " + name + " {}" for name in ['AssertionError', 'Boolean', 'Byte', 'Character', 'Class', 'Double', 'Exception', 'Float', 'IllegalArgumentException', 'Integer', 'Long', 'Object', 'Short', 'String', 'StringBuilder', 'SuppressWarnings', 'System'])
        (cls.folder / "Shadows.java").write_text(shadows)
        result = subprocess.run([JAVAC, "OteleqGraph.java", "Probe.java", "Shadows.java"], cwd=cls.folder,
                                capture_output=True, check=False, timeout=30)
        if result.returncode:
            cls.temporary.cleanup()
            raise AssertionError(result.stderr.decode())
        coverage_classes = os.environ.get("OTELEQ_JAVA_COVERAGE_CLASSES")
        if coverage_classes:
            shutil.copyfile(cls.folder / "OteleqGraph.class", Path(coverage_classes) / "OteleqGraph.class")

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def run_probe(self, mode):
        agent = os.environ.get("OTELEQ_JAVA_COVERAGE_AGENT")
        coverage = ["-javaagent:" + agent + "=destfile=" + os.environ["OTELEQ_JAVA_COVERAGE_EXEC"] + ",includes=OteleqGraph"] if agent else []
        return subprocess.run([JAVA, *coverage, "-Xshare:off", "-cp", self.folder, "Probe", mode],
                              cwd=self.folder, capture_output=True, check=False, timeout=10)

    @staticmethod
    def node(graph, reference):
        return next(node for node in graph["nodes"] if node["id"] == reference["node_id"])

    def test_alias_cycles_private_fields_static_roots_and_mutation_without_callbacks(self):
        result = self.run_probe("boundaries")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, b"")
        before, after = [json.loads(line) for line in result.stdout.splitlines()]
        roots = before["roots"]
        self.assertEqual(roots["receiver"], roots["alias"])
        self.assertEqual(roots["receiver"], roots["static:Counter.global"])
        self.assertEqual(roots["receiver"], roots["result"])
        fields = self.node(before, roots["receiver"])["fields"]
        self.assertEqual(fields["number"]["value"], "7")
        self.assertEqual(fields["self"], roots["receiver"])
        self.assertEqual(fields["first"], fields["second"])
        array = self.node(before, fields["array"])
        self.assertEqual(array["fields"]["item:0"], roots["receiver"])
        self.assertEqual(array["fields"]["item:1"], fields["array"])
        string = self.node(before, fields["first"])["fields"]["value"]
        self.assertEqual(string["value"], "00610000d800")
        self.assertEqual(self.node(after, after["roots"]["receiver"])["fields"]["number"]["value"], "8")
        self.assertNotIn(b"APP_CALLBACK", result.stdout + result.stderr)

    def test_primitive_bits_and_reference_box_identity_remain_distinct(self):
        result = self.run_probe("primitives")
        self.assertEqual(result.returncode, 0, result.stderr)
        graph = json.loads(result.stdout)
        roots = graph["roots"]
        self.assertEqual(roots["left"], roots["same"])
        self.assertNotEqual(roots["left"], roots["right"])
        self.assertEqual(roots["integer"]["kind"], "integer")
        self.assertEqual(roots["integer"]["bits"], 32)
        self.assertEqual(roots["negative_zero"]["bits"], "8000000000000000")
        self.assertEqual(roots["nan"]["bits"], "7ff8000000000001")
        self.assertEqual(roots["void"], {"kind": "undefined"})
        self.assertEqual(roots["null"], {"kind": "null"})

    def test_unbound_storage_and_exceeded_budgets_refuse_without_application_callbacks(self):
        for mode in ("duplicate", "mismatch", "type", "opaque", "inherited", "array", "depth", "nodes", "bytes", "reuse", "static"):
            with self.subTest(mode=mode):
                result = self.run_probe(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(b"IllegalArgumentException", result.stderr)
                self.assertNotIn(b"APP_CALLBACK", result.stdout + result.stderr)

    def test_every_primitive_and_boxed_kind_preserves_its_actual_jdk_payload(self):
        result = self.run_probe("types")
        self.assertEqual(result.returncode, 0, result.stderr)
        graph = json.loads(result.stdout)
        for index, name in enumerate(("boolean", "byte", "short", "int", "long", "char", "float", "double")):
            primitive = graph["roots"]["primitive:" + str(index)]
            boxed = self.node(graph, graph["roots"]["boxed:" + str(index)])
            self.assertEqual(primitive["type"], "java." + name)
            self.assertEqual(boxed["fields"]["value"], primitive)
            self.assertNotEqual(primitive["kind"], "reference")
        self.assertEqual(graph["roots"]["primitive:4"]["value"], "-9223372036854775808")
        self.assertEqual(graph["roots"]["primitive:5"]["value"], "65535")
        self.assertEqual(graph["roots"]["primitive:6"]["bits"], "7fc00001")
        result = self.run_probe("errors")
        self.assertEqual(result.returncode, 0, result.stderr)
        graph = json.loads(result.stdout)
        self.assertEqual(graph["roots"]["error"], graph["roots"]["alias"])
        error = self.node(graph, graph["roots"]["error"])
        self.assertEqual(error["type"], "java.lang.IllegalArgumentException")
        self.assertEqual(self.node(graph, error["fields"]["message"])["fields"]["value"]["value"], "00650078007000650063007400650064")


class JavaReceiverWorkerTests(unittest.TestCase):
    def worker(self, source: str, factory: str = "Counter", construction: tuple = ()) -> tuple:
        """Compile and execute a real declared receiver without a test-only codec."""
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "Counter.java").write_text(source)
            parsed = subprocess.run([JAVA, REPO / "adapters/generation/Discover.java", folder / "Counter.java"],
                                    cwd=folder, capture_output=True, check=False, timeout=30)
            self.assertEqual(parsed.returncode, 0, parsed.stderr)
            discovered = json.loads(parsed.stdout)
            discovered["entrypoints"] = []
            config = policy.validate({"languages": ["java"], "functions": {"include": ["Counter.run(int)"]},
                                      "fixtures": [{"function": "Counter.run(int)", "cases": [[7]],
                                                    "receiver": {"factory": factory, "arguments": list(construction)}}]})
            function = next(item for item in discovered["functions"] if item["name"] == "Counter.run")
            entry = gen.inventory_entry(function, discovered, "Counter.java", "java", "a" * 64, folder,
                                        argparse.Namespace(configuration=config, cases=1))
            self.assertEqual(entry["status"], "ready", entry["reason"])
            driver = harness.materialise(folder, entry, [7])
            built = subprocess.run([JAVAC, "Counter.java", str(driver)], cwd=folder,
                                   capture_output=True, check=False, timeout=30)
            self.assertEqual(built.returncode, 0, built.stderr)
            observation = folder / "observation.json"
            result = subprocess.run([JAVA, "-Xshare:off", "-cp", folder, "OteleqDriver"], cwd=folder,
                                    env={**os.environ, "OTELEQ_OBSERVATION": str(observation)},
                                    capture_output=True, check=False, timeout=10)
            return entry, result, observation.read_bytes() if observation.exists() else None

    def test_private_static_factory_private_method_and_standard_error_capture(self):
        source = '''class Counter {
private int value;
private Counter(int start){value=start;}
private static Counter make(int start){return new Counter(start);}
private Counter run(int amount){value+=amount;return this;}
}
'''
        candidate, result, raw = self.worker(source, "make", (10,))
        self.assertEqual(result.returncode, 0, result.stderr)
        capture = typed.observation(raw, candidate, {"case_id": "private", "function_id": "method", "fixture_sha256": "f" * 64})
        self.assertEqual(capture["after"]["nodes"][0]["fields"]["value"]["value"], "17")
        source = 'class Counter { int value; String run(int amount){value+=amount;throw new IllegalArgumentException("bad\\0");} }'
        candidate, result, raw = self.worker(source)
        self.assertEqual(result.returncode, 0, result.stderr)
        capture = typed.observation(raw, candidate, {"case_id": "error", "function_id": "method", "fixture_sha256": "f" * 64})
        self.assertEqual(capture["outcome"]["category"], "exception")
        self.assertEqual(capture["after"]["nodes"][0]["fields"]["value"]["value"], "7")
        self.assertIn(b'0062006100640000', raw)

    def test_custom_exception_formatters_and_wrong_factory_class_refuse(self):
        error = '''class BadException extends RuntimeException {
public String toString(){return "APP_CALLBACK";}
public String getMessage(){throw new AssertionError("APP_CALLBACK");}
}
'''
        for source, factory in ((error + 'class Counter {int run(int amount){throw new BadException();}}', 'Counter'),
                                ('class Counter {static Object make(){return new Object();}int run(int amount){throw new AssertionError("APP_CALLBACK");}}', 'make')):
            with self.subTest(factory=factory):
                _, result, raw = self.worker(source, factory)
                self.assertNotEqual(result.returncode, 0)
                self.assertIsNone(raw)
                self.assertNotIn(b"APP_CALLBACK", result.stdout + result.stderr)

    def test_class_initialisation_failure_never_formats_the_application_exception(self):
        source = '''class BadException extends RuntimeException {
public String toString(){return "APP_CALLBACK";}
}
class Counter {static {if(true)throw new BadException();}int run(int amount){return amount;}}
'''
        _, result, raw = self.worker(source)
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(raw)
        self.assertNotIn(b"APP_CALLBACK", result.stdout + result.stderr)

    def test_inventory_does_not_load_application_classpath_api_shadows(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "Counter.java").write_text("class Counter { int value; int read(){return value;} }\n")
            (folder / "ApiShadows.java").write_text('''class ToolProvider {
static javax.tools.JavaCompiler getSystemJavaCompiler(){throw new java.lang.AssertionError("APP_CALLBACK");}
}
class System { static java.io.PrintStream out; static { if(true)throw new java.lang.AssertionError("APP_CALLBACK"); } }
''')
            built = subprocess.run([JAVAC, "ApiShadows.java"], cwd=folder, capture_output=True, check=False, timeout=30)
            self.assertEqual(built.returncode, 0, built.stderr)
            parsed = subprocess.run([JAVA, REPO / "adapters/generation/Discover.java", folder / "Counter.java"],
                                    cwd=folder, capture_output=True, check=False, timeout=30)
            self.assertEqual(parsed.returncode, 0, parsed.stderr)
            self.assertNotIn(b"APP_CALLBACK", parsed.stdout + parsed.stderr)
            self.assertIn("functions", json.loads(parsed.stdout))

    def test_real_inventory_and_worker_capture_constructor_instance_static_and_result_aliases(self):
        source = '''class Counter {
private int value; private static int total; Counter self=this;
Counter(int start){value=start;}
Counter add(int amount){value+=amount;total+=amount;return this;}
}
'''
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / "Counter.java").write_text(source)
            parsed = subprocess.run([JAVA, REPO / "adapters/generation/Discover.java", folder / "Counter.java"],
                                    cwd=folder, capture_output=True, check=False, timeout=30)
            self.assertEqual(parsed.returncode, 0, parsed.stderr)
            discovered = json.loads(parsed.stdout)
            discovered["entrypoints"] = []
            self.assertEqual(discovered["classes"][0]["fields"][0]["modifiers"], 2)
            config = policy.validate({"languages": ["java"], "functions": {"include": ["Counter.add(int)"]},
                                      "fixtures": [{"function": "Counter.add(int)", "cases": [[7]],
                                                    "receiver": {"factory": "Counter", "arguments": [10]}}]})
            function = next(item for item in discovered["functions"] if item["name"] == "Counter.add")
            entry = gen.inventory_entry(function, discovered, "Counter.java", "java", "a" * 64, folder,
                                        argparse.Namespace(configuration=config, cases=1))
            self.assertEqual(entry["status"], "ready", entry["reason"])
            driver = harness.materialise(folder, entry, [7])
            result = subprocess.run([JAVAC, "Counter.java", str(driver)], cwd=folder,
                                    capture_output=True, check=False, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            observation = folder / "observation.json"
            result = subprocess.run([JAVA, "-Xshare:off", "-cp", folder, "OteleqDriver"], cwd=folder,
                                    env={**os.environ, "OTELEQ_OBSERVATION": str(observation)},
                                    capture_output=True, check=False, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout + result.stderr, b"")
            capture = json.loads(observation.read_text())
            self.assertEqual(capture["java_receiver_schema_version"], 1)
            before, after = capture["before"], capture["after"]
            self.assertEqual(before["nodes"][0]["fields"]["value"]["value"], "10")
            self.assertEqual(after["nodes"][0]["fields"]["value"]["value"], "17")
            self.assertEqual(before["roots"]["static:Counter.total"]["value"], "0")
            self.assertEqual(after["roots"]["static:Counter.total"]["value"], "7")
            roots = capture["outcome"]["value"]["roots"]
            self.assertEqual(roots["result"], roots["receiver"])
            contract = {"case_id": "receiver", "function_id": entry["id"], "fixture_sha256": "f" * 64}
            converted = typed.observation(observation.read_bytes(), entry, contract)
            self.assertEqual(converted["before"], before)
            self.assertEqual(converted["after"], after)
            self.assertEqual(set(typed.required_roots(entry)), set(before["roots"]))
            self.assertEqual(converted["outcome"]["graph"]["roots"]["result"], roots["receiver"])


if __name__ == "__main__":
    unittest.main()
