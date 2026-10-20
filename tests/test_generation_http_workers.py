"""Real plain workers in all eight languages exchange exact binary HTTP data."""
import argparse
import copy
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "adapters/generation"), str(ROOT / "examples")]
import generation
import discovery
import harness
import http_effects as effects
import policy
import typed_capture
import test_generation_filesystem_workers as filesystem_workers

NATIVE = r'''#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/socket.h>
#include <netinet/in.h>
static void send_all(int descriptor,const void* data,size_t size){size_t sent=0;while(sent<size){ssize_t part=write(descriptor,(const char*)data+sent,size-sent);if(part<=0)abort();sent+=(size_t)part;}}
int selected(void){const char* url=getenv("APP_SERVICE_URL");int port=atoi(strrchr(url,':')+1);int descriptor=socket(AF_INET,SOCK_STREAM,0);struct sockaddr_in address={0};address.sin_family=AF_INET;address.sin_port=htons(port);address.sin_addr.s_addr=htonl(INADDR_LOOPBACK);if(connect(descriptor,(struct sockaddr*)&address,sizeof(address))!=0)abort();char header[1024];int size=snprintf(header,sizeof(header),"POST /observe HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nX-Check: fixture\r\nContent-Length: 2\r\nConnection: close\r\n\r\n",port);send_all(descriptor,header,(size_t)size);unsigned char data[2]={0,255};send_all(descriptor,data,2);unsigned char response[8193];size_t total=0;ssize_t part;while((part=read(descriptor,response+total,8192-total))>0){total+=(size_t)part;if(total==8192)abort();}close(descriptor);response[total]=0;char* body=strstr((char*)response,"\r\n\r\n");return body&&total-(size_t)(body-(char*)response)-4==2&&body[4]==0&&(unsigned char)body[5]==255&&strncmp((char*)response,"HTTP/1.1 201",12)==0?7:8;}
'''
SOURCES = {
    "c": ("source.c", "int", NATIVE),
    "cpp": ("source.cpp", "int", NATIVE),
    "rust": ("source.rs", "i32", r'''use std::io::{Read,Write};
fn selected()->i32{let url=std::env::var("APP_SERVICE_URL").unwrap();let address=url.strip_prefix("http://").unwrap();let mut stream=std::net::TcpStream::connect(address).unwrap();stream.write_all(format!("POST /observe HTTP/1.1\r\nHost: {}\r\nX-Check: fixture\r\nContent-Length: 2\r\nConnection: close\r\n\r\n",address).as_bytes()).unwrap();stream.write_all(&[0,255]).unwrap();let mut response=Vec::new();stream.read_to_end(&mut response).unwrap();let start=response.windows(4).position(|part|part==b"\r\n\r\n").unwrap()+4;if response.starts_with(b"HTTP/1.1 201")&&response[start..]==[0,255]{7}else{8}}
'''),
    "go": ("source.go", "int", '''package main
import("bytes";"io";"net/http";"os")
func selected() int{request,err:=http.NewRequest("POST",os.Getenv("APP_SERVICE_URL")+"/observe",bytes.NewReader([]byte{0,255}));if err!=nil{panic(err)};request.Header.Set("x-check","fixture");response,err:=http.DefaultClient.Do(request);if err!=nil{panic(err)};defer response.Body.Close();data,err:=io.ReadAll(response.Body);if err!=nil{panic(err)};if response.StatusCode==201&&bytes.Equal(data,[]byte{0,255}){return 7};return 8}
'''),
    "java": ("App.java", "int", '''class App{static int selected() throws Exception{java.net.HttpURLConnection connection=(java.net.HttpURLConnection)new java.net.URI(java.lang.System.getenv("APP_SERVICE_URL")+"/observe").toURL().openConnection();connection.setRequestMethod("POST");connection.setRequestProperty("x-check","fixture");connection.setDoOutput(true);connection.setFixedLengthStreamingMode(2);try{try(java.io.OutputStream stream=connection.getOutputStream()){stream.write(new byte[]{0,(byte)255});}byte[] data;try(java.io.InputStream stream=connection.getInputStream()){data=stream.readAllBytes();}return connection.getResponseCode()==201&&java.util.Arrays.equals(data,new byte[]{0,(byte)255})?7:8;}finally{connection.disconnect();}}}
'''),
    "python": ("source.py", "int", '''import os
import urllib.request
def selected()->int:
 request=urllib.request.Request(os.environ["APP_SERVICE_URL"]+"/observe",data=b"\\0\\xff",headers={"x-check":"fixture"})
 with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=2) as response:
  return 7 if response.status==201 and response.read()==b"\\0\\xff" else 8
'''),
    "javascript": ("source.mjs", "number", '''async function selected(){const response=await fetch(process.env.APP_SERVICE_URL+"/observe",{method:"POST",headers:{"x-check":"fixture"},body:new Uint8Array([0,255])});const data=new Uint8Array(await response.arrayBuffer());return response.status===201&&data.length===2&&data[0]===0&&data[1]===255?7:8;}
'''),
    "typescript": ("source.mts", "number", '''async function selected():Promise<number>{const response=await fetch(process.env.APP_SERVICE_URL+"/observe",{method:"POST",headers:{"x-check":"fixture"},body:new Uint8Array([0,255])});const data=new Uint8Array(await response.arrayBuffer());return response.status===201&&data.length===2&&data[0]===0&&data[1]===255?7:8;}
'''),
}


