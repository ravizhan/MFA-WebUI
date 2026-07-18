package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"time"

	"github.com/mholt/archives"
	"github.com/ravizhan/MWU/updater/internal/filelock"
	"github.com/zeebo/xxh3"
)

const (
	exitCodeSelfUpdate = 10
	exitCodeError      = 1
	exitCodeOK         = 0
	defaultChangesFile = "changes.json"

	// Cross-account modes for updater-owned coordination/log artifacts.
	// Staging/install dirs stay 0755 (not world-writable); ownership is restored
	// to the install-root owner after elevated runs (POSIX).
	logFileMode     = 0o666
	stagingDirMode  = 0o755
	installFileMode = 0o755
	installDirMode  = 0o755

	selfUpdateBackupSuffix = ".old"
	selfUpdateNewSuffix    = ".new"
)

// deps holds injectable collaborators for unit tests.
type deps struct {
	getwd          func() (string, error)
	executable     func() (string, error)
	acquireUpdate  func(appRoot string, timeout, interval time.Duration) (*filelock.Lock, error)
	acquireRuntime func(appRoot string, timeout, interval time.Duration) (*filelock.Lock, error)
	extract        func(ctx context.Context, archivePath, destDir string) error
	selfUpdate     func(installDir, extractDir string) (bool, error)
	notify         func(url string) error
	getChanges     func(installDir, extractDir string) (ChangeLog, error)
	apply          func(installDir, extractDir string, changes ChangeLog) error
	writeChanges   func(path string, changes ChangeLog) error
	restart        func(exePath string) error
	removeAll      func(path string) error
	remove         func(path string) error
	mkdirAll       func(path string, perm os.FileMode) error
	openLog        func(name string, flag int, perm os.FileMode) (*os.File, error)
	output         func(v any)
	sleep          func(d time.Duration)
	now            func() time.Time
	// test hooks
	onUpdateLocked     func()
	recoverInterrupted func(installDir string) error // nil → recoverInterruptedSelfUpdate
	runtimeUnlock      func(l *filelock.Lock) error  // default: l.Close
	atomicReplaceHook  func(src, dst string, mode os.FileMode) error
	syncDirHook        func(dir string) error
	lockTimeout        time.Duration
	lockInterval       time.Duration
	shutdownWait       time.Duration
}

func defaultDeps() deps {
	return deps{
		getwd:          os.Getwd,
		executable:     os.Executable,
		acquireUpdate:  filelock.AcquireUpdateLock,
		acquireRuntime: filelock.AcquireRuntimeLock,
		extract:        extractArchive,
		selfUpdate:     nil, // set in run to bind executable resolver
		notify:         notifyShutdown,
		getChanges:     getChanges,
		apply:          nil,
		writeChanges: func(path string, changes ChangeLog) error {
			return writeChanges(path, changes)
		},
		restart:      restartMain,
		removeAll:    os.RemoveAll,
		remove:       os.Remove,
		mkdirAll:     os.MkdirAll,
		openLog:      os.OpenFile,
		output:       outputJSON,
		sleep:        time.Sleep,
		now:          time.Now,
		lockTimeout:  filelock.DefaultTimeout,
		lockInterval: filelock.DefaultRetryInterval,
		shutdownWait: 2 * time.Second,
	}
}

type Config struct {
	Archive    string
	WebhookURL string
	// RestartCmd is an opaque executable path (NOT a shell command line).
	// Paths may contain spaces, e.g. C:\Program Files\MWU\MWU.exe.
	RestartCmd string
}

type UpdateResult struct {
	Status          string `json:"status"`
	Message         string `json:"message,omitempty"`
	RestartRequired bool   `json:"restart_required"`
}

func main() {
	os.Exit(run(defaultDeps(), parseFlags(os.Args[1:])))
}

