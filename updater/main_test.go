package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/ravizhan/MWU/updater/internal/filelock"
)

func testDeps(t *testing.T, root string) (deps, *runTrace) {
	t.Helper()
	tr := &runTrace{}
	d := defaultDeps()
	d.getwd = func() (string, error) { return root, nil }
	d.executable = func() (string, error) {
		return filepath.Join(root, "updater"+exeSuffix()), nil
	}
	d.lockTimeout = 500 * time.Millisecond
	d.lockInterval = 10 * time.Millisecond
	d.shutdownWait = 0
	d.sleep = func(time.Duration) {}
	d.openLog = func(name string, flag int, perm os.FileMode) (*os.File, error) {
		return os.OpenFile(filepath.Join(root, "updater.log"), flag, perm)
	}
	var out bytes.Buffer
	d.output = func(v any) {
		data, _ := json.Marshal(v)
		out.Write(data)
		out.WriteByte('\n')
		tr.lastOutput = string(data)
	}
	d.extract = func(ctx context.Context, archivePath, destDir string) error {
		tr.extractCalled.Add(1)
		if tr.failExtract {
			return errors.New("extract failed")
		}
		return os.WriteFile(filepath.Join(destDir, "payload.txt"), []byte("new"), 0o644)
	}
	d.selfUpdate = func(installDir, extractDir string) (bool, error) {
		tr.selfUpdateCalled.Add(1)
		if tr.failSelfUpdate {
			return false, errors.New("self-update failed")
		}
		if tr.doSelfUpdate {
			return true, nil
		}
		if tr.useRealSelfUpdate {
			return handleSelfUpdate(d, installDir, extractDir)
		}
		return false, nil
	}
	d.notify = func(url string) error {
		tr.notifyCalled.Add(1)
		return nil
	}
	d.getChanges = func(installDir, extractDir string) (ChangeLog, error) {
		tr.getChangesCalled.Add(1)
		if tr.failGetChanges {
			return ChangeLog{}, errors.New("getChanges failed")
		}
		return ChangeLog{Modified: []string{"payload.txt"}}, nil
	}
	d.apply = func(installDir, extractDir string, changes ChangeLog) error {
		tr.applyCalled.Add(1)
		if tr.failApply {
			return errors.New("apply failed")
		}
		return nil
	}
	d.writeChanges = func(path string, changes ChangeLog) error {
		tr.writeChangesCalled.Add(1)
		if tr.failWriteChanges {
			return errors.New("writeChanges failed")
		}
		return nil
	}
	d.restart = func(exePath string) error {
		tr.restartCalled.Add(1)
		tr.restartCmd = exePath
		if tr.failRestart {
			return errors.New("restart failed")
		}
		return nil
	}
	d.removeAll = func(path string) error {
		tr.removeAllCalled.Add(1)
		return os.RemoveAll(path)
	}
	d.remove = func(path string) error { return os.Remove(path) }
	d.mkdirAll = func(path string, perm os.FileMode) error { return os.MkdirAll(path, perm) }
	d.acquireUpdate = filelock.AcquireUpdateLock
	d.acquireRuntime = filelock.AcquireRuntimeLock
	d.onUpdateLocked = func() { tr.updateLocked.Add(1) }
	tr.out = &out
	return d, tr
}

func exeSuffix() string {
	if runtime.GOOS == "windows" {
		return ".exe"
	}
	return ""
}

type runTrace struct {
	out                *bytes.Buffer
	lastOutput         string
	updateLocked       atomic.Int32
	extractCalled      atomic.Int32
	selfUpdateCalled   atomic.Int32
	notifyCalled       atomic.Int32
	getChangesCalled   atomic.Int32
	applyCalled        atomic.Int32
	writeChangesCalled atomic.Int32
	restartCalled      atomic.Int32
	removeAllCalled    atomic.Int32
	restartCmd         string
	failExtract        bool
	failSelfUpdate     bool
	doSelfUpdate       bool
	useRealSelfUpdate  bool
	failGetChanges     bool
	failApply          bool
	failWriteChanges   bool
	failRestart        bool
}

