"""Real eight-language HTTP effects with unchanged returns and preserved sources."""
import argparse
from collections import defaultdict
import copy
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
from urllib.parse import urlsplit

from qualify_generation import command

SOURCES = {
    'c': ('source.c', '#include <stdio.h>\n#include <stdlib.h>\n#include <string.h>\n#include <unistd.h>\n#include <sys/socket.h>\n#include <netinet/in.h>\nstatic void send_all(int descriptor,const void* data,size_t size){size_t sent=0;while(sent<size){ssize_t part=write(descriptor,(const char*)data+sent,size-sent);if(part<=0)abort();sent+=(size_t)part;}}\nstatic int exchange(int bad){const char* url=getenv("APP_SERVICE_URL");int port=atoi(strrchr(url,\':\')+1);int descriptor=socket(AF_INET,SOCK_STREAM,0);struct sockaddr_in address={0};address.sin_family=AF_INET;address.sin_port=htons(port);address.sin_addr.s_addr=htonl(INADDR_LOOPBACK);if(connect(descriptor,(struct sockaddr*)&address,sizeof(address))!=0)abort();char header[1024];int size=snprintf(header,sizeof(header),"POST /observe HTTP/1.1\\r\\nHost: 127.0.0.1:%d\\r\\nX-Check: fixture\\r\\nContent-Length: 2\\r\\nConnection: close\\r\\n\\r\\n",port);send_all(descriptor,header,(size_t)size);unsigned char data[2]={(unsigned char)(bad?1:0),255};send_all(descriptor,data,2);unsigned char response[8193];size_t total=0;ssize_t part;while((part=read(descriptor,response+total,8192-total))>0){total+=(size_t)part;if(total==8192)abort();}close(descriptor);response[total]=0;char* body=strstr((char*)response,"\\r\\n\\r\\n");return body&&total-(size_t)(body-(char*)response)-4==2&&body[4]==0&&(unsigned char)body[5]==255&&strncmp((char*)response,"HTTP/1.1 201",12)==0?7:8;}\n\nint http_match(int value){(void)value;return exchange(0);}\nint http_difference(int value){return exchange(value>0 && getenv("OTELC_CONFIG")!=NULL);}\n'),
    'cpp': ('source.cpp', '#include <stdio.h>\n#include <stdlib.h>\n#include <string.h>\n#include <unistd.h>\n#include <sys/socket.h>\n#include <netinet/in.h>\nstatic void send_all(int descriptor,const void* data,size_t size){size_t sent=0;while(sent<size){ssize_t part=write(descriptor,(const char*)data+sent,size-sent);if(part<=0)abort();sent+=(size_t)part;}}\nstatic int exchange(int bad){const char* url=getenv("APP_SERVICE_URL");int port=atoi(strrchr(url,\':\')+1);int descriptor=socket(AF_INET,SOCK_STREAM,0);struct sockaddr_in address={0};address.sin_family=AF_INET;address.sin_port=htons(port);address.sin_addr.s_addr=htonl(INADDR_LOOPBACK);if(connect(descriptor,(struct sockaddr*)&address,sizeof(address))!=0)abort();char header[1024];int size=snprintf(header,sizeof(header),"POST /observe HTTP/1.1\\r\\nHost: 127.0.0.1:%d\\r\\nX-Check: fixture\\r\\nContent-Length: 2\\r\\nConnection: close\\r\\n\\r\\n",port);send_all(descriptor,header,(size_t)size);unsigned char data[2]={(unsigned char)(bad?1:0),255};send_all(descriptor,data,2);unsigned char response[8193];size_t total=0;ssize_t part;while((part=read(descriptor,response+total,8192-total))>0){total+=(size_t)part;if(total==8192)abort();}close(descriptor);response[total]=0;char* body=strstr((char*)response,"\\r\\n\\r\\n");return body&&total-(size_t)(body-(char*)response)-4==2&&body[4]==0&&(unsigned char)body[5]==255&&strncmp((char*)response,"HTTP/1.1 201",12)==0?7:8;}\n\nint http_match(int value){(void)value;return exchange(0);}\nint http_difference(int value){return exchange(value>0 && getenv("OTELC_CONFIG")!=NULL);}\n'),
    'rust': ('source.rs', 'use std::io::{Read,Write};\nfn exchange(bad:bool)->i32{let url=std::env::var("APP_SERVICE_URL").unwrap();let address=url.strip_prefix("http://").unwrap();let mut stream=std::net::TcpStream::connect(address).unwrap();stream.write_all(format!("POST /observe HTTP/1.1\\r\\nHost: {}\\r\\nX-Check: fixture\\r\\nContent-Length: 2\\r\\nConnection: close\\r\\n\\r\\n",address).as_bytes()).unwrap();stream.write_all(&[if bad{1}else{0},255]).unwrap();let mut response=Vec::new();stream.read_to_end(&mut response).unwrap();let start=response.windows(4).position(|part|part==b"\\r\\n\\r\\n").unwrap()+4;if response.starts_with(b"HTTP/1.1 201")&&response[start..]==[0,255]{7}else{8}}\n\nfn active()->bool{let bytes=std::fs::read(std::env::current_exe().unwrap()).unwrap();let mut count=0;for part in bytes.windows(15){if part==b"quux_otelc_rust"{count+=1}}count>1}\nfn http_match(value:i32)->i32{let _=value;exchange(false)}\nfn http_difference(value:i32)->i32{exchange(value>0 && active())}\n'),
    'go': ('source.go', 'package main\nimport("bytes";"io";"net/http";"runtime";"os")\nfunc exchange(bad bool) int{first:=byte(0);if bad{first=1};request,err:=http.NewRequest("POST",os.Getenv("APP_SERVICE_URL")+"/observe",bytes.NewReader([]byte{first,255}));if err!=nil{panic(err)};request.Header.Set("x-check","fixture");response,err:=http.DefaultClient.Do(request);if err!=nil{panic(err)};defer response.Body.Close();data,err:=io.ReadAll(response.Body);if err!=nil{panic(err)};if response.StatusCode==201&&bytes.Equal(data,[]byte{0,255}){return 7};return 8}\n\nfunc http_match(value int) int{return exchange(false)}\nfunc http_difference(value int) int{return exchange(value>0 && runtime.NumGoroutine()>1)}\n'),
    'java': ('App.java', 'class App{static int exchange(boolean bad) throws Exception{java.net.HttpURLConnection connection=(java.net.HttpURLConnection)new java.net.URI(java.lang.System.getenv("APP_SERVICE_URL")+"/observe").toURL().openConnection();connection.setRequestMethod("POST");connection.setRequestProperty("x-check","fixture");connection.setDoOutput(true);connection.setFixedLengthStreamingMode(2);try{try(java.io.OutputStream stream=connection.getOutputStream()){stream.write(new byte[]{(byte)(bad?1:0),(byte)255});}byte[] data;try(java.io.InputStream stream=connection.getInputStream()){data=stream.readAllBytes();}return connection.getResponseCode()==201&&java.util.Arrays.equals(data,new byte[]{0,(byte)255})?7:8;}finally{connection.disconnect();}}\nstatic int http_match(int value) throws Exception{return exchange(false);}\nstatic int http_difference(int value) throws Exception{return exchange(value>0 && java.lang.management.ManagementFactory.getRuntimeMXBean().getInputArguments().toString().contains("-javaagent:"));}\n}\n'),
    'python': ('source.py', 'import os,sys,socket\nfrom urllib.parse import urlsplit\nimport urllib.request\ndef exchange(bad:bool)->int:\n request=urllib.request.Request(os.environ["APP_SERVICE_URL"]+"/observe",data=(b"\\1\\xff" if bad else b"\\0\\xff"),headers={"x-check":"fixture"})\n with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=2) as response:\n  return 7 if response.status==201 and response.read()==b"\\0\\xff" else 8\n\ndef http_match(value:int)->int:\n return exchange(False)\ndef http_difference(value:int)->int:\n return exchange(value>0 and "quux.otelc" in tuple(sys.monitoring.get_tool(index) for index in range(6)))\ndef http_missing(value:int)->int:\n return 7\ndef http_chunked(value:int)->int:\n target=urlsplit(os.environ["APP_SERVICE_URL"])\n with socket.create_connection((target.hostname,target.port),timeout=2) as connection:\n  try:\n   connection.sendall(b"POST /observe HTTP/1.1\\r\\nHost: fixture\\r\\nTransfer-Encoding: chunked\\r\\n\\r\\n2\\r\\n\\0\\xff\\r\\n0\\r\\n\\r\\n")\n   connection.recv(4096)\n  except OSError:\n   pass\n return 7\n'),
    'javascript': ('source.mjs', 'async function exchange(bad){const response=await fetch(process.env.APP_SERVICE_URL+"/observe",{method:"POST",headers:{"x-check":"fixture"},body:new Uint8Array([bad?1:0,255])});const data=new Uint8Array(await response.arrayBuffer());return response.status===201&&data.length===2&&data[0]===0&&data[1]===255?7:8;}\n\nasync function http_match(value){return await exchange(false);}\nasync function http_difference(value){return await exchange(value>0 && process.execArgv.join(" ").includes("/node/register.mjs"));}\n'),
    'typescript': ('source.mts', 'async function exchange(bad:boolean):Promise<number>{const response=await fetch(process.env.APP_SERVICE_URL+"/observe",{method:"POST",headers:{"x-check":"fixture"},body:new Uint8Array([bad?1:0,255])});const data=new Uint8Array(await response.arrayBuffer());return response.status===201&&data.length===2&&data[0]===0&&data[1]===255?7:8;}\n\nasync function http_match(value:number):Promise<number>{return await exchange(false);}\nasync function http_difference(value:number):Promise<number>{return await exchange(value>0 && process.execArgv.join(" ").includes("/node/register.mjs"));}\n'),
}