// run executes the updater and always returns an exit code so lock owners are
// released via defers before process exit.
//
// Ordering (normative):
//  1. Resolve single install root (locks + mutations share it)
//  2. Capture install owner (no install mutation)
//  3. Acquire update.lock BEFORE any recovery/staging/self-update/file mutation
//  4. Recover interrupted self-update under lock (failure releases via defer)
//  5. Stage extract + optional self-update (exit 10 after cleanup)
//  6. Notify shutdown, wait for runtime.lock
//  7. Apply changes (atomic replace + fsync), hold both locks
//  8. Handoff: unlock runtime (fail aborts) → Start replacement → release update
func run(d deps, cfg Config) int {
	if d.openLog == nil {
		d.openLog = os.OpenFile
	}
	if d.output == nil {
		d.output = outputJSON
	}
	if d.sleep == nil {
		d.sleep = time.Sleep
	}
	if d.lockTimeout <= 0 {
		d.lockTimeout = filelock.DefaultTimeout
	}
	if d.lockInterval <= 0 {
		d.lockInterval = filelock.DefaultRetryInterval
	}
	if d.executable == nil {
		d.executable = os.Executable
	}
	if d.runtimeUnlock == nil {
		d.runtimeUnlock = func(l *filelock.Lock) error {
			if l == nil {
				return nil
			}
			return l.Close()
		}
	}
	if d.recoverInterrupted == nil {
		d.recoverInterrupted = func(installDir string) error {
			return recoverInterruptedSelfUpdate(d, installDir)
		}
	}
	if d.selfUpdate == nil {
		d.selfUpdate = func(installDir, extractDir string) (bool, error) {
			return handleSelfUpdate(d, installDir, extractDir)
		}
	}
	if d.apply == nil {
		d.apply = func(installDir, extractDir string, changes ChangeLog) error {
			return applyChanges(d, installDir, extractDir, changes)
		}
	}

	logFile, logErr := d.openLog("updater.log", os.O_APPEND|os.O_CREATE|os.O_WRONLY, logFileMode)
	if logFile != nil {
		defer logFile.Close()
		log.SetOutput(logFile)
		if err := ensureCrossAccountFileMode("updater.log", logFileMode); err != nil {
			log.Printf("警告：updater.log 权限规范化失败：%v", err)
		}
	} else if logErr != nil {
		log.Printf("警告：无法打开 updater.log：%v", logErr)
	}

	if cfg.Archive == "" {
		return failResult(d, "Missing -archive argument")
	}
	if cfg.WebhookURL == "" {
		return failResult(d, "Missing -webhook argument")
	}
	if cfg.RestartCmd == "" {
		return failResult(d, "Missing -restart-cmd argument")
	}

	wd, err := d.getwd()
	if err != nil {
		return failResult(d, "Failed to get working directory: %v", err)
	}

	installDir, err := filelock.ResolveInstallRoot(wd, "")
	if err != nil {
		return failResult(d, "Failed to resolve install root: %v", err)
	}
	log.Printf("安装根目录（锁与变更同一根）：%s", installDir)

	owner, err := captureInstallOwner(installDir)
	if err != nil {
		return failResult(d, "Failed to capture install owner: %v", err)
	}

	// --- update.lock BEFORE any recovery / staging / self-update / install mutation ---
	log.Println("获取 update.lock...")
	updateLock, err := d.acquireUpdate(installDir, d.lockTimeout, d.lockInterval)
	if err != nil {
		return failResult(d, "Could not acquire update.lock: %v", err)
	}
	defer func() {
		if updateLock != nil {
			if err := updateLock.Close(); err != nil {
				log.Printf("警告：释放 update.lock 失败：%v", err)
			} else {
				log.Println("已释放 update.lock")
			}
		}
	}()

	if err := d.recoverInterrupted(installDir); err != nil {
		return failResult(d, "Self-update recovery failed: %v", err)
	}

	if d.onUpdateLocked != nil {
		d.onUpdateLocked()
	}

	ctx := context.Background()
	extractDir := filepath.Join(installDir, "update_temp")

	if err := d.removeAll(extractDir); err != nil && !os.IsNotExist(err) {
		return failResult(d, "Failed to clear staging dir: %v", err)
	}
	if err := d.mkdirAll(extractDir, stagingDirMode); err != nil {
		return failResult(d, "Failed to create temp dir: %v", err)
	}
	if err := ensureCrossAccountFileMode(extractDir, stagingDirMode); err != nil {
		return failResult(d, "Failed to set staging dir mode: %v", err)
	}
	if err := owner.apply(extractDir); err != nil {
		return failResult(d, "Failed to assign staging ownership: %v", err)
	}
	defer func() {
		// Re-assign ownership before remove so a root crash mid-run still leaves
		// a tree the install owner can delete; then remove.
		_ = owner.applyTree(extractDir)
		_ = d.removeAll(extractDir)
	}()

	log.Printf("正在将 %s 解压到 %s", cfg.Archive, extractDir)
	if err := d.extract(ctx, cfg.Archive, extractDir); err != nil {
		return failResult(d, "Failed to extract archive: %v", err)
	}
	// Staging contents must be owned by install owner for crash cleanup.
	if err := owner.applyTree(extractDir); err != nil {
		return failResult(d, "Failed to assign staging tree ownership: %v", err)
	}

	log.Println("检查自更新...")
	if performedSelfUpdate, err := d.selfUpdate(installDir, extractDir); err != nil {
		return failResult(d, "Self update failed: %v", err)
	} else if performedSelfUpdate {
		log.Println("已执行自更新。清理后以代码 10 退出。")
		_ = owner.applyTree(extractDir)
		_ = d.removeAll(extractDir)
		return exitCodeSelfUpdate
	}

	log.Println("通知主程序退出...")
	if cfg.WebhookURL != "" {
		if err := d.notify(cfg.WebhookURL); err != nil {
			log.Printf("警告：通知关闭失败：%v。", err)
		} else if d.shutdownWait > 0 {
			d.sleep(d.shutdownWait)
		}
	}

	log.Println("等待 runtime.lock...")
	runtimeLock, err := d.acquireRuntime(installDir, d.lockTimeout, d.lockInterval)
	if err != nil {
		return failResult(d, "Could not acquire runtime.lock: %v", err)
	}
	runtimeHeld := true
	defer func() {
		if runtimeHeld && runtimeLock != nil {
			// Deferred cleanup retry if handoff never unlocked.
			if err := d.runtimeUnlock(runtimeLock); err != nil {
				log.Printf("警告：释放 runtime.lock 失败：%v", err)
			}
			runtimeHeld = false
		}
	}()

	log.Println("计算更改...")
	changes, err := d.getChanges(installDir, extractDir)
	if err != nil {
		return failResult(d, "Failed to get changes: %v", err)
	}

	log.Println("应用更新...")
	if err := d.apply(installDir, extractDir, changes); err != nil {
		return failResult(d, "Failed to apply changes: %v", err)
	}

	changesPath := filepath.Join(installDir, defaultChangesFile)
	if err := d.writeChanges(changesPath, changes); err != nil {
		return failResult(d, "Failed to write changes log: %v", err)
	}
	_ = owner.apply(changesPath)

	_ = owner.applyTree(extractDir)
	_ = d.removeAll(extractDir)
	_ = d.remove(cfg.Archive)

	// Handoff: runtime unlock MUST succeed before restart/success.
	log.Println("重启交接：释放 runtime.lock...")
	if err := d.runtimeUnlock(runtimeLock); err != nil {
		// Keep runtimeHeld true so deferred cleanup retries Close; abort handoff.
		return failResult(d, "Failed to release runtime.lock before restart: %v", err)
	}
	runtimeHeld = false

	log.Printf("启动替换进程：%s", cfg.RestartCmd)
	if err := d.restart(cfg.RestartCmd); err != nil {
		return failResult(d, "Failed to start replacement process: %v", err)
	}

	log.Println("更新完成。")
	d.output(UpdateResult{
		Status:          "success",
		Message:         "更新成功完成",
		RestartRequired: true,
	})
	return exitCodeOK
}

