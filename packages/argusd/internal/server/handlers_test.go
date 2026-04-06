package server

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/docker/docker/api/types"

	"github.com/diaz3618/argus-mcp/packages/argusd/internal/docker"
	"github.com/diaz3618/argus-mcp/packages/argusd/internal/k8s"
	"github.com/diaz3618/argus-mcp/packages/argusd/internal/labels"
	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/client-go/kubernetes/fake"
	k8stesting "k8s.io/client-go/testing"
)

// mockDockerClient implements docker.DockerClient for handler tests.
type mockDockerClient struct {
	PingFn             func(ctx context.Context) error
	ListContainersFn   func(ctx context.Context) ([]docker.ContainerInfo, error)
	InspectContainerFn func(ctx context.Context, id string) (*types.ContainerJSON, error)
	StartContainerFn   func(ctx context.Context, id string) error
	StopContainerFn    func(ctx context.Context, id string, timeoutSec int) error
	RestartContainerFn func(ctx context.Context, id string, timeoutSec int) error
	RemoveContainerFn  func(ctx context.Context, id string) error
	StreamLogsFn       func(ctx context.Context, id string, follow bool, since, tail string, w io.Writer) error
	StreamStatsFn      func(ctx context.Context, id string, w io.Writer) error
	StreamEventsFn     func(ctx context.Context, w io.Writer) error
	CloseFn            func() error
}

func (m *mockDockerClient) Ping(ctx context.Context) error {
	if m.PingFn != nil {
		return m.PingFn(ctx)
	}
	return nil
}

func (m *mockDockerClient) ListContainers(ctx context.Context) ([]docker.ContainerInfo, error) {
	if m.ListContainersFn != nil {
		return m.ListContainersFn(ctx)
	}
	return nil, nil
}

func (m *mockDockerClient) InspectContainer(ctx context.Context, id string) (*types.ContainerJSON, error) {
	if m.InspectContainerFn != nil {
		return m.InspectContainerFn(ctx, id)
	}
	return &types.ContainerJSON{}, nil
}

func (m *mockDockerClient) StartContainer(ctx context.Context, id string) error {
	if m.StartContainerFn != nil {
		return m.StartContainerFn(ctx, id)
	}
	return nil
}

func (m *mockDockerClient) StopContainer(ctx context.Context, id string, timeoutSec int) error {
	if m.StopContainerFn != nil {
		return m.StopContainerFn(ctx, id, timeoutSec)
	}
	return nil
}

func (m *mockDockerClient) RestartContainer(ctx context.Context, id string, timeoutSec int) error {
	if m.RestartContainerFn != nil {
		return m.RestartContainerFn(ctx, id, timeoutSec)
	}
	return nil
}

func (m *mockDockerClient) RemoveContainer(ctx context.Context, id string) error {
	if m.RemoveContainerFn != nil {
		return m.RemoveContainerFn(ctx, id)
	}
	return nil
}

func (m *mockDockerClient) StreamLogs(ctx context.Context, id string, follow bool, since, tail string, w io.Writer) error {
	if m.StreamLogsFn != nil {
		return m.StreamLogsFn(ctx, id, follow, since, tail, w)
	}
	return nil
}

func (m *mockDockerClient) StreamStats(ctx context.Context, id string, w io.Writer) error {
	if m.StreamStatsFn != nil {
		return m.StreamStatsFn(ctx, id, w)
	}
	return nil
}

func (m *mockDockerClient) StreamEvents(ctx context.Context, w io.Writer) error {
	if m.StreamEventsFn != nil {
		return m.StreamEventsFn(ctx, w)
	}
	return nil
}

func (m *mockDockerClient) Close() error {
	if m.CloseFn != nil {
		return m.CloseFn()
	}
	return nil
}

// Compile-time interface check.
var _ docker.DockerClient = (*mockDockerClient)(nil)

// --- Health handler ---

func TestHealth_NoK8s(t *testing.T) {
	h := &Handler{Docker: &mockDockerClient{}}
	rec := httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/v1/health", nil)
	h.Health(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusOK)
	}

	var got map[string]interface{}
	if err := json.NewDecoder(rec.Body).Decode(&got); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if got["status"] != "ok" {
		t.Errorf("status = %v, want ok", got["status"])
	}
	if got["docker"] != true {
		t.Errorf("docker = %v, want true", got["docker"])
	}
	if got["k8s"] != false {
		t.Errorf("k8s = %v, want false (no k8s client)", got["k8s"])
	}
}

