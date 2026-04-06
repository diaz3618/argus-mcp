package docker

import (
	"context"
	"io"

	"github.com/docker/docker/api/types"
)

// DockerClient defines the operations that handlers need from a Docker client.
// This allows test doubles to be injected in handler tests.
type DockerClient interface {
	Ping(ctx context.Context) error
	ListContainers(ctx context.Context) ([]ContainerInfo, error)
	InspectContainer(ctx context.Context, id string) (*types.ContainerJSON, error)
	StartContainer(ctx context.Context, id string) error
	StopContainer(ctx context.Context, id string, timeoutSec int) error
	RestartContainer(ctx context.Context, id string, timeoutSec int) error
	RemoveContainer(ctx context.Context, id string) error
	StreamLogs(ctx context.Context, id string, follow bool, since string, tail string, w io.Writer) error
	StreamStats(ctx context.Context, id string, w io.Writer) error
	StreamEvents(ctx context.Context, w io.Writer) error
	Close() error
}

// Compile-time check that *Client satisfies DockerClient.
var _ DockerClient = (*Client)(nil)