func parseFlags(args []string) Config {
	cfg := Config{}
	fs := flag.NewFlagSet("updater", flag.ContinueOnError)
	fs.SetOutput(io.Discard)
	fs.StringVar(&cfg.Archive, "archive", "", "更新包路径（zip/7z）")
	fs.StringVar(&cfg.WebhookURL, "webhook", "", "用于请求主程序关闭的URL")
	// Opaque executable path — may contain spaces. Not a shell command line.
	fs.StringVar(&cfg.RestartCmd, "restart-cmd", "", "重启主程序的可执行文件路径（可含空格）")
	_ = fs.Parse(args)
	return cfg
}

func extractArchive(ctx context.Context, archivePath, destDir string) error {
	file, err := os.Open(archivePath)
	if err != nil {
		return err
	}
	defer file.Close()

	format, reader, err := archives.Identify(ctx, archivePath, file)
	if err != nil {
		return err
	}
	extractor, ok := format.(archives.Extractor)
	if !ok {
		return errors.New("不支持的归档格式")
	}

	return extractor.Extract(ctx, reader, func(ctx context.Context, f archives.FileInfo) error {
		if f.NameInArchive == "" {
			return nil
		}
		pathInArchive := f.NameInArchive
		if runtime.GOOS == "windows" {
			pathInArchive = strings.ReplaceAll(pathInArchive, "\\", "/")
		}

		outPath, err := safeJoin(destDir, pathInArchive)
		if err != nil {
			return err
		}
		if f.IsDir() {
			return os.MkdirAll(outPath, stagingDirMode)
		}

		if err := os.MkdirAll(filepath.Dir(outPath), stagingDirMode); err != nil {
			return err
		}

		mode := f.Mode()
		if mode == 0 {
			mode = 0o644
		}
		outFile, err := os.OpenFile(outPath, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, mode)
		if err != nil {
			return err
		}
		defer outFile.Close()

		rc, err := f.Open()
		if err != nil {
			return err
		}
		defer rc.Close()

		if _, err := io.Copy(outFile, rc); err != nil {
			return err
		}
		return outFile.Sync()
	})
}

