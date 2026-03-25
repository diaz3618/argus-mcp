package server

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strconv"
	"time"
)

// ───────────────────────── Health ────────────────────────────

// Health reports daemon readiness.
func (h *Handler) Health(w http.ResponseWriter, r *http.Request) {
	resp := map[string]interface{}{
		"status":    "ok",
		"timestamp": time.Now().UTC(),
		"docker":    true,
		"k8s":       h.K8s != nil && h.K8s.Available(),
	}
	respondJSON(w, http.StatusOK, resp)
}

// ───────────────────── Docker Containers ─────────────────────

// ListContainers returns all Argus-managed containers.
func (h *Handler) ListContainers(w http.ResponseWriter, r *http.Request) {
	containers, err := h.Docker.ListContainers(r.Context())
	if err != nil {
		respondError(w, http.StatusInternalServerError, err.Error())
		return
	}
	respondJSON(w, http.StatusOK, containers)
}

// InspectContainer returns details of a single container.
func (h *Handler) InspectContainer(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	info, err := h.Docker.InspectContainer(r.Context(), id)
	if err != nil {
		respondError(w, http.StatusNotFound, err.Error())
		return
	}
	respondJSON(w, http.StatusOK, info)
}

// StartContainer starts a container.
func (h *Handler) StartContainer(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if err := h.Docker.StartContainer(r.Context(), id); err != nil {
		respondError(w, http.StatusInternalServerError, err.Error())
		return
	}
	respondJSON(w, http.StatusOK, map[string]string{"status": "started"})
}

// StopContainer stops a container.
func (h *Handler) StopContainer(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if err := h.Docker.StopContainer(r.Context(), id, 10); err != nil {
		respondError(w, http.StatusInternalServerError, err.Error())
		return
	}
	respondJSON(w, http.StatusOK, map[string]string{"status": "stopped"})
}

// RestartContainer restarts a container.
func (h *Handler) RestartContainer(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if err := h.Docker.RestartContainer(r.Context(), id, 10); err != nil {
		respondError(w, http.StatusInternalServerError, err.Error())
		return
	}
	respondJSON(w, http.StatusOK, map[string]string{"status": "restarted"})
}

// RemoveContainer removes a container.
func (h *Handler) RemoveContainer(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if err := h.Docker.RemoveContainer(r.Context(), id); err != nil {
		respondError(w, http.StatusInternalServerError, err.Error())
		return
	}
	respondJSON(w, http.StatusOK, map[string]string{"status": "removed"})
}

// ContainerLogs streams logs via SSE.
func (h *Handler) ContainerLogs(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	sse := NewSSEWriter(w)
	if sse == nil {
		respondError(w, http.StatusInternalServerError, "streaming not supported")
		return
	}

	tail := r.URL.Query().Get("tail")
	since := r.URL.Query().Get("since")

	ctx := clientDisconnected(r)
	err := h.Docker.StreamLogs(ctx, id, true, since, tail, &sseLogAdapter{sse: sse})
	if err != nil && ctx.Err() == nil {
		sse.WriteError(err.Error())
	}
}

// sseLogAdapter bridges Docker log JSON lines to SSE events.
type sseLogAdapter struct {
	sse *SSEWriter
}

func (a *sseLogAdapter) Write(p []byte) (int, error) {
	err := a.sse.WriteEvent("log", json.RawMessage(p))
	if err != nil {
		return 0, err
	}
	return len(p), nil
}

func (a *sseLogAdapter) Flush() {}

// ContainerStats streams resource stats via SSE.
func (h *Handler) ContainerStats(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	sse := NewSSEWriter(w)
	if sse == nil {
		respondError(w, http.StatusInternalServerError, "streaming not supported")
		return
	}

	ctx := clientDisconnected(r)
	err := h.Docker.StreamStats(ctx, id, &sseStatsAdapter{sse: sse})
	if err != nil && ctx.Err() == nil {
		sse.WriteError(err.Error())
	}
}

type sseStatsAdapter struct {
	sse *SSEWriter
}

func (a *sseStatsAdapter) Write(p []byte) (int, error) {
	err := a.sse.WriteEvent("stats", json.RawMessage(p))
	if err != nil {
		return 0, err
	}
	return len(p), nil
}

func (a *sseStatsAdapter) Flush() {}

