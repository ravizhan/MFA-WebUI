package main_test

import (
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"
)

// TestLockhelperTryHoldInterop builds the test-only helper and verifies try/hold
// exit codes (0/1/2) used by Python interop.
func TestLockhelperTryHoldInterop(t *testing.T) {
	if testing.Short() {
		t.Skip("builds helper binary")
	}
	tmp := t.TempDir()
	helper := filepath.Join(tmp, "lockhelper")
	if runtime.GOOS == "windows" {
		helper += ".exe"
	}
	build := exec.Command("go", "build", "-o", helper, "./cmd/lockhelper")
	build.Dir = mustUpdaterDir(t)
	if out, err := build.CombinedOutput(); err != nil {
		t.Fatalf("build lockhelper: %v\n%s", err, out)
	}

	parent := filepath.Join(tmp, "parent")
	if err := os.MkdirAll(parent, 0o755); err != nil {
		t.Fatal(err)
	}
	lockPath := filepath.Join(parent, "t.lock")

	// try on free lock → acquired (0)
	out, err := exec.Command(helper, "try", "-path", lockPath).CombinedOutput()
	if err != nil {
		t.Fatalf("try free: %v\n%s", err, out)
	}
	if !strings.Contains(string(out), "acquired") {
		t.Fatalf("try out=%s", out)
	}

	// hold then try → busy (2)
	hold := exec.Command(helper, "hold", "-path", lockPath, "-seconds", "2")
	holdOut, err := hold.StdoutPipe()
	if err != nil {
		t.Fatal(err)
	}
	if err := hold.Start(); err != nil {
		t.Fatal(err)
	}
	buf := make([]byte, 64)
	n, _ := holdOut.Read(buf)
	if !strings.Contains(string(buf[:n]), "held") {
		_ = hold.Process.Kill()
		t.Fatalf("hold did not signal held: %q", buf[:n])
	}
	tryBusy := exec.Command(helper, "try", "-path", lockPath)
	bout, err := tryBusy.CombinedOutput()
	if err == nil {
		_ = hold.Process.Kill()
		t.Fatalf("expected busy, got success: %s", bout)
	}
	if !strings.Contains(string(bout), "busy") {
		_ = hold.Process.Kill()
		t.Fatalf("expected busy output, got %s err=%v", bout, err)
	}
	done := make(chan error, 1)
	go func() { done <- hold.Wait() }()
	select {
	case <-done:
	case <-time.After(5 * time.Second):
		_ = hold.Process.Kill()
		t.Fatal("hold did not exit")
	}

	// paths subcommand
	root := t.TempDir()
	pout, err := exec.Command(helper, "paths", "-app-root", root).CombinedOutput()
	if err != nil {
		t.Fatalf("paths: %v\n%s", err, pout)
	}
	lines := strings.Split(strings.TrimSpace(string(pout)), "\n")
	if len(lines) != 2 || !strings.HasSuffix(lines[0], "update.lock") || !strings.HasSuffix(lines[1], "runtime.lock") {
		t.Fatalf("paths out=%q", pout)
	}
}

func mustUpdaterDir(t *testing.T) string {
	t.Helper()
	wd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(wd, "cmd", "lockhelper")); err == nil {
		return wd
	}
	if _, err := os.Stat(filepath.Join(wd, "..", "cmd", "lockhelper")); err == nil {
		return filepath.Clean(filepath.Join(wd, ".."))
	}
	t.Fatalf("cannot locate updater module from %s", wd)
	return ""
}