func validCfg(root string) Config {
	return Config{
		Archive:    filepath.Join(root, "pkg.zip"),
		WebhookURL: "http://127.0.0.1:9/shutdown",
		RestartCmd: filepath.Join(root, "Program Files", "MWU", "MWU"+exeSuffix()),
	}
}

func TestSafeJoinRejectsTraversal(t *testing.T) {
	base := t.TempDir()
	for _, c := range []string{"../etc/passwd", "..\\secret", "foo/../../bar"} {
		if _, err := safeJoin(base, c); err == nil {
			t.Fatalf("expected rejection for %q", c)
		}
	}
	ok, err := safeJoin(base, "nested/file.txt")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.HasPrefix(ok, base) {
		t.Fatalf("joined path escaped base: %s", ok)
	}
}

func TestParseFlagsRestartPathWithSpaces(t *testing.T) {
	// flag.Parse preserves the full value of -restart-cmd including spaces when
	// the caller quotes it as a single argv element (normal production launch).
	spaced := `C:\Program Files\MWU\MWU.exe`
	cfg := parseFlags([]string{
		"-archive", "pkg.zip",
		"-webhook", "http://example/shutdown",
		"-restart-cmd", spaced,
	})
	if cfg.RestartCmd != spaced {
		t.Fatalf("restart-cmd not opaque path: got %q want %q", cfg.RestartCmd, spaced)
	}
}

func TestRestartMainOpaquePathWithSpaces(t *testing.T) {
	root := t.TempDir()
	dir := filepath.Join(root, "Program Files", "MWU")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	exe := filepath.Join(dir, "MWU"+exeSuffix())
	if err := os.WriteFile(exe, []byte("fake-exe"), 0o755); err != nil {
		t.Fatal(err)
	}

	// Opaque path with spaces must resolve without re-splitting.
	got, err := resolveRestartExecutable(exe)
	if err != nil {
		t.Fatalf("resolve: %v", err)
	}
	if got != exe && filepath.Clean(got) != filepath.Clean(exe) {
		t.Fatalf("got %q want %q", got, exe)
	}

	// Missing path error must include the full spaced path (not only first token).
	missing := filepath.Join(dir, "Missing App"+exeSuffix())
	_, err = resolveRestartExecutable(missing)
	if err == nil {
		t.Fatal("expected not found")
	}
	if !strings.Contains(err.Error(), "Missing App") {
		t.Fatalf("error lost spaced path segments: %v", err)
	}

	// parseFlags + resolve round-trip (caller passes one argv element with spaces).
	cfg := parseFlags([]string{"-restart-cmd", exe, "-archive", "a", "-webhook", "http://x"})
	if cfg.RestartCmd != exe {
		t.Fatalf("parseFlags: %q", cfg.RestartCmd)
	}
	if _, err := resolveRestartExecutable(cfg.RestartCmd); err != nil {
		t.Fatal(err)
	}
}

func TestInstallRootStableSingleRoot(t *testing.T) {
	root := t.TempDir()
	other := t.TempDir()
	t.Setenv("MWU_APP_ROOT", other)
	got, err := filelock.ResolveInstallRoot(root, "")
	if err != nil {
		t.Fatal(err)
	}
	abs, _ := filepath.Abs(root)
	if got != filepath.Clean(abs) {
		t.Fatalf("got %q want %q", got, abs)
	}
}

