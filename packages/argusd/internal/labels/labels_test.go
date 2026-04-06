package labels

import "testing"

func TestSelector(t *testing.T) {
	got := Selector()
	want := "argus.managed=true"
	if got != want {
		t.Errorf("Selector() = %q, want %q", got, want)
	}
}

func TestDefaultLabels(t *testing.T) {
	tests := []struct {
		name      string
		project   string
		serverID  string
		sessionID string
		wantKeys  []string
		wantLen   int
	}{
		{
			name:     "all empty",
			wantKeys: []string{Managed},
			wantLen:  1,
		},
		{
			name:      "all set",
			project:   "myproject",
			serverID:  "srv-1",
			sessionID: "sess-abc",
			wantKeys:  []string{Managed, Project, ServerID, SessionID},
			wantLen:   4,
		},
		{
			name:     "project only",
			project:  "p1",
			wantKeys: []string{Managed, Project},
			wantLen:  2,
		},
		{
			name:      "server and session",
			serverID:  "srv-x",
			sessionID: "sess-y",
			wantKeys:  []string{Managed, ServerID, SessionID},
			wantLen:   3,
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			got := DefaultLabels(tc.project, tc.serverID, tc.sessionID)
			if len(got) != tc.wantLen {
				t.Errorf("len(DefaultLabels) = %d, want %d", len(got), tc.wantLen)
			}
			for _, k := range tc.wantKeys {
				if _, ok := got[k]; !ok {
					t.Errorf("missing key %q in result", k)
				}
			}
			if got[Managed] != ManagedValue {
				t.Errorf("Managed label = %q, want %q", got[Managed], ManagedValue)
			}
		})
	}
}