// pathWithinRoot reports whether target is the root or a path strictly inside it.
func pathWithinRoot(root, target string) (bool, error) {
	absRoot, err := resolveCanonicalPath(root)
	if err != nil {
		return false, err
	}
	absTarget, err := resolveCanonicalPath(target)
	if err != nil {
		return false, err
	}
	rel, err := filepath.Rel(absRoot, absTarget)
	if err != nil {
		return false, err
	}
	relSlash := filepath.ToSlash(rel)
	if relSlash == ".." || strings.HasPrefix(relSlash, "../") {
		return false, nil
	}
	return true, nil
}

// resolveCanonicalPath EvalSymlinks the longest existing ancestor, then re-appends
// any missing trailing components (needed for .new/.old recovery of a missing exe).
func resolveCanonicalPath(path string) (string, error) {
	abs, err := filepath.Abs(path)
	if err != nil {
		return "", err
	}
	abs = filepath.Clean(abs)

	existing := abs
	var missing []string
	for {
		_, err := os.Lstat(existing)
		if err == nil {
			break
		}
		if !os.IsNotExist(err) {
			return "", err
		}
		parent := filepath.Dir(existing)
		if parent == existing {
			return abs, nil
		}
		missing = append([]string{filepath.Base(existing)}, missing...)
		existing = parent
	}

	resolved, err := filepath.EvalSymlinks(existing)
	if err != nil {
		return "", err
	}
	result := resolved
	for _, comp := range missing {
		result = filepath.Join(result, comp)
	}
	return filepath.Clean(result), nil
}

// recoverInterruptedSelfUpdate restores a canonical updater if a previous
// self-update left .new / .old journal artifacts.
func recoverInterruptedSelfUpdate(d deps, installDir string) error {
	exePath, err := d.executable()
	if err != nil {
		return nil // cannot recover without knowing exe
	}
	if ok, err := pathWithinRoot(installDir, exePath); err != nil || !ok {
		return nil
	}
	newPath := exePath + selfUpdateNewSuffix
	oldPath := exePath + selfUpdateBackupSuffix

	// Case A: .new exists and canonical missing/corrupt → promote .new
	if st, err := os.Stat(newPath); err == nil && !st.IsDir() {
		if _, err := os.Stat(exePath); err != nil {
			log.Printf("恢复自更新：提升 %s → 规范路径", newPath)
			if err := replaceFile(newPath, exePath); err != nil {
				return fmt.Errorf("promote .new: %w", err)
			}
			_ = doSyncDir(d, filepath.Dir(exePath))
		} else {
			// Canonical exists; drop stale .new
			_ = os.Remove(newPath)
		}
	}

	// Case B: .old exists and canonical missing → restore .old
	if _, err := os.Stat(exePath); err != nil {
		if st, err := os.Stat(oldPath); err == nil && !st.IsDir() {
			log.Printf("恢复自更新：从备份恢复 %s", oldPath)
			if err := replaceFile(oldPath, exePath); err != nil {
				return fmt.Errorf("restore .old: %w", err)
			}
			_ = doSyncDir(d, filepath.Dir(exePath))
		}
	}
	return nil
}