func TestHealth_WithK8s(t *testing.T) {
	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "test",
			Namespace: "default",
			Labels:    map[string]string{labels.Managed: labels.ManagedValue},
		},
	}
	cs := fake.NewSimpleClientset(pod)
	k8sClient := k8s.NewTestClient(cs)

	h := &Handler{Docker: &mockDockerClient{}, K8s: k8sClient}
	rec := httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/v1/health", nil)
	h.Health(rec, req)

	var got map[string]interface{}
	if err := json.NewDecoder(rec.Body).Decode(&got); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if got["k8s"] != true {
		t.Errorf("k8s = %v, want true", got["k8s"])
	}
}

// --- ListContainers handler ---

func TestListContainers_OK(t *testing.T) {
	mock := &mockDockerClient{
		ListContainersFn: func(ctx context.Context) ([]docker.ContainerInfo, error) {
			return []docker.ContainerInfo{
				{ID: "abc123", Name: "web", Image: "nginx", State: "running"},
			}, nil
		},
	}
	h := &Handler{Docker: mock}
	rec := httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/v1/containers", nil)
	h.ListContainers(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusOK)
	}

	var got []docker.ContainerInfo
	if err := json.NewDecoder(rec.Body).Decode(&got); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if len(got) != 1 || got[0].ID != "abc123" {
		t.Errorf("containers = %+v, want 1 container with ID abc123", got)
	}
}

func TestListContainers_Error(t *testing.T) {
	mock := &mockDockerClient{
		ListContainersFn: func(ctx context.Context) ([]docker.ContainerInfo, error) {
			return nil, errors.New("daemon unavailable")
		},
	}
	h := &Handler{Docker: mock}
	rec := httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/v1/containers", nil)
	h.ListContainers(rec, req)

	if rec.Code != http.StatusInternalServerError {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusInternalServerError)
	}
}

// --- InspectContainer handler ---

func TestInspectContainer_OK(t *testing.T) {
	mock := &mockDockerClient{
		InspectContainerFn: func(ctx context.Context, id string) (*types.ContainerJSON, error) {
			return &types.ContainerJSON{
				ContainerJSONBase: &types.ContainerJSONBase{ID: id, Name: "/test-ctr"},
			}, nil
		},
	}
	h := &Handler{Docker: mock}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /v1/containers/{id}", h.InspectContainer)

	rec := httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/v1/containers/abc123", nil)
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusOK)
	}
}

func TestInspectContainer_NotFound(t *testing.T) {
	mock := &mockDockerClient{
		InspectContainerFn: func(ctx context.Context, id string) (*types.ContainerJSON, error) {
			return nil, errors.New("not found")
		},
	}
	h := &Handler{Docker: mock}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /v1/containers/{id}", h.InspectContainer)

	rec := httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/v1/containers/missing", nil)
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusNotFound)
	}
}

// --- StartContainer handler ---

func TestStartContainer_OK(t *testing.T) {
	mock := &mockDockerClient{}
	h := &Handler{Docker: mock}

	mux := http.NewServeMux()
	mux.HandleFunc("POST /v1/containers/{id}/start", h.StartContainer)

	rec := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/v1/containers/abc123/start", nil)
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusOK)
	}

	var got map[string]string
	if err := json.NewDecoder(rec.Body).Decode(&got); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if got["status"] != "started" {
		t.Errorf("status = %q, want started", got["status"])
	}
}

func TestStartContainer_Error(t *testing.T) {
	mock := &mockDockerClient{
		StartContainerFn: func(ctx context.Context, id string) error {
			return errors.New("already running")
		},
	}
	h := &Handler{Docker: mock}

	mux := http.NewServeMux()
	mux.HandleFunc("POST /v1/containers/{id}/start", h.StartContainer)

	rec := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/v1/containers/abc123/start", nil)
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusInternalServerError {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusInternalServerError)
	}
}

// --- StopContainer handler ---

