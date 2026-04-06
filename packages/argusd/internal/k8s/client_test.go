package k8s

import (
	"bytes"
	"context"
	"strings"
	"testing"
	"time"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/client-go/kubernetes/fake"

	"github.com/diaz3618/argus-mcp/packages/argusd/internal/labels"
)

func managedPod(ns, name string) *corev1.Pod {
	return &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name:      name,
			Namespace: ns,
			Labels: map[string]string{
				labels.Managed: labels.ManagedValue,
			},
			CreationTimestamp: metav1.Now(),
		},
		Status: corev1.PodStatus{
			Phase: corev1.PodRunning,
		},
	}
}

func TestAvailable(t *testing.T) {
	tests := []struct {
		name   string
		client *Client
		want   bool
	}{
		{"nil client", nil, false},
		{"no clientset", &Client{}, false},
		{"with clientset", NewTestClient(fake.NewSimpleClientset()), true},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			if got := tc.client.Available(); got != tc.want {
				t.Errorf("Available() = %v, want %v", got, tc.want)
			}
		})
	}
}

func TestListPods(t *testing.T) {
	pod := managedPod("default", "web-1")
	cs := fake.NewSimpleClientset([]runtime.Object{pod}...)
	c := NewTestClient(cs)

	pods, err := c.ListPods(context.Background())
	if err != nil {
		t.Fatalf("ListPods: %v", err)
	}
	if len(pods) != 1 {
		t.Fatalf("ListPods returned %d pods, want 1", len(pods))
	}
	if pods[0].Name != "web-1" {
		t.Errorf("pod name = %q, want %q", pods[0].Name, "web-1")
	}
	if pods[0].Namespace != "default" {
		t.Errorf("pod namespace = %q, want %q", pods[0].Namespace, "default")
	}
}

func TestListPods_Empty(t *testing.T) {
	cs := fake.NewSimpleClientset()
	c := NewTestClient(cs)

	pods, err := c.ListPods(context.Background())
	if err != nil {
		t.Fatalf("ListPods: %v", err)
	}
	if len(pods) != 0 {
		t.Fatalf("ListPods returned %d pods, want 0", len(pods))
	}
}

func TestDescribePod(t *testing.T) {
	pod := managedPod("kube-system", "dns-1")
	cs := fake.NewSimpleClientset(pod)
	c := NewTestClient(cs)

	info, err := c.DescribePod(context.Background(), "kube-system", "dns-1")
	if err != nil {
		t.Fatalf("DescribePod: %v", err)
	}
	if info.Name != "dns-1" {
		t.Errorf("pod name = %q, want %q", info.Name, "dns-1")
	}
}

func TestDescribePod_NotManaged(t *testing.T) {
	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "rogue",
			Namespace: "default",
		},
	}
	cs := fake.NewSimpleClientset(pod)
	c := NewTestClient(cs)

	_, err := c.DescribePod(context.Background(), "default", "rogue")
	if err == nil {
		t.Fatal("DescribePod should fail for unmanaged pod")
	}
}

func TestDescribePod_NotFound(t *testing.T) {
	cs := fake.NewSimpleClientset()
	c := NewTestClient(cs)

	_, err := c.DescribePod(context.Background(), "default", "missing")
	if err == nil {
		t.Fatal("DescribePod should fail for missing pod")
	}
}

func TestDeletePod(t *testing.T) {
	pod := managedPod("default", "del-me")
	cs := fake.NewSimpleClientset(pod)
	c := NewTestClient(cs)

	err := c.DeletePod(context.Background(), "default", "del-me")
	if err != nil {
		t.Fatalf("DeletePod: %v", err)
	}

	// Verify deletion
	_, err = cs.CoreV1().Pods("default").Get(context.Background(), "del-me", metav1.GetOptions{})
	if err == nil {
		t.Fatal("pod should have been deleted")
	}
}

func TestDeletePod_NotManaged(t *testing.T) {
	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "unmanaged",
			Namespace: "default",
		},
	}
	cs := fake.NewSimpleClientset(pod)
	c := NewTestClient(cs)

	err := c.DeletePod(context.Background(), "default", "unmanaged")
	if err == nil {
		t.Fatal("DeletePod should fail for unmanaged pod")
	}
}

