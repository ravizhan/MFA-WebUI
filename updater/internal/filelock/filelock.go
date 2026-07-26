// Package filelock provides a cross-platform exclusive advisory lock
// interoperable with MWU's Python runtime locks (services/process_lock.py).
//
// Canonical paths under app root:
//
//	config/locks/update.lock
//	config/locks/runtime.lock
//
// Stable lock files are never deleted on unlock. Implementation delegates to
// github.com/gofrs/flock, which uses POSIX whole-file flock and Windows
// LockFileEx on offset 0 length 1 — the same kernel primitives as the previous
// hand-rolled platform backends and as Python process_lock.py.
package filelock

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"time"

	"github.com/gofrs/flock"
)

const (
	// RelativeLockDir is the app-root-relative directory for coordination locks.
	RelativeLockDir = "config/locks"
	// UpdateLockName is the updater exclusive coordination lock file name.
	UpdateLockName = "update.lock"
	// RuntimeLockName is the MWU process lifetime lock file name.
	RuntimeLockName = "runtime.lock"

	// lockFileMode is the create mode for stable lock files (POSIX open only).
	lockFileMode = 0o666
	// dirMode is used for MkdirAll of missing parents / lock directory.
	dirMode = 0o755

	// DefaultRetryInterval is the pause between nonblocking lock attempts.
	DefaultRetryInterval = 100 * time.Millisecond
	// DefaultTimeout is the bounded wait used by the updater for both locks.
	DefaultTimeout = 30 * time.Second
)

// ErrBusy is returned when a nonblocking exclusive lock attempt finds the lock held.
var ErrBusy = errors.New("filelock: lock is busy")

// ErrTimeout is returned when Acquire exhausts its deadline.
var ErrTimeout = errors.New("filelock: acquire timed out")

// Lock is an open handle to a stable lock file that may hold an exclusive advisory lock.
// Closing releases any held lock but never deletes the lock file.
type Lock struct {
	path   string
	locked bool
	fl     *flock.Flock
}

// Locked reports whether this handle currently holds the exclusive lock.
func (l *Lock) Locked() bool {
	return l != nil && l.locked
}

// LockDir returns config/locks under appRoot.
func LockDir(appRoot string) string {
	return filepath.Join(appRoot, RelativeLockDir)
}

// UpdateLockPath returns the absolute path of update.lock under appRoot.
func UpdateLockPath(appRoot string) string {
	return filepath.Join(LockDir(appRoot), UpdateLockName)
}

// RuntimeLockPath returns the absolute path of runtime.lock under appRoot.
func RuntimeLockPath(appRoot string) string {
	return filepath.Join(LockDir(appRoot), RuntimeLockName)
}

// Open creates or opens a stable lock file without truncating and without locking.
// Missing parent directories are created with 0755; existing parents are never chmod'd.
// The lock file is created eagerly so observers (including Python process_lock.py)
// always see a stable path; the exclusive lock itself is taken lazily by TryLock.
// Open never holds the lock, so no concurrent observer sees a transient busy state
// and there is no probe-unlock-to-acquire steal window.
func Open(path string) (*Lock, error) {
	if path == "" {
		return nil, errors.New("filelock: empty path")
	}
	abs, err := filepath.Abs(path)
	if err != nil {
		return nil, fmt.Errorf("filelock: abs path: %w", err)
	}
	parent := filepath.Dir(abs)
	if err := ensureParentExists(parent); err != nil {
		return nil, err
	}
	// Create/open the stable lock file without locking. flock.New does not touch
	// the filesystem; without this the file would not exist until TryLock opened
	// it lazily. Opening here (no lock taken) preserves Open's "creates or opens"
	// contract without the transient lock and steal window the old probe had.
	f, err := os.OpenFile(abs, os.O_RDWR|os.O_CREATE, lockFileMode)
	if err != nil {
		return nil, fmt.Errorf("filelock: open %s: %w", abs, err)
	}
	_ = f.Close()
	fl := flock.New(abs,
		// os.OpenFile always applies O_CLOEXEC on supported platforms.
		flock.SetFlag(os.O_RDWR|os.O_CREATE),
		flock.SetPermissions(fs.FileMode(lockFileMode)),
	)
	return &Lock{
		path: abs,
		fl:   fl,
	}, nil
}

