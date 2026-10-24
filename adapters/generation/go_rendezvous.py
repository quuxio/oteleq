# Generated observer boilerplate is MIT licensed; see GENERATED-LICENSE.txt.
"""Create a private Go worker gate before constructors, observations or calls."""

from pathlib import Path
import json

import go_project

ROOT_ENV = "OTELEQ_GO_CONTROL_ROOT"
TOKEN_ENV = "OTELEQ_GO_CONTROL_TOKEN"
WAIT_ENV = "OTELEQ_GO_CONTROL_WAIT_MS"
HELPER = "rendezvous.go"

SOURCE = r'''
import (
 __oteleq_gate_fmt "fmt"
 __oteleq_gate_os "os"
 __oteleq_gate_filepath "path/filepath"
 __oteleq_gate_strconv "strconv"
 __oteleq_gate_syscall "syscall"
 __oteleq_gate_time "time"
)

func AwaitHost(){
 root:=__oteleq_gate_os.Getenv("OTELEQ_GO_CONTROL_ROOT")
 token:=__oteleq_gate_os.Getenv("OTELEQ_GO_CONTROL_TOKEN")
 text:=__oteleq_gate_os.Getenv("OTELEQ_GO_CONTROL_WAIT_MS")
 budget,err:=__oteleq_gate_strconv.Atoi(text)
 if err!=nil || __oteleq_gate_strconv.Itoa(budget)!=text || budget<1 || budget>900000 {panic("invalid Go host wait budget")}
 real,err:=__oteleq_gate_filepath.EvalSymlinks(root)
 if err!=nil || !__oteleq_gate_filepath.IsAbs(root) || real!=root {panic("invalid Go host root")}
 info,err:=__oteleq_gate_os.Lstat(root)
 if err!=nil || !info.IsDir() || info.Mode().Perm()!=0700 || info.Sys().(*__oteleq_gate_syscall.Stat_t).Uid!=uint32(__oteleq_gate_os.Getuid()) {panic("unsafe Go host root")}
 if len(token)!=32 {panic("invalid Go host token")}
 for _,c:=range token {if !(c>='0' && c<='9' || c>='a' && c<='f'){panic("invalid Go host token")}}
 resume:=__oteleq_gate_filepath.Join(root,"start.resume")
 if _,err=__oteleq_gate_os.Lstat(resume);!__oteleq_gate_os.IsNotExist(err){panic("Go host release already exists")}
 message:=__oteleq_gate_fmt.Sprintf("{\"schema_version\":1,\"kind\":\"oteleq.go.ready\",\"token\":%q,\"pid\":%d,\"parent_pid\":%d}\n",token,__oteleq_gate_os.Getpid(),__oteleq_gate_os.Getppid())
 temporary:=__oteleq_gate_filepath.Join(root,"start.tmp")
 file,err:=__oteleq_gate_os.OpenFile(temporary,__oteleq_gate_os.O_WRONLY|__oteleq_gate_os.O_CREATE|__oteleq_gate_os.O_EXCL,0600)
 if err!=nil {panic(err)}
 _,writeErr:=file.WriteString(message)
 closeErr:=file.Close()
 if writeErr!=nil {panic(writeErr)}
 if closeErr!=nil {panic(closeErr)}
 if err=__oteleq_gate_os.Link(temporary,__oteleq_gate_filepath.Join(root,"start.ready"));err!=nil {panic(err)}
 // Keep both links for the retained audit. Unlinking changes the shared inode's ctime.
 expected:=token+" release\n"
 deadline:=__oteleq_gate_time.Now().Add(__oteleq_gate_time.Duration(budget)*__oteleq_gate_time.Millisecond)
 for {
  if __oteleq_gate_time.Now().After(deadline){panic("Go host did not release the worker")}
  input,openErr:=__oteleq_gate_os.OpenFile(resume,__oteleq_gate_os.O_RDONLY|__oteleq_gate_syscall.O_NOFOLLOW|__oteleq_gate_syscall.O_NONBLOCK,0)
  if __oteleq_gate_os.IsNotExist(openErr){__oteleq_gate_time.Sleep(__oteleq_gate_time.Millisecond);continue}
  if openErr!=nil {panic(openErr)}
  stat,statErr:=input.Stat()
  if statErr!=nil {input.Close();panic(statErr)}
  native:=stat.Sys().(*__oteleq_gate_syscall.Stat_t)
  if !stat.Mode().IsRegular() || stat.Mode().Perm()!=0600 || native.Uid!=uint32(__oteleq_gate_os.Getuid()) || native.Nlink!=2 || stat.Size()!=int64(len(expected)){input.Close();panic("unsafe Go host release")}
  data:=make([]byte,len(expected)+1)
  n,readErr:=input.Read(data)
  after,afterErr:=input.Stat()
  current,currentErr:=__oteleq_gate_os.Lstat(resume)
  closeErr:=input.Close()
  if readErr!=nil || afterErr!=nil || currentErr!=nil || closeErr!=nil || n!=len(expected) || string(data[:n])!=expected || !__oteleq_gate_os.SameFile(stat,after) || !__oteleq_gate_os.SameFile(stat,current) || stat.Size()!=after.Size() || stat.ModTime()!=after.ModTime(){panic("invalid Go host release")}
  return
 }
}
'''


def enabled(entry: dict) -> bool:
    return entry.get("go_backend") == "source-v1"


def statement(entry: dict) -> str:
    return "__oteleq_gate.AwaitHost();" if enabled(entry) else ""


def imports(entry: dict) -> str:
    """Keep all helper builtins outside the application's lexical package."""
    if not enabled(entry):
        return ""
    module = go_project.module_import(entry["go_context"])
    return "\nimport __oteleq_gate " + json.dumps(module + "/" + go_project.CONTROL_DIRECTORY) + "\n"


def materialise(project: Path, context: dict) -> Path:
    """Create one private package, never add builtin calls to application scope."""
    go_project.module_import(context)
    directory = project / context["module_root"] / go_project.CONTROL_DIRECTORY
    directory.mkdir()
    path = directory / HELPER
    with path.open("x") as output:
        output.write("// Generated observer boilerplate is MIT licensed.\npackage oteleqcontrol\n" + SOURCE)
    return path