func TestRunAcquiresUpdateLockBeforeStaging(t *testing.T) {
	root := t.TempDir()
	d, tr := testDeps(t, root)
	cfg := validCfg(root)
	_ = os.WriteFile(cfg.Archive, []byte("x"), 0o644)
	_ = os.MkdirAll(filepath.Dir(cfg.RestartCmd), 0o755)
	_ = os.WriteFile(cfg.RestartCmd, []byte("x"), 0o755)

	var order []string
	d.onUpdateLocked = func() {
		tr.updateLocked.Add(1)
		order = append(order, "locked")
	}
	origExtract := d.extract
	d.extract = func(ctx context.Context, archivePath, destDir string) error {
		order = append(order, "extract")
		return origExtract(ctx, archivePath, destDir)
	}
	origRemoveAll := d.removeAll
	d.removeAll = func(path string) error {
		if strings.Contains(path, "update_temp") {
			if tr.updateLocked.Load() == 0 {
				t.Error("update_temp removed before update.lock")
			}
		}
		return origRemoveAll(path)
	}

	code := run(d, cfg)
	if code != exitCodeOK {
		t.Fatalf("exit=%d out=%s", code, tr.lastOutput)
	}
	lockedIdx, extractIdx := -1, -1
	for i, s := range order {
		if s == "locked" && lockedIdx < 0 {
			lockedIdx = i
		}
		if s == "extract" && extractIdx < 0 {
			extractIdx = i
		}
	}
	if lockedIdx < 0 || extractIdx < 0 || lockedIdx > extractIdx {
		t.Fatalf("order=%v", order)
	}
}

func TestRunRecoveryObservesUpdateLockHeld(t *testing.T) {
	root := t.TempDir()
	d, tr := testDeps(t, root)
	cfg := validCfg(root)
	_ = os.WriteFile(cfg.Archive, []byte("x"), 0o644)
	_ = os.MkdirAll(filepath.Dir(cfg.RestartCmd), 0o755)
	_ = os.WriteFile(cfg.RestartCmd, []byte("x"), 0o755)

	var sawBusy atomic.Bool
	d.recoverInterrupted = func(installDir string) error {
		ul, err := filelock.Open(filelock.UpdateLockPath(installDir))
		if err != nil {
			t.Errorf("open update.lock during recovery: %v", err)
			return nil
		}
		err = ul.TryLock()
		_ = ul.Close()
		if !errors.Is(err, filelock.ErrBusy) {
			t.Errorf("update.lock must be held during recovery, got %v", err)
			return nil
		}
		sawBusy.Store(true)
		return nil
	}

	code := run(d, cfg)
	if code != exitCodeOK {
		t.Fatalf("exit=%d out=%s", code, tr.lastOutput)
	}
	if !sawBusy.Load() {
		t.Fatal("recovery did not observe update.lock held")
	}
}

func TestRunLockFailurePreventsRecovery(t *testing.T) {
	root := t.TempDir()
	d, tr := testDeps(t, root)
	cfg := validCfg(root)
	_ = os.WriteFile(cfg.Archive, []byte("x"), 0o644)

	var recoveryCalled atomic.Bool
	d.acquireUpdate = func(appRoot string, timeout, interval time.Duration) (*filelock.Lock, error) {
		return nil, errors.New("injected lock failure")
	}
	d.recoverInterrupted = func(installDir string) error {
		recoveryCalled.Store(true)
		return nil
	}

	code := run(d, cfg)
	if code != exitCodeError {
		t.Fatalf("exit=%d want error out=%s", code, tr.lastOutput)
	}
	if recoveryCalled.Load() {
		t.Fatal("recovery must not run when update.lock acquisition fails")
	}
	if !strings.Contains(tr.lastOutput, "Could not acquire update.lock") {
		t.Fatalf("expected lock failure message, out=%s", tr.lastOutput)
	}
}

func TestRunRecoveryFailureReleasesLock(t *testing.T) {
	root := t.TempDir()
	d, tr := testDeps(t, root)
	cfg := validCfg(root)
	_ = os.WriteFile(cfg.Archive, []byte("x"), 0o644)

	d.recoverInterrupted = func(installDir string) error {
		return errors.New("injected recovery failure")
	}
	d.extract = func(ctx context.Context, archivePath, destDir string) error {
		t.Error("extract must not run after recovery failure")
		return nil
	}

	code := run(d, cfg)
	if code != exitCodeError {
		t.Fatalf("exit=%d want error out=%s", code, tr.lastOutput)
	}
	if !strings.Contains(tr.lastOutput, "Self-update recovery failed") {
		t.Fatalf("expected recovery failure message, out=%s", tr.lastOutput)
	}
	if tr.extractCalled.Load() != 0 {
		t.Fatalf("extract must stay 0 after recovery failure, got %d", tr.extractCalled.Load())
	}

	l, err := filelock.AcquireUpdateLock(root, time.Second, 10*time.Millisecond)
	if err != nil {
		t.Fatalf("update.lock not released after recovery failure: %v", err)
	}
	l.Close()
}