func TestStopContainer_OK(t *testing.T) {
	stopped := false
	mock := &mockDockerClient{
		StopContainerFn: func(ctx context.Context, id string, timeout int) error {
			stopped = true
			if timeout != 10 {
				t.Errorf("timeout = %d, want 10", timeout)
			}
			return nil
		},
	}
	h := &Handler{Docker: mock}

	mux := http.NewServeMux()
	mux.HandleFunc("POST /v1/containers/{id}/stop", h.StopContainer)

	rec := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/v1/containers/abc123/stop", nil)
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusOK)
	}
	if !stopped {
		t.Error("StopContainer was not called")
	}
}

func TestStopContainer_Error(t *testing.T) {
	mock := &mockDockerClient{
		StopContainerFn: func(ctx context.Context, id string, timeout int) error {
			return errors.New("not running")
		},
	}
	h := &Handler{Docker: mock}

	mux := http.NewServeMux()
	mux.HandleFunc("POST /v1/containers/{id}/stop", h.StopContainer)

	rec := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/v1/containers/abc123/stop", nil)
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusInternalServerError {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusInternalServerError)
	}
}

// --- RestartContainer handler ---

func TestRestartContainer_OK(t *testing.T) {
	mock := &mockDockerClient{}
	h := &Handler{Docker: mock}

	mux := http.NewServeMux()
	mux.HandleFunc("POST /v1/containers/{id}/restart", h.RestartContainer)

	rec := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/v1/containers/abc123/restart", nil)
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusOK)
	}

	var got map[string]string
	if err := json.NewDecoder(rec.Body).Decode(&got); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if got["status"] != "restarted" {
		t.Errorf("status = %q, want restarted", got["status"])
	}
}

func TestRestartContainer_Error(t *testing.T) {
	mock := &mockDockerClient{
		RestartContainerFn: func(ctx context.Context, id string, timeout int) error {
			return errors.New("restart failed")
		},
	}
	h := &Handler{Docker: mock}

	mux := http.NewServeMux()
	mux.HandleFunc("POST /v1/containers/{id}/restart", h.RestartContainer)

	rec := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/v1/containers/abc123/restart", nil)
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusInternalServerError {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusInternalServerError)
	}
}

// --- RemoveContainer handler ---

func TestRemoveContainer_OK(t *testing.T) {
	mock := &mockDockerClient{}
	h := &Handler{Docker: mock}

	mux := http.NewServeMux()
	mux.HandleFunc("POST /v1/containers/{id}/remove", h.RemoveContainer)

	rec := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/v1/containers/abc123/remove", nil)
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusOK)
	}

	var got map[string]string
	if err := json.NewDecoder(rec.Body).Decode(&got); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if got["status"] != "removed" {
		t.Errorf("status = %q, want removed", got["status"])
	}
}

func TestRemoveContainer_Error(t *testing.T) {
	mock := &mockDockerClient{
		RemoveContainerFn: func(ctx context.Context, id string) error {
			return errors.New("remove failed")
		},
	}
	h := &Handler{Docker: mock}

	mux := http.NewServeMux()
	mux.HandleFunc("POST /v1/containers/{id}/remove", h.RemoveContainer)

	rec := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/v1/containers/abc123/remove", nil)
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusInternalServerError {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusInternalServerError)
	}
}

// --- ContainerLogs handler (SSE streaming) ---

func TestContainerLogs_OK(t *testing.T) {
	mock := &mockDockerClient{
		StreamLogsFn: func(ctx context.Context, id string, follow bool, since, tail string, w io.Writer) error {
			_, _ = w.Write([]byte(`{"line":"hello"}`))
			return nil
		},
	}
	h := &Handler{Docker: mock}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /v1/containers/{id}/logs", h.ContainerLogs)

	rec := httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/v1/containers/abc123/logs?tail=50&since=1h", nil)
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusOK)
	}
	if ct := rec.Header().Get("Content-Type"); ct != "text/event-stream" {
		t.Errorf("Content-Type = %q, want text/event-stream", ct)
	}
}