class PlainHttpWorkerTests(unittest.TestCase):
    compile_worker = filesystem_workers.PlainFilesystemWorkerTests.compile_worker

    def test_native_network_headers_use_the_separate_bounded_metadata_budget(self):
        for language, variable, compiler in (("c", "OTELC_CLANG", "clang"),
                                             ("cpp", "OTELC_CLANGXX", "clang++")):
            with self.subTest(language=language), tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary)
                name, _, source = SOURCES[language]
                path = folder / name
                path.write_text(source)
                tools = {compiler: Path(os.environ.get(variable) or shutil.which(compiler))}
                with patch.object(generation, "MAX_OUTPUT", 1024):
                    result = discovery.discover(path, language, folder, tools, generation.execute)
                selected = next(entry for entry in result["functions"] if entry["name"] == "selected")
                self.assertEqual(selected["reason"], "")
                self.assertEqual(selected["parameters"], [])

    def test_all_eight_workers_send_and_receive_the_declared_binary_http_data(self):
        for language, (name, output, source) in SOURCES.items():
            with self.subTest(language=language), tempfile.TemporaryDirectory() as temporary:
                folder = Path(temporary); (folder / name).write_text(source)
                entry = {"language": language, "path": name, "name": "App.selected" if language == "java" else "selected", "output": output,
                         "line": 3 if language == "python" else 1, "parameters": [], "globals": [], "file_functions": [], "package": "", "package_end": len("package main"), "async": language in ("javascript", "typescript")}
                driver = harness.materialise(folder, entry, [])
                command = self.compile_worker(language, folder, driver)
                configured = policy.validate({"effects": {"http": [{"name": "service", "environment": "APP_SERVICE_URL", "headers": ["x-check"], "responses": [{"status": 201, "hex": "00ff"}], "min_requests": 1}]}})
                with effects.fixtures(configured) as fixtures:
                    with effects.observe(fixtures, folder, 65536) as captures:
                        observation = folder / "observation"
                        result = subprocess.run(command, cwd=folder, env={**os.environ, **effects.bindings(fixtures), "OTELEQ_OBSERVATION": str(observation), "GOTOOLCHAIN": "local"}, capture_output=True, timeout=30, check=False)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, b"")
                    channels, complete = effects.finish(captures)
                    self.assertTrue(complete, json.loads(bytes(channels["http:service"])))
                    record = json.loads(bytes(channels["http:service"]))["requests"][0]
                    self.assertEqual(record["method"], "POST")
                    self.assertEqual(record["target_hex"], b"/observe".hex())
                    self.assertEqual(record["body_hex"], "00ff")
                    self.assertEqual([bytes.fromhex(value).lower() for value in record["header_lines_hex"]], [b"x-check: fixture"])
                    typed = typed_capture.observation(observation.read_bytes(), entry, {"case_id": "case", "function_id": "selected", "fixture_sha256": "a" * 64})
                    value = typed["outcome"]["graph"]["roots"]["result"]
                    self.assertEqual(struct.unpack('>d', bytes.fromhex(value["bits"]))[0] if value["kind"] == "float" else int(value["value"]), 7)