def prepare(cli: Path, provider: Path, folder: Path) -> Path:
    folder.mkdir()
    source = folder / "application"; source.mkdir()
    fixtures = []
    for language, (name, text) in SOURCES.items():
        (source / name).write_text(text)
        names = ["http_match", "http_difference", *(["http_missing", "http_chunked"] if language == "python" else [])]
        for function in names:
            fixtures.append('\n[[fixtures]]\nlanguage=' + json.dumps(language) + '\nsource=' + json.dumps(name)
                            + '\nfunction=' + json.dumps('*' + function + '*') + '\ncases=[[7]]\ndomains=[{kind="integer",minimum=0,maximum=7}]\n')
    config = folder / "equivalence.toml"
    config.write_text('schema_version=1\n[functions]\ninclude=["*http_match*","*http_difference*","*http_missing*","*http_chunked*"]\n'
                      '[[effects.http]]\nname="service"\nenvironment="APP_SERVICE_URL"\nheaders=["host","x-check"]\n'
                      'responses=[{status=201,hex="00ff"}]\nmin_requests=1\nmax_requests=1\nmax_bytes=2\n' + ''.join(fixtures))
    workspace = Path(command([cli, "plan", "--source", source, "--otelc-root", provider, "--workspace-parent", folder, "--config", config], folder, "plan"))
    inventory = json.loads((workspace / "plan.json").read_text())["inventory"]
    assert sum(item["status"] == "ready" for item in inventory) == 18 and not any(item["status"] == "blocked" for item in inventory), inventory
    command([cli, "generate", "--workspace", workspace], folder, "generate")
    return workspace


