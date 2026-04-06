package server

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// noFlushWriter wraps an http.ResponseWriter but does NOT implement http.Flusher.
type noFlushWriter struct {
	http.ResponseWriter
}

func TestNewSSEWriter_WithFlusher(t *testing.T) {
	rec := httptest.NewRecorder()
	sse := NewSSEWriter(rec)
	if sse == nil {
		t.Fatal("expected non-nil SSEWriter for httptest.ResponseRecorder")
	}
	if ct := rec.Header().Get("Content-Type"); ct != "text/event-stream" {
		t.Errorf("Content-Type = %q, want text/event-stream", ct)
	}
	if cc := rec.Header().Get("Cache-Control"); cc != "no-cache" {
		t.Errorf("Cache-Control = %q, want no-cache", cc)
	}
	if conn := rec.Header().Get("Connection"); conn != "keep-alive" {
		t.Errorf("Connection = %q, want keep-alive", conn)
	}
	if xab := rec.Header().Get("X-Accel-Buffering"); xab != "no" {
		t.Errorf("X-Accel-Buffering = %q, want no", xab)
	}
	if rec.Code != http.StatusOK {
		t.Errorf("status = %d, want %d", rec.Code, http.StatusOK)
	}
}

func TestNewSSEWriter_NoFlusher(t *testing.T) {
	rec := httptest.NewRecorder()
	w := &noFlushWriter{ResponseWriter: rec}
	sse := NewSSEWriter(w)
	if sse != nil {
		t.Fatal("expected nil SSEWriter for non-flusher writer")
	}
}

func TestSSEWriter_WriteEvent(t *testing.T) {
	rec := httptest.NewRecorder()
	sse := NewSSEWriter(rec)
	if sse == nil {
		t.Fatal("SSEWriter is nil")
	}

	data := map[string]string{"hello": "world"}
	if err := sse.WriteEvent("test", data); err != nil {
		t.Fatalf("WriteEvent: %v", err)
	}

	body := rec.Body.String()
	if !strings.Contains(body, "event: test\n") {
		t.Errorf("body missing event line: %s", body)
	}
	if !strings.Contains(body, `"hello":"world"`) {
		t.Errorf("body missing data: %s", body)
	}
}

func TestSSEWriter_WriteData(t *testing.T) {
	rec := httptest.NewRecorder()
	sse := NewSSEWriter(rec)
	if sse == nil {
		t.Fatal("SSEWriter is nil")
	}

	if err := sse.WriteData(42); err != nil {
		t.Fatalf("WriteData: %v", err)
	}

	body := rec.Body.String()
	if !strings.Contains(body, "data: 42\n\n") {
		t.Errorf("body = %q, want data: 42 line", body)
	}
}

func TestSSEWriter_WriteError(t *testing.T) {
	rec := httptest.NewRecorder()
	sse := NewSSEWriter(rec)
	if sse == nil {
		t.Fatal("SSEWriter is nil")
	}

	sse.WriteError("something broke")

	body := rec.Body.String()
	if !strings.Contains(body, "event: error\n") {
		t.Errorf("body missing error event: %s", body)
	}
	if !strings.Contains(body, "something broke") {
		t.Errorf("body missing error message: %s", body)
	}
}

func TestRespondJSON(t *testing.T) {
	rec := httptest.NewRecorder()
	data := map[string]int{"count": 3}
	respondJSON(rec, http.StatusCreated, data)

	if rec.Code != http.StatusCreated {
		t.Errorf("status = %d, want %d", rec.Code, http.StatusCreated)
	}
	if ct := rec.Header().Get("Content-Type"); ct != "application/json" {
		t.Errorf("Content-Type = %q, want application/json", ct)
	}

	var got map[string]int
	if err := json.NewDecoder(rec.Body).Decode(&got); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if got["count"] != 3 {
		t.Errorf("count = %d, want 3", got["count"])
	}
}

func TestRespondJSON_Nil(t *testing.T) {
	rec := httptest.NewRecorder()
	respondJSON(rec, http.StatusNoContent, nil)

	if rec.Code != http.StatusNoContent {
		t.Errorf("status = %d, want %d", rec.Code, http.StatusNoContent)
	}
	if rec.Body.Len() != 0 {
		t.Errorf("body should be empty, got %q", rec.Body.String())
	}
}

func TestRespondError(t *testing.T) {
	rec := httptest.NewRecorder()
	respondError(rec, http.StatusBadRequest, "bad input")

	if rec.Code != http.StatusBadRequest {
		t.Errorf("status = %d, want %d", rec.Code, http.StatusBadRequest)
	}

	var got map[string]string
	if err := json.NewDecoder(rec.Body).Decode(&got); err != nil {
		t.Fatalf("decode: %v", err)
	}
	if got["error"] != "bad input" {
		t.Errorf("error = %q, want %q", got["error"], "bad input")
	}
}

func TestClientDisconnected(t *testing.T) {
	req := httptest.NewRequest("GET", "/test", nil)
	ctx := clientDisconnected(req)
	if ctx != req.Context() {
		t.Error("clientDisconnected should return the request context")
	}
}
