package oteleqcontrol

import (
	"encoding/json"
	"os"
	"path/filepath"
	"syscall"
	"testing"
	"time"
)

func gateEnvironment(t *testing.T) string {
	t.Helper()
	root, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(root, 0700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("OTELEQ_GO_CONTROL_ROOT", root)
	t.Setenv("OTELEQ_GO_CONTROL_TOKEN", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
	t.Setenv("OTELEQ_GO_CONTROL_WAIT_MS", "1000")
	return root
}
func gateTask() chan any {
	done := make(chan any, 1)
	go func() { defer func() { done <- recover() }(); AwaitHost() }()
	return done
}
func waitGate(t *testing.T, root string, done chan any) {
	t.Helper()
	end := time.Now().Add(2 * time.Second)
	for {
		if _, err := os.Stat(filepath.Join(root, "start.ready")); err == nil {
			return
		}
		select {
		case failure := <-done:
			t.Fatalf("worker completed before release: %v", failure)
		default:
		}
		if time.Now().After(end) {
			t.Fatal("worker did not publish readiness")
		}
		time.Sleep(time.Millisecond)
	}
}
func gateResult(t *testing.T, done chan any, wantFailure bool) {
	t.Helper()
	select {
	case failure := <-done:
		if (failure != nil) != wantFailure {
			t.Fatalf("unexpected gate result: %v", failure)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("worker did not finish")
	}
}
func gateRelease(t *testing.T, root, message string, mode os.FileMode, linked bool) {
	t.Helper()
	temporary := filepath.Join(root, "start.resume.tmp")
	if err := os.WriteFile(temporary, []byte(message), mode); err != nil {
		t.Fatal(err)
	}
	if linked {
		if err := os.Link(temporary, filepath.Join(root, "start.resume")); err != nil {
			t.Fatal(err)
		}
	} else if err := os.Rename(temporary, filepath.Join(root, "start.resume")); err != nil {
		t.Fatal(err)
	}
}
func TestGoGatePausesBeforeReleaseAndRetainsStableLinks(t *testing.T) {
	root := gateEnvironment(t)
	done := gateTask()
	waitGate(t, root, done)
	data, err := os.ReadFile(filepath.Join(root, "start.ready"))
	if err != nil {
		t.Fatal(err)
	}
	var ready struct {
		Schema int    `json:"schema_version"`
		Kind   string `json:"kind"`
		Token  string `json:"token"`
		PID    int    `json:"pid"`
		Parent int    `json:"parent_pid"`
	}
	if err = json.Unmarshal(data, &ready); err != nil {
		t.Fatal(err)
	}
	if ready.Schema != 1 || ready.Kind != "oteleq.go.ready" || ready.Token != os.Getenv("OTELEQ_GO_CONTROL_TOKEN") || ready.PID != os.Getpid() || ready.Parent != os.Getppid() {
		t.Fatalf("wrong readiness: %+v", ready)
	}
	before, err := os.Stat(filepath.Join(root, "start.ready"))
	if err != nil {
		t.Fatal(err)
	}
	select {
	case result := <-done:
		t.Fatalf("target released early: %v", result)
	default:
	}
	gateRelease(t, root, ready.Token+" release\n", 0600, true)
	gateResult(t, done, false)
	after, err := os.Stat(filepath.Join(root, "start.ready"))
	if err != nil {
		t.Fatal(err)
	}
	temporary, err := os.Stat(filepath.Join(root, "start.tmp"))
	if err != nil {
		t.Fatal(err)
	}
	if !os.SameFile(before, after) || !os.SameFile(after, temporary) || after.Sys().(*syscall.Stat_t).Nlink != 2 {
		t.Fatal("readiness inode/link changed")
	}
}
func TestGoGateInvalidBindings(t *testing.T) {
	for _, row := range []struct{ key, value string }{
		{"OTELEQ_GO_CONTROL_WAIT_MS", "01"}, {"OTELEQ_GO_CONTROL_WAIT_MS", "0"}, {"OTELEQ_GO_CONTROL_WAIT_MS", "900001"},
		{"OTELEQ_GO_CONTROL_WAIT_MS", "not-a-number"}, {"OTELEQ_GO_CONTROL_ROOT", "relative"},
		{"OTELEQ_GO_CONTROL_TOKEN", "a"}, {"OTELEQ_GO_CONTROL_TOKEN", "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"},
	} {
		t.Run(row.key+row.value, func(t *testing.T) { gateEnvironment(t); t.Setenv(row.key, row.value); gateResult(t, gateTask(), true) })
	}
	t.Run("root-mode", func(t *testing.T) { root := gateEnvironment(t); os.Chmod(root, 0755); gateResult(t, gateTask(), true) })
	t.Run("root-alias", func(t *testing.T) {
		root := gateEnvironment(t)
		alias := filepath.Join(t.TempDir(), "alias")
		if err := os.Symlink(root, alias); err != nil {
			t.Fatal(err)
		}
		t.Setenv("OTELEQ_GO_CONTROL_ROOT", alias)
		gateResult(t, gateTask(), true)
	})
}
func TestGoGateRefusesExistingPublicationsAndEarlyRelease(t *testing.T) {
	for _, name := range []string{"start.tmp", "start.ready", "start.resume"} {
		t.Run(name, func(t *testing.T) {
			root := gateEnvironment(t)
			if err := os.WriteFile(filepath.Join(root, name), []byte("stale"), 0600); err != nil {
				t.Fatal(err)
			}
			gateResult(t, gateTask(), true)
		})
	}
}
func TestGoGateRejectsUnsafeOrSubstitutedRelease(t *testing.T) {
	for _, name := range []string{"wrong-token", "wrong-mode", "single-link", "symlink", "fifo"} {
		t.Run(name, func(t *testing.T) {
			root := gateEnvironment(t)
			done := gateTask()
			waitGate(t, root, done)
			message := os.Getenv("OTELEQ_GO_CONTROL_TOKEN") + " release\n"
			switch name {
			case "wrong-token":
				gateRelease(t, root, "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb release\n", 0600, true)
			case "wrong-mode":
				gateRelease(t, root, message, 0644, true)
			case "single-link":
				gateRelease(t, root, message, 0600, false)
			case "symlink":
				target := filepath.Join(root, "other")
				os.WriteFile(target, []byte(message), 0600)
				if err := os.Symlink(target, filepath.Join(root, "start.resume")); err != nil {
					t.Fatal(err)
				}
			case "fifo":
				if err := syscall.Mkfifo(filepath.Join(root, "start.resume"), 0600); err != nil {
					t.Fatal(err)
				}
			}
			gateResult(t, done, true)
		})
	}
}
func TestGoGateHasItsOwnBoundedWait(t *testing.T) {
	gateEnvironment(t)
	os.Setenv("OTELEQ_GO_CONTROL_WAIT_MS", "1")
	gateResult(t, gateTask(), true)
}
