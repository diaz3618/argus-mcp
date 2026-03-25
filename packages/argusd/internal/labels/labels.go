// Package labels defines Argus resource labeling constants used to scope
// Docker containers and Kubernetes pods managed by Argus.
//
// All Argus-created resources are tagged with these labels so that argusd
// only operates on resources it owns — unmanaged containers/pods are
// invisible by default.
package labels

// Label keys applied to Docker containers and Kubernetes pods.
const (
	// Managed marks a resource as Argus-managed.
	Managed = "argus.managed"
	// Project identifies the Argus project that owns the resource.
	Project = "argus.project"
	// ServerID identifies the MCP backend server name.
	ServerID = "argus.server_id"
	// SessionID identifies the session that created the resource.
	SessionID = "argus.session_id"
)

// ManagedValue is the expected value for the Managed label.
const ManagedValue = "true"

// Selector returns a Docker label filter string that matches all
// Argus-managed resources.
func Selector() string {
	return Managed + "=" + ManagedValue
}

// DefaultLabels returns the base labels applied to every Argus resource.
func DefaultLabels(project, serverID, sessionID string) map[string]string {
	m := map[string]string{
		Managed: ManagedValue,
	}
	if project != "" {
		m[Project] = project
	}
	if serverID != "" {
		m[ServerID] = serverID
	}
	if sessionID != "" {
		m[SessionID] = sessionID
	}
	return m
}