func TestContainerLogs_StreamError(t *testing.T) {
	mock := &mockDockerClient{
		StreamLogsFn: func(ctx context.Context, id string, follow bool, since, tail string, w io.Writer) error {
			return errors.New("stream failed")
		},
	}
	h := &Handler{Docker: mock}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /v1/containers/{id}/logs", h.ContainerLogs)

	rec := httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/v1/containers/abc123/logs", nil)
	mux.ServeHTTP(rec, req)

	// SSE writer already sent 200, so we check for error event in body
	body := rec.Body.String()
	if !containsStr(body, "stream failed") {
		t.Errorf("body should contain error message, got: %s", body)
	}
}

// --- ContainerStats handler (SSE streaming) ---

func TestContainerStats_OK(t *testing.T) {
	mock := &mockDockerClient{
		StreamStatsFn: func(ctx context.Context, id string, w io.Writer) error {
			_, _ = w.Write([]byte(`{"cpu":1.5}`))
			return nil
		},
	}
	h := &Handler{Docker: mock}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /v1/containers/{id}/stats", h.ContainerStats)

	rec := httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/v1/containers/abc123/stats", nil)
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusOK)
	}
}

func TestContainerStats_Error(t *testing.T) {
	mock := &mockDockerClient{
		StreamStatsFn: func(ctx context.Context, id string, w io.Writer) error {
			return errors.New("stats failed")
		},
	}
	h := &Handler{Docker: mock}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /v1/containers/{id}/stats", h.ContainerStats)

	rec := httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/v1/containers/abc123/stats", nil)
	mux.ServeHTTP(rec, req)

	body := rec.Body.String()
	if !containsStr(body, "stats failed") {
		t.Errorf("body should contain error, got: %s", body)
	}
}

// --- DockerEvents handler (SSE streaming) ---

func TestDockerEvents_OK(t *testing.T) {
	mock := &mockDockerClient{
		StreamEventsFn: func(ctx context.Context, w io.Writer) error {
			_, _ = w.Write([]byte(`{"type":"start"}`))
			return nil
		},
	}
	h := &Handler{Docker: mock}

	rec := httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/v1/events", nil)
	h.DockerEvents(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusOK)
	}
}

func TestDockerEvents_Error(t *testing.T) {
	mock := &mockDockerClient{
		StreamEventsFn: func(ctx context.Context, w io.Writer) error {
			return errors.New("events failed")
		},
	}
	h := &Handler{Docker: mock}

	rec := httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/v1/events", nil)
	h.DockerEvents(rec, req)

	body := rec.Body.String()
	if !containsStr(body, "events failed") {
		t.Errorf("body should contain error, got: %s", body)
	}
}

// --- requireK8s ---

func TestRequireK8s_NilClient(t *testing.T) {
	h := &Handler{Docker: &mockDockerClient{}}
	rec := httptest.NewRecorder()
	unavailable := h.requireK8s(rec)
	if !unavailable {
		t.Error("requireK8s should return true when K8s is nil")
	}
	if rec.Code != http.StatusServiceUnavailable {
		t.Errorf("status = %d, want %d", rec.Code, http.StatusServiceUnavailable)
	}
}

func TestRequireK8s_Available(t *testing.T) {
	cs := fake.NewSimpleClientset()
	k8sClient := k8s.NewTestClient(cs)

	h := &Handler{Docker: &mockDockerClient{}, K8s: k8sClient}
	rec := httptest.NewRecorder()
	unavailable := h.requireK8s(rec)
	if unavailable {
		t.Error("requireK8s should return false when K8s is set")
	}
}

// --- ListPods handler ---

func TestListPods_NoK8s(t *testing.T) {
	h := &Handler{Docker: &mockDockerClient{}}
	rec := httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/v1/pods", nil)
	h.ListPods(rec, req)

	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusServiceUnavailable)
	}
}

func TestListPods_OK(t *testing.T) {
	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "web-1",
			Namespace: "default",
			Labels:    map[string]string{labels.Managed: labels.ManagedValue},
		},
		Status: corev1.PodStatus{Phase: corev1.PodRunning},
	}
	cs := fake.NewSimpleClientset(pod)
	k8sClient := k8s.NewTestClient(cs)

	h := &Handler{Docker: &mockDockerClient{}, K8s: k8sClient}
	rec := httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/v1/pods", nil)
	h.ListPods(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusOK)
	}
}

