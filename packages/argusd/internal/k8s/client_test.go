package k8s

import (
	"context"
	"testing"

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