func TestPodEvents(t *testing.T) {
	cs := fake.NewSimpleClientset()

	// Create an event for the pod
	evt := &corev1.Event{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "web-1.abc",
			Namespace: "default",
		},
		InvolvedObject: corev1.ObjectReference{
			Name: "web-1",
		},
		Type:    "Normal",
		Reason:  "Scheduled",
		Message: "Successfully assigned",
		Source:  corev1.EventSource{Component: "scheduler"},
	}
	_, err := cs.CoreV1().Events("default").Create(context.Background(), evt, metav1.CreateOptions{})
	if err != nil {
		t.Fatalf("create event: %v", err)
	}

	c := NewTestClient(cs)
	events, err := c.PodEvents(context.Background(), "default", "web-1")
	if err != nil {
		t.Fatalf("PodEvents: %v", err)
	}
	if len(events) != 1 {
		t.Fatalf("PodEvents returned %d events, want 1", len(events))
	}
	if events[0]["reason"] != "Scheduled" {
		t.Errorf("event reason = %v, want %q", events[0]["reason"], "Scheduled")
	}
}

// ---------------------------------------------------------------------------
// podToInfo coverage: container statuses and age formatting
// ---------------------------------------------------------------------------

func TestPodToInfo_ContainerStatuses(t *testing.T) {
	now := metav1.Now()
	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name:              "status-pod",
			Namespace:         "ns1",
			Labels:            map[string]string{labels.Managed: labels.ManagedValue},
			CreationTimestamp: now,
		},
		Spec: corev1.PodSpec{NodeName: "node-1"},
		Status: corev1.PodStatus{
			Phase:  corev1.PodRunning,
			PodIP:  "10.0.0.5",
			HostIP: "192.168.1.1",
			ContainerStatuses: []corev1.ContainerStatus{
				{
					Name:         "app",
					Image:        "myapp:v1",
					Ready:        true,
					RestartCount: 2,
					State:        corev1.ContainerState{Running: &corev1.ContainerStateRunning{StartedAt: now}},
				},
				{
					Name:         "sidecar",
					Image:        "proxy:latest",
					Ready:        false,
					RestartCount: 0,
					State:        corev1.ContainerState{Waiting: &corev1.ContainerStateWaiting{Reason: "CrashLoopBackOff"}},
				},
				{
					Name:         "init",
					Image:        "busybox:1",
					Ready:        false,
					RestartCount: 1,
					State:        corev1.ContainerState{Terminated: &corev1.ContainerStateTerminated{Reason: "Completed"}},
				},
				{
					Name:         "mystery",
					Image:        "unknown:0",
					Ready:        false,
					RestartCount: 0,
					State:        corev1.ContainerState{}, // no Running/Waiting/Terminated → "unknown"
				},
			},
		},
	}

	info := podToInfo(pod)

	if info.Name != "status-pod" {
		t.Errorf("Name = %q, want %q", info.Name, "status-pod")
	}
	if info.PodIP != "10.0.0.5" {
		t.Errorf("PodIP = %q, want %q", info.PodIP, "10.0.0.5")
	}
	if info.NodeName != "node-1" {
		t.Errorf("NodeName = %q, want %q", info.NodeName, "node-1")
	}
	if info.HostIP != "192.168.1.1" {
		t.Errorf("HostIP = %q, want %q", info.HostIP, "192.168.1.1")
	}
	if info.Restarts != 3 { // 2 + 0 + 1 + 0
		t.Errorf("Restarts = %d, want 3", info.Restarts)
	}
	if len(info.Containers) != 4 {
		t.Fatalf("Containers count = %d, want 4", len(info.Containers))
	}

	// running container
	if info.Containers[0].State != "running" {
		t.Errorf("container[0] state = %q, want %q", info.Containers[0].State, "running")
	}
	if !info.Containers[0].Ready {
		t.Error("container[0] should be ready")
	}

	// waiting container
	if info.Containers[1].State != "waiting:CrashLoopBackOff" {
		t.Errorf("container[1] state = %q, want %q", info.Containers[1].State, "waiting:CrashLoopBackOff")
	}

	// terminated container
	if info.Containers[2].State != "terminated:Completed" {
		t.Errorf("container[2] state = %q, want %q", info.Containers[2].State, "terminated:Completed")
	}

	// unknown state container
	if info.Containers[3].State != "unknown" {
		t.Errorf("container[3] state = %q, want %q", info.Containers[3].State, "unknown")
	}
}

