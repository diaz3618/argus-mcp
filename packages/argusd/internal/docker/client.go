// Package docker wraps the Docker Engine API client and provides
// container lifecycle, event streaming, log tailing, and stats
// aggregation for Argus-managed containers.
package docker

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"strings"
	"sync"
	"time"

	"github.com/docker/docker/api/types"
	"github.com/docker/docker/api/types/container"
	"github.com/docker/docker/api/types/events"
	"github.com/docker/docker/api/types/filters"
	"github.com/docker/docker/client"

	"github.com/diaz3618/argus-mcp/packages/argusd/internal/labels"
)

// Client wraps the Docker API client and exposes Argus-scoped operations.
type Client struct {
	cli *client.Client
	mu  sync.RWMutex
}

// NewClient creates a Docker client from environment settings.
func NewClient() (*Client, error) {
	cli, err := client.NewClientWithOpts(
		client.FromEnv,
		client.WithAPIVersionNegotiation(),
	)
	if err != nil {
		return nil, fmt.Errorf("docker client: %w", err)
	}
	return &Client{cli: cli}, nil
}

// Close releases the Docker client resources.
func (c *Client) Close() error {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.cli.Close()
}

// Ping checks Docker daemon connectivity.
func (c *Client) Ping(ctx context.Context) error {
	c.mu.RLock()
	defer c.mu.RUnlock()
	_, err := c.cli.Ping(ctx)
	return err
}

// ContainerInfo is a simplified container representation.
type ContainerInfo struct {
	ID        string            `json:"id"`
	Name      string            `json:"name"`
	Image     string            `json:"image"`
	State     string            `json:"state"`
	Status    string            `json:"status"`
	Created   time.Time         `json:"created"`
	Labels    map[string]string `json:"labels"`
	Ports     []PortBinding     `json:"ports,omitempty"`
	NetworkID string            `json:"network_id,omitempty"`
}

// PortBinding describes a container port mapping.
type PortBinding struct {
	Container uint16 `json:"container"`
	Host      uint16 `json:"host,omitempty"`
	Protocol  string `json:"protocol"`
}

// ListContainers returns all Argus-managed containers.
func (c *Client) ListContainers(ctx context.Context) ([]ContainerInfo, error) {
	c.mu.RLock()
	defer c.mu.RUnlock()

	f := filters.NewArgs()
	f.Add("label", labels.Selector())

	containers, err := c.cli.ContainerList(ctx, container.ListOptions{
		All:     true,
		Filters: f,
	})
	if err != nil {
		return nil, fmt.Errorf("list containers: %w", err)
	}

	result := make([]ContainerInfo, 0, len(containers))
	for _, ctr := range containers {
		name := ""
		if len(ctr.Names) > 0 {
			name = strings.TrimPrefix(ctr.Names[0], "/")
		}
		ports := make([]PortBinding, 0, len(ctr.Ports))
		for _, p := range ctr.Ports {
			ports = append(ports, PortBinding{
				Container: p.PrivatePort,
				Host:      p.PublicPort,
				Protocol:  p.Type,
			})
		}
		result = append(result, ContainerInfo{
			ID:      ctr.ID[:12],
			Name:    name,
			Image:   ctr.Image,
			State:   ctr.State,
			Status:  ctr.Status,
			Created: time.Unix(ctr.Created, 0),
			Labels:  ctr.Labels,
			Ports:   ports,
		})
	}
	return result, nil
}

// InspectContainer returns detailed information for a container.
func (c *Client) InspectContainer(ctx context.Context, id string) (*types.ContainerJSON, error) {
	c.mu.RLock()
	defer c.mu.RUnlock()

	info, err := c.cli.ContainerInspect(ctx, id)
	if err != nil {
		return nil, fmt.Errorf("inspect %s: %w", id, err)
	}
	// Verify it's Argus-managed.
	if info.Config == nil || info.Config.Labels[labels.Managed] != labels.ManagedValue {
		return nil, fmt.Errorf("container %s is not Argus-managed", id)
	}
	return &info, nil
}

