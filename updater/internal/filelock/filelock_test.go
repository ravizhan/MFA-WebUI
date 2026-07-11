package filelock

import (
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"testing"
	"time"
)

func TestOpenCreatesStableFileNeverDeleted(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "test.lock")

	l, err := Open(path)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	if _, err := os.Stat(path); err != nil {
		t.Fatalf("lock file missing after Open: %v", err)
	}
	if err := l.TryLock(); err != nil {
		t.Fatalf("TryLock: %v", err)
	}
	if err := l.Unlock(); err != nil {
		t.Fatalf("Unlock: %v", err)
	}
	if err := l.Close(); err != nil {
		t.Fatalf("Close: %v", err)
	}
	if _, err := os.Stat(path); err != nil {
		t.Fatalf("stable lock file was deleted on Close: %v", err)
	}
}

func TestContentionSecondHolderGetsBusy(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "contend.lock")

	a, err := Open(path)
	if err != nil {
		t.Fatalf("Open a: %v", err)
	}
	defer a.Close()
	if err := a.TryLock(); err != nil {
		t.Fatalf("a.TryLock: %v", err)
	}

	b, err := Open(path)
	if err != nil {
		t.Fatalf("Open b: %v", err)
	}
	defer b.Close()
	err = b.TryLock()
	if !errors.Is(err, ErrBusy) {
		t.Fatalf("expected ErrBusy, got %v", err)
	}

	if err := a.Unlock(); err != nil {
		t.Fatalf("a.Unlock: %v", err)
	}
	if err := b.TryLock(); err != nil {
		t.Fatalf("b.TryLock after release: %v", err)
	}
}

func TestAcquireTimeout(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "timeout.lock")

	holder, err := Acquire(path, time.Second, 10*time.Millisecond)
	if err != nil {
		t.Fatalf("holder Acquire: %v", err)
	}
	defer holder.Close()

	start := time.Now()
	_, err = Acquire(path, 200*time.Millisecond, 20*time.Millisecond)
	elapsed := time.Since(start)
	if !errors.Is(err, ErrTimeout) {
		t.Fatalf("expected ErrTimeout, got %v", err)
	}
	if elapsed < 150*time.Millisecond {
		t.Fatalf("timeout returned too early: %v", elapsed)
	}
}

func TestAcquireCleanupOnTimeout(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "cleanup.lock")

	holder, err := Acquire(path, time.Second, 10*time.Millisecond)
	if err != nil {
		t.Fatalf("holder: %v", err)
	}
	defer holder.Close()

	_, err = Acquire(path, 100*time.Millisecond, 20*time.Millisecond)
	if !errors.Is(err, ErrTimeout) {
		t.Fatalf("expected timeout, got %v", err)
	}
	third, err := Open(path)
	if err != nil {
		t.Fatalf("Open third: %v", err)
	}
	defer third.Close()
	if err := third.TryLock(); !errors.Is(err, ErrBusy) {
		t.Fatalf("expected still busy after failed Acquire, got %v", err)
	}
}

func TestUpdateAndRuntimePaths(t *testing.T) {
	root := t.TempDir()
	if err := EnsureLockDir(root); err != nil {
		t.Fatalf("EnsureLockDir: %v", err)
	}
	u := UpdateLockPath(root)
	r := RuntimeLockPath(root)
	if filepath.Base(u) != UpdateLockName {
		t.Fatalf("update path base: %s", u)
	}
	if filepath.Base(r) != RuntimeLockName {
		t.Fatalf("runtime path base: %s", r)
	}
	if filepath.Dir(u) != LockDir(root) {
		t.Fatalf("update not under lock dir")
	}

	ul, err := AcquireUpdateLock(root, time.Second, 10*time.Millisecond)
	if err != nil {
		t.Fatalf("AcquireUpdateLock: %v", err)
	}
	defer ul.Close()
	rl, err := AcquireRuntimeLock(root, time.Second, 10*time.Millisecond)
	if err != nil {
		t.Fatalf("AcquireRuntimeLock: %v", err)
	}
	defer rl.Close()

	if !ul.Locked() || !rl.Locked() {
		t.Fatal("both locks should be held")
	}
	if _, err := os.Stat(u); err != nil {
		t.Fatalf("update.lock missing: %v", err)
	}
	if _, err := os.Stat(r); err != nil {
		t.Fatalf("runtime.lock missing: %v", err)
	}
}

func TestResolveInstallRootFromWorkingDir(t *testing.T) {
	wd := t.TempDir()
	root, err := ResolveInstallRoot(wd, "")
	if err != nil {
		t.Fatalf("ResolveInstallRoot: %v", err)
	}
	abs, _ := filepath.Abs(wd)
	if root != filepath.Clean(abs) {
		t.Fatalf("got %q want %q", root, abs)
	}
}

func TestResolveInstallRootIgnoresMWUAppRootEnv(t *testing.T) {
	// Production must not diverge lock root from install root via env.
	wd := t.TempDir()
	other := t.TempDir()
	t.Setenv("MWU_APP_ROOT", other)
	root, err := ResolveInstallRoot(wd, "")
	if err != nil {
		t.Fatal(err)
	}
	absWD, _ := filepath.Abs(wd)
	if root != filepath.Clean(absWD) {
		t.Fatalf("MWU_APP_ROOT must not override install root: got %q want %q", root, absWD)
	}
	if root == other {
		t.Fatal("must not use MWU_APP_ROOT as install root")
	}
}