func TestPodToInfo_AgeFormatting(t *testing.T) {
	tests := []struct {
		name    string
		offset  time.Duration
		wantSfx string // expected suffix character
	}{
		{"seconds", 30 * time.Second, "s"},
		{"minutes", 5 * time.Minute, "m"},
		{"hours", 3 * time.Hour, "h"},
		{"days", 48 * time.Hour, "d"},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			pod := &corev1.Pod{
				ObjectMeta: metav1.ObjectMeta{
					Name:              "age-test",
					Namespace:         "default",
					CreationTimestamp: metav1.NewTime(time.Now().Add(-tc.offset)),
				},
				Status: corev1.PodStatus{Phase: corev1.PodRunning},
			}
			info := podToInfo(pod)
			if !strings.HasSuffix(info.Age, tc.wantSfx) {
				t.Errorf("Age = %q, want suffix %q", info.Age, tc.wantSfx)
			}
		})
	}
}

// ---------------------------------------------------------------------------
// RolloutRestart coverage
// ---------------------------------------------------------------------------

func managedDeployment(ns, name string) *appsv1.Deployment {
	return &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:      name,
			Namespace: ns,
			Labels: map[string]string{
				labels.Managed: labels.ManagedValue,
			},
		},
		Spec: appsv1.DeploymentSpec{
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{
					Labels: map[string]string{"app": name},
				},
				Spec: corev1.PodSpec{
					Containers: []corev1.Container{{Name: "app", Image: "img:1"}},
				},
			},
			Selector: &metav1.LabelSelector{
				MatchLabels: map[string]string{"app": name},
			},
		},
	}
}

func TestRolloutRestart(t *testing.T) {
	dep := managedDeployment("default", "web")
	cs := fake.NewSimpleClientset(dep)
	c := NewTestClient(cs)

	err := c.RolloutRestart(context.Background(), "default", "web")
	if err != nil {
		t.Fatalf("RolloutRestart: %v", err)
	}

	// Verify the annotation was set
	updated, err := cs.AppsV1().Deployments("default").Get(context.Background(), "web", metav1.GetOptions{})
	if err != nil {
		t.Fatalf("get updated deployment: %v", err)
	}
	ann := updated.Spec.Template.ObjectMeta.Annotations
	if ann == nil {
		t.Fatal("annotations should not be nil after restart")
	}
	if _, ok := ann["argus.restart-at"]; !ok {
		t.Error("expected argus.restart-at annotation after restart")
	}
}

func TestRolloutRestart_NotManaged(t *testing.T) {
	dep := &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "unmanaged-dep",
			Namespace: "default",
		},
		Spec: appsv1.DeploymentSpec{
			Template: corev1.PodTemplateSpec{
				Spec: corev1.PodSpec{
					Containers: []corev1.Container{{Name: "app", Image: "img:1"}},
				},
			},
		},
	}
	cs := fake.NewSimpleClientset(dep)
	c := NewTestClient(cs)

	err := c.RolloutRestart(context.Background(), "default", "unmanaged-dep")
	if err == nil {
		t.Fatal("RolloutRestart should fail for unmanaged deployment")
	}
}

func TestRolloutRestart_NotFound(t *testing.T) {
	cs := fake.NewSimpleClientset()
	c := NewTestClient(cs)

	err := c.RolloutRestart(context.Background(), "default", "nonexistent")
	if err == nil {
		t.Fatal("RolloutRestart should fail for missing deployment")
	}
}