class HttpExecutionTests(unittest.TestCase):
    def test_missing_case_context_refuses_before_any_application_launch(self):
        data = {"configuration": policy.validate({"effects": {"http": [{"name": "service", "environment": "APP_SERVICE_URL"}]}})}
        with patch.object(generation, "execute") as execute:
            with self.assertRaisesRegex(ValueError, "case fixture context"):
                generation.attempt(None, data, None, None, None, None, None)
            execute.assert_not_called()

    def test_attempt_binds_after_build_and_retains_required_incomplete_and_typed_channels(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary); source = base / "source"; source.mkdir(); sdk = base / "sdk"; sdk.mkdir()
            text = '''import os,urllib.request,urllib.error
def sample(extra:bool)->int:
 for _ in range(2 if extra else 1):
  try:
   request=urllib.request.Request(os.environ["APP_SERVICE_URL"]+"/observe",data=b"good",headers={"x-check":"fixture"})
   with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=2) as response:
    if response.read()!=b"\\0\\xff":return 8
  except urllib.error.HTTPError:
   if not extra:raise
 return 7
'''
            (source / "source.py").write_text(text)
            config = base / "policy.toml"
            config.write_text('schema_version=1\nlanguages=["python"]\n[[effects.http]]\nname="service"\nenvironment="APP_SERVICE_URL"\nheaders=["x-check"]\nresponses=[{status=201,hex="00ff"}]\nmin_requests=1\nmax_requests=1\n')
            tools, selected = {"python": Path(sys.executable)}, {"tool:python": "a" * 64}
            with patch.dict(os.environ, {"OTELEQ_EXECUTABLE": sys.executable}), patch.object(generation.capture, "selected_tools", return_value=tools), patch.object(generation.capture, "artefacts", return_value=selected), redirect_stdout(io.StringIO()) as out:
                generation.plan(argparse.Namespace(source=source, otelc_root=sdk, workspace_parent=base, language=None, exclude=[], cases=2, config=config))
                workspace = Path(out.getvalue().strip())
                generation.generate(argparse.Namespace(workspace=workspace))
                _, data = generation.load_workspace(workspace, generated=True)
                entry = next(item for item in data["inventory"] if item["status"] == "ready")
                cases = generation.read(workspace / "tests/corpus.json")
                def build(root, project, candidate, driver, policy_path, selected_tools, environment, *rest):
                    self.assertNotIn("APP_SERVICE_URL", environment)
                    return [sys.executable, driver]
                frames = {}
                with patch.object(generation.capture, "stable"), patch.object(generation, "build_command", side_effect=build), effects.fixtures(data["configuration"]) as fixtures:
                    for case in cases:
                        folder = base / ("attempt-" + str(case["arguments"][0]))
                        result = generation.attempt(workspace, data, entry, case, "baseline", folder, None, http_fixtures=fixtures)
                        frames[case["arguments"][0]] = result
                        self.assertEqual(result["capture_complete"], not case["arguments"][0])
                        observed = json.loads(bytes(result["channels"]["http:service"]))
                        self.assertEqual(observed["complete"], not case["arguments"][0])
                        self.assertEqual(observed["requests"][0]["body_hex"], b"good".hex())
                        controls = generation.read(folder / "http-controls.json")
                        self.assertEqual(controls["environment"], effects.bindings(fixtures))
                frame = copy.deepcopy(frames[False]); frame["witness"] = {"functions": {entry["otelc_function"]: 1}}
                seen = []
                def captured(*arguments, **options):
                    arguments[5].mkdir()
                    seen.append(effects.bindings(options["http_fixtures"]))
                    return frame
                destination = base / "comparison"; destination.mkdir()
                ordinary = next(case for case in cases if case["arguments"] == [False])
                with patch.object(generation, "attempt", side_effect=captured), patch.object(generation, "execute", return_value=subprocess.CompletedProcess([], 0, b'{"verdict":"equivalent_observed"}', b"")):
                    generation.compare_case(workspace, data, entry, ordinary, destination, None)
                bundle = generation.read(destination / "typed-bundle.json")
                self.assertEqual(len(seen), 4)
                self.assertTrue(all(value == seen[0] for value in seen))
                self.assertIn("http:service", bundle["scope"]["channels"])
                self.assertEqual(bundle["cases"][0]["baseline"][0]["execution"]["channels"]["http:service"], frame["channels"]["http:service"])
                roots = typed_capture.required_roots(entry)
                initial = generation.identity({"case": ordinary, "source": entry["source_sha256"], "roots": roots})
                configured = generation.identity({"fixture": initial, "effects": data["configuration"]["effects"]})
                self.assertEqual(bundle["cases"][0]["contract"]["fixture_sha256"], generation.identity({"fixture": configured, "http_environment": seen[0]}))
                budget = copy.deepcopy(data)
                folder = base / "attempt-False"
                budget["configuration"]["limits"]["max_capture_bytes"] = (folder / "observation").stat().st_size + 1
                completed = subprocess.CompletedProcess([], 0, b"", b"")
                with self.assertRaisesRegex(ValueError, "channel budget"):
                    generation.qualify_attempt(budget, entry, "baseline", folder, completed, [], [], "service", None, extra_channels={"http:service": frame["channels"]["http:service"]})
                self.assertEqual((source / "source.py").read_text(), text)
                generation.load_workspace(workspace, generated=True)


if __name__ == "__main__":
    unittest.main()