func handleSelfUpdate(d deps, installDir, extractDir string) (bool, error) {
	exePath, err := d.executable()
	if err != nil {
		return false, err
	}

	ok, err := pathWithinRoot(installDir, exePath)
	if err != nil {
		return false, fmt.Errorf("validate executable path: %w", err)
	}
	if !ok {
		return false, fmt.Errorf("executable outside install root: %s (root %s)", exePath, installDir)
	}

	relPath, err := filepath.Rel(installDir, exePath)
	if err != nil {
		return false, fmt.Errorf("executable not relative to install root: %w", err)
	}

	candidate := filepath.Join(extractDir, relPath)
	if _, err := os.Stat(candidate); os.IsNotExist(err) {
		candidate = filepath.Join(extractDir, filepath.Base(exePath))
	}
	if _, err := os.Stat(candidate); err != nil {
		return false, nil
	}

	currentHash, _ := hashFile(exePath)
	candidateHash, _ := hashFile(candidate)
	if currentHash == candidateHash {
		return false, nil
	}

	// Prepare + sync candidate beside canonical as .new BEFORE touching canonical.
	newPath := exePath + selfUpdateNewSuffix
	oldPath := exePath + selfUpdateBackupSuffix
	_ = os.Remove(newPath)

	if err := prepareSelfUpdateCandidate(d, candidate, newPath, installFileMode); err != nil {
		_ = os.Remove(newPath)
		return false, fmt.Errorf("prepare self-update candidate: %w", err)
	}

	// Atomic replace with backup: never leave a window with no canonical updater.
	if err := replaceFileWithBackup(newPath, exePath, oldPath); err != nil {
		_ = os.Remove(newPath)
		return false, fmt.Errorf("atomic self-update replace: %w", err)
	}
	return true, nil
}

// prepareSelfUpdateCandidate copies src to dst (same dir as final), chmod, fsync.
func prepareSelfUpdateCandidate(d deps, src, dst string, mode os.FileMode) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()

	dir := filepath.Dir(dst)
	if err := os.MkdirAll(dir, installDirMode); err != nil {
		return err
	}
	out, err := os.OpenFile(dst, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, mode)
	if err != nil {
		return err
	}
	if _, err := io.Copy(out, in); err != nil {
		out.Close()
		return err
	}
	if err := out.Chmod(mode); err != nil && runtime.GOOS != "windows" {
		out.Close()
		return fmt.Errorf("chmod candidate: %w", err)
	}
	if err := out.Sync(); err != nil {
		out.Close()
		return fmt.Errorf("fsync candidate: %w", err)
	}
	if err := out.Close(); err != nil {
		return err
	}
	return doSyncDir(d, dir)
}

func notifyShutdown(urlStr string) error {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	req, err := http.NewRequestWithContext(ctx, "GET", urlStr, nil)
	if err != nil {
		return err
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return fmt.Errorf("服务器返回 %d", resp.StatusCode)
	}
	return nil
}

type ChangeLog struct {
	Added    []string `json:"added"`
	Deleted  []string `json:"deleted"`
	Modified []string `json:"modified"`
}

// validateRelativeChangePath rejects absolute paths, empty paths, and .. traversal
// so ChangeLog entries cannot escape install/extract roots.
func validateRelativeChangePath(rel string) error {
	if strings.TrimSpace(rel) == "" {
		return errors.New("empty change path")
	}
	normalized := strings.ReplaceAll(rel, "\\", "/")
	if filepath.IsAbs(normalized) || filepath.VolumeName(normalized) != "" {
		return fmt.Errorf("illegal absolute change path: %q", rel)
	}
	clean := filepath.Clean(normalized)
	if filepath.IsAbs(clean) || filepath.VolumeName(clean) != "" {
		return fmt.Errorf("illegal absolute change path: %q", rel)
	}
	slash := filepath.ToSlash(clean)
	if slash == "." || slash == "" {
		return fmt.Errorf("illegal change path: %q", rel)
	}
	if slash == ".." || strings.HasPrefix(slash, "../") {
		return fmt.Errorf("illegal change path escapes root: %q", rel)
	}
	return nil
}