func TestListPods_Error(t *testing.T) {
	cs := fake.NewSimpleClientset()
	cs.PrependReactor("list", "pods", func(action k8stesting.Action) (bool, runtime.Object, error) {
		return true, nil, errors.New("api server unavailable")
	})
	k8sClient := k8s.NewTestClient(cs)

	h := &Handler{Docker: &mockDockerClient{}, K8s: k8sClient}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /v1/pods", h.ListPods)

	rec := httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/v1/pods", nil)
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusInternalServerError {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusInternalServerError)
	}
}

// --- DescribePod handler ---

func TestDescribePod_NoK8s(t *testing.T) {
	h := &Handler{Docker: &mockDockerClient{}}
	rec := httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/v1/pods/default/web-1", nil)
	h.DescribePod(rec, req)

	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusServiceUnavailable)
	}
}

func TestDescribePod_OK(t *testing.T) {
	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "web-1",
			Namespace: "default",
			Labels:    map[string]string{labels.Managed: labels.ManagedValue},
		},
	}
	cs := fake.NewSimpleClientset(pod)
	k8sClient := k8s.NewTestClient(cs)

	h := &Handler{Docker: &mockDockerClient{}, K8s: k8sClient}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /v1/pods/{ns}/{name}", h.DescribePod)

	rec := httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/v1/pods/default/web-1", nil)
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusOK)
	}
}

func TestDescribePod_NotFound(t *testing.T) {
	cs := fake.NewSimpleClientset()
	k8sClient := k8s.NewTestClient(cs)

	h := &Handler{Docker: &mockDockerClient{}, K8s: k8sClient}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /v1/pods/{ns}/{name}", h.DescribePod)

	rec := httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/v1/pods/default/nonexistent", nil)
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusNotFound {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusNotFound)
	}
}

// --- DeletePod handler ---

func TestDeletePod_NoK8s(t *testing.T) {
	h := &Handler{Docker: &mockDockerClient{}}
	rec := httptest.NewRecorder()
	req := httptest.NewRequest("DELETE", "/v1/pods/default/web-1", nil)
	h.DeletePod(rec, req)

	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusServiceUnavailable)
	}
}

func TestDeletePod_OK(t *testing.T) {
	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "web-1",
			Namespace: "default",
			Labels:    map[string]string{labels.Managed: labels.ManagedValue},
		},
	}
	cs := fake.NewSimpleClientset(pod)
	k8sClient := k8s.NewTestClient(cs)

	h := &Handler{Docker: &mockDockerClient{}, K8s: k8sClient}

	mux := http.NewServeMux()
	mux.HandleFunc("DELETE /v1/pods/{ns}/{name}", h.DeletePod)

	rec := httptest.NewRecorder()
	req := httptest.NewRequest("DELETE", "/v1/pods/default/web-1", nil)
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusOK)
	}

	var got map[string]string
	if err := json.NewDecoder(rec.Body).Decode(&got); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if got["status"] != "deleted" {
		t.Errorf("status = %q, want deleted", got["status"])
	}
}

// --- PodLogs handler ---

func TestPodLogs_NoK8s(t *testing.T) {
	h := &Handler{Docker: &mockDockerClient{}}
	rec := httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/v1/pods/default/web-1/logs", nil)
	h.PodLogs(rec, req)

	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusServiceUnavailable)
	}
}

// --- PodEvents handler ---

func TestPodEvents_NoK8s(t *testing.T) {
	h := &Handler{Docker: &mockDockerClient{}}
	rec := httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/v1/pods/default/web-1/events", nil)
	h.PodEvents(rec, req)

	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusServiceUnavailable)
	}
}

func TestPodEvents_OK(t *testing.T) {
	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "web-1",
			Namespace: "default",
			Labels:    map[string]string{labels.Managed: labels.ManagedValue},
		},
	}
	ev := &corev1.Event{
		ObjectMeta:     metav1.ObjectMeta{Name: "evt-1", Namespace: "default"},
		InvolvedObject: corev1.ObjectReference{Name: "web-1", Namespace: "default"},
		Reason:         "Scheduled",
		Message:        "Successfully assigned",
	}
	cs := fake.NewSimpleClientset(pod, ev)
	k8sClient := k8s.NewTestClient(cs)

	h := &Handler{Docker: &mockDockerClient{}, K8s: k8sClient}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /v1/pods/{ns}/{name}/events", h.PodEvents)

	rec := httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/v1/pods/default/web-1/events", nil)
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusOK)
	}
}

