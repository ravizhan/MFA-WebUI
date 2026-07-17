// Package filelock provides a cross-platform exclusive advisory lock
// interoperable with MWU's Python runtime locks (services/process_lock.py).
//
// Canonical paths under app root:
//
//	config/locks/update.lock
//	config/locks/runtime.lock
//
// Stable lock files are never deleted on unlock. POSIX uses whole-file flock;
// Windows uses LockFileEx on offset 0 length 1 with shared open flags.
package filelock

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"time"
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

// ErrPermission is returned for access/permission failures (not retried as busy).
var ErrPermission = errors.New("filelock: permission denied")

// Lock is an open handle to a stable lock file that may hold an exclusive advisory lock.
// Closing releases any held lock but never deletes the lock file.
type Lock struct {
	path   string
	locked bool
	plat   platformState
}

// Path returns the absolute path of the lock file.
func (l *Lock) Path() string {
	if l == nil {
		return ""
	}
	return l.path
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

// EnsureLockDir creates config/locks under appRoot with ordinary MkdirAll(0755).
// No sticky bit, no chmod of existing directories, no mode verification.
func EnsureLockDir(appRoot string) error {
	if appRoot == "" {
		return errors.New("filelock: empty app root")
	}
	absRoot, err := filepath.Abs(appRoot)
	if err != nil {
		return fmt.Errorf("filelock: app root: %w", err)
	}
	dir := filepath.Join(absRoot, RelativeLockDir)
	if err := os.MkdirAll(dir, dirMode); err != nil {
		return fmt.Errorf("filelock: create lock dir: %w", err)
	}
	return nil
}

// Open creates or opens a stable lock file without truncating and without locking.
// Missing parent directories are created with 0755; existing parents are never chmod'd.
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
	return openPlatform(abs)
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
// Permission errors fail closed and are never treated as busy.
func (l *Lock) TryLock() error {
	if l == nil {
		return errors.New("filelock: nil lock")
	}
	if l.locked {
		return nil
	}
	if err := l.tryLockPlatform(); err != nil {
		return err
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
	if err := l.unlockPlatform(); err != nil {
		return err
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
	if err := l.closePlatform(); err != nil && first == nil {
		first = err
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

// AcquireUpdateLock ensures the lock dir then acquires update.lock under appRoot.
func AcquireUpdateLock(appRoot string, timeout, interval time.Duration) (*Lock, error) {
	if err := EnsureLockDir(appRoot); err != nil {
		return nil, err
	}
	return Acquire(UpdateLockPath(appRoot), timeout, interval)
}

// AcquireRuntimeLock ensures the lock dir then acquires runtime.lock under appRoot.
func AcquireRuntimeLock(appRoot string, timeout, interval time.Duration) (*Lock, error) {
	if err := EnsureLockDir(appRoot); err != nil {
		return nil, err
	}
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

// ResolveAppRoot is an alias for ResolveInstallRoot for callers that used the
// previous name. Same single-root contract; no MWU_APP_ROOT divergence.
func ResolveAppRoot(workingDir, exePath string) (string, error) {
	return ResolveInstallRoot(workingDir, exePath)
}