func validateChangeLog(changes ChangeLog) error {
	for _, rel := range changes.Added {
		if err := validateRelativeChangePath(rel); err != nil {
			return fmt.Errorf("added: %w", err)
		}
	}
	for _, rel := range changes.Modified {
		if err := validateRelativeChangePath(rel); err != nil {
			return fmt.Errorf("modified: %w", err)
		}
	}
	for _, rel := range changes.Deleted {
		if err := validateRelativeChangePath(rel); err != nil {
			return fmt.Errorf("deleted: %w", err)
		}
	}
	return nil
}

func getChanges(installDir, extractDir string) (ChangeLog, error) {
	empty := ChangeLog{
		Added:    []string{},
		Deleted:  []string{},
		Modified: []string{},
	}
	changesPath := filepath.Join(extractDir, defaultChangesFile)

	if _, err := os.Stat(changesPath); err == nil {
		data, err := os.ReadFile(changesPath)
		if err != nil {
			return empty, err
		}
		changes := empty
		if err := json.Unmarshal(data, &changes); err != nil {
			return empty, err
		}
		if changes.Added == nil {
			changes.Added = []string{}
		}
		if changes.Deleted == nil {
			changes.Deleted = []string{}
		}
		if changes.Modified == nil {
			changes.Modified = []string{}
		}
		if err := validateChangeLog(changes); err != nil {
			return empty, err
		}
		return changes, nil
	} else if !os.IsNotExist(err) {
		return empty, err
	}

	type fileInfo struct {
		path string
		rel  string
	}
	type workerResult struct {
		added    []string
		modified []string
		err      error
	}

	pkgFiles := make(chan fileInfo, 100)
	pkgFileMap := make(map[string]bool)
	var mapMu sync.Mutex
	numWorkers := runtime.NumCPU()
	if numWorkers < 1 {
		numWorkers = 1
	}
	var wg sync.WaitGroup
	results := make(chan workerResult, numWorkers)
	walkDone := make(chan error, 1)

	go func() {
		walkDone <- filepath.WalkDir(extractDir, func(path string, d os.DirEntry, err error) error {
			if err != nil {
				return err
			}
			if d.IsDir() {
				return nil
			}
			rel, err := filepath.Rel(extractDir, path)
			if err != nil {
				return err
			}
			rel = filepath.ToSlash(rel)
			if rel == defaultChangesFile || rel == filepath.Base(os.Args[0]) {
				return nil
			}
			if err := validateRelativeChangePath(rel); err != nil {
				return err
			}
			mapMu.Lock()
			pkgFileMap[rel] = true
			mapMu.Unlock()
			pkgFiles <- fileInfo{path: path, rel: rel}
			return nil
		})
		close(pkgFiles)
	}()

	for i := 0; i < numWorkers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			var added, modified []string
			var werr error
			for f := range pkgFiles {
				if werr != nil {
					continue
				}
				targetPath, err := safeJoin(installDir, f.rel)
				if err != nil {
					werr = fmt.Errorf("install path %q: %w", f.rel, err)
					continue
				}
				_, err = os.Stat(targetPath)
				if os.IsNotExist(err) {
					added = append(added, f.rel)
					continue
				}
				if err != nil {
					werr = fmt.Errorf("stat install file %s: %w", f.rel, err)
					continue
				}
				h1, err := hashFile(f.path)
				if err != nil {
					werr = fmt.Errorf("hash package file %s: %w", f.rel, err)
					continue
				}
				h2, err := hashFile(targetPath)
				if err != nil {
					werr = fmt.Errorf("hash install file %s: %w", f.rel, err)
					continue
				}
				if h1 != h2 {
					modified = append(modified, f.rel)
				}
			}
			results <- workerResult{added: added, modified: modified, err: werr}
		}()
	}
	go func() {
		wg.Wait()
		close(results)
	}()

	changes := empty
	var workerErr error
	for r := range results {
		if r.err != nil && workerErr == nil {
			workerErr = r.err
		}
		changes.Added = append(changes.Added, r.added...)
		changes.Modified = append(changes.Modified, r.modified...)
	}
	if err := <-walkDone; err != nil {
		return empty, err
	}
	if workerErr != nil {
		return empty, workerErr
	}

	err := filepath.WalkDir(installDir, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() {
			return nil
		}
		rel, err := filepath.Rel(installDir, path)
		if err != nil {
			return err
		}
		rel = filepath.ToSlash(rel)
		if strings.HasPrefix(rel, "config/") ||
			rel == "update_temp" ||
			strings.HasPrefix(rel, "update_temp/") ||
			strings.HasPrefix(rel, "debug/") ||
			rel == filepath.Base(os.Args[0]) ||
			rel == "updater.log" ||
			strings.HasSuffix(rel, ".old") ||
			strings.HasSuffix(rel, ".new") ||
			rel == defaultChangesFile {
			return nil
		}
		mapMu.Lock()
		exists := pkgFileMap[rel]
		mapMu.Unlock()
		if !exists {
			changes.Deleted = append(changes.Deleted, rel)
		}
		return nil
	})
	if err != nil {
		return empty, err
	}
	return changes, nil
}

