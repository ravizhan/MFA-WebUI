//go:build unix

package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"syscall"

	"golang.org/x/sys/unix"
)

// replaceFile renames src over dst atomically on the same filesystem.
func replaceFile(src, dst string) error {
	if err := os.Rename(src, dst); err != nil {
		return fmt.Errorf("rename replace: %w", err)
	}
	return nil
}

// replaceFileWithBackup moves target to backup (if present), then new to target,
// restoring backup on failure. Caller must have already fsynced the new file.
func replaceFileWithBackup(newPath, targetPath, backupPath string) error {
	_ = os.Remove(backupPath)
	if _, err := os.Stat(targetPath); err == nil {
		if err := os.Rename(targetPath, backupPath); err != nil {
			return fmt.Errorf("backup current file: %w", err)
		}
		if err := syncDir(filepath.Dir(targetPath)); err != nil {
			// best-effort restore attempt
			_ = os.Rename(backupPath, targetPath)
			return fmt.Errorf("sync after backup: %w", err)
		}
	}
	if err := os.Rename(newPath, targetPath); err != nil {
		if _, berr := os.Stat(backupPath); berr == nil {
			_ = os.Rename(backupPath, targetPath)
			_ = syncDir(filepath.Dir(targetPath))
		}
		return fmt.Errorf("install new file: %w", err)
	}
	if err := syncDir(filepath.Dir(targetPath)); err != nil {
		return fmt.Errorf("sync after install: %w", err)
	}
	return nil
}

// syncDir fsyncs the parent directory so the directory entry is durable.
// Fail-closed: open or sync errors are returned.
func syncDir(dir string) error {
	// O_DIRECTORY|O_RDONLY where available; plain Open is sufficient for fsync on most FS.
	f, err := os.Open(dir)
	if err != nil {
		return fmt.Errorf("open dir for fsync %s: %w", dir, err)
	}
	defer f.Close()
	if err := f.Sync(); err != nil {
		return fmt.Errorf("fsync dir %s: %w", dir, err)
	}
	return nil
}

// configureDetached sets Setsid so the child is not a session leader of the updater.
func configureDetached(cmd *exec.Cmd) error {
	cmd.SysProcAttr = &syscall.SysProcAttr{
		Setsid: true,
	}
	return nil
}

// installOwner captures POSIX uid/gid of the install root so root-created
// staging/install artifacts can be reassigned to the normal install owner.
type installOwner struct {
	uid  int
	gid  int
	mode os.FileMode
}

func captureInstallOwner(path string) (installOwner, error) {
	st, err := os.Stat(path)
	if err != nil {
		return installOwner{}, err
	}
	stat, ok := st.Sys().(*syscall.Stat_t)
	if !ok {
		return installOwner{}, fmt.Errorf("unsupported stat type for %s", path)
	}
	return installOwner{
		uid:  int(stat.Uid),
		gid:  int(stat.Gid),
		mode: st.Mode().Perm(),
	}, nil
}

func (o installOwner) apply(path string) error {
	if err := os.Chown(path, o.uid, o.gid); err != nil {
		return fmt.Errorf("chown %s to %d:%d: %w", path, o.uid, o.gid, err)
	}
	return nil
}

// applyTree walks root and chowns every path to the install owner (fail closed).
func (o installOwner) applyTree(root string) error {
	return filepath.WalkDir(root, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if err := o.apply(path); err != nil {
			return err
		}
		return nil
	})
}

func ensureCrossAccountFileMode(path string, mode os.FileMode) error {
	if err := os.Chmod(path, mode); err != nil {
		return fmt.Errorf("chmod %s: %w", path, err)
	}
	// Verify bits that matter for coordination files.
	st, err := os.Stat(path)
	if err != nil {
		return err
	}
	got := st.Mode().Perm()
	// Require at least the requested permission bits that we care about.
	if got&mode != mode && mode != 0 {
		// Some FS mask bits; for 0666 require other-read at minimum for logs/locks.
		if mode&0o004 != 0 && got&0o004 == 0 {
			return fmt.Errorf("mode verify failed for %s: got %04o want bits %04o", path, got, mode)
		}
	}
	_ = unix.Access // keep import for potential future access checks
	return nil
}