// StartContainer starts a stopped container.
func (c *Client) StartContainer(ctx context.Context, id string) error {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.cli.ContainerStart(ctx, id, container.StartOptions{})
}

// StopContainer stops a running container with a timeout.
func (c *Client) StopContainer(ctx context.Context, id string, timeoutSec int) error {
	c.mu.RLock()
	defer c.mu.RUnlock()
	timeout := timeoutSec
	return c.cli.ContainerStop(ctx, id, container.StopOptions{Timeout: &timeout})
}

// RestartContainer restarts a container.
func (c *Client) RestartContainer(ctx context.Context, id string, timeoutSec int) error {
	c.mu.RLock()
	defer c.mu.RUnlock()
	timeout := timeoutSec
	return c.cli.ContainerRestart(ctx, id, container.StopOptions{Timeout: &timeout})
}

// RemoveContainer removes a container (force).
func (c *Client) RemoveContainer(ctx context.Context, id string) error {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.cli.ContainerRemove(ctx, id, container.RemoveOptions{Force: true})
}

// LogEntry represents a single log line from a container.
type LogEntry struct {
	Timestamp time.Time `json:"timestamp"`
	Stream    string    `json:"stream"` // "stdout" or "stderr"
	Message   string    `json:"message"`
}

// StreamLogs streams container logs. Sends LogEntry JSON lines to the
// writer until the context is cancelled or the stream ends.
func (c *Client) StreamLogs(ctx context.Context, id string, follow bool, since string, tail string, w io.Writer) error {
	c.mu.RLock()
	cli := c.cli
	c.mu.RUnlock()

	opts := container.LogsOptions{
		ShowStdout: true,
		ShowStderr: true,
		Follow:     follow,
		Timestamps: true,
		Tail:       tail,
	}
	if since != "" {
		opts.Since = since
	}
	if tail == "" {
		opts.Tail = "100"
	}

	rc, err := cli.ContainerLogs(ctx, id, opts)
	if err != nil {
		return fmt.Errorf("logs %s: %w", id, err)
	}
	defer rc.Close()

	// Docker multiplexes stdout/stderr in an 8-byte header per frame.
	header := make([]byte, 8)
	enc := json.NewEncoder(w)

	for {
		_, err := io.ReadFull(rc, header)
		if err != nil {
			if err == io.EOF || ctx.Err() != nil {
				return nil
			}
			return err
		}

		stream := "stdout"
		if header[0] == 2 {
			stream = "stderr"
		}

		size := int64(header[4])<<24 | int64(header[5])<<16 | int64(header[6])<<8 | int64(header[7])
		payload := make([]byte, size)
		if _, err := io.ReadFull(rc, payload); err != nil {
			return err
		}

		line := strings.TrimRight(string(payload), "\n")
		// Parse timestamp from Docker log format: "2026-01-01T00:00:00.000000000Z message"
		var ts time.Time
		msg := line
		if idx := strings.IndexByte(line, ' '); idx > 0 {
			if t, err := time.Parse(time.RFC3339Nano, line[:idx]); err == nil {
				ts = t
				msg = line[idx+1:]
			}
		}

		entry := LogEntry{
			Timestamp: ts,
			Stream:    stream,
			Message:   msg,
		}
		if err := enc.Encode(entry); err != nil {
			return err
		}
		if f, ok := w.(interface{ Flush() }); ok {
			f.Flush()
		}
	}
}

// StatsSnapshot holds a point-in-time resource usage snapshot.
type StatsSnapshot struct {
	Timestamp   time.Time `json:"timestamp"`
	ContainerID string    `json:"container_id"`
	CPUPercent  float64   `json:"cpu_percent"`
	MemoryUsage uint64    `json:"memory_usage"`
	MemoryLimit uint64    `json:"memory_limit"`
	MemoryPct   float64   `json:"memory_percent"`
	NetRxBytes  uint64    `json:"net_rx_bytes"`
	NetTxBytes  uint64    `json:"net_tx_bytes"`
	BlockRead   uint64    `json:"block_read"`
	BlockWrite  uint64    `json:"block_write"`
	PidsCurrent uint64    `json:"pids_current"`
}