// DockerEvents streams Docker events for Argus containers via SSE.
func (h *Handler) DockerEvents(w http.ResponseWriter, r *http.Request) {
	sse := NewSSEWriter(w)
	if sse == nil {
		respondError(w, http.StatusInternalServerError, "streaming not supported")
		return
	}

	ctx := clientDisconnected(r)
	err := h.Docker.StreamEvents(ctx, &sseEventAdapter{sse: sse})
	if err != nil && ctx.Err() == nil {
		sse.WriteError(err.Error())
	}
}

type sseEventAdapter struct {
	sse *SSEWriter
}

func (a *sseEventAdapter) Write(p []byte) (int, error) {
	err := a.sse.WriteEvent("docker_event", json.RawMessage(p))
	if err != nil {
		return 0, err
	}
	return len(p), nil
}

func (a *sseEventAdapter) Flush() {}

// ───────────────────── Kubernetes Pods ────────────────────────

// ListPods returns all Argus-managed pods.
func (h *Handler) ListPods(w http.ResponseWriter, r *http.Request) {
	pods, err := h.K8s.ListPods(r.Context())
	if err != nil {
		respondError(w, http.StatusInternalServerError, err.Error())
		return
	}
	respondJSON(w, http.StatusOK, pods)
}

// DescribePod returns detailed pod information.
func (h *Handler) DescribePod(w http.ResponseWriter, r *http.Request) {
	ns := r.PathValue("ns")
	name := r.PathValue("name")
	info, err := h.K8s.DescribePod(r.Context(), ns, name)
	if err != nil {
		respondError(w, http.StatusNotFound, err.Error())
		return
	}
	respondJSON(w, http.StatusOK, info)
}

// DeletePod deletes an Argus-managed pod.
func (h *Handler) DeletePod(w http.ResponseWriter, r *http.Request) {
	ns := r.PathValue("ns")
	name := r.PathValue("name")
	if err := h.K8s.DeletePod(r.Context(), ns, name); err != nil {
		respondError(w, http.StatusInternalServerError, err.Error())
		return
	}
	respondJSON(w, http.StatusOK, map[string]string{"status": "deleted"})
}

// PodLogs streams pod logs via SSE.
func (h *Handler) PodLogs(w http.ResponseWriter, r *http.Request) {
	ns := r.PathValue("ns")
	name := r.PathValue("name")
	container := r.URL.Query().Get("container")

	sse := NewSSEWriter(w)
	if sse == nil {
		respondError(w, http.StatusInternalServerError, "streaming not supported")
		return
	}

	tail := int64(100)
	if t := r.URL.Query().Get("tail"); t != "" {
		if v, err := strconv.ParseInt(t, 10, 64); err == nil {
			tail = v
		}
	}
	since := r.URL.Query().Get("since")

	ctx := clientDisconnected(r)
	err := h.K8s.StreamPodLogs(ctx, ns, name, container, true, since, tail, &ssePodLogAdapter{sse: sse})
	if err != nil && ctx.Err() == nil {
		sse.WriteError(err.Error())
	}
}

type ssePodLogAdapter struct {
	sse *SSEWriter
}

func (a *ssePodLogAdapter) Write(p []byte) (int, error) {
	err := a.sse.WriteEvent("log", json.RawMessage(p))
	if err != nil {
		return 0, err
	}
	return len(p), nil
}

func (a *ssePodLogAdapter) Flush() {}

// PodEvents returns Kubernetes events for a pod.
func (h *Handler) PodEvents(w http.ResponseWriter, r *http.Request) {
	ns := r.PathValue("ns")
	name := r.PathValue("name")
	events, err := h.K8s.PodEvents(r.Context(), ns, name)
	if err != nil {
		respondError(w, http.StatusInternalServerError, err.Error())
		return
	}
	respondJSON(w, http.StatusOK, events)
}

// RolloutRestart triggers a rolling restart of an Argus-managed deployment.
func (h *Handler) RolloutRestart(w http.ResponseWriter, r *http.Request) {
	ns := r.PathValue("ns")
	name := r.PathValue("name")
	if err := h.K8s.RolloutRestart(r.Context(), ns, name); err != nil {
		msg := fmt.Sprintf("rollout restart %s/%s: %s", ns, name, err)
		respondError(w, http.StatusInternalServerError, msg)
		return
	}
	respondJSON(w, http.StatusOK, map[string]string{"status": "restarting"})
}
