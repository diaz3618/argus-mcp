// Package k8s wraps the Kubernetes client-go library and provides
// pod lifecycle, event streaming, log tailing, and metrics for
// Argus-managed pods scoped by label selectors.
package k8s

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"strings"
	"sync"
	"time"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
	"k8s.io/client-go/tools/clientcmd"
	metricsv1beta1 "k8s.io/metrics/pkg/client/clientset/versioned"

	"github.com/diaz3618/argus-mcp/packages/argusd/internal/labels"
)

// Client wraps the Kubernetes API client for Argus-scoped operations.
type Client struct {
	cs      kubernetes.Interface
	metrics metricsv1beta1.Interface
	mu      sync.RWMutex
}

// NewClient creates a Kubernetes client. It tries in-cluster config first,
// then falls back to the default kubeconfig.
func NewClient() (*Client, error) {
	cfg, err := rest.InClusterConfig()
	if err != nil {
		cfg, err = clientcmd.BuildConfigFromFlags("", clientcmd.RecommendedHomeFile)
		if err != nil {
			return nil, fmt.Errorf("k8s config: %w", err)
		}
	}

	cs, err := kubernetes.NewForConfig(cfg)
	if err != nil {
		return nil, fmt.Errorf("k8s clientset: %w", err)
	}

	var mc metricsv1beta1.Interface
	if mcs, err := metricsv1beta1.NewForConfig(cfg); err == nil {
		mc = mcs
	}

	return &Client{cs: cs, metrics: mc}, nil
}

// Available reports whether the k8s client was successfully initialized.
func (c *Client) Available() bool {
	return c != nil && c.cs != nil
}

// PodInfo is a simplified pod representation.
type PodInfo struct {
	Name       string            `json:"name"`
	Namespace  string            `json:"namespace"`
	Status     string            `json:"status"`
	PodIP      string            `json:"pod_ip"`
	NodeName   string            `json:"node_name"`
	HostIP     string            `json:"host_ip"`
	Age        string            `json:"age"`
	Restarts   int32             `json:"restarts"`
	Labels     map[string]string `json:"labels"`
	Containers []ContainerStatus `json:"containers"`
}

// ContainerStatus describes one container in a pod.
type ContainerStatus struct {
	Name         string `json:"name"`
	Image        string `json:"image"`
	Ready        bool   `json:"ready"`
	RestartCount int32  `json:"restart_count"`
	State        string `json:"state"`
}

// ListPods returns all Argus-managed pods across all namespaces.
func (c *Client) ListPods(ctx context.Context) ([]PodInfo, error) {
	c.mu.RLock()
	defer c.mu.RUnlock()

	pods, err := c.cs.CoreV1().Pods("").List(ctx, metav1.ListOptions{
		LabelSelector: labels.Selector(),
	})
	if err != nil {
		return nil, fmt.Errorf("list pods: %w", err)
	}

	result := make([]PodInfo, 0, len(pods.Items))
	for _, pod := range pods.Items {
		result = append(result, podToInfo(&pod))
	}
	return result, nil
}

func podToInfo(pod *corev1.Pod) PodInfo {
	age := time.Since(pod.CreationTimestamp.Time)
	var ageStr string
	switch {
	case age < time.Minute:
		ageStr = fmt.Sprintf("%ds", int(age.Seconds()))
	case age < time.Hour:
		ageStr = fmt.Sprintf("%dm", int(age.Minutes()))
	case age < 24*time.Hour:
		ageStr = fmt.Sprintf("%dh", int(age.Hours()))
	default:
		ageStr = fmt.Sprintf("%dd", int(age.Hours()/24))
	}

	var totalRestarts int32
	containers := make([]ContainerStatus, 0, len(pod.Status.ContainerStatuses))
	for _, cs := range pod.Status.ContainerStatuses {
		totalRestarts += cs.RestartCount
		state := "unknown"
		switch {
		case cs.State.Running != nil:
			state = "running"
		case cs.State.Waiting != nil:
			state = "waiting:" + cs.State.Waiting.Reason
		case cs.State.Terminated != nil:
			state = "terminated:" + cs.State.Terminated.Reason
		}
		containers = append(containers, ContainerStatus{
			Name:         cs.Name,
			Image:        cs.Image,
			Ready:        cs.Ready,
			RestartCount: cs.RestartCount,
			State:        state,
		})
	}

	return PodInfo{
		Name:       pod.Name,
		Namespace:  pod.Namespace,
		Status:     string(pod.Status.Phase),
		PodIP:      pod.Status.PodIP,
		NodeName:   pod.Spec.NodeName,
		HostIP:     pod.Status.HostIP,
		Age:        ageStr,
		Restarts:   totalRestarts,
		Labels:     pod.Labels,
		Containers: containers,
	}
}

