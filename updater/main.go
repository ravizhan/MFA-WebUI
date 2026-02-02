package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/mholt/archives"
	"github.com/zeebo/xxh3"
	"golang.org/x/mod/semver"
)

const (
	defaultRepo          = "ravizhan/MWU"
	defaultVersionFile   = "version"
	defaultChangesFile   = "changes.json"
	defaultHTTPTimeout   = 10 * time.Second
	jsonTypeCheckResult  = "check"
	jsonTypeUpdateResult = "update"
)

type Config struct {
	Repo  string
	Proxy string
	Check bool
}

type CheckResult struct {
	Type           string `json:"type"`
	Status         string `json:"status"`
	HasUpdate      bool   `json:"has_update"`
	CurrentVersion string `json:"current_version"`
	LatestVersion  string `json:"latest_version,omitempty"`
	AssetName      string `json:"asset_name,omitempty"`
	AssetURL       string `json:"asset_url,omitempty"`
	Platform       string `json:"platform"`
	Arch           string `json:"arch"`
	Message        string `json:"message,omitempty"`
}

type UpdateResult struct {
	Type              string `json:"type"`
	Status            string `json:"status"`
	Applied           bool   `json:"applied"`
	SelfUpdatePending bool   `json:"self_update_pending"`
	RestartRequired   bool   `json:"restart_required"`
	ChangesPath       string `json:"changes_path,omitempty"`
	Message           string `json:"message,omitempty"`
}

type Release struct {
	TagName string         `json:"tag_name"`
	Assets  []ReleaseAsset `json:"assets"`
}

type ReleaseAsset struct {
	Name string `json:"name"`
	URL  string `json:"browser_download_url"`
}

type Changes struct {
	Added    []string `json:"added"`
	Deleted  []string `json:"deleted"`
	Modified []string `json:"modified"`
}

type FileHash struct {
	Hash string
}

func main() {
	cfg := parseFlags()
	platform, arch := detectPlatform()
	ctx := context.Background()

	client, err := newHTTPClient(cfg.Proxy)
	if err != nil {
		outputJSON(CheckResult{
			Type:     jsonTypeCheckResult,
			Status:   "failed",
			Message:  fmt.Sprintf("创建 HTTP 客户端失败: %v", err),
			Platform: platform,
			Arch:     arch,
		})
		outputJSON(UpdateResult{
			Type:    jsonTypeUpdateResult,
			Status:  "failed",
			Applied: false,
			Message: "更新器初始化失败",
		})
		return
	}

	installDir, err := os.Getwd()
	if err != nil {
		outputJSON(CheckResult{
			Type:     jsonTypeCheckResult,
			Status:   "failed",
			Message:  fmt.Sprintf("获取工作目录失败: %v", err),
			Platform: platform,
			Arch:     arch,
		})
		outputJSON(UpdateResult{
			Type:    jsonTypeUpdateResult,
			Status:  "failed",
			Applied: false,
			Message: "获取工作目录失败",
		})
		return
	}

	currentVersion, err := resolveCurrentVersion(installDir)
	if err != nil {
		outputJSON(CheckResult{
			Type:     jsonTypeCheckResult,
			Status:   "failed",
			Message:  err.Error(),
			Platform: platform,
			Arch:     arch,
		})
		outputJSON(UpdateResult{
			Type:    jsonTypeUpdateResult,
			Status:  "failed",
			Applied: false,
			Message: "无法解析当前版本",
		})
		return
	}

	checkResult := CheckResult{
		Type:           jsonTypeCheckResult,
		Status:         "success",
		HasUpdate:      false,
		CurrentVersion: currentVersion,
		Platform:       platform,
		Arch:           arch,
	}

	release, err := fetchLatestRelease(ctx, client, cfg)
	if err != nil {
		checkResult.Status = "failed"
		checkResult.Message = err.Error()
		outputJSON(checkResult)
		outputJSON(UpdateResult{
			Type:    jsonTypeUpdateResult,
			Status:  "failed",
			Applied: false,
			Message: "更新检查失败",
		})
		return
	}

	latestVersion := normalizeVersion(release.TagName)
	checkResult.LatestVersion = latestVersion

	asset, err := selectAsset(release.Assets, platform, arch)
	if err != nil {
		checkResult.Status = "failed"
		checkResult.Message = err.Error()
		outputJSON(checkResult)
		outputJSON(UpdateResult{
			Type:    jsonTypeUpdateResult,
			Status:  "failed",
			Applied: false,
			Message: "查找更新包失败",
		})
		return
	}
	checkResult.AssetName = asset.Name
	checkResult.AssetURL = asset.URL

	if semver.Compare(normalizeVersion(currentVersion), latestVersion) < 0 {
		checkResult.HasUpdate = true
	}

	outputJSON(checkResult)

	if !checkResult.HasUpdate {
		outputJSON(UpdateResult{
			Type:    jsonTypeUpdateResult,
			Status:  "success",
			Applied: false,
			Message: "已是最新版本",
		})
		return
	}

	if cfg.Check {
		outputJSON(UpdateResult{
			Type:    jsonTypeUpdateResult,
			Status:  "success",
			Applied: false,
			Message: "发现新版本: " + latestVersion,
		})
		return
	}

	updateResult, err := runUpdate(ctx, client, cfg, installDir, asset, latestVersion)
	if err != nil {
		updateResult.Status = "failed"
		if updateResult.Message == "" {
			updateResult.Message = err.Error()
		}
	}
	outputJSON(updateResult)
}