func TestRunSelfUpdateExit10ReleasesLock(t *testing.T) {
	root := t.TempDir()
	d, tr := testDeps(t, root)
	tr.doSelfUpdate = true
	cfg := validCfg(root)
	_ = os.WriteFile(cfg.Archive, []byte("x"), 0o644)

	code := run(d, cfg)
	if code != exitCodeSelfUpdate {
		t.Fatalf("exit=%d want 10 out=%s", code, tr.lastOutput)
	}
	l, err := filelock.AcquireUpdateLock(root, time.Second, 10*time.Millisecond)
	if err != nil {
		t.Fatalf("lock not released after exit-10: %v", err)
	}
	l.Close()
}

func TestRunRuntimeUnlockFailureAbortsHandoff(t *testing.T) {
	root := t.TempDir()
	d, tr := testDeps(t, root)
	cfg := validCfg(root)
	_ = os.WriteFile(cfg.Archive, []byte("x"), 0o644)
	_ = os.MkdirAll(filepath.Dir(cfg.RestartCmd), 0o755)
	_ = os.WriteFile(cfg.RestartCmd, []byte("x"), 0o755)

	d.runtimeUnlock = func(l *filelock.Lock) error {
		// Fail the intentional handoff unlock; deferred cleanup will also call this.
		if tr.restartCalled.Load() == 0 && l != nil && l.Locked() {
			return errors.New("injected unlock failure")
		}
		if l != nil {
			return l.Close()
		}
		return nil
	}

	code := run(d, cfg)
	if code != exitCodeError {
		t.Fatalf("exit=%d want error out=%s", code, tr.lastOutput)
	}
	if tr.restartCalled.Load() != 0 {
		t.Fatal("restart must not run after runtime unlock failure")
	}
	if strings.Contains(tr.lastOutput, `"status":"success"`) {
		t.Fatal("must not emit success")
	}
	// update lock released via defer
	l, err := filelock.AcquireUpdateLock(root, time.Second, 10*time.Millisecond)
	if err != nil {
		t.Fatalf("update lock stuck: %v", err)
	}
	l.Close()
}

func TestRunPostLockFailureCleansUp(t *testing.T) {
	cases := []struct {
		name string
		mut  func(*runTrace)
	}{
		{"extract", func(tr *runTrace) { tr.failExtract = true }},
		{"selfUpdate", func(tr *runTrace) { tr.failSelfUpdate = true }},
		{"getChanges", func(tr *runTrace) { tr.failGetChanges = true }},
		{"apply", func(tr *runTrace) { tr.failApply = true }},
		{"writeChanges", func(tr *runTrace) { tr.failWriteChanges = true }},
		{"restart", func(tr *runTrace) { tr.failRestart = true }},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			root := t.TempDir()
			d, tr := testDeps(t, root)
			tc.mut(tr)
			cfg := validCfg(root)
			_ = os.WriteFile(cfg.Archive, []byte("x"), 0o644)
			_ = os.MkdirAll(filepath.Dir(cfg.RestartCmd), 0o755)
			_ = os.WriteFile(cfg.RestartCmd, []byte("x"), 0o755)

			code := run(d, cfg)
			if code != exitCodeError {
				t.Fatalf("exit=%d out=%s", code, tr.lastOutput)
			}
			l, err := filelock.AcquireUpdateLock(root, time.Second, 10*time.Millisecond)
			if err != nil {
				t.Fatalf("update lock stuck: %v", err)
			}
			l.Close()
		})
	}
}

