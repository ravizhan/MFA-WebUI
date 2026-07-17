// Command lockhelper is a test-only interoperability helper for proving that
// Python (services/process_lock.py) and Go (internal/filelock) see the same
// kernel advisory locks.
//
//	cd updater && go build -o lockhelper ./cmd/lockhelper
//
// Commands:
//
//	lockhelper try -path <file>
//	  Nonblocking exclusive try. Exit 0 if acquired (then released),
//	  exit 2 if busy, exit 1 on hard error.
//	  Prints: "acquired" | "busy" | "error: ..."
//
//	lockhelper hold -path <file> [-seconds N]
//	  Acquire with default 30s retry, print "held", keep lock until
//	  N seconds elapse (if -seconds > 0) or stdin EOF. Then "released".
//	  Exit 0 on success, 1 on hard error, 2 on busy/timeout.
//
//	lockhelper paths -app-root <dir>
//	  Print absolute update.lock and runtime.lock paths (one per line).
//
// Exit codes (stable for Python interop):
//
//	0 success / free-and-acquired
//	1 hard error (permission/usage)
//	2 busy or acquire timeout
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
	path := fs.String("path", "", "lock file path")
	if err := fs.Parse(args); err != nil {
		return 1
	}
	if *path == "" {
		fmt.Fprintln(os.Stderr, "try: -path required")
		return 1
	}
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
	path := fs.String("path", "", "lock file path")
	seconds := fs.Float64("seconds", 0, "hold duration; 0 = until stdin EOF")
	timeout := fs.Duration("timeout", filelock.DefaultTimeout, "acquire timeout")
	if err := fs.Parse(args); err != nil {
		return 1
	}
	if *path == "" {
		fmt.Fprintln(os.Stderr, "hold: -path required")
		return 1
	}

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
	root, err := filelock.ResolveInstallRoot(*appRoot, "")
	if err != nil {
		fmt.Printf("error: %v\n", err)
		return 1
	}
	fmt.Println(filelock.UpdateLockPath(root))
	fmt.Println(filelock.RuntimeLockPath(root))
	return 0
}