func parseFlags() Config {
	cfg := Config{}
	flag.StringVar(&cfg.Repo, "repo", defaultRepo, "GitHub owner/repo")
	flag.StringVar(&cfg.Proxy, "proxy", "", "HTTP 代理，例如 http://127.0.0.1:7890")
	flag.BoolVar(&cfg.Check, "check", false, "仅检查更新")
	flag.Parse()
	return cfg
}

func resolveCurrentVersion(installDir string) (string, error) {
	versionPath := filepath.Join(installDir, defaultVersionFile)
	data, err := os.ReadFile(versionPath)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return "v0.0.0", nil
		}
		return "", fmt.Errorf("读取版本文件失败: %w", err)
	}
	version := strings.TrimSpace(string(data))
	if version == "" {
		return "v0.0.0", nil
	}
	return normalizeVersion(version), nil
}

func normalizeVersion(version string) string {
	v := strings.TrimSpace(version)
	if v == "" {
		return "v0.0.0"
	}
	if !strings.HasPrefix(v, "v") {
		return "v" + v
	}
	return v
}

func detectPlatform() (string, string) {
	platform := "linux"
	arch := "x64"
	switch runtime.GOOS {
	case "windows":
		platform = "win"
	case "darwin":
		platform = "osx"
	case "linux":
		platform = "linux"
	default:
		platform = runtime.GOOS
	}

	switch runtime.GOARCH {
	case "amd64":
		arch = "x64"
	case "arm64":
		arch = "arm64"
	default:
		arch = runtime.GOARCH
	}

	return platform, arch
}

func fetchLatestRelease(ctx context.Context, client *http.Client, cfg Config) (Release, error) {
	repo := strings.TrimSpace(cfg.Repo)
	if repo == "" {
		return Release{}, errors.New("缺少 --repo 参数")
	}
	parts := strings.Split(repo, "/")
	if len(parts) != 2 {
		return Release{}, fmt.Errorf("非法 repo 格式: %s", repo)
	}
	url := fmt.Sprintf("https://api.github.com/repos/%s/releases/latest", repo)

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return Release{}, err
	}
	req.Header.Set("Accept", "application/vnd.github+json")
	req.Header.Set("User-Agent", "mwu-updater")

	resp, err := client.Do(req)
	if err != nil {
		return Release{}, fmt.Errorf("请求 GitHub 失败: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		body, _ := io.ReadAll(resp.Body)
		return Release{}, fmt.Errorf("GitHub 返回错误: %s", strings.TrimSpace(string(body)))
	}

	var release Release
	if err := json.NewDecoder(resp.Body).Decode(&release); err != nil {
		return Release{}, fmt.Errorf("解析 Release 失败: %w", err)
	}
	if release.TagName == "" {
		return Release{}, errors.New("Release 缺少 tag_name")
	}
	return release, nil
}