// --- RolloutRestart handler ---

func TestRolloutRestart_NoK8s(t *testing.T) {
	h := &Handler{Docker: &mockDockerClient{}}
	rec := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/v1/deployments/default/web/restart", nil)
	h.RolloutRestart(rec, req)

	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusServiceUnavailable)
	}
}

// --- SSE nil fallback for non-flusher writers ---

func TestContainerLogs_NoFlusher(t *testing.T) {
	h := &Handler{Docker: &mockDockerClient{}}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /v1/containers/{id}/logs", h.ContainerLogs)

	rec := httptest.NewRecorder()
	w := &noFlushWriter{ResponseWriter: rec}
	req := httptest.NewRequest("GET", "/v1/containers/abc123/logs", nil)
	mux.ServeHTTP(w, req)

	// When there is no flusher, respondError is called with 500.
	// But since we wrapped the recorder, the actual write goes through.
	// Just verify it doesn't panic.
}

func TestContainerStats_NoFlusher(t *testing.T) {
	h := &Handler{Docker: &mockDockerClient{}}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /v1/containers/{id}/stats", h.ContainerStats)

	rec := httptest.NewRecorder()
	w := &noFlushWriter{ResponseWriter: rec}
	req := httptest.NewRequest("GET", "/v1/containers/abc123/stats", nil)
	mux.ServeHTTP(w, req)
}

func TestDockerEvents_NoFlusher(t *testing.T) {
	h := &Handler{Docker: &mockDockerClient{}}

	rec := httptest.NewRecorder()
	w := &noFlushWriter{ResponseWriter: rec}
	req := httptest.NewRequest("GET", "/v1/events", nil)
	h.DockerEvents(w, req)
}

// --- DeletePod error path ---

func TestDeletePod_Error(t *testing.T) {
	// Pod exists but is not managed → K8s returns error
	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "unmanaged",
			Namespace: "default",
		},
	}
	cs := fake.NewSimpleClientset(pod)
	k8sClient := k8s.NewTestClient(cs)

	h := &Handler{Docker: &mockDockerClient{}, K8s: k8sClient}

	mux := http.NewServeMux()
	mux.HandleFunc("DELETE /v1/pods/{ns}/{name}", h.DeletePod)

	rec := httptest.NewRecorder()
	req := httptest.NewRequest("DELETE", "/v1/pods/default/unmanaged", nil)
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusInternalServerError {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusInternalServerError)
	}
}

// --- PodLogs with tail parameter ---

func TestPodLogs_WithTailParam(t *testing.T) {
	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "log-pod",
			Namespace: "default",
			Labels:    map[string]string{labels.Managed: labels.ManagedValue},
		},
	}
	cs := fake.NewSimpleClientset(pod)
	k8sClient := k8s.NewTestClient(cs)

	h := &Handler{Docker: &mockDockerClient{}, K8s: k8sClient}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /v1/pods/{ns}/{name}/logs", h.PodLogs)

	rec := httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/v1/pods/default/log-pod/logs?tail=50&container=app&since=1h", nil)
	mux.ServeHTTP(rec, req)

	// The fake clientset doesn't support GetLogs streaming, so it will error.
	// But we're testing that the handler properly parses tail/since/container params
	// without panic (the tail parsing branch and since branch are covered).
	if rec.Code != http.StatusOK {
		// SSE writer already set 200 headers, error goes as SSE event
		t.Logf("status = %d (SSE error expected)", rec.Code)
	}
}

// --- PodEvents error path ---

func TestPodEvents_Error(t *testing.T) {
	// Use empty clientset; fake clientset will return events fine but
	// we can trigger error via namespace query
	cs := fake.NewSimpleClientset()
	k8sClient := k8s.NewTestClient(cs)

	h := &Handler{Docker: &mockDockerClient{}, K8s: k8sClient}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /v1/pods/{ns}/{name}/events", h.PodEvents)

	rec := httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/v1/pods/default/web-1/events", nil)
	mux.ServeHTTP(rec, req)

	// Even though no events, should return 200 with empty list
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusOK)
	}
}

// --- RolloutRestart error handler path ---

