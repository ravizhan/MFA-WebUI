//go:build windows

package filelock

import (
	"errors"
	"fmt"
	"os"
	"syscall"

	"golang.org/x/sys/windows"
)

// Windows lock region: offset 0, length 1 (interop with Python ctypes LockFileEx).
const (
	lockOffsetLow  = 0
	lockOffsetHigh = 0
	lockLengthLow  = 1
	lockLengthHigh = 0
)

// platformState holds the Windows HANDLE for the open lock file.
// Handles created without inheritable SECURITY_ATTRIBUTES are non-inheritable.
type platformState struct {
	handle windows.Handle
}

func openPlatform(path string) (*Lock, error) {
	pathPtr, err := windows.UTF16PtrFromString(path)
	if err != nil {
		return nil, fmt.Errorf("filelock: path utf16: %w", err)
	}

	// Match Python process_lock.py CreateFileW flags exactly.
	// sa == nil → non-inheritable handle (Windows default).
	access := uint32(windows.GENERIC_READ | windows.GENERIC_WRITE)
	share := uint32(windows.FILE_SHARE_READ | windows.FILE_SHARE_WRITE | windows.FILE_SHARE_DELETE)
	creation := uint32(windows.OPEN_ALWAYS)
	attrs := uint32(windows.FILE_ATTRIBUTE_NORMAL)

	h, err := windows.CreateFile(
		pathPtr,
		access,
		share,
		nil, // non-inheritable
		creation,
		attrs,
		0,
	)
	if err != nil {
		if errors.Is(err, windows.ERROR_ACCESS_DENIED) {
			return nil, fmt.Errorf("%w: CreateFile %s: %v", ErrPermission, path, err)
		}
		return nil, fmt.Errorf("filelock: CreateFile %s: %w", path, err)
	}
	if h == windows.InvalidHandle {
		return nil, fmt.Errorf("filelock: CreateFile %s: invalid handle", path)
	}

	return &Lock{
		path: path,
		plat: platformState{handle: h},
	}, nil
}

func (l *Lock) applySharedMode() error {
	// Windows: lock files inherit the app-root/config DACL from CreateFile.
	if l.plat.handle == 0 || l.plat.handle == windows.InvalidHandle {
		return fmt.Errorf("%w: invalid handle for %s", ErrPermission, l.path)
	}
	if _, err := os.Stat(l.path); err != nil {
		return fmt.Errorf("filelock: lock file missing after open: %w", err)
	}
	return nil
}

func (l *Lock) tryLockPlatform() error {
	var ov windows.Overlapped
	ov.Offset = lockOffsetLow
	ov.OffsetHigh = lockOffsetHigh

	flags := uint32(windows.LOCKFILE_EXCLUSIVE_LOCK | windows.LOCKFILE_FAIL_IMMEDIATELY)
	err := windows.LockFileEx(
		l.plat.handle,
		flags,
		0,
		lockLengthLow,
		lockLengthHigh,
		&ov,
	)
	if err == nil {
		return nil
	}
	if errors.Is(err, windows.ERROR_LOCK_VIOLATION) || errors.Is(err, windows.ERROR_IO_PENDING) {
		return ErrBusy
	}
	if errno, ok := err.(syscall.Errno); ok {
		switch errno {
		case windows.ERROR_LOCK_VIOLATION, windows.ERROR_IO_PENDING:
			return ErrBusy
		case windows.ERROR_ACCESS_DENIED:
			return fmt.Errorf("%w: LockFileEx: %v", ErrPermission, err)
		}
	}
	if errors.Is(err, windows.ERROR_ACCESS_DENIED) {
		return fmt.Errorf("%w: LockFileEx: %v", ErrPermission, err)
	}
	return fmt.Errorf("filelock: LockFileEx: %w", err)
}

func (l *Lock) unlockPlatform() error {
	var ov windows.Overlapped
	ov.Offset = lockOffsetLow
	ov.OffsetHigh = lockOffsetHigh
	err := windows.UnlockFileEx(
		l.plat.handle,
		0,
		lockLengthLow,
		lockLengthHigh,
		&ov,
	)
	if err != nil {
		return fmt.Errorf("filelock: UnlockFileEx: %w", err)
	}
	return nil
}

func (l *Lock) closePlatform() error {
	if l.plat.handle == 0 || l.plat.handle == windows.InvalidHandle {
		return nil
	}
	err := windows.CloseHandle(l.plat.handle)
	l.plat.handle = 0
	if err != nil {
		return fmt.Errorf("filelock: CloseHandle: %w", err)
	}
	return nil
}

// applyLockDirMode on Windows relies on DACL inheritance from app-root/config.
// No world-writable chmod; fail closed only if the directory is inaccessible.
func applyLockDirMode(dir string) error {
	if _, err := os.Stat(dir); err != nil {
		return fmt.Errorf("filelock: lock dir inaccessible: %w", err)
	}
	return nil
}

// applyConfigDirMode ensures config/ exists and is accessible (DACL inheritance).
func applyConfigDirMode(dir string) error {
	if _, err := os.Stat(dir); err != nil {
		return fmt.Errorf("%w: config dir inaccessible: %v", ErrPermission, err)
	}
	return nil
}
