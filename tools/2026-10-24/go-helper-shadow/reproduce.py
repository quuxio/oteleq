import hashlib,json,os,subprocess,sys,time
from pathlib import Path
repo=Path('/Users/sclarke/github/oteleq-qualification/work/oteleq-go-public-provider')
sys.path[:0]=[str(repo/'adapters/generation'),str(repo/'examples')]
import go_rendezvous as gate
root=Path(__file__).resolve().parent
app=root/'before-fix-02'
app.mkdir()
control=app/'control';control.mkdir(mode=0o700)
source='''package main
import "fmt"
var Calls int
func len(text string) int { Calls++; count:=0; for range []byte(text) {count++}; return count }
func main() { __oteleqAwaitGoHost(); fmt.Println(Calls) }
'''
(app/'main.go').write_text(source)
(app/'go.mod').write_text('module example.test/shadow\n\ngo 1.26.0\n')
gate.materialise(app,'main')
go='/Users/sclarke/go/pkg/mod/golang.org/toolchain@v0.0.1-go1.27.3.darwin-arm64/bin/go'
env={k:v for k,v in os.environ.items() if not k.startswith(('OTEL','GH_','GITHUB_','AWS_','SONAR_'))}
env.update(GOWORK='off',GOFLAGS='',GOENV='off',GOTOOLCHAIN='local',GOPROXY='off',GOCACHE=str(repo/'build/go-rendezvous-cache'))
command=[go,'build','-o',str(app/'worker'),'.']
build=subprocess.run(command,cwd=app,env=env,capture_output=True,timeout=90)
assert build.returncode==0,(build.stdout+build.stderr).decode()
token='a'*32
env.update({gate.ROOT_ENV:str(control),gate.TOKEN_ENV:token,gate.WAIT_ENV:'5000'})
process=subprocess.Popen([str(app/'worker')],cwd=app,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
deadline=time.monotonic()+5
while not (control/'start.ready').exists():
 assert process.poll() is None,'worker exited before readiness'
 assert time.monotonic()<deadline,'readiness timeout'
 time.sleep(.005)
(control/'start.resume.tmp').write_text(token+' release\n')
os.chmod(control/'start.resume.tmp',0o600)
os.link(control/'start.resume.tmp',control/'start.resume')
out,err=process.communicate(timeout=10)
result={'scope':'Compiled generated gate with legal application len function; no target/factory call','exit_code':process.returncode,'expected_application_calls':0,'actual_application_calls':int(out),'stderr':err.decode(),'source_sha256':hashlib.sha256(source.encode()).hexdigest(),'command':command}
(root/'before-fix.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
assert process.returncode==0 and int(out)>0