// StreamStats streams container resource stats as JSON lines. The daemon
// keeps this open, pushing ~1 snapshot/second until the context cancels.
func (c *Client) StreamStats(ctx context.Context, id string, w io.Writer) error {
	c.mu.RLock()
	cli := c.cli
	c.mu.RUnlock()

	resp, err := cli.ContainerStats(ctx, id, true)
	if err != nil {
		return fmt.Errorf("stats %s: %w", id, err)
	}
	defer resp.Body.Close()

	dec := json.NewDecoder(resp.Body)
	enc := json.NewEncoder(w)
	var prev container.StatsResponse

	for dec.More() {
		var raw container.StatsResponse
		if err := dec.Decode(&raw); err != nil {
			if ctx.Err() != nil {
				return nil
			}
			return err
		}

		snap := computeStats(id, &raw, &prev)
		prev = raw

		if err := enc.Encode(snap); err != nil {
			return err
		}
		if f, ok := w.(interface{ Flush() }); ok {
			f.Flush()
		}
	}
	return nil
}

func computeStats(id string, cur, prev *container.StatsResponse) StatsSnapshot {
	snap := StatsSnapshot{
		Timestamp:   time.Now(),
		ContainerID: id[:12],
		MemoryUsage: cur.MemoryStats.Usage,
		MemoryLimit: cur.MemoryStats.Limit,
		PidsCurrent: cur.PidsStats.Current,
	}

	if cur.MemoryStats.Limit > 0 {
		snap.MemoryPct = float64(cur.MemoryStats.Usage) / float64(cur.MemoryStats.Limit) * 100.0
	}

	// CPU percentage calculation.
	cpuDelta := float64(cur.CPUStats.CPUUsage.TotalUsage - prev.CPUStats.CPUUsage.TotalUsage)
	sysDelta := float64(cur.CPUStats.SystemUsage - prev.CPUStats.SystemUsage)
	if sysDelta > 0 && cpuDelta > 0 {
		cpuCount := float64(cur.CPUStats.OnlineCPUs)
		if cpuCount == 0 {
			cpuCount = float64(len(cur.CPUStats.CPUUsage.PercpuUsage))
		}
		if cpuCount == 0 {
			cpuCount = 1
		}
		snap.CPUPercent = (cpuDelta / sysDelta) * cpuCount * 100.0
	}

	// Network I/O (aggregate across all interfaces).
	for _, netStat := range cur.Networks {
		snap.NetRxBytes += netStat.RxBytes
		snap.NetTxBytes += netStat.TxBytes
	}

	// Block I/O.
	for _, bio := range cur.BlkioStats.IoServiceBytesRecursive {
		switch bio.Op {
		case "read", "Read":
			snap.BlockRead += bio.Value
		case "write", "Write":
			snap.BlockWrite += bio.Value
		}
	}

	return snap
}

// StreamEvents streams Docker events for Argus-managed containers.
// Each event is written as a JSON line to w.
func (c *Client) StreamEvents(ctx context.Context, w io.Writer) error {
	c.mu.RLock()
	cli := c.cli
	c.mu.RUnlock()

	f := filters.NewArgs()
	f.Add("label", labels.Selector())
	f.Add("type", string(events.ContainerEventType))

	msgCh, errCh := cli.Events(ctx, events.ListOptions{Filters: f})
	enc := json.NewEncoder(w)

	for {
		select {
		case <-ctx.Done():
			return nil
		case err := <-errCh:
			if ctx.Err() != nil {
				return nil
			}
			return err
		case msg := <-msgCh:
			event := map[string]interface{}{
				"type":      msg.Type,
				"action":    msg.Action,
				"actor_id":  msg.Actor.ID[:12],
				"actor":     msg.Actor.Attributes,
				"timestamp": time.Unix(msg.Time, msg.TimeNano),
			}
			if err := enc.Encode(event); err != nil {
				return err
			}
			if f, ok := w.(interface{ Flush() }); ok {
				f.Flush()
			}
		}
	}
}
