// argusd is a lightweight daemon that exposes Docker and Kubernetes
// operations for Argus-managed resources over an HTTP API on a Unix
// Domain Socket.
//
// Usage:
//
//	argusd [-socket /path/to/argusd.sock]
package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"net"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"
	"time"

	"github.com/diaz3618/argus-mcp/packages/argusd/internal/docker"
	"github.com/diaz3618/argus-mcp/packages/argusd/internal/k8s"
	"github.com/diaz3618/argus-mcp/packages/argusd/internal/server"
)

func defaultSocketPath() string {
	if d := os.Getenv("XDG_RUNTIME_DIR"); d != "" {
		return filepath.Join(d, "argusd.sock")
	}
	return filepath.Join(os.TempDir(), "argusd.sock")
}

func main() {
	socketPath := flag.String("socket", defaultSocketPath(), "UDS path for the HTTP API")
	flag.Parse()

	log.SetFlags(log.Ldate | log.Ltime | log.Lmicroseconds | log.Lshortfile)
	log.Printf("argusd starting — socket=%s", *socketPath)

	// Docker client (required)
	dc, err := docker.NewClient()
	if err != nil {
		log.Fatalf("docker: %v", err)
	}
	defer dc.Close()

	// Kubernetes client (optional)
	var kc *k8s.Client
	if c, err := k8s.NewClient(); err != nil {
		log.Printf("k8s: unavailable (%v)", err)
	} else {
		kc = c
		log.Printf("k8s: available")
	}

	handler := &server.Handler{Docker: dc, K8s: kc}
	router := server.NewRouter(handler)

	// Remove stale socket file
	if err := os.Remove(*socketPath); err != nil && !os.IsNotExist(err) {
		log.Fatalf("remove stale socket: %v", err)
	}

	// Ensure socket directory exists
	if err := os.MkdirAll(filepath.Dir(*socketPath), 0o700); err != nil {
		log.Fatalf("create socket dir: %v", err)
	}

	listener, err := net.Listen("unix", *socketPath)
	if err != nil {
		log.Fatalf("listen: %v", err)
	}
	// Restrict socket permissions to owner
	if err := os.Chmod(*socketPath, 0o600); err != nil {
		log.Printf("warning: chmod socket: %v", err)
	}

	srv := &http.Server{
		Handler:           router,
		ReadHeaderTimeout: 10 * time.Second,
	}

	// Graceful shutdown on SIGINT/SIGTERM
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	go func() {
		log.Printf("listening on unix://%s", *socketPath)
		if err := srv.Serve(listener); err != nil && err != http.ErrServerClosed {
			log.Fatalf("serve: %v", err)
		}
	}()

	<-ctx.Done()
	log.Println("shutting down...")

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := srv.Shutdown(shutdownCtx); err != nil {
		log.Printf("shutdown: %v", err)
	}

	_ = os.Remove(*socketPath)
	fmt.Println("argusd stopped")
}