// ensureParentExists creates missing parents with 0755 and never chmods existing dirs.
func ensureParentExists(parent string) error {
	st, err := os.Stat(parent)
	if err == nil {
		if !st.IsDir() {
			return fmt.Errorf("filelock: parent is not a directory: %s", parent)
		}
		return nil
	}
	if !os.IsNotExist(err) {
		return fmt.Errorf("filelock: parent stat: %w", err)
	}
	if err := os.MkdirAll(parent, dirMode); err != nil {
		return fmt.Errorf("filelock: parent dir: %w", err)
	}
	return nil
}

// TryLock attempts a nonblocking exclusive lock.
// Returns ErrBusy if another process holds the lock.
// Non-busy errors fail closed and are never treated as busy.
func (l *Lock) TryLock() error {
	if l == nil {
		return errors.New("filelock: nil lock")
	}
	if l.locked {
		return nil
	}
	ok, err := l.fl.TryLock()
	if err != nil {
		return fmt.Errorf("filelock: flock: %w", err)
	}
	if !ok {
		return ErrBusy
	}
	l.locked = true
	return nil
}

// Unlock releases the exclusive lock. The lock file is never deleted.
func (l *Lock) Unlock() error {
	if l == nil {
		return errors.New("filelock: nil lock")
	}
	if !l.locked {
		return nil
	}
	if err := l.fl.Unlock(); err != nil {
		return fmt.Errorf("filelock: flock unlock: %w", err)
	}
	l.locked = false
	return nil
}

// Close unlocks (if held) and closes the underlying handle/fd.
// The stable lock file is never deleted.
func (l *Lock) Close() error {
	if l == nil {
		return nil
	}
	var first error
	if l.locked {
		if err := l.Unlock(); err != nil {
			first = err
		}
	}
	// gofrs Close() == Unlock(); safe and idempotent when already unlocked.
	if err := l.fl.Close(); err != nil && first == nil {
		first = fmt.Errorf("filelock: close: %w", err)
	}
	return first
}

// Acquire opens path and acquires an exclusive lock with bounded nonblocking retries.
// On failure the handle is closed. Non-busy errors fail immediately (no retry).
func Acquire(path string, timeout, interval time.Duration) (*Lock, error) {
	if timeout <= 0 {
		timeout = DefaultTimeout
	}
	if interval <= 0 {
		interval = DefaultRetryInterval
	}

	l, err := Open(path)
	if err != nil {
		return nil, err
	}

	deadline := time.Now().Add(timeout)
	for {
		err := l.TryLock()
		if err == nil {
			return l, nil
		}
		if !errors.Is(err, ErrBusy) {
			_ = l.Close()
			return nil, err
		}
		if !time.Now().Before(deadline) {
			_ = l.Close()
			return nil, fmt.Errorf("%w: %s", ErrTimeout, path)
		}
		time.Sleep(interval)
	}
}

// AcquireUpdateLock acquires update.lock under appRoot.
// The lock directory is created on demand by Open.
func AcquireUpdateLock(appRoot string, timeout, interval time.Duration) (*Lock, error) {
	return Acquire(UpdateLockPath(appRoot), timeout, interval)
}

// AcquireRuntimeLock acquires runtime.lock under appRoot.
// The lock directory is created on demand by Open.
func AcquireRuntimeLock(appRoot string, timeout, interval time.Duration) (*Lock, error) {
	return Acquire(RuntimeLockPath(appRoot), timeout, interval)
}

// ResolveInstallRoot returns the single absolute install root used for BOTH lock
// coordination and file mutation. Preference:
//  1. workingDir when provided (updater contract: cwd = install dir)
//  2. directory containing the updater executable
//
// There is no separate env override: production must not coordinate one root and
// mutate another. User home is never used.
func ResolveInstallRoot(workingDir, exePath string) (string, error) {
	if workingDir != "" {
		abs, err := filepath.Abs(workingDir)
		if err != nil {
			return "", fmt.Errorf("filelock: working dir: %w", err)
		}
		return filepath.Clean(abs), nil
	}

	if exePath == "" {
		var err error
		exePath, err = os.Executable()
		if err != nil {
			return "", fmt.Errorf("filelock: executable: %w", err)
		}
	}
	if resolved, err := filepath.EvalSymlinks(exePath); err == nil {
		exePath = resolved
	}
	abs, err := filepath.Abs(exePath)
	if err != nil {
		return "", fmt.Errorf("filelock: exe abs: %w", err)
	}
	return filepath.Clean(filepath.Dir(abs)), nil
}
