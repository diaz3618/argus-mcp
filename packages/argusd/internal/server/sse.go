// Package server implements the HTTP API served over a Unix Domain Socket.
// Streaming endpoints use Server-Sent Events (SSE).
package server

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
)

// SSEWriter wraps an http.ResponseWriter for Server-Sent Events.
type SSEWriter struct {
	w       http.ResponseWriter
	flusher http.Flusher
}

// NewSSEWriter sets SSE headers and returns a writer.
// Returns nil if the ResponseWriter does not support flushing.
func NewSSEWriter(w http.ResponseWriter) *SSEWriter {
	f, ok := w.(http.Flusher)
	if !ok {
		return nil
	}
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("X-Accel-Buffering", "no") // disable nginx buffering
	w.WriteHeader(http.StatusOK)
	f.Flush()
	return &SSEWriter{w: w, flusher: f}
}

// WriteEvent sends a named SSE event with JSON data.
func (s *SSEWriter) WriteEvent(event string, data interface{}) error {
	b, err := json.Marshal(data)
	if err != nil {
		return err
	}
	_, err = fmt.Fprintf(s.w, "event: %s\ndata: %s\n\n", event, b)
	if err != nil {
		return err
	}
	s.flusher.Flush()
	return nil
}

// WriteData sends an unnamed SSE event with JSON data.
func (s *SSEWriter) WriteData(data interface{}) error {
	b, err := json.Marshal(data)
	if err != nil {
		return err
	}
	_, err = fmt.Fprintf(s.w, "data: %s\n\n", b)
	if err != nil {
		return err
	}
	s.flusher.Flush()
	return nil
}

// WriteError sends an SSE error event, then signals end-of-stream.
func (s *SSEWriter) WriteError(msg string) {
	_ = s.WriteEvent("error", map[string]string{"error": msg})
}

// respondJSON writes a JSON response with status code.
func respondJSON(w http.ResponseWriter, status int, v interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if v != nil {
		_ = json.NewEncoder(w).Encode(v)
	}
}

// respondError writes a JSON error response.
func respondError(w http.ResponseWriter, status int, msg string) {
	respondJSON(w, status, map[string]string{"error": msg})
}

// clientDisconnected returns a context that cancels when the client disconnects.
func clientDisconnected(r *http.Request) context.Context {
	return r.Context()
}
