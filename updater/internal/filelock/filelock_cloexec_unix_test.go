//go:build unix

package filelock

import (
	"os"
	"path/filepath"
	"testing"

	"golang.org/x/sys/unix"
)

func TestOpenUsesCLOEXEC(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "cloexec.lock")
	l, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer l.Close()

	fd := l.plat.fd
	if fd < 0 {
		t.Fatal("invalid fd")
	}
	flags, err := unix.FcntlInt(uintptr(fd), unix.F_GETFD, 0)
	if err != nil {
		t.Fatalf("F_GETFD: %v", err)
	}
	if flags&unix.FD_CLOEXEC == 0 {
		t.Fatalf("lock fd missing CLOEXEC: flags=%#x", flags)
	}
	if _, err := os.Stat(path); err != nil {
		t.Fatal(err)
	}
}