func selectAsset(assets []ReleaseAsset, platform, arch string) (ReleaseAsset, error) {
	suffix := fmt.Sprintf("-%s-%s.7z", platform, arch)
	for _, asset := range assets {
		if strings.HasSuffix(asset.Name, suffix) {
			return asset, nil
		}
	}
	return ReleaseAsset{}, fmt.Errorf("未找到匹配资产: *%s", suffix)
}

func runUpdate(ctx context.Context, client *http.Client, cfg Config, installDir string, asset ReleaseAsset, latestVersion string) (UpdateResult, error) {
	updateResult := UpdateResult{
		Type:    jsonTypeUpdateResult,
		Status:  "failed",
		Applied: false,
	}

	downloadPath := filepath.Join(installDir, asset.Name)
	if err := downloadAsset(ctx, client, asset.URL, downloadPath); err != nil {
		updateResult.Message = "更新包下载失败"
		return updateResult, err
	}
	defer os.Remove(downloadPath)

	extractDir := filepath.Join(installDir, "update")
	if err := os.MkdirAll(extractDir, 0o755); err != nil {
		return updateResult, fmt.Errorf("创建解压目录失败: %w", err)
	}
	defer os.RemoveAll(extractDir)

	if err := extractArchive(ctx, downloadPath, extractDir); err != nil {
		updateResult.Message = "解压失败"
		return updateResult, err
	}

	selfUpdateResult, err := handleSelfUpdate(installDir, extractDir)
	if err != nil {
		updateResult.Message = "自更新失败"
		return updateResult, err
	}
	if selfUpdateResult.SelfUpdatePending {
		updateResult.SelfUpdatePending = true
		updateResult.RestartRequired = true
		updateResult.Status = "self_update_pending"
		updateResult.Message = "更新器已准备更新，请重启后再继续"
		return updateResult, nil
	}

	changes, err := diffDirectories(ctx, installDir, extractDir, []string{"update", asset.Name})
	if err != nil {
		updateResult.Message = "差异计算失败"
		return updateResult, err
	}

	changesPath := filepath.Join(installDir, defaultChangesFile)
	if err := writeChanges(changesPath, changes); err != nil {
		updateResult.Message = "写入 changes.json 失败"
		return updateResult, err
	}
	updateResult.ChangesPath = changesPath

	err = applyChanges(installDir, extractDir, changes)
	if err != nil {
		updateResult.Message = "应用更新失败"
		return updateResult, err
	}

	if err := os.WriteFile(filepath.Join(installDir, defaultVersionFile), []byte(latestVersion+"\n"), 0o644); err != nil {
		updateResult.Message = "更新版本文件失败"
		return updateResult, err
	}

	updateResult.Status = "success"
	updateResult.Applied = true
	updateResult.Message = "更新完成"
	return updateResult, nil
}

