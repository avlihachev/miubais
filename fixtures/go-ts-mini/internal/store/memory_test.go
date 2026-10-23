package store

import (
	"errors"
	"testing"

	"example.com/go-ts-mini/internal/jobs"
)

func TestGetUnknownIsNotFound(t *testing.T) {
	if _, err := NewMemory().Get("job-0001"); !errors.Is(err, jobs.ErrNotFound) {
		t.Fatalf("want ErrNotFound, got %v", err)
	}
}

func TestPutReplacesAndListSortsByID(t *testing.T) {
	m := NewMemory()
	for _, id := range []string{"job-0002", "job-0001", "job-0002"} {
		if err := m.Put(jobs.Job{ID: id, Reference: "REF-" + id}); err != nil {
			t.Fatal(err)
		}
	}
	all, err := m.List()
	if err != nil {
		t.Fatal(err)
	}
	if len(all) != 2 || all[0].ID != "job-0001" || all[1].ID != "job-0002" {
		t.Fatalf("unexpected list %+v", all)
	}
}
