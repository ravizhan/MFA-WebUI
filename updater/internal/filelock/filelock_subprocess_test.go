package filelock_test

import (
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"testing"
	"time"

	"github.com/ravizhan/MWU/updater/internal/filelock"
)

// TestCrashReleaseSubprocess verifies that when a child process exits while
// holding a lock, the kernel releases it and a parent can acquire afterwards.
func TestCrashReleaseSubprocess(t *testing.T) {
	if testing.Short() {
		t.Skip("subprocess test")
	}
	dir := t.TempDir()
	path := filepath.Join(dir, "crash.lock")

	// Child: acquire lock, signal ready on stdout, then exit without Unlock
	// (os.Exit skips defers — kernel still releases on process death).
	helper := os.Getenv("FILELOCK_CRASH_HELPER")
	if helper == "1" {
		l, err := filelock.Acquire(os.Getenv("FILELOCK_CRASH_PATH"), 2*time.Second, 20*time.Millisecond)
		if err != nil {
			os.Stderr.WriteString(err.Error())
			os.Exit(2)
		}
		// Intentionally do not Close/Unlock; write ready then hard-exit.
		os.Stdout.WriteString("ready\n")
		os.Stdout.Sync()
		// Keep handle alive until process death.
		_ = l
		os.Exit(0)
	}

	cmd := exec.Command(os.Args[0], "-test.run=TestCrashReleaseSubprocess", "-test.v")
	cmd.Env = append(os.Environ(),
		"FILELOCK_CRASH_HELPER=1",
		"FILELOCK_CRASH_PATH="+path,
	)
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("helper failed: %v\n%s", err, out)
	}
	// Parent should now acquire (kernel released on child exit).
	l, err := filelock.Acquire(path, 2*time.Second, 20*time.Millisecond)
	if err != nil {
		t.Fatalf("parent acquire after crash: %v\nhelper out: %s", err, out)
	}
	l.Close()
}

// TestSubprocessContention proves two OS processes see the same exclusive lock.
func TestSubprocessContention(t *testing.T) {
	if testing.Short() {
		t.Skip("subprocess test")
	}
	dir := t.TempDir()
	path := filepath.Join(dir, "proc.lock")

	if os.Getenv("FILELOCK_HOLD_HELPER") == "1" {
		l, err := filelock.Acquire(os.Getenv("FILELOCK_HOLD_PATH"), 2*time.Second, 20*time.Millisecond)
		if err != nil {
			os.Stderr.WriteString(err.Error())
			os.Exit(2)
		}
		os.Stdout.WriteString("held\n")
		os.Stdout.Sync()
		// Hold until parent kills us or we see release signal file.
		deadline := time.Now().Add(10 * time.Second)
		signal := os.Getenv("FILELOCK_RELEASE_SIGNAL")
		for time.Now().Before(deadline) {
			if _, err := os.Stat(signal); err == nil {
				l.Close()
				os.Exit(0)
			}
			time.Sleep(20 * time.Millisecond)
		}
		l.Close()
		os.Exit(0)
	}

	signal := filepath.Join(dir, "release")
	cmd := exec.Command(os.Args[0], "-test.run=TestSubprocessContention")
	cmd.Env = append(os.Environ(),
		"FILELOCK_HOLD_HELPER=1",
		"FILELOCK_HOLD_PATH="+path,
		"FILELOCK_RELEASE_SIGNAL="+signal,
	)
	if err := cmd.Start(); err != nil {
		t.Fatalf("start helper: %v", err)
	}
	defer func() {
		_ = os.WriteFile(signal, []byte("1"), 0o644)
		_, _ = cmd.Process.Wait()
	}()

	// Wait until child holds the lock.
	deadline := time.Now().Add(5 * time.Second)
	var busy error
	for time.Now().Before(deadline) {
		l, err := filelock.Open(path)
		if err != nil {
			time.Sleep(20 * time.Millisecond)
			continue
		}
		busy = l.TryLock()
		l.Close()
		if errors.Is(busy, filelock.ErrBusy) {
			break
		}
		time.Sleep(20 * time.Millisecond)
	}
	if !errors.Is(busy, filelock.ErrBusy) {
		t.Fatalf("expected child to hold lock, last err=%v (GOOS=%s)", busy, runtime.GOOS)
	}

	// Release child and acquire.
	if err := os.WriteFile(signal, []byte("1"), 0o644); err != nil {
		t.Fatal(err)
	}
	_, _ = cmd.Process.Wait()

	l, err := filelock.Acquire(path, 2*time.Second, 20*time.Millisecond)
	if err != nil {
		t.Fatalf("acquire after child release: %v", err)
	}
	l.Close()
}