func applyChanges(d deps, installDir, extractDir string, changes ChangeLog) error {
	if err := validateChangeLog(changes); err != nil {
		return err
	}
	owner, err := captureInstallOwner(installDir)
	if err != nil {
		return err
	}
	for _, rel := range append(changes.Added, changes.Modified...) {
		if rel == filepath.Base(os.Args[0]) || rel == defaultChangesFile {
			continue
		}
		src, err := resolveChangePath(extractDir, rel)
		if err != nil {
			return fmt.Errorf("invalid change path %q: %w", rel, err)
		}
		dst, err := resolveChangePath(installDir, rel)
		if err != nil {
			return fmt.Errorf("invalid change path %q: %w", rel, err)
		}
		if err := os.MkdirAll(filepath.Dir(dst), installDirMode); err != nil {
			return err
		}
		// Ensure intermediate dirs owned by install owner (not left root-owned).
		if err := owner.apply(filepath.Dir(dst)); err != nil {
			return err
		}
		if err := doAtomicReplace(d, src, dst, installFileMode); err != nil {
			return err
		}
		if err := owner.apply(dst); err != nil {
			return err
		}
	}
	for _, rel := range changes.Deleted {
		dst, err := resolveChangePath(installDir, rel)
		if err != nil {
			return fmt.Errorf("invalid delete path %q: %w", rel, err)
		}
		if err := os.Remove(dst); err != nil && !os.IsNotExist(err) {
			return fmt.Errorf("delete %q: %w", rel, err)
		}
	}
	return nil
}

func resolveChangePath(root, rel string) (string, error) {
	path, err := safeJoin(root, rel)
	if err != nil {
		return "", err
	}
	ok, err := pathWithinRoot(root, path)
	if err != nil {
		return "", err
	}
	if !ok {
		return "", errors.New("非法路径：路径超出目标目录")
	}
	return path, nil
}

// restartMain treats exePath as an opaque executable path (may contain spaces).
// It does NOT re-split the string as a shell command line.
func restartMain(exePath string) error {
	exe, err := resolveRestartExecutable(exePath)
	if err != nil {
		return err
	}

	cmd := exec.Command(exe)
	cmd.Stdout = nil
	cmd.Stderr = nil
	cmd.Stdin = nil
	if err := configureDetached(cmd); err != nil {
		return err
	}
	if err := cmd.Start(); err != nil {
		return err
	}
	if cmd.Process == nil {
		return errors.New("replacement process handle is nil after Start")
	}
	go func() { _ = cmd.Process.Release() }()
	return nil
}

// resolveRestartExecutable normalizes an opaque executable path (spaces allowed).
// No shell splitting is performed.
func resolveRestartExecutable(exePath string) (string, error) {
	exePath = strings.TrimSpace(exePath)
	if exePath == "" {
		return "", errors.New("empty restart executable path")
	}
	if !filepath.IsAbs(exePath) {
		if abs, err := filepath.Abs(exePath); err == nil {
			exePath = abs
		}
	}
	if st, err := os.Stat(exePath); err != nil || st.IsDir() {
		return "", fmt.Errorf("replacement executable not found: %s", exePath)
	}
	return exePath, nil
}

func writeChanges(path string, changes ChangeLog) error {
	data, err := json.MarshalIndent(changes, "", "  ")
	if err != nil {
		return err
	}
	return atomicWriteFile(path, data, 0o644)
}