def expected(case: dict) -> int:
    if any(name in case["function"] for name in ("http_missing", "http_chunked")):
        return 3
    return int("http_difference" in case["function"] and case["arguments"][0] > 0)


def actual_attempt(folder: Path, case_id: str) -> tuple[Path, Path]:
    """Copied shrink evidence retains its actual, original execution directory."""
    cwd = Path(json.loads((folder / "working-directory.json").read_text()))
    assert cwd.name == "project"
    actual = cwd.parent
    assert actual.name == folder.name and actual.parent.name == case_id
    if actual.resolve() != folder.resolve():
        assert folder.parent.parent.name == "original"
        assert actual.resolve().is_relative_to(folder.parents[3].resolve())
        for name in ("command.json", "working-directory.json", "http-controls.json", "http-service.json", "typed-observation.json", "http-capture.json"):
            assert (actual / name).read_bytes() == (folder / name).read_bytes(), name
    return cwd, actual


def check_report(path: Path, count: int = 18) -> int:
    """Request/response literals and return oracles are independent of lane agreement."""
    report = json.loads(path.read_text())
    assert report["source_preserved"] and not report["blocked"] and len(report["cases"]) == count
    inventory = {item["otelc_function"]: item for item in report["inventory"]}
    launches = 0
    for case in report["cases"]:
        assert case["exit_code"] == expected(case), case
        entry = inventory[case["function"]]
        bundle = json.loads((path.parent / case["case"] / "typed-bundle.json").read_text())["cases"][0]
        incomplete = expected(case) == 3
        bindings = []
        for lane in ("baseline", "instrumented_on"):
            assert len(bundle[lane]) == 2
            for index, attempt in enumerate(bundle[lane]):
                launches += 1
                execution, observation = attempt["execution"], attempt["observation"]
                value = observation["outcome"]["graph"]["roots"]["result"]
                actual = struct.unpack('>d', bytes.fromhex(value["bits"]))[0] if value["kind"] == "float" else int(value["value"])
                assert actual == 7 and observation["outcome"]["kind"] == "return"
                assert execution["channels"]["stdout"] == execution["channels"]["stderr"] == []
                effect = json.loads(bytes(execution["channels"]["http:service"]))
                assert effect["complete"] is (not incomplete) and execution["capture_complete"] is (not incomplete)
                folder = path.parent / case["case"] / (lane + "-" + str(index))
                controls = json.loads((folder / "http-controls.json").read_text())
                binding = controls["environment"]["APP_SERVICE_URL"]; bindings.append(binding)
                actual_attempt(folder, case["case"])
                assert json.loads((folder / "http-service.json").read_text()) == effect
                if incomplete:
                    assert effect["gaps"] and not effect["requests"]
                else:
                    assert not effect["gaps"] and len(effect["requests"]) == 1
                    request = effect["requests"][0]
                    assert request["method"] == "POST" and request["target_hex"] == b"/observe".hex() and request["version"] == "HTTP/1.1"
                    bad = lane == "instrumented_on" and expected(case) == 1
                    assert request["body_hex"] == ("01ff" if bad else "00ff")
                    assert request["response_index"] == 0
                    assert bytes.fromhex(request["response_hex"]) == b"HTTP/1.1 201 Fixture\r\nConnection: close\r\nContent-Length: 2\r\n\r\n\0\xff"
                    headers = [bytes.fromhex(value) for value in request["header_lines_hex"]]
                    assert len(headers) == 2
                    assert [line.partition(b":")[2].strip() for line in headers if line.partition(b":")[0].lower() == b"host"] == [urlsplit(binding).netloc.encode()]
                    assert [line.partition(b":")[2].strip() for line in headers if line.partition(b":")[0].lower() == b"x-check"] == [b"fixture"]
                if lane == "instrumented_on":
                    assert execution["witness"]["functions"] == {entry.get("otelc_runtime_function", case["function"]): 1}
                    assert not any(execution["witness"]["losses"].values())
        assert len(set(bindings)) == 1
        if case["exit_code"] == 1:
            compared = case["comparison"]["cases"][0]
            assert {item["path"] for item in compared["execution"]["differences"]} == {"channels.http:service"}
            assert all(not pair["comparison"]["differences"] for pair in compared["pairs"])
    return launches