func TestResolveInstallRootNeverHome(t *testing.T) {
	wd := t.TempDir()
	root, err := ResolveInstallRoot(wd, "")
	if err != nil {
		t.Fatal(err)
	}
	home, err := os.UserHomeDir()
	if err == nil && root == home {
		t.Fatal("app root must not be user home")
	}
	if filepath.Base(root) == ".mwu" && filepath.Dir(root) == home {
		t.Fatal("must not use ~/.mwu as app root")
	}
}

func TestHandoffOrderingReleaseRuntimeThenUpdate(t *testing.T) {
	root := t.TempDir()
	update, err := AcquireUpdateLock(root, time.Second, 10*time.Millisecond)
	if err != nil {
		t.Fatalf("update: %v", err)
	}
	defer update.Close()
	runtimeL, err := AcquireRuntimeLock(root, time.Second, 10*time.Millisecond)
	if err != nil {
		t.Fatalf("runtime: %v", err)
	}

	otherU, err := Open(UpdateLockPath(root))
	if err != nil {
		t.Fatal(err)
	}
	defer otherU.Close()
	if err := otherU.TryLock(); !errors.Is(err, ErrBusy) {
		t.Fatalf("update should be busy, got %v", err)
	}

	if err := runtimeL.Close(); err != nil {
		t.Fatalf("runtime close: %v", err)
	}
	otherR, err := Open(RuntimeLockPath(root))
	if err != nil {
		t.Fatal(err)
	}
	defer otherR.Close()
	if err := otherR.TryLock(); err != nil {
		t.Fatalf("runtime should be free after handoff step1: %v", err)
	}
	if err := otherU.TryLock(); !errors.Is(err, ErrBusy) {
		t.Fatalf("update must remain held during handoff, got %v", err)
	}

	if err := update.Unlock(); err != nil {
		t.Fatalf("update unlock: %v", err)
	}
	if err := otherU.TryLock(); err != nil {
		t.Fatalf("update free after handoff: %v", err)
	}
}

func TestReopenAfterClose(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "reopen.lock")

	l1, err := Acquire(path, time.Second, 10*time.Millisecond)
	if err != nil {
		t.Fatal(err)
	}
	pathCopy := l1.Path()
	if err := l1.Close(); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(pathCopy); err != nil {
		t.Fatalf("file deleted: %v", err)
	}
	l2, err := Acquire(pathCopy, time.Second, 10*time.Millisecond)
	if err != nil {
		t.Fatalf("reopen acquire: %v", err)
	}
	l2.Close()
}

func TestEnsureLockDirStickyOnPOSIX(t *testing.T) {
	root := t.TempDir()
	if err := EnsureLockDir(root); err != nil {
		t.Fatalf("EnsureLockDir: %v", err)
	}
	dir := LockDir(root)
	st, err := os.Stat(dir)
	if err != nil {
		t.Fatal(err)
	}
	if runtime.GOOS == "windows" {
		// Windows relies on DACL inheritance; sticky bit is a no-op.
		return
	}
	if st.Mode()&os.ModeSticky == 0 {
		t.Fatalf("lock dir missing sticky bit: mode=%v", st.Mode())
	}
	if st.Mode().Perm()&0o002 == 0 {
		t.Fatalf("lock dir not world-writable: mode=%04o", st.Mode().Perm())
	}
}

func TestOpenDoesNotChmodExistingParent(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("POSIX mode bits")
	}
	parent := t.TempDir()
	// Restrict parent to 0700
	if err := os.Chmod(parent, 0o700); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(parent, "x.lock")
	l, err := Open(path)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	l.Close()
	st, err := os.Stat(parent)
	if err != nil {
		t.Fatal(err)
	}
	if st.Mode().Perm() != 0o700 {
		t.Fatalf("Open must not chmod existing parent: got %04o", st.Mode().Perm())
	}
}

func TestPermissionErrorNotBusy(t *testing.T) {
	// ErrPermission must not be retryable as busy.
	if errors.Is(ErrPermission, ErrBusy) {
		t.Fatal("ErrPermission must not equal ErrBusy")
	}
	if errors.Is(ErrBusy, ErrPermission) {
		t.Fatal("ErrBusy must not equal ErrPermission")
	}
}

func TestLockFileMode0666OnPOSIX(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("POSIX mode bits")
	}
	root := t.TempDir()
	if err := EnsureLockDir(root); err != nil {
		t.Fatal(err)
	}
	l, err := AcquireUpdateLock(root, time.Second, 10*time.Millisecond)
	if err != nil {
		t.Fatal(err)
	}
	l.Close()
	st, err := os.Stat(UpdateLockPath(root))
	if err != nil {
		t.Fatal(err)
	}
	if st.Mode().Perm() != 0o666 {
		t.Fatalf("lock file mode=%04o want 0666", st.Mode().Perm())
	}
}
