// Command lockhelper is a test-only interoperability helper for proving that
// Python (services/process_lock.py) and Go (internal/filelock) see the same
// kernel advisory locks.
//
// It is NOT part of the release updater binary. Build explicitly:
//
//	cd updater && go build -o lockhelper.exe ./cmd/lockhelper
//
// Python tests can invoke the binary (or `go run ./cmd/lockhelper`) without
// linking it into the production updater.
//
// IMPORTANT: try/hold operate on the given -path only. They call filelock.Open
// which never chmods existing parent directories. Prefer paths under a directory
// already prepared by EnsureLockDir / Python lock_paths (config/locks).
//
// # Invocation contract
//
//	lockhelper try -path <file>
//	  Nonblocking exclusive try. Exit 0 if acquired (then released),
//	  exit 2 if busy, exit 1 on permission/protocol error.
//	  Prints one line: "acquired" | "busy" | "error: ..."
//
//	lockhelper hold -path <file> [-seconds N]
//	  Acquire with default 30s retry, print "held", keep lock until:
//	    - N seconds elapse (if -seconds > 0), or
//	    - stdin reaches EOF (parent closed the pipe), or
//	    - process is killed (kernel releases lock).
//	  Then print "released" and exit 0. Exit 1 on acquire failure, 2 on busy/timeout.
//
//	lockhelper paths -app-root <dir>
//	  Print absolute update.lock and runtime.lock paths (one per line).
//	  Uses ResolveInstallRoot(app-root) — same single-root contract as the updater.
//	  Exit 0.
//
// Exit codes are stable for Python assertions:
//
//	0 success / free-and-acquired
//	1 hard error (permission/protocol/usage)
//	2 busy or acquire timeout
//
// # Python interop sketch (tests only)
//
//	import subprocess
//	from pathlib import Path
//	from services.process_lock import AdvisoryFileLock, lock_paths
//
//	helper = Path("updater/lockhelper.exe")  # built artifact
//	app_root = Path(tmp_path)
//	runtime, update = lock_paths(app_root)
//	# Ensure parent exists without world-chmod from helper:
//	update.parent.mkdir(parents=True, exist_ok=True)
//
//	# Go holds update.lock; Python must observe busy.
//	proc = subprocess.Popen(
//	    [str(helper), "hold", "-path", str(update), "-seconds", "10"],
//	    stdout=subprocess.PIPE, text=True,
//	)
//	assert proc.stdout.readline().strip() == "held"
//	py = AdvisoryFileLock(update)
//	try:
//	    py.acquire(timeout_seconds=0)  # nonblocking
//	    raise AssertionError("expected busy")
//	except Exception as e:
//	    assert e.__class__.__name__ == "LockBusyError"
//	proc.wait(timeout=15)
//
//	# Python holds; Go try must exit 2.
//	lk = AdvisoryFileLock(runtime)
//	lk.acquire(timeout_seconds=1)
//	try:
//	    r = subprocess.run([str(helper), "try", "-path", str(runtime)], capture_output=True, text=True)
//	    assert r.returncode == 2
//	    assert "busy" in r.stdout
//	finally:
//	    lk.release()
package main

import (
	"bufio"
	"errors"
	"flag"
	"fmt"
	"os"
	"time"

	"github.com/ravizhan/MWU/updater/internal/filelock"
)

func main() {
	os.Exit(run(os.Args[1:]))
}

func run(args []string) int {
	if len(args) < 1 {
		fmt.Fprintln(os.Stderr, "usage: lockhelper <try|hold|paths> [flags]")
		return 1
	}
	cmd := args[0]
	switch cmd {
	case "try":
		return cmdTry(args[1:])
	case "hold":
		return cmdHold(args[1:])
	case "paths":
		return cmdPaths(args[1:])
	default:
		fmt.Fprintf(os.Stderr, "unknown command %q\n", cmd)
		return 1
	}
}

func cmdTry(args []string) int {
	fs := flag.NewFlagSet("try", flag.ContinueOnError)
	path := fs.String("path", "", "lock file path (no parent chmod)")
	if err := fs.Parse(args); err != nil {
		return 1
	}
	if *path == "" {
		fmt.Fprintln(os.Stderr, "try: -path required")
		return 1
	}
	// Open never chmods existing parents — safe for arbitrary test paths.
	l, err := filelock.Open(*path)
	if err != nil {
		fmt.Printf("error: %v\n", err)
		return 1
	}
	defer l.Close()
	if err := l.TryLock(); err != nil {
		if errors.Is(err, filelock.ErrBusy) {
			fmt.Println("busy")
			return 2
		}
		fmt.Printf("error: %v\n", err)
		return 1
	}
	fmt.Println("acquired")
	return 0
}

func cmdHold(args []string) int {
	fs := flag.NewFlagSet("hold", flag.ContinueOnError)
	path := fs.String("path", "", "lock file path (no parent chmod)")
	seconds := fs.Float64("seconds", 0, "hold duration; 0 = until stdin EOF")
	timeout := fs.Duration("timeout", filelock.DefaultTimeout, "acquire timeout")
	if err := fs.Parse(args); err != nil {
		return 1
	}
	if *path == "" {
		fmt.Fprintln(os.Stderr, "hold: -path required")
		return 1
	}

	// Acquire → Open (no parent chmod) + TryLock retries.
	l, err := filelock.Acquire(*path, *timeout, filelock.DefaultRetryInterval)
	if err != nil {
		if errors.Is(err, filelock.ErrTimeout) || errors.Is(err, filelock.ErrBusy) {
			fmt.Printf("error: %v\n", err)
			return 2
		}
		fmt.Printf("error: %v\n", err)
		return 1
	}
	defer l.Close()

	fmt.Println("held")
	_ = os.Stdout.Sync()

	if *seconds > 0 {
		time.Sleep(time.Duration(*seconds * float64(time.Second)))
	} else {
		scanner := bufio.NewScanner(os.Stdin)
		for scanner.Scan() {
		}
	}

	if err := l.Unlock(); err != nil {
		fmt.Printf("error: unlock: %v\n", err)
		return 1
	}
	fmt.Println("released")
	return 0
}

func cmdPaths(args []string) int {
	fs := flag.NewFlagSet("paths", flag.ContinueOnError)
	appRoot := fs.String("app-root", "", "application/install root")
	if err := fs.Parse(args); err != nil {
		return 1
	}
	if *appRoot == "" {
		fmt.Fprintln(os.Stderr, "paths: -app-root required")
		return 1
	}
	// Single-root contract: ResolveInstallRoot(workingDir) — no MWU_APP_ROOT.
	root, err := filelock.ResolveInstallRoot(*appRoot, "")
	if err != nil {
		fmt.Printf("error: %v\n", err)
		return 1
	}
	fmt.Println(filelock.UpdateLockPath(root))
	fmt.Println(filelock.RuntimeLockPath(root))
	return 0
}
