//go:build unix

package filelock

import (
	"errors"
	"fmt"
	"syscall"

	"golang.org/x/sys/unix"
)

// platformState holds the POSIX file descriptor for the open lock file.
type platformState struct {
	fd int
}

func openPlatform(path string) (*Lock, error) {
	// O_RDWR|O_CREAT|O_CLOEXEC, never truncate — stable lock file; fd does not
	// survive exec. Mode 0666 is create-mode only (subject to umask); no post-open chmod.
	fd, err := unix.Open(path, unix.O_RDWR|unix.O_CREAT|unix.O_CLOEXEC, lockFileMode)
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

func isBusyErrno(err error) bool {
	if err == nil {
		return false
	}
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