// DescribePod returns detailed pod information.
func (c *Client) DescribePod(ctx context.Context, namespace, name string) (*PodInfo, error) {
	c.mu.RLock()
	defer c.mu.RUnlock()

	pod, err := c.cs.CoreV1().Pods(namespace).Get(ctx, name, metav1.GetOptions{})
	if err != nil {
		return nil, fmt.Errorf("get pod %s/%s: %w", namespace, name, err)
	}

	if pod.Labels[labels.Managed] != labels.ManagedValue {
		return nil, fmt.Errorf("pod %s/%s is not Argus-managed", namespace, name)
	}

	info := podToInfo(pod)
	return &info, nil
}

// DeletePod deletes an Argus-managed pod.
func (c *Client) DeletePod(ctx context.Context, namespace, name string) error {
	c.mu.RLock()
	defer c.mu.RUnlock()

	pod, err := c.cs.CoreV1().Pods(namespace).Get(ctx, name, metav1.GetOptions{})
	if err != nil {
		return fmt.Errorf("get pod %s/%s: %w", namespace, name, err)
	}
	if pod.Labels[labels.Managed] != labels.ManagedValue {
		return fmt.Errorf("pod %s/%s is not Argus-managed", namespace, name)
	}

	return c.cs.CoreV1().Pods(namespace).Delete(ctx, name, metav1.DeleteOptions{})
}

// StreamPodLogs streams logs from a pod container. Writes JSON lines to w.
func (c *Client) StreamPodLogs(ctx context.Context, namespace, name, containerName string, follow bool, since string, tail int64, w io.Writer) error {
	c.mu.RLock()
	cs := c.cs
	c.mu.RUnlock()

	opts := &corev1.PodLogOptions{
		Follow:     follow,
		Timestamps: true,
	}
	if containerName != "" {
		opts.Container = containerName
	}
	if tail > 0 {
		opts.TailLines = &tail
	}
	if since != "" {
		if d, err := time.ParseDuration(since); err == nil {
			secs := int64(d.Seconds())
			opts.SinceSeconds = &secs
		}
	}

	stream, err := cs.CoreV1().Pods(namespace).GetLogs(name, opts).Stream(ctx)
	if err != nil {
		return fmt.Errorf("pod logs %s/%s: %w", namespace, name, err)
	}
	defer stream.Close()

	enc := json.NewEncoder(w)
	buf := make([]byte, 32*1024)
	for {
		n, readErr := stream.Read(buf)
		if n > 0 {
			lines := strings.Split(strings.TrimRight(string(buf[:n]), "\n"), "\n")
			for _, line := range lines {
				var ts time.Time
				msg := line
				if idx := strings.IndexByte(line, ' '); idx > 0 {
					if t, err := time.Parse(time.RFC3339Nano, line[:idx]); err == nil {
						ts = t
						msg = line[idx+1:]
					}
				}
				entry := map[string]interface{}{
					"timestamp": ts,
					"pod":       name,
					"container": containerName,
					"message":   msg,
				}
				if err := enc.Encode(entry); err != nil {
					return err
				}
			}
			if f, ok := w.(interface{ Flush() }); ok {
				f.Flush()
			}
		}
		if readErr != nil {
			if readErr == io.EOF || ctx.Err() != nil {
				return nil
			}
			return readErr
		}
	}
}

// PodEvents returns recent Kubernetes events for a pod.
func (c *Client) PodEvents(ctx context.Context, namespace, name string) ([]map[string]interface{}, error) {
	c.mu.RLock()
	defer c.mu.RUnlock()

	evts, err := c.cs.CoreV1().Events(namespace).List(ctx, metav1.ListOptions{
		FieldSelector: "involvedObject.name=" + name,
	})
	if err != nil {
		return nil, fmt.Errorf("events for %s/%s: %w", namespace, name, err)
	}

	result := make([]map[string]interface{}, 0, len(evts.Items))
	for _, e := range evts.Items {
		result = append(result, map[string]interface{}{
			"type":       e.Type,
			"reason":     e.Reason,
			"message":    e.Message,
			"count":      e.Count,
			"first_seen": e.FirstTimestamp.Time,
			"last_seen":  e.LastTimestamp.Time,
			"source":     e.Source.Component,
		})
	}
	return result, nil
}

// RolloutRestart triggers a rolling restart of a deployment by patching
// its pod template annotation.
func (c *Client) RolloutRestart(ctx context.Context, namespace, deployment string) error {
	c.mu.RLock()
	defer c.mu.RUnlock()

	dep, err := c.cs.AppsV1().Deployments(namespace).Get(ctx, deployment, metav1.GetOptions{})
	if err != nil {
		return fmt.Errorf("get deployment %s/%s: %w", namespace, deployment, err)
	}

	if dep.Labels[labels.Managed] != labels.ManagedValue {
		return fmt.Errorf("deployment %s/%s is not Argus-managed", namespace, deployment)
	}

	if dep.Spec.Template.ObjectMeta.Annotations == nil {
		dep.Spec.Template.ObjectMeta.Annotations = make(map[string]string)
	}
	dep.Spec.Template.ObjectMeta.Annotations["argus.restart-at"] = time.Now().Format(time.RFC3339)

	_, err = c.cs.AppsV1().Deployments(namespace).Update(ctx, dep, metav1.UpdateOptions{})
	return err
}
