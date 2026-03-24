package main

import (
	"testing"
)

func TestImageTagRegex(t *testing.T) {
	tests := []struct {
		tag   string
		valid bool
	}{
		{"alpine:latest", true},
		{"argus/test-server:sha-abc123", true},
		{"my.registry/org/img:v1.2.3", true},
		{"node:22-alpine", true},
		{"a:b", true},
		{"", false},
		{"UPPER:case", false},
		{":notag", false},
		{"no-tag", false},
		{"has space:v1", false},
		{"img:tag with space", false},
		{"../escape:v1", false},
	}
	for _, tc := range tests {
		got := imageTagRe.MatchString(tc.tag)
		if got != tc.valid {
			t.Errorf("imageTagRe(%q) = %v, want %v", tc.tag, got, tc.valid)
		}
	}
}

func TestBuildArgKeyRegex(t *testing.T) {
	tests := []struct {
		key   string
		valid bool
	}{
		{"NODE_VERSION", true},
		{"my-arg", true},
		{"SIMPLE", true},
		{"_private", true},
		{"a", true},
		{"", false},
		{"123start", false},
		{"has space", false},
		{"key=val", false},
		{"semi;colon", false},
	}
	for _, tc := range tests {
		got := buildArgKeyRe.MatchString(tc.key)
		if got != tc.valid {
			t.Errorf("buildArgKeyRe(%q) = %v, want %v", tc.key, got, tc.valid)
		}
	}
}

func TestVolumeRegex(t *testing.T) {
	tests := []struct {
		vol   string
		valid bool
	}{
		{"/tmp/work:/app", true},
		{"data_vol:/data", true},
		{"/host/path:/container/path", true},
		{"vol-name:/mnt", true},
		{"", false},
		{"/path with space:/dest", false},
		{"$(cmd):/dest", false},
		{";rm -rf /:/x", false},
	}
	for _, tc := range tests {
		got := volumeRe.MatchString(tc.vol)
		if got != tc.valid {
			t.Errorf("volumeRe(%q) = %v, want %v", tc.vol, got, tc.valid)
		}
	}
}

func TestNetworkNameRegex(t *testing.T) {
	tests := []struct {
		name  string
		valid bool
	}{
		{"my-network", true},
		{"argus_net", true},
		{"net.1", true},
		{"simple", true},
		{"", false},
		{"has space", false},
		{"net;drop", false},
		{"net/slash", false},
	}
	for _, tc := range tests {
		got := networkNameRe.MatchString(tc.name)
		if got != tc.valid {
			t.Errorf("networkNameRe(%q) = %v, want %v", tc.name, got, tc.valid)
		}
	}
}

func TestBoolPtr(t *testing.T) {
	tr := boolPtr(true)
	if *tr != true {
		t.Error("boolPtr(true) should return pointer to true")
	}
	fa := boolPtr(false)
	if *fa != false {
		t.Error("boolPtr(false) should return pointer to false")
	}
}