// safeJoin joins baseDir/name and rejects any result that escapes baseDir.
// Single filepath.Rel root check covers absolute names and .. traversal on
// both Windows and Unix.
func safeJoin(baseDir, name string) (string, error) {
	joined := filepath.Join(baseDir, filepath.Clean(strings.ReplaceAll(name, "\\", "/")))
	rel, err := filepath.Rel(baseDir, joined)
	if err != nil {
		return "", fmt.Errorf("路径解析失败: %w", err)
	}
	relSlash := filepath.ToSlash(rel)
	if relSlash == ".." || strings.HasPrefix(relSlash, "../") {
		return "", errors.New("非法路径：路径超出目标目录")
	}
	return joined, nil
}

func doSyncDir(d deps, dir string) error {
	if d.syncDirHook != nil {
		return d.syncDirHook(dir)
	}
	return syncDir(dir)
}

func doAtomicReplace(d deps, src, dst string, mode os.FileMode) error {
	if d.atomicReplaceHook != nil {
		return d.atomicReplaceHook(src, dst, mode)
	}
	return atomicReplaceFile(d, src, dst, mode)
}

// atomicReplaceFile copies src to a same-directory temp file, fsyncs, sets mode
// (fail-closed), atomically replaces dst, then syncs the parent directory
// (fail-closed). Never removes/truncates destination first.
func atomicReplaceFile(d deps, src, dst string, mode os.FileMode) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()

	dir := filepath.Dir(dst)
	if err := os.MkdirAll(dir, installDirMode); err != nil {
		return err
	}

	tmp, err := os.CreateTemp(dir, ".mwu-update-*")
	if err != nil {
		return err
	}
	tmpName := tmp.Name()
	cleanup := true
	defer func() {
		if cleanup {
			_ = tmp.Close()
			_ = os.Remove(tmpName)
		}
	}()

	if _, err := io.Copy(tmp, in); err != nil {
		return err
	}
	if err := tmp.Chmod(mode); err != nil {
		if runtime.GOOS != "windows" {
			return fmt.Errorf("chmod temp: %w", err)
		}
	}
	if err := tmp.Sync(); err != nil {
		return fmt.Errorf("fsync temp: %w", err)
	}
	if err := tmp.Close(); err != nil {
		return err
	}

	if err := replaceFile(tmpName, dst); err != nil {
		return err
	}
	cleanup = false
	if err := doSyncDir(d, dir); err != nil {
		return err
	}
	return nil
}

// atomicWriteFile writes data via same-dir temp + fsync + chmod (fail-closed) + replace + dirsync.
func atomicWriteFile(path string, data []byte, mode os.FileMode) error {
	dir := filepath.Dir(path)
	if err := os.MkdirAll(dir, installDirMode); err != nil {
		return err
	}
	tmp, err := os.CreateTemp(dir, ".mwu-write-*")
	if err != nil {
		return err
	}
	tmpName := tmp.Name()
	cleanup := true
	defer func() {
		if cleanup {
			_ = tmp.Close()
			_ = os.Remove(tmpName)
		}
	}()
	if _, err := tmp.Write(data); err != nil {
		return err
	}
	if err := tmp.Chmod(mode); err != nil {
		if runtime.GOOS != "windows" {
			return fmt.Errorf("chmod write temp: %w", err)
		}
	}
	if err := tmp.Sync(); err != nil {
		return fmt.Errorf("fsync write temp: %w", err)
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	if err := replaceFile(tmpName, path); err != nil {
		return err
	}
	cleanup = false
	if err := syncDir(dir); err != nil {
		return err
	}
	return nil
}

func hashFile(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()
	h := xxh3.New128()
	if _, err := io.Copy(h, f); err != nil {
		return "", err
	}
	sum := h.Sum128()
	return fmt.Sprintf("%016x%016x", sum.Hi, sum.Lo), nil
}

func outputJSON(v any) {
	data, _ := json.Marshal(v)
	fmt.Println(string(data))
}

func failResult(d deps, format string, v ...any) int {
	msg := fmt.Sprintf(format, v...)
	log.Printf("错误：%s", msg)
	if d.output != nil {
		d.output(UpdateResult{Status: "failed", Message: msg})
	} else {
		outputJSON(UpdateResult{Status: "failed", Message: msg})
	}
	return exitCodeError
}