func downloadAsset(ctx context.Context, client *http.Client, assetURL, outputPath string) error {
	const maxRetries = 3
	var lastErr error

	for i := 1; i <= maxRetries; i++ {
		err := func() error {
			req, err := http.NewRequestWithContext(ctx, http.MethodGet, assetURL, nil)
			if err != nil {
				return err
			}
			req.Header.Set("User-Agent", "mwu-updater")

			resp, err := client.Do(req)
			if err != nil {
				return err
			}
			defer resp.Body.Close()

			if resp.StatusCode < 200 || resp.StatusCode >= 300 {
				body, _ := io.ReadAll(resp.Body)
				return fmt.Errorf("HTTP %d: %s", resp.StatusCode, strings.TrimSpace(string(body)))
			}

			out, err := os.Create(outputPath)
			if err != nil {
				return err
			}
			defer out.Close()

			_, err = io.Copy(out, resp.Body)
			return err
		}()

		if err == nil {
			return nil
		}
		lastErr = err

		if ctx.Err() != nil {
			return ctx.Err()
		}
	}

	return fmt.Errorf("在重试 %d 次后依然失败: %w", maxRetries, lastErr)
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
		return errors.New("不支持的压缩格式")
	}

	return extractor.Extract(ctx, reader, func(ctx context.Context, f archives.FileInfo) error {
		if f.NameInArchive == "" {
			return nil
		}
		outPath, err := safeJoin(destDir, f.NameInArchive)
		if err != nil {
			return err
		}
		if f.IsDir() {
			return os.MkdirAll(outPath, 0o755)
		}
		if !f.Mode().IsRegular() {
			return fmt.Errorf("不支持的文件类型: %s", f.NameInArchive)
		}

		if err := os.MkdirAll(filepath.Dir(outPath), 0o755); err != nil {
			return err
		}
		reader, err := f.Open()
		if err != nil {
			return err
		}
		defer reader.Close()
		outFile, err := os.OpenFile(outPath, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, f.Mode())
		if err != nil {
			return err
		}
		defer outFile.Close()
		_, err = io.Copy(outFile, reader)
		return err
	})
}

func safeJoin(baseDir, name string) (string, error) {
	cleanName := path.Clean(name)
	if cleanName == "" || cleanName == "." {
		return "", errors.New("非法路径")
	}
	joined := filepath.Join(baseDir, filepath.FromSlash(cleanName))
	baseClean := filepath.Clean(baseDir) + string(os.PathSeparator)
	joinedClean := filepath.Clean(joined)
	if !strings.HasPrefix(joinedClean+string(os.PathSeparator), baseClean) {
		return "", fmt.Errorf("非法路径: %s", name)
	}
	return joinedClean, nil
}

func handleSelfUpdate(installDir string, extractDir string) (UpdateResult, error) {
	result := UpdateResult{}
	exePath, err := os.Executable()
	if err != nil {
		return result, nil
	}
	relPath, err := filepath.Rel(installDir, exePath)
	if err != nil || strings.HasPrefix(relPath, "..") {
		return result, nil
	}
	candidate := filepath.Join(extractDir, relPath)
	if _, err := os.Stat(candidate); err != nil {
		return result, nil
	}

	currentHash, err := hashFile(exePath)
	if err != nil {
		return result, nil
	}
	candidateHash, err := hashFile(candidate)
	if err != nil {
		return result, nil
	}
	if currentHash == candidateHash {
		return result, nil
	}

	if runtime.GOOS == "windows" {
		pendingPath := exePath + ".new"
		mode := os.FileMode(0o755)
		if info, err := os.Stat(candidate); err == nil {
			mode = info.Mode()
		}
		if err := copyFile(candidate, pendingPath, mode); err != nil {
			return result, err
		}
		result.SelfUpdatePending = true
		return result, nil
	}

	backupPath := exePath + ".old"
	_ = os.Remove(backupPath)
	if err := os.Rename(exePath, backupPath); err != nil {
		return result, err
	}
	if err := os.Rename(candidate, exePath); err != nil {
		_ = os.Rename(backupPath, exePath)
		return result, err
	}
	_ = os.Remove(backupPath)
	return result, nil
}