def framework(workspace: Path, folder: Path, name: str, count: int = 18, *, resume: bool = False) -> int:
    retained = folder / (name + ".stdout")
    text = retained.read_text() if resume and retained.is_file() else command([sys.executable, workspace / "tests/test_equivalence.py"], folder, name, expected=1)
    reports = [json.loads(line) for line in text.splitlines()]
    assert len(reports) == count
    return sum(check_report(Path(row["report"]), 1) for row in reports)


def evidence_controls(cli: Path, folder: Path) -> int:
    report = json.loads((folder / "comparison/report.json").read_text())
    controls = 0
    for case in report["cases"]:
        if "http_match" not in case["function"]:continue
        original = json.loads((folder / "comparison" / case["case"] / "typed-bundle.json").read_text())
        for kind in ("missing", "incomplete"):
            altered = copy.deepcopy(original)
            execution = altered["cases"][0]["instrumented_on"][0]["execution"]
            if kind == "missing":del execution["channels"]["http:service"]
            else:execution["capture_complete"] = False
            name = "control-" + case["case"] + "-" + kind
            path = folder / (name + ".json");path.write_text(json.dumps(altered))
            command([cli, "compare-observations", path], folder, name, expected=3)
            controls += 1
    assert controls == 16
    return controls


def retained_workflows(cli: Path, provider: Path, folder: Path, resume: bool) -> tuple[Path, Path, int, int]:
    """Revalidate completed routes on resume without repeating application launches."""
    if resume:
        required = ("comparison/report.json", "framework.stdout", "exported/plan.json", "export-comparison/report.json", "export-framework.stdout")
        if not all((folder / name).is_file() for name in required):
            raise ValueError("resume requires all four completed initial execution routes")
        plans = list((folder / "cases").glob("*/plan.json"))
        assert len(plans) == 1
        assert Path(json.loads(plans[0].read_text())["otelc_root"]).resolve() == provider
        workspace = plans[0].parent
        command([cli, "export-tests", "--workspace", workspace, "--destination", folder / "resume-identity-check"], folder, "resume-identity-check")
    else:
        folder.mkdir(mode=0o700)
        workspace = prepare(cli, provider, folder / "cases")
        command([cli, "run", "--workspace", workspace, "--report-dir", folder / "comparison"], folder, "run", expected=3)
    launches = check_report(folder / "comparison/report.json")
    controls = evidence_controls(cli, folder)
    launches += framework(workspace, folder, "framework", resume=resume)
    exported = folder / "exported"
    if not resume:
        command([cli, "export-tests", "--workspace", workspace, "--destination", exported, "--apply"], folder, "export")
        command([cli, "run", "--workspace", exported, "--report-dir", folder / "export-comparison"], folder, "export-run", expected=3)
    launches += check_report(folder / "export-comparison/report.json")
    launches += framework(exported, folder, "export-framework", resume=resume)
    return workspace, exported, launches, controls


