package docker

import (
	"testing"

	"github.com/docker/docker/api/types/container"
)

func TestSafeShortID(t *testing.T) {
	tests := []struct {
		name string
		id   string
		want string
	}{
		{"long id", "abcdef123456789xyz", "abcdef123456"},
		{"exactly 12", "abcdef123456", "abcdef123456"},
		{"short id", "abc", "abc"},
		{"empty", "", ""},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			got := safeShortID(tc.id)
			if got != tc.want {
				t.Errorf("safeShortID(%q) = %q, want %q", tc.id, got, tc.want)
			}
		})
	}
}

func TestComputeStats_Basic(t *testing.T) {
	cur := &container.StatsResponse{}
	cur.MemoryStats.Usage = 1024 * 1024
	cur.MemoryStats.Limit = 4 * 1024 * 1024
	cur.PidsStats.Current = 5
	cur.CPUStats.CPUUsage.TotalUsage = 200
	cur.CPUStats.SystemUsage = 1000
	cur.CPUStats.OnlineCPUs = 2

	prev := &container.StatsResponse{}
	prev.CPUStats.CPUUsage.TotalUsage = 100
	prev.CPUStats.SystemUsage = 500

	snap := computeStats("abcdef1234567890", cur, prev)

	if snap.ContainerID != "abcdef123456" {
		t.Errorf("ContainerID = %q, want %q", snap.ContainerID, "abcdef123456")
	}
	if snap.MemoryUsage != 1024*1024 {
		t.Errorf("MemoryUsage = %d, want %d", snap.MemoryUsage, 1024*1024)
	}
	if snap.MemoryLimit != 4*1024*1024 {
		t.Errorf("MemoryLimit = %d, want %d", snap.MemoryLimit, 4*1024*1024)
	}
	if snap.PidsCurrent != 5 {
		t.Errorf("PidsCurrent = %d, want 5", snap.PidsCurrent)
	}

	// MemoryPct = 1MB / 4MB * 100 = 25%
	if snap.MemoryPct < 24.9 || snap.MemoryPct > 25.1 {
		t.Errorf("MemoryPct = %f, want ~25.0", snap.MemoryPct)
	}

	// CPU: (200-100)/(1000-500) * 2 * 100 = 40%
	if snap.CPUPercent < 39.9 || snap.CPUPercent > 40.1 {
		t.Errorf("CPUPercent = %f, want ~40.0", snap.CPUPercent)
	}
}

func TestComputeStats_ZeroPrev(t *testing.T) {
	// Both cur and prev at zero — should not panic
	cur := &container.StatsResponse{}
	prev := &container.StatsResponse{}

	snap := computeStats("short", cur, prev)

	if snap.ContainerID != "short" {
		t.Errorf("ContainerID = %q, want %q", snap.ContainerID, "short")
	}
	if snap.CPUPercent != 0 {
		t.Errorf("CPUPercent = %f, want 0", snap.CPUPercent)
	}
	if snap.MemoryPct != 0 {
		t.Errorf("MemoryPct = %f, want 0", snap.MemoryPct)
	}
}

func TestComputeStats_NetworkIO(t *testing.T) {
	cur := &container.StatsResponse{
		Networks: map[string]container.NetworkStats{
			"eth0": {RxBytes: 100, TxBytes: 200},
			"eth1": {RxBytes: 50, TxBytes: 50},
		},
	}
	prev := &container.StatsResponse{}

	snap := computeStats("netid0123456789", cur, prev)

	if snap.NetRxBytes != 150 {
		t.Errorf("NetRxBytes = %d, want 150", snap.NetRxBytes)
	}
	if snap.NetTxBytes != 250 {
		t.Errorf("NetTxBytes = %d, want 250", snap.NetTxBytes)
	}
}

func TestComputeStats_BlockIO(t *testing.T) {
	cur := &container.StatsResponse{}
	cur.BlkioStats.IoServiceBytesRecursive = []container.BlkioStatEntry{
		{Op: "read", Value: 1000},
		{Op: "Read", Value: 500},
		{Op: "write", Value: 2000},
		{Op: "Write", Value: 300},
		{Op: "sync", Value: 999}, // should be ignored
	}
	prev := &container.StatsResponse{}

	snap := computeStats("blkid012345678", cur, prev)

	if snap.BlockRead != 1500 {
		t.Errorf("BlockRead = %d, want 1500", snap.BlockRead)
	}
	if snap.BlockWrite != 2300 {
		t.Errorf("BlockWrite = %d, want 2300", snap.BlockWrite)
	}
}

func TestComputeStats_FallbackCPUCount(t *testing.T) {
	// OnlineCPUs = 0, PercpuUsage has entries → should use len(PercpuUsage)
	cur := &container.StatsResponse{}
	cur.CPUStats.CPUUsage.TotalUsage = 300
	cur.CPUStats.SystemUsage = 1000
	cur.CPUStats.OnlineCPUs = 0
	cur.CPUStats.CPUUsage.PercpuUsage = []uint64{100, 200}

	prev := &container.StatsResponse{}
	prev.CPUStats.CPUUsage.TotalUsage = 100
	prev.CPUStats.SystemUsage = 500

	snap := computeStats("cpuid012345678", cur, prev)

	// (300-100)/(1000-500) * 2 * 100 = 80%
	if snap.CPUPercent < 79.9 || snap.CPUPercent > 80.1 {
		t.Errorf("CPUPercent = %f, want ~80.0", snap.CPUPercent)
	}
}