func diffDirectories(ctx context.Context, installDir, extractDir string, ignores []string) (Changes, error) {
	installFiles, err := listFiles(installDir, ignores)
	if err != nil {
		return Changes{}, err
	}
	extractFiles, err := listFiles(extractDir, nil)
	if err != nil {
		return Changes{}, err
	}

	installHashes, err := hashFiles(ctx, installDir, installFiles)
	if err != nil {
		return Changes{}, err
	}
	extractHashes, err := hashFiles(ctx, extractDir, extractFiles)
	if err != nil {
		return Changes{}, err
	}

	changes := Changes{}
	for rel := range extractHashes {
		if _, ok := installHashes[rel]; !ok {
			changes.Added = append(changes.Added, rel)
		}
	}
	for rel := range installHashes {
		if _, ok := extractHashes[rel]; !ok {
			changes.Deleted = append(changes.Deleted, rel)
		}
	}
	for rel, newHash := range extractHashes {
		if oldHash, ok := installHashes[rel]; ok {
			if oldHash.Hash != newHash.Hash {
				changes.Modified = append(changes.Modified, rel)
			}
		}
	}

	sort.Strings(changes.Added)
	sort.Strings(changes.Deleted)
	sort.Strings(changes.Modified)
	return changes, nil
}

func listFiles(root string, ignores []string) ([]string, error) {
	var files []string
	ignoreMap := make(map[string]bool)
	for _, ig := range ignores {
		ignoreMap[filepath.ToSlash(ig)] = true
	}

	err := filepath.WalkDir(root, func(fullPath string, entry os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(root, fullPath)
		if err != nil {
			return err
		}
		rel = filepath.ToSlash(rel)

		if ignoreMap[rel] {
			if entry.IsDir() {
				return filepath.SkipDir
			}
			return nil
		}

		if entry.IsDir() {
			return nil
		}
		if rel == defaultChangesFile {
			return nil
		}
		files = append(files, rel)
		return nil
	})
	return files, err
}

func hashFiles(ctx context.Context, root string, files []string) (map[string]FileHash, error) {
	results := make(map[string]FileHash, len(files))
	if len(files) == 0 {
		return results, nil
	}

	workerCount := runtime.NumCPU() / 2
	if workerCount < 1 {
		workerCount = 1
	}
	if workerCount > 8 {
		workerCount = 8
	}
	jobs := make(chan string)
	var wg sync.WaitGroup
	var mu sync.Mutex
	var firstErr error
	var errMu sync.Mutex

	worker := func() {
		defer wg.Done()
		for rel := range jobs {
			if ctx.Err() != nil {
				return
			}
			fullPath := filepath.Join(root, filepath.FromSlash(rel))
			hashValue, err := hashFile(fullPath)
			if err != nil {
				errMu.Lock()
				if firstErr == nil {
					firstErr = err
				}
				errMu.Unlock()
				return
			}
			mu.Lock()
			results[rel] = FileHash{Hash: hashValue}
			mu.Unlock()
		}
	}

	wg.Add(workerCount)
	for i := 0; i < workerCount; i++ {
		go worker()
	}

	for _, rel := range files {
		errMu.Lock()
		if firstErr != nil {
			errMu.Unlock()
			break
		}
		errMu.Unlock()
		jobs <- rel
	}
	close(jobs)
	wg.Wait()

	if firstErr != nil {
		return nil, firstErr
	}
	return results, nil
}

func hashFile(path string) (string, error) {
	file, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer file.Close()

	hasher := xxh3.New128()
	if _, err := io.Copy(hasher, file); err != nil {
		return "", err
	}
	sum := hasher.Sum128()
	return fmt.Sprintf("%016x%016x", sum.Hi, sum.Lo), nil
}

