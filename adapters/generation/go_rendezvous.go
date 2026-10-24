// Generated observer boilerplate is MIT licensed; see GENERATED-LICENSE.txt.
package oteleqcontrol

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"
)

func hostEnvironment() (string, string, int) {
	root := os.Getenv("OTELEQ_GO_CONTROL_ROOT")
	token := os.Getenv("OTELEQ_GO_CONTROL_TOKEN")
	text := os.Getenv("OTELEQ_GO_CONTROL_WAIT_MS")
	budget, err := strconv.Atoi(text)
	if err != nil || strconv.Itoa(budget) != text || budget < 1 || budget > 900000 {
		panic("invalid Go host wait budget")
	}
	real, err := filepath.EvalSymlinks(root)
	if err != nil || !filepath.IsAbs(root) || real != root {
		panic("invalid Go host root")
	}
	info, err := os.Lstat(root)
	if err != nil || !info.IsDir() || info.Mode().Perm() != 0700 || info.Sys().(*syscall.Stat_t).Uid != uint32(os.Getuid()) {
		panic("unsafe Go host root")
	}
	if len(token) != 32 {
		panic("invalid Go host token")
	}
	for _, char := range token {
		if !(char >= '0' && char <= '9' || char >= 'a' && char <= 'f') {
			panic("invalid Go host token")
		}
	}
	return root, token, budget
}

func hostMessage(kind, phase, token string) []byte {
	message := struct {
		Schema int    `json:"schema_version"`
		Kind   string `json:"kind"`
		Token  string `json:"token"`
		PID    int    `json:"pid"`
		Parent int    `json:"parent_pid"`
		Phase  string `json:"phase,omitempty"`
	}{1, kind, token, os.Getpid(), os.Getppid(), phase}
	data, err := json.Marshal(message)
	if err != nil {
		panic(err)
	}
	return append(data, '\n')
}

func hostPublish(root, name string, message []byte) {
	temporary := filepath.Join(root, name+".tmp")
	file, err := os.OpenFile(temporary, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		panic(err)
	}
	n, writeErr := file.Write(message)
	closeErr := file.Close()
	if writeErr != nil || n != len(message) || closeErr != nil {
		panic("incomplete Go host checkpoint")
	}
	if err = os.Link(temporary, filepath.Join(root, name+".ready")); err != nil {
		panic(err)
	}
	// Both links stay retained: unlinking changes the shared inode's ctime.
}

func hostResume(root, name, expected string, budget int) {
	resume := filepath.Join(root, name+".resume")
	deadline := time.Now().Add(time.Duration(budget) * time.Millisecond)
	for {
		if time.Now().After(deadline) {
			panic("Go host did not release the worker")
		}
		input, openErr := os.OpenFile(resume, os.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_NONBLOCK, 0)
		if os.IsNotExist(openErr) {
			time.Sleep(time.Millisecond)
			continue
		}
		if openErr != nil {
			panic(openErr)
		}
		stat, statErr := input.Stat()
		if statErr != nil {
			input.Close()
			panic(statErr)
		}
		native := stat.Sys().(*syscall.Stat_t)
		if !stat.Mode().IsRegular() || stat.Mode().Perm() != 0600 || native.Uid != uint32(os.Getuid()) || native.Nlink != 2 || stat.Size() != int64(len(expected)) {
			input.Close()
			panic("unsafe Go host release")
		}
		data := make([]byte, len(expected)+1)
		n, readErr := input.Read(data)
		after, afterErr := input.Stat()
		current, currentErr := os.Lstat(resume)
		closeErr := input.Close()
		if readErr != nil || afterErr != nil || currentErr != nil || closeErr != nil || n != len(expected) || string(data[:n]) != expected || !os.SameFile(stat, after) || !os.SameFile(stat, current) || stat.Size() != after.Size() || stat.ModTime() != after.ModTime() {
			panic("invalid Go host release")
		}
		return
	}
}

func hostAwait(root, name string, message []byte, expected string, budget int) {
	if _, err := os.Lstat(filepath.Join(root, name+".resume")); !os.IsNotExist(err) {
		panic("Go host release already exists")
	}
	hostPublish(root, name, message)
	hostResume(root, name, expected, budget)
}

// AwaitHost stops the worker before its factory, observations or selected calls.
func AwaitHost() {
	root, token, budget := hostEnvironment()
	hostAwait(root, "start", hostMessage("oteleq.go.ready", "", token), token+" release\n", budget)
}

// Checkpoint keeps the same native process paused at a declared call boundary.
// The host independently validates process ownership and the complete phase order.
func Checkpoint(phase string) {
	if phase != "finish" {
		kind, text, found := strings.Cut(phase, "-")
		index, err := strconv.Atoi(text)
		if !found || (kind != "before" && kind != "after") || err != nil || strconv.Itoa(index) != text || index < 0 || index >= 32 {
			panic("invalid Go host phase")
		}
	}
	root, token, budget := hostEnvironment()
	hostAwait(root, phase, hostMessage("oteleq.go.checkpoint", phase, token), token+" "+phase+"\n", budget)
}
