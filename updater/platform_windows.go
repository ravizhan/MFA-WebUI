//go:build windows

package main

import (
	"fmt"
	"os"
	"os/exec"
	"syscall"
	"unsafe"

	"golang.org/x/sys/windows"
)

// replaceFile atomically replaces dst with src (same volume). Uses MoveFileEx
// with MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH so destination is
// never removed first and the rename is durable.
func replaceFile(src, dst string) error {
	from, err := windows.UTF16PtrFromString(src)
	if err != nil {
		return err
	}
	to, err := windows.UTF16PtrFromString(dst)
	if err != nil {
		return err
	}
	flags := uint32(windows.MOVEFILE_REPLACE_EXISTING | windows.MOVEFILE_WRITE_THROUGH)
	if err := windows.MoveFileEx(from, to, flags); err != nil {
		return fmt.Errorf("MoveFileEx replace: %w", err)
	}
	return nil
}

// replaceFileWithBackup swaps newPath into targetPath, moving the previous
// target to backupPath when present. Prefer ReplaceFileW for atomic backup
// semantics; fall back to MoveFileEx/Rename chain.
func replaceFileWithBackup(newPath, targetPath, backupPath string) error {
	if err := replaceFileW(newPath, targetPath, backupPath); err == nil {
		return nil
	}

	// Manual durable backup then replace when ReplaceFileW unavailable/fails.
	_ = os.Remove(backupPath)
	if _, err := os.Stat(targetPath); err == nil {
		if err := os.Rename(targetPath, backupPath); err != nil {
			// Try MoveFileEx if Rename fails (e.g. cross-link rare cases)
			if err2 := replaceFile(targetPath, backupPath); err2 != nil {
				return fmt.Errorf("backup current file: %w", err)
			}
		}
	}
	if err := replaceFile(newPath, targetPath); err != nil {
		if _, berr := os.Stat(backupPath); berr == nil {
			_ = replaceFile(backupPath, targetPath)
		}
		return err
	}
	return nil
}

func replaceFileW(newPath, targetPath, backupPath string) error {
	mod := windows.NewLazySystemDLL("kernel32.dll")
	proc := mod.NewProc("ReplaceFileW")
	if err := proc.Find(); err != nil {
		return err
	}
	newP, err := windows.UTF16PtrFromString(newPath)
	if err != nil {
		return err
	}
	targetP, err := windows.UTF16PtrFromString(targetPath)
	if err != nil {
		return err
	}
	var backupP *uint16
	if backupPath != "" {
		backupP, err = windows.UTF16PtrFromString(backupPath)
		if err != nil {
			return err
		}
	}
	// REPLACEFILE_WRITE_THROUGH = 0x00000001
	const REPLACEFILE_WRITE_THROUGH = 0x00000001
	r1, _, e1 := proc.Call(
		uintptr(unsafe.Pointer(targetP)),
		uintptr(unsafe.Pointer(newP)),
		uintptr(unsafe.Pointer(backupP)),
		uintptr(REPLACEFILE_WRITE_THROUGH),
		0,
		0,
	)
	if r1 == 0 {
		if e1 != nil && e1 != syscall.Errno(0) {
			return fmt.Errorf("ReplaceFileW: %w", e1)
		}
		return fmt.Errorf("ReplaceFileW failed")
	}
	return nil
}

// syncDir is a no-op success on Windows (MOVEFILE_WRITE_THROUGH covers rename durability).
func syncDir(dir string) error {
	return nil
}

// configureDetached sets Windows process creation flags so the child is not tied
// to the updater console session. Lock handles are non-inheritable (CreateFile sa=nil).
func configureDetached(cmd *exec.Cmd) error {
	cmd.SysProcAttr = &syscall.SysProcAttr{
		CreationFlags: windows.CREATE_NEW_PROCESS_GROUP | windows.DETACHED_PROCESS,
	}
	return nil
}

// installOwner is a no-op identity on Windows (DACL inheritance is the contract).
type installOwner struct{}

func captureInstallOwner(path string) (installOwner, error) {
	if _, err := os.Stat(path); err != nil {
		return installOwner{}, err
	}
	return installOwner{}, nil
}

func (o installOwner) apply(path string) error {
	return nil
}

func (o installOwner) applyTree(root string) error {
	return nil
}

func ensureCrossAccountFileMode(path string, mode os.FileMode) error {
	if err := os.Chmod(path, mode); err != nil {
		if _, stErr := os.Stat(path); stErr != nil {
			return fmt.Errorf("chmod/stat %s: %w", path, stErr)
		}
	}
	return nil
}
