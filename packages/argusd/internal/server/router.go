package server

import (
	"net/http"

	"github.com/diaz3618/argus-mcp/packages/argusd/internal/docker"
	"github.com/diaz3618/argus-mcp/packages/argusd/internal/k8s"
)

// Handler holds dependencies for route handlers.
type Handler struct {
	Docker docker.DockerClient
	K8s    *k8s.Client
}

// NewRouter returns a configured HTTP handler for the argusd API.
func NewRouter(h *Handler) http.Handler {
	mux := http.NewServeMux()

	// Health
	mux.HandleFunc("GET /v1/health", h.Health)

	// Docker containers
	mux.HandleFunc("GET /v1/containers", h.ListContainers)
	mux.HandleFunc("GET /v1/containers/{id}", h.InspectContainer)
	mux.HandleFunc("POST /v1/containers/{id}/start", h.StartContainer)
	mux.HandleFunc("POST /v1/containers/{id}/stop", h.StopContainer)
	mux.HandleFunc("POST /v1/containers/{id}/restart", h.RestartContainer)
	mux.HandleFunc("POST /v1/containers/{id}/remove", h.RemoveContainer)
	mux.HandleFunc("GET /v1/containers/{id}/logs", h.ContainerLogs)
	mux.HandleFunc("GET /v1/containers/{id}/stats", h.ContainerStats)

	// Docker events
	mux.HandleFunc("GET /v1/events", h.DockerEvents)

	// Kubernetes pods (only registered if k8s is available)
	if h.K8s != nil && h.K8s.Available() {
		mux.HandleFunc("GET /v1/pods", h.ListPods)
		mux.HandleFunc("GET /v1/pods/{ns}/{name}", h.DescribePod)
		mux.HandleFunc("DELETE /v1/pods/{ns}/{name}", h.DeletePod)
		mux.HandleFunc("GET /v1/pods/{ns}/{name}/logs", h.PodLogs)
		mux.HandleFunc("GET /v1/pods/{ns}/{name}/events", h.PodEvents)
		mux.HandleFunc("POST /v1/deployments/{ns}/{name}/restart", h.RolloutRestart)
	}

	return mux
}