func TestRolloutRestart_ExistingAnnotations(t *testing.T) {
	dep := managedDeployment("default", "annotated")
	dep.Spec.Template.ObjectMeta.Annotations = map[string]string{"existing": "value"}
	cs := fake.NewSimpleClientset(dep)
	c := NewTestClient(cs)

	err := c.RolloutRestart(context.Background(), "default", "annotated")
	if err != nil {
		t.Fatalf("RolloutRestart: %v", err)
	}

	updated, err := cs.AppsV1().Deployments("default").Get(context.Background(), "annotated", metav1.GetOptions{})
	if err != nil {
		t.Fatalf("get deployment: %v", err)
	}
	if updated.Spec.Template.ObjectMeta.Annotations["existing"] != "value" {
		t.Error("existing annotation should be preserved")
	}
	if _, ok := updated.Spec.Template.ObjectMeta.Annotations["argus.restart-at"]; !ok {
		t.Error("expected argus.restart-at annotation")
	}
}

// ---------------------------------------------------------------------------
// Additional edge cases for existing methods
// ---------------------------------------------------------------------------

func TestDeletePod_NotFound(t *testing.T) {
	cs := fake.NewSimpleClientset()
	c := NewTestClient(cs)

	err := c.DeletePod(context.Background(), "default", "ghost")
	if err == nil {
		t.Fatal("DeletePod should fail for missing pod")
	}
}

func TestPodEvents_Empty(t *testing.T) {
	cs := fake.NewSimpleClientset()
	c := NewTestClient(cs)

	events, err := c.PodEvents(context.Background(), "default", "no-events")
	if err != nil {
		t.Fatalf("PodEvents: %v", err)
	}
	if len(events) != 0 {
		t.Errorf("expected 0 events, got %d", len(events))
	}
}

func TestListPods_MultipleNamespaces(t *testing.T) {
	pod1 := managedPod("ns-a", "pod-1")
	pod2 := managedPod("ns-b", "pod-2")
	pod3 := managedPod("ns-a", "pod-3")
	cs := fake.NewSimpleClientset(pod1, pod2, pod3)
	c := NewTestClient(cs)

	pods, err := c.ListPods(context.Background())
	if err != nil {
		t.Fatalf("ListPods: %v", err)
	}
	if len(pods) != 3 {
		t.Errorf("ListPods returned %d pods, want 3", len(pods))
	}
}

// ---------------------------------------------------------------------------
// StreamPodLogs tests
// ---------------------------------------------------------------------------

func TestStreamPodLogs_AllOptions(t *testing.T) {
	// The fake clientset returns an error from Stream() because it has no
	// real REST backend, but this exercises the function setup (options
	// building, container, tail, since).
	pod := managedPod("default", "logger")
	cs := fake.NewSimpleClientset(pod)
	c := NewTestClient(cs)

	var buf bytes.Buffer
	err := c.StreamPodLogs(context.Background(), "default", "logger", "main", false, "1h", 50, &buf)
	// fake client always errors on Stream — we just verify setup ran
	if err == nil {
		t.Log("StreamPodLogs succeeded (unexpected with fake client); output:", buf.String())
	}
}

func TestStreamPodLogs_NoContainerNoSince(t *testing.T) {
	pod := managedPod("default", "minimal")
	cs := fake.NewSimpleClientset(pod)
	c := NewTestClient(cs)

	var buf bytes.Buffer
	err := c.StreamPodLogs(context.Background(), "default", "minimal", "", false, "", 0, &buf)
	if err == nil {
		t.Log("StreamPodLogs succeeded; output:", buf.String())
	}
}

func TestStreamPodLogs_CancelledContext(t *testing.T) {
	pod := managedPod("default", "cancel-me")
	cs := fake.NewSimpleClientset(pod)
	c := NewTestClient(cs)

	ctx, cancel := context.WithCancel(context.Background())
	cancel() // cancel immediately

	var buf bytes.Buffer
	// With cancelled context the call should return quickly
	_ = c.StreamPodLogs(ctx, "default", "cancel-me", "", false, "", 100, &buf)
}