def reduce_case(cli: Path, workspace: Path, folder: Path, case: dict, resume: bool) -> tuple[int, dict]:
    target = folder / ("shrink-" + case["case"])
    if not (resume and (target / "shrink.json").is_file()):
        command([cli, "shrink", "--workspace", workspace, "--case", case["case"], "--report-dir", target, "--trials", "8"], folder, target.name, expected=1)
    shrink = json.loads((target / "shrink.json").read_text())
    assert shrink["reduced_arguments"] == [1] and shrink["status"] == "candidate_rule_minimal"
    launches = sum(check_report(path, 1) for path in [target / "original/report.json", target / "confirmation/report.json", *[Path(row["report"]) for row in shrink["trials"]]])
    reduced = Path(shrink["workspace"])
    launches += framework(reduced, folder, "reduced-" + case["case"], 1, resume=resume)
    name = "replay-" + case["case"]
    retained = folder / (name + ".stdout")
    text = retained.read_text() if resume and retained.is_file() else command([cli, "replay", "--workspace", reduced, "--case", case["case"]], folder, name, expected=1)
    replay = json.loads(text)
    launches += check_report(Path(replay["report"]), 1)
    print(json.dumps({"completed_reduction": case["function"], "arguments": shrink["reduced_arguments"], "actual_launches": launches}), flush=True)
    return launches, {"function": case["function"], "arguments": shrink["reduced_arguments"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--otelc-root", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--resume", action="store_true", help="revalidate retained completed routes/shrinks and continue; never restart an unfinished shrink")
    args = parser.parse_args()
    cli, provider, folder = args.cli.resolve(strict=True), args.otelc_root.resolve(strict=True), args.report_dir.resolve()
    if any(folder.is_relative_to(path) for path in (provider, Path(__file__).resolve().parents[1])):
        parser.error("qualification directory must be new and outside both repositories")
    os.environ.update(OTELEQ_PYTHON=sys.executable, OTELEQ_CLI=str(cli))
    workspace, exported, launches, controls = retained_workflows(cli, provider, folder, args.resume)
    report = json.loads((folder / "comparison/report.json").read_text())
    reductions = []
    for case in report["cases"]:
        if "http_difference" not in case["function"]:continue
        actual, reduction = reduce_case(cli, workspace, folder, case, args.resume)
        launches += actual
        reductions.append(reduction)
    assert len(reductions) == 8
    identities = defaultdict(list)
    for path in folder.rglob("command.json"):
        if (path.parent / "http-capture.json").is_file():identities[hashlib.sha256(path.read_bytes()).hexdigest()].append(str(path.parent))
    assert len(identities) == launches
    for path in (workspace, exported):
        plan = json.loads((path / "plan.json").read_text())
        assert all(hashlib.sha256((Path(plan["source"]) / name).read_bytes()).hexdigest() == sha for name, sha in plan["source_manifest"].items())
    result = {"claim": "equivalence over these tests and observations", "artefact_class": "diagnostic",
              "cli_sha256": hashlib.sha256(cli.read_bytes()).hexdigest(), "cases": 18, "matching_cases": 8,
              "same_return_http_difference_cases": 8, "incomplete_effect_cases": 2,
              "actual_application_launches": launches, "source_preserved": True,
              "altered_evidence_controls": controls, "reductions": reductions,
              "raw_attempt_folders": sum(map(len, identities.values())), "unique_command_identities": len(identities),
              "scope": "Eight-language scripted local HTTP requests/offered responses, matched literal case URLs, generated/exported suites and scalar reduction/replay; no general network/concurrency/TLS/socket-lifecycle/shipping proof."}
    (folder / "QUALIFICATION.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