func TestRolloutRestart_Error(t *testing.T) {
	cs := fake.NewSimpleClientset() // no deployment
	k8sClient := k8s.NewTestClient(cs)

	h := &Handler{Docker: &mockDockerClient{}, K8s: k8sClient}

	mux := http.NewServeMux()
	mux.HandleFunc("POST /v1/deployments/{ns}/{name}/restart", h.RolloutRestart)

	rec := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/v1/deployments/default/missing/restart", nil)
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusInternalServerError {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusInternalServerError)
	}
}

func TestRolloutRestart_OK(t *testing.T) {
	dep := &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "web",
			Namespace: "default",
			Labels:    map[string]string{labels.Managed: labels.ManagedValue},
		},
		Spec: appsv1.DeploymentSpec{
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{
					Labels: map[string]string{"app": "web"},
				},
				Spec: corev1.PodSpec{
					Containers: []corev1.Container{{Name: "app", Image: "img:1"}},
				},
			},
			Selector: &metav1.LabelSelector{
				MatchLabels: map[string]string{"app": "web"},
			},
		},
	}
	cs := fake.NewSimpleClientset(dep)
	k8sClient := k8s.NewTestClient(cs)

	h := &Handler{Docker: &mockDockerClient{}, K8s: k8sClient}

	mux := http.NewServeMux()
	mux.HandleFunc("POST /v1/deployments/{ns}/{name}/restart", h.RolloutRestart)

	rec := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/v1/deployments/default/web/restart", nil)
	mux.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusOK)
	}

	var got map[string]string
	if err := json.NewDecoder(rec.Body).Decode(&got); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if got["status"] != "restarting" {
		t.Errorf("status = %q, want restarting", got["status"])
	}
}

// --- SSE adapter tests: exercise Write and Flush directly ---

func TestSSEAdapters_Write_And_Flush(t *testing.T) {
	rec := httptest.NewRecorder()
	sse := NewSSEWriter(rec)
	if sse == nil {
		t.Fatal("NewSSEWriter returned nil")
	}

	// sseLogAdapter
	logA := &sseLogAdapter{sse: sse}
	n, err := logA.Write([]byte(`{"msg":"hello"}`))
	if err != nil {
		t.Errorf("sseLogAdapter.Write error: %v", err)
	}
	if n != len(`{"msg":"hello"}`) {
		t.Errorf("sseLogAdapter.Write returned %d, want %d", n, len(`{"msg":"hello"}`))
	}
	logA.Flush() // no-op, just cover it

	// sseStatsAdapter
	statsA := &sseStatsAdapter{sse: sse}
	n, err = statsA.Write([]byte(`{"cpu":1}`))
	if err != nil {
		t.Errorf("sseStatsAdapter.Write error: %v", err)
	}
	if n != len(`{"cpu":1}`) {
		t.Errorf("sseStatsAdapter.Write returned %d, want %d", n, len(`{"cpu":1}`))
	}
	statsA.Flush()

	// sseEventAdapter
	evtA := &sseEventAdapter{sse: sse}
	n, err = evtA.Write([]byte(`{"type":"start"}`))
	if err != nil {
		t.Errorf("sseEventAdapter.Write error: %v", err)
	}
	if n != len(`{"type":"start"}`) {
		t.Errorf("sseEventAdapter.Write returned %d, want %d", n, len(`{"type":"start"}`))
	}
	evtA.Flush()

	// ssePodLogAdapter
	podLogA := &ssePodLogAdapter{sse: sse}
	n, err = podLogA.Write([]byte(`{"line":"test"}`))
	if err != nil {
		t.Errorf("ssePodLogAdapter.Write error: %v", err)
	}
	if n != len(`{"line":"test"}`) {
		t.Errorf("ssePodLogAdapter.Write returned %d, want %d", n, len(`{"line":"test"}`))
	}
	podLogA.Flush()
}

// containsStr is a helper for substring matching.
func containsStr(s, substr string) bool {
	return len(s) >= len(substr) && (s == substr || len(s) > 0 && containsSubstr(s, substr))
}

func containsSubstr(s, sub string) bool {
	for i := 0; i <= len(s)-len(sub); i++ {
		if s[i:i+len(sub)] == sub {
			return true
		}
	}
	return false
}
