//go:build unix

package filelock

import (
	"errors"
	"fmt"
	"os"
	"syscall"

	"golang.org/x/sys/unix"
)

// platformState holds the POSIX file descriptor for the open lock file.
type platformState struct {
	fd int
}

func openPlatform(path string) (*Lock, error) {
	// O_RDWR|O_CREATE|O_CLOEXEC, never truncate — stable lock file; fd does not
	// survive exec of restarted child/shell.
	fd, err := unix.Open(path, unix.O_RDWR|unix.O_CREAT|unix.O_CLOEXEC, LockFileMode)
	if err != nil {
		if isPermissionErrno(err) {
			return nil, fmt.Errorf("%w: open %s: %v", ErrPermission, path, err)
		}
		return nil, fmt.Errorf("filelock: open %s: %w", path, err)
	}
	return &Lock{
		path: path,
		plat: platformState{fd: fd},
	}, nil
}

func (l *Lock) applySharedMode() error {
	// Non-secret coordination files: mode 0666 for cross-account reopen. Fail closed.
	if err := unix.Fchmod(l.plat.fd, LockFileMode); err != nil {
		if err2 := os.Chmod(l.path, LockFileMode); err2 != nil {
			return fmt.Errorf("%w: chmod 0666 %s: %v", ErrPermission, l.path, err)
		}
	}
	return nil
}

func (l *Lock) tryLockPlatform() error {
	err := unix.Flock(l.plat.fd, unix.LOCK_EX|unix.LOCK_NB)
	if err == nil {
		return nil
	}
	if isBusyErrno(err) {
		return ErrBusy
	}
	if isPermissionErrno(err) {
		return fmt.Errorf("%w: flock: %v", ErrPermission, err)
	}
	return fmt.Errorf("filelock: flock: %w", err)
}

func (l *Lock) unlockPlatform() error {
	if err := unix.Flock(l.plat.fd, unix.LOCK_UN); err != nil {
		return fmt.Errorf("filelock: flock unlock: %w", err)
	}
	return nil
}

func (l *Lock) closePlatform() error {
	fd := l.plat.fd
	l.plat.fd = -1
	if fd < 0 {
		return nil
	}
	if err := unix.Close(fd); err != nil {
		return fmt.Errorf("filelock: close: %w", err)
	}
	return nil
}

// applyLockDirMode sets sticky world-writable 01777 and fails closed if chmod fails
// or the resulting mode is not sticky-writable as required.
func applyLockDirMode(dir string) error {
	if err := os.Chmod(dir, LockDirMode); err != nil {
		return fmt.Errorf("%w: chmod lock dir 01777 %s: %v", ErrPermission, dir, err)
	}
	st, err := os.Stat(dir)
	if err != nil {
		return fmt.Errorf("filelock: lock dir inaccessible: %w", err)
	}
	mode := st.Mode().Perm()
	if st.Mode()&os.ModeSticky == 0 {
		return fmt.Errorf("%w: lock dir %s missing sticky bit (mode %04o)", ErrPermission, dir, mode)
	}
	if mode&0o002 == 0 {
		return fmt.Errorf("%w: lock dir %s not world-writable (mode %04o)", ErrPermission, dir, mode)
	}
	return nil
}

// applyConfigDirMode normalizes config/ to 0755 and verifies owner+group+other
// execute (traverse) bits so a normal user can reach locks after elevated runs.
// Fail closed on chmod or verification failure.
func applyConfigDirMode(dir string) error {
	if err := os.Chmod(dir, ConfigDirMode); err != nil {
		return fmt.Errorf("%w: chmod config dir %s: %v", ErrPermission, dir, err)
	}
	st, err := os.Stat(dir)
	if err != nil {
		return fmt.Errorf("%w: config dir inaccessible: %v", ErrPermission, err)
	}
	mode := st.Mode().Perm()
	// Require owner rwx and at least other-x for traversal by non-owner accounts.
	if mode&0o100 == 0 {
		return fmt.Errorf("%w: config dir %s not owner-executable (mode %04o)", ErrPermission, dir, mode)
	}
	if mode&0o001 == 0 {
		return fmt.Errorf("%w: config dir %s not other-traversable (mode %04o)", ErrPermission, dir, mode)
	}
	// Must not be world-writable.
	if mode&0o002 != 0 {
		return fmt.Errorf("%w: config dir %s is world-writable (mode %04o)", ErrPermission, dir, mode)
	}
	return nil
}

func isBusyErrno(err error) bool {
	if err == nil {
		return false
	}
	// Prefer errors.Is against unix constants first.
	if errors.Is(err, unix.EAGAIN) {
		return true
	}
	// On platforms where EWOULDBLOCK != EAGAIN, also match EWOULDBLOCK.
	if unix.EWOULDBLOCK != unix.EAGAIN && errors.Is(err, unix.EWOULDBLOCK) {
		return true
	}
	if errno, ok := err.(syscall.Errno); ok {
		if errno == syscall.EAGAIN {
			return true
		}
		if syscall.EWOULDBLOCK != syscall.EAGAIN && errno == syscall.EWOULDBLOCK {
			return true
		}
	}
	return false
}

func isPermissionErrno(err error) bool {
	if err == nil {
		return false
	}
	if errors.Is(err, unix.EACCES) || errors.Is(err, unix.EPERM) {
		return true
	}
	if errno, ok := err.(syscall.Errno); ok {
		return errno == syscall.EACCES || errno == syscall.EPERM
	}
	return false
}