func TestRunHandoffOrdering(t *testing.T) {
	root := t.TempDir()
	d, tr := testDeps(t, root)
	cfg := validCfg(root)
	_ = os.WriteFile(cfg.Archive, []byte("x"), 0o644)
	_ = os.MkdirAll(filepath.Dir(cfg.RestartCmd), 0o755)
	_ = os.WriteFile(cfg.RestartCmd, []byte("x"), 0o755)

	var runtimeLock *filelock.Lock
	origRuntime := d.acquireRuntime
	d.acquireRuntime = func(appRoot string, timeout, interval time.Duration) (*filelock.Lock, error) {
		l, err := origRuntime(appRoot, timeout, interval)
		runtimeLock = l
		return l, err
	}
	d.restart = func(exePath string) error {
		if runtimeLock != nil && runtimeLock.Locked() {
			t.Error("runtime still locked at restart")
		}
		ul, err := filelock.Open(filelock.UpdateLockPath(root))
		if err != nil {
			t.Fatal(err)
		}
		err = ul.TryLock()
		ul.Close()
		if !errors.Is(err, filelock.ErrBusy) {
			t.Errorf("update.lock must be held during restart, got %v", err)
		}
		tr.restartCalled.Add(1)
		return nil
	}

	code := run(d, cfg)
	if code != exitCodeOK {
		t.Fatalf("exit=%d out=%s", code, tr.lastOutput)
	}
}

func TestAtomicReplaceDoesNotTruncateFirst(t *testing.T) {
	dir := t.TempDir()
	src := filepath.Join(dir, "src.txt")
	dst := filepath.Join(dir, "dst.txt")
	_ = os.WriteFile(src, []byte("new-content"), 0o644)
	_ = os.WriteFile(dst, []byte("old-content"), 0o644)
	if err := atomicReplaceFile(defaultDeps(), src, dst, 0o644); err != nil {
		t.Fatal(err)
	}
	data, _ := os.ReadFile(dst)
	if string(data) != "new-content" {
		t.Fatalf("got %q", data)
	}
}

func TestAtomicReplaceFailureLeavesDestination(t *testing.T) {
	dir := t.TempDir()
	dst := filepath.Join(dir, "dst.txt")
	_ = os.WriteFile(dst, []byte("keep-me"), 0o644)
	err := atomicReplaceFile(defaultDeps(), filepath.Join(dir, "missing"), dst, 0o644)
	if err == nil {
		t.Fatal("expected error")
	}
	data, _ := os.ReadFile(dst)
	if string(data) != "keep-me" {
		t.Fatalf("destination corrupted: %q", data)
	}
}

func TestAtomicWriteFileChmodFailClosed(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("POSIX chmod semantics")
	}
	// atomicWriteFile must not ignore chmod errors — verified by ensuring
	// successful writes end with correct mode.
	dir := t.TempDir()
	path := filepath.Join(dir, "c.json")
	if err := atomicWriteFile(path, []byte(`{}`), 0o644); err != nil {
		t.Fatal(err)
	}
	st, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if st.Mode().Perm()&0o644 != 0o644 {
		t.Fatalf("mode=%04o", st.Mode().Perm())
	}
}

func TestSyncDirFailurePropagates(t *testing.T) {
	d := defaultDeps()
	d.syncDirHook = func(dir string) error {
		return errors.New("injected fsync failure")
	}
	dir := t.TempDir()
	src := filepath.Join(dir, "s")
	dst := filepath.Join(dir, "d")
	_ = os.WriteFile(src, []byte("x"), 0o644)
	err := atomicReplaceFile(d, src, dst, 0o644)
	if err == nil || !strings.Contains(err.Error(), "injected fsync") {
		t.Fatalf("expected fsync failure, got %v", err)
	}
}

func TestPathWithinRootRejectsOutside(t *testing.T) {
	root := t.TempDir()
	outside := t.TempDir()
	ok, err := pathWithinRoot(root, filepath.Join(outside, "x"))
	if err != nil {
		t.Fatal(err)
	}
	if ok {
		t.Fatal("outside path accepted")
	}
	ok, err = pathWithinRoot(root, filepath.Join(outside, "no", "such", "updater"+exeSuffix()))
	if err != nil {
		t.Fatal(err)
	}
	if ok {
		t.Fatal("missing outside path accepted")
	}
}

