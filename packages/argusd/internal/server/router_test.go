package server

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/diaz3618/argus-mcp/packages/argusd/internal/k8s"
	"github.com/diaz3618/argus-mcp/packages/argusd/internal/labels"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes/fake"
)

func TestNewRouter_DockerRoutes(t *testing.T) {
	h := &Handler{Docker: &mockDockerClient{}}
	router := NewRouter(h)

	tests := []struct {
		method string
		path   string
		want   int // expected status (not 405)
	}{
		{"GET", "/v1/health", http.StatusOK},
		{"GET", "/v1/containers", http.StatusOK},
		{"GET", "/v1/containers/abc123", http.StatusOK},
		{"POST", "/v1/containers/abc123/start", http.StatusOK},
		{"POST", "/v1/containers/abc123/stop", http.StatusOK},
		{"POST", "/v1/containers/abc123/restart", http.StatusOK},
		{"POST", "/v1/containers/abc123/remove", http.StatusOK},
		{"GET", "/v1/containers/abc123/logs", http.StatusOK},
		{"GET", "/v1/containers/abc123/stats", http.StatusOK},
		{"GET", "/v1/events", http.StatusOK},
	}

	for _, tt := range tests {
		t.Run(tt.method+" "+tt.path, func(t *testing.T) {
			rec := httptest.NewRecorder()
			req := httptest.NewRequest(tt.method, tt.path, nil)
			router.ServeHTTP(rec, req)

			if rec.Code == http.StatusMethodNotAllowed || rec.Code == http.StatusNotFound {
				t.Errorf("%s %s returned %d, route not registered", tt.method, tt.path, rec.Code)
			}
		})
	}
}

func TestNewRouter_K8sRoutes_Registered(t *testing.T) {
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
	router := NewRouter(h)

	tests := []struct {
		method string
		path   string
	}{
		{"GET", "/v1/pods"},
		{"GET", "/v1/pods/default/test"},
		{"DELETE", "/v1/pods/default/test"},
		{"GET", "/v1/pods/default/test/logs"},
		{"GET", "/v1/pods/default/test/events"},
		{"POST", "/v1/deployments/default/web/restart"},
	}

	for _, tt := range tests {
		t.Run(tt.method+" "+tt.path, func(t *testing.T) {
			rec := httptest.NewRecorder()
			req := httptest.NewRequest(tt.method, tt.path, nil)
			router.ServeHTTP(rec, req)

			// Routes should be registered (not 404/405)
			if rec.Code == http.StatusNotFound || rec.Code == http.StatusMethodNotAllowed {
				t.Errorf("%s %s returned %d, k8s route not registered", tt.method, tt.path, rec.Code)
			}
		})
	}
}

func TestNewRouter_K8sRoutes_NotRegistered_WhenNilK8s(t *testing.T) {
	h := &Handler{Docker: &mockDockerClient{}}
	router := NewRouter(h)

	// K8s routes should NOT be registered when K8s is nil
	tests := []struct {
		method string
		path   string
	}{
		{"GET", "/v1/pods"},
		{"GET", "/v1/pods/default/test"},
		{"DELETE", "/v1/pods/default/test"},
		{"GET", "/v1/pods/default/test/logs"},
		{"GET", "/v1/pods/default/test/events"},
		{"POST", "/v1/deployments/default/web/restart"},
	}

	for _, tt := range tests {
		t.Run(tt.method+" "+tt.path, func(t *testing.T) {
			rec := httptest.NewRecorder()
			req := httptest.NewRequest(tt.method, tt.path, nil)
			router.ServeHTTP(rec, req)

			if rec.Code != http.StatusNotFound {
				t.Errorf("%s %s returned %d, want 404 (k8s routes should not be registered)", tt.method, tt.path, rec.Code)
			}
		})
	}
}

func TestNewRouter_WrongMethod(t *testing.T) {
	h := &Handler{Docker: &mockDockerClient{}}
	router := NewRouter(h)

	// POST to a GET-only route
	rec := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/v1/health", nil)
	router.ServeHTTP(rec, req)

	if rec.Code == http.StatusOK {
		t.Error("POST /v1/health should not return 200")
	}
}

func TestNewRouter_UnknownPath(t *testing.T) {
	h := &Handler{Docker: &mockDockerClient{}}
	router := NewRouter(h)

	rec := httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/v1/unknown", nil)
	router.ServeHTTP(rec, req)

	if rec.Code != http.StatusNotFound {
		t.Errorf("status = %d, want %d", rec.Code, http.StatusNotFound)
	}
}