func applyChanges(installDir, extractDir string, changes Changes) error {
	backupDir, err := os.MkdirTemp(installDir, "update-backup-")
	if err != nil {
		return err
	}
	rollbackNeeded := false
	defer func() {
		if !rollbackNeeded {
			_ = os.RemoveAll(backupDir)
		}
	}()

	rollback := func() {
		rollbackNeeded = true
		_ = filepath.WalkDir(backupDir, func(fullPath string, entry os.DirEntry, err error) error {
			if err != nil {
				return err
			}
			if entry.IsDir() {
				return nil
			}
			rel, err := filepath.Rel(backupDir, fullPath)
			if err != nil {
				return err
			}
			target := filepath.Join(installDir, rel)
			_ = os.MkdirAll(filepath.Dir(target), 0o755)
			_ = os.Rename(fullPath, target)
			return nil
		})
	}

	copyWithBackup := func(rel string, mode os.FileMode) error {
		installPath := filepath.Join(installDir, filepath.FromSlash(rel))
		extractPath := filepath.Join(extractDir, filepath.FromSlash(rel))

		if _, err := os.Stat(installPath); err == nil {
			backupPath := filepath.Join(backupDir, filepath.FromSlash(rel))
			if err := os.MkdirAll(filepath.Dir(backupPath), 0o755); err != nil {
				return err
			}
			if err := os.Rename(installPath, backupPath); err != nil {
				return err
			}
		}

		if err := os.MkdirAll(filepath.Dir(installPath), 0o755); err != nil {
			return err
		}
		return copyFile(extractPath, installPath, mode)
	}

	for _, rel := range append(changes.Added, changes.Modified...) {
		src := filepath.Join(extractDir, filepath.FromSlash(rel))
		info, err := os.Stat(src)
		if err != nil {
			rollback()
			return err
		}
		if err := copyWithBackup(rel, info.Mode()); err != nil {
			rollback()
			return err
		}
	}

	for _, rel := range changes.Deleted {
		installPath := filepath.Join(installDir, filepath.FromSlash(rel))
		if _, err := os.Stat(installPath); err != nil {
			continue
		}
		backupPath := filepath.Join(backupDir, filepath.FromSlash(rel))
		if err := os.MkdirAll(filepath.Dir(backupPath), 0o755); err != nil {
			rollback()
			return err
		}
		if err := os.Rename(installPath, backupPath); err != nil {
			rollback()
			return err
		}
	}

	rollbackNeeded = false
	_ = os.RemoveAll(backupDir)

	_ = removeEmptyDirs(installDir)

	return nil
}

func removeEmptyDirs(root string) error {
	var dirs []string
	_ = filepath.WalkDir(root, func(p string, d os.DirEntry, err error) error {
		if err == nil && d.IsDir() && p != root {
			dirs = append(dirs, p)
		}
		return nil
	})

	sort.Slice(dirs, func(i, j int) bool {
		return len(dirs[i]) > len(dirs[j])
	})

	for _, d := range dirs {
		entries, err := os.ReadDir(d)
		if err == nil && len(entries) == 0 {
			_ = os.Remove(d)
		}
	}
	return nil
}

func copyFile(src, dst string, mode os.FileMode) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()

	tmp, err := os.CreateTemp(filepath.Dir(dst), ".tmp-*")
	if err != nil {
		return err
	}
	defer func() {
		_ = tmp.Close()
		_ = os.Remove(tmp.Name())
	}()

	if _, err := io.Copy(tmp, in); err != nil {
		return err
	}
	if err := tmp.Chmod(mode); err != nil {
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	return os.Rename(tmp.Name(), dst)
}

func writeChanges(path string, changes Changes) error {
	data, err := json.MarshalIndent(changes, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(path, data, 0o644)
}

func newHTTPClient(proxy string) (*http.Client, error) {
	transport := &http.Transport{}
	proxy = strings.TrimSpace(proxy)
	if proxy != "" {
		proxyURL, err := url.Parse(proxy)
		if err != nil {
			return nil, fmt.Errorf("代理地址无效: %w", err)
		}
		transport.Proxy = http.ProxyURL(proxyURL)
	}
	return &http.Client{Timeout: defaultHTTPTimeout, Transport: transport}, nil
}

func outputJSON(v any) {
	data, err := json.Marshal(v)
	if err != nil {
		fallback := map[string]string{"type": "error", "status": "failed", "message": err.Error()}
		data, _ = json.Marshal(fallback)
	}
	fmt.Println(string(data))
}
