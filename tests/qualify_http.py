"""Real eight-language HTTP effects with unchanged returns and preserved sources."""
import json
from pathlib import Path
from urllib.parse import urlsplit

from effect_qualification import EffectQualification
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
                execution = attempt["execution"]
                qualification.return_seven(attempt)
                effect = json.loads(bytes(execution["channels"]["http:service"]))
                assert effect["complete"] is (not incomplete) and execution["capture_complete"] is (not incomplete)
                folder = path.parent / case["case"] / (lane + "-" + str(index))
                controls = json.loads((folder / "http-controls.json").read_text())
                binding = controls["environment"]["APP_SERVICE_URL"]; bindings.append(binding)
                qualification.actual_attempt(folder, case["case"])
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
                qualification.witness(execution, entry, case, lane)
        assert len(set(bindings)) == 1
        qualification.differences(case)
    return launches


qualification = EffectQualification(
    prepare=prepare, check_report=check_report, channel='http:service',
    match_name='http_match', difference_name='http_difference',
    sidecars=('http-controls.json', 'http-service.json'),
    scope='Eight-language scripted local HTTP requests/offered responses, matched literal case URLs, generated/exported suites and scalar reduction/replay; no general network/concurrency/TLS/socket-lifecycle/shipping proof.',
)


if __name__ == "__main__":
    qualification.main()