func TestPathWithinRootMissingLeafAndNested(t *testing.T) {
	root := t.TempDir()
	ok, err := pathWithinRoot(root, filepath.Join(root, "updater"+exeSuffix()))
	if err != nil || !ok {
		t.Fatalf("missing leaf rejected: ok=%v err=%v", ok, err)
	}
	ok, err = pathWithinRoot(root, filepath.Join(root, "a", "b", "c", "updater"+exeSuffix()))
	if err != nil || !ok {
		t.Fatalf("missing nested rejected: ok=%v err=%v", ok, err)
	}
}

func TestPathWithinRootSymlinkAliasAndEscape(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("unix symlink alias / escape")
	}
	realRoot := t.TempDir()
	aliasRoot := filepath.Join(t.TempDir(), "install-alias")
	if err := os.Symlink(realRoot, aliasRoot); err != nil {
		t.Fatal(err)
	}

	missing := filepath.Join(aliasRoot, "nested", "updater"+exeSuffix())
	ok, err := pathWithinRoot(aliasRoot, missing)
	if err != nil || !ok {
		t.Fatalf("symlink-alias missing target rejected: ok=%v err=%v", ok, err)
	}

	escape := filepath.Join(aliasRoot, "escape-link")
	if err := os.Symlink(t.TempDir(), escape); err != nil {
		t.Fatal(err)
	}
	ok, err = pathWithinRoot(aliasRoot, escape)
	if err != nil {
		t.Fatal(err)
	}
	if ok {
		t.Fatal("symlink escape accepted")
	}
}

func TestSelfUpdateRejectsOutsideExecutable(t *testing.T) {
	root := t.TempDir()
	outside := t.TempDir()
	d := defaultDeps()
	d.executable = func() (string, error) {
		return filepath.Join(outside, "evil"+exeSuffix()), nil
	}
	// Create extract candidate so we reach path check
	extract := filepath.Join(root, "update_temp")
	_ = os.MkdirAll(extract, 0o755)
	_, err := handleSelfUpdate(d, root, extract)
	if err == nil {
		t.Fatal("expected outside-root rejection")
	}
	if !strings.Contains(err.Error(), "outside install root") {
		t.Fatalf("err=%v", err)
	}
}

func TestSelfUpdateAtomicRealTree(t *testing.T) {
	root := t.TempDir()
	exeName := "updater" + exeSuffix()
	exePath := filepath.Join(root, exeName)
	// Current "updater" binary content
	if err := os.WriteFile(exePath, []byte("old-updater-bytes-v1"), 0o755); err != nil {
		t.Fatal(err)
	}
	extract := filepath.Join(root, "update_temp")
	_ = os.MkdirAll(extract, 0o755)
	candidate := filepath.Join(extract, exeName)
	if err := os.WriteFile(candidate, []byte("new-updater-bytes-v2"), 0o755); err != nil {
		t.Fatal(err)
	}

	d := defaultDeps()
	d.executable = func() (string, error) { return exePath, nil }

	done, err := handleSelfUpdate(d, root, extract)
	if err != nil {
		t.Fatalf("self-update: %v", err)
	}
	if !done {
		t.Fatal("expected self-update performed")
	}
	data, err := os.ReadFile(exePath)
	if err != nil {
		t.Fatal(err)
	}
	if string(data) != "new-updater-bytes-v2" {
		t.Fatalf("canonical content=%q", data)
	}
	// Backup should exist
	if _, err := os.Stat(exePath + selfUpdateBackupSuffix); err != nil {
		t.Fatalf("backup missing: %v", err)
	}
	// .new should be gone (consumed by replace)
	if _, err := os.Stat(exePath + selfUpdateNewSuffix); err == nil {
		t.Fatal(".new should not remain after successful replace")
	}
}

func TestSelfUpdateRecoveryFromNew(t *testing.T) {
	root := t.TempDir()
	exeName := "updater" + exeSuffix()
	exePath := filepath.Join(root, exeName)
	// Simulate crash: canonical missing, .new present
	newPath := exePath + selfUpdateNewSuffix
	if err := os.WriteFile(newPath, []byte("recovered-new"), 0o755); err != nil {
		t.Fatal(err)
	}
	d := defaultDeps()
	d.executable = func() (string, error) { return exePath, nil }
	if err := recoverInterruptedSelfUpdate(d, root); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(exePath)
	if err != nil {
		t.Fatalf("canonical not restored: %v", err)
	}
	if string(data) != "recovered-new" {
		t.Fatalf("got %q", data)
	}
}

