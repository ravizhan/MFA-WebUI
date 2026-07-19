package filelock

import (
	"path/filepath"
	"testing"
)

// Path/root policy only; gofrs/flock and OS lock primitives are trusted.

func TestUpdateAndRuntimePaths(t *testing.T) {
	root := t.TempDir()
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
	if filepath.Dir(r) != LockDir(root) {
		t.Fatalf("runtime not under lock dir")
	}
	wantDir := filepath.Join(root, RelativeLockDir)
	if LockDir(root) != wantDir {
		t.Fatalf("LockDir: got %q want %q", LockDir(root), wantDir)
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