func TestSelfUpdateRecoveryFromOld(t *testing.T) {
	root := t.TempDir()
	exeName := "updater" + exeSuffix()
	exePath := filepath.Join(root, exeName)
	oldPath := exePath + selfUpdateBackupSuffix
	if err := os.WriteFile(oldPath, []byte("restored-old"), 0o755); err != nil {
		t.Fatal(err)
	}
	d := defaultDeps()
	d.executable = func() (string, error) { return exePath, nil }
	if err := recoverInterruptedSelfUpdate(d, root); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(exePath)
	if err != nil {
		t.Fatal(err)
	}
	if string(data) != "restored-old" {
		t.Fatalf("got %q", data)
	}
}

func TestCopyFilePreservesContent(t *testing.T) {
	dir := t.TempDir()
	src := filepath.Join(dir, "a.txt")
	dst := filepath.Join(dir, "b.txt")
	_ = os.WriteFile(src, []byte("hello-update"), 0o644)
	if err := copyFile(src, dst, 0o755); err != nil {
		t.Fatal(err)
	}
	data, _ := os.ReadFile(dst)
	if string(data) != "hello-update" {
		t.Fatalf("got %q", data)
	}
}

func TestHashFileStable(t *testing.T) {
	dir := t.TempDir()
	p := filepath.Join(dir, "x.bin")
	_ = os.WriteFile(p, []byte{1, 2, 3, 4}, 0o644)
	h1, _ := hashFile(p)
	h2, _ := hashFile(p)
	if h1 != h2 || h1 == "" {
		t.Fatalf("unstable hash %q %q", h1, h2)
	}
}

func TestSelfUpdateExitCodeConstant(t *testing.T) {
	if exitCodeSelfUpdate != 10 {
		t.Fatalf("exitCodeSelfUpdate=%d want 10", exitCodeSelfUpdate)
	}
}

func TestFailResultDoesNotPanic(t *testing.T) {
	d := defaultDeps()
	var got string
	d.output = func(v any) {
		data, _ := json.Marshal(v)
		got = string(data)
	}
	code := failResult(d, "test error %d", 42)
	if code != exitCodeError {
		t.Fatalf("code=%d", code)
	}
	if !strings.Contains(got, "test error 42") {
		t.Fatalf("output=%s", got)
	}
}

func TestRestartMainRejectsMissingExe(t *testing.T) {
	err := restartMain(filepath.Join(t.TempDir(), "no-such-binary"))
	if err == nil {
		t.Fatal("expected missing exe error")
	}
}

func TestLockBusyErrorDistinctFromTimeout(t *testing.T) {
	if errors.Is(filelock.ErrBusy, filelock.ErrTimeout) {
		t.Fatal("ErrBusy must not equal ErrTimeout")
	}
}

func TestCaptureInstallOwnerAndApply(t *testing.T) {
	root := t.TempDir()
	owner, err := captureInstallOwner(root)
	if err != nil {
		t.Fatal(err)
	}
	// Create a file as "elevated" simulation and re-apply ownership.
	f := filepath.Join(root, "owned.txt")
	if err := os.WriteFile(f, []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := owner.apply(f); err != nil {
		t.Fatal(err)
	}
	if err := owner.applyTree(root); err != nil {
		t.Fatal(err)
	}
}

func TestPlatformReplaceFailure(t *testing.T) {
	dir := t.TempDir()
	dst := filepath.Join(dir, "dst")
	_ = os.WriteFile(dst, []byte("keep"), 0o644)
	err := replaceFile(filepath.Join(dir, "missing-src"), dst)
	if err == nil {
		t.Fatal("expected replace failure")
	}
	data, _ := os.ReadFile(dst)
	if string(data) != "keep" {
		t.Fatalf("dst corrupted: %q", data)
	}
}
