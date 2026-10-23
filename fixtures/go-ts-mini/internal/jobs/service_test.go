package jobs_test

import (
	"errors"
	"testing"
	"time"

	"example.com/go-ts-mini/internal/jobs"
	"example.com/go-ts-mini/internal/store"
)

var fixedNow = time.Date(2026, 10, 1, 9, 30, 0, 0, time.UTC)

func newService() *jobs.Service {
	return jobs.NewService(store.NewMemory(), func() time.Time { return fixedNow })
}

func sample(reference string) jobs.NewJob {
	return jobs.NewJob{
		Reference:     reference,
		SourceLang:    "en",
		TargetLang:    "de",
		HoursEstimate: 12.5,
	}
}

func TestCreateAssignsIDStatusAndTime(t *testing.T) {
	svc := newService()
	got, err := svc.Create(sample("REF-1"))
	if err != nil {
		t.Fatal(err)
	}
	if got.ID != "job-0001" || got.Status != jobs.StatusPending || !got.CreatedAt.Equal(fixedNow) {
		t.Fatalf("unexpected job %+v", got)
	}
}

func TestListFiltersByStatus(t *testing.T) {
	svc := newService()
	first, _ := svc.Create(sample("REF-1"))
	if _, err := svc.Create(sample("REF-2")); err != nil {
		t.Fatal(err)
	}
	if _, err := svc.Cancel(first.ID); err != nil {
		t.Fatal(err)
	}
	cancelled, err := svc.List(jobs.StatusCancelled)
	if err != nil {
		t.Fatal(err)
	}
	if len(cancelled) != 1 || cancelled[0].ID != first.ID {
		t.Fatalf("want only %s, got %+v", first.ID, cancelled)
	}
	all, _ := svc.List("")
	if len(all) != 2 {
		t.Fatalf("want 2 jobs, got %d", len(all))
	}
}

func TestCancelTwiceIsInvalid(t *testing.T) {
	svc := newService()
	created, _ := svc.Create(sample("REF-1"))
	if _, err := svc.Cancel(created.ID); err != nil {
		t.Fatal(err)
	}
	if _, err := svc.Cancel(created.ID); !errors.Is(err, jobs.ErrInvalidStatus) {
		t.Fatalf("want ErrInvalidStatus, got %v", err)
	}
}

func TestCancelUnknown(t *testing.T) {
	if _, err := newService().Cancel("job-9999"); !errors.Is(err, jobs.ErrNotFound) {
		t.Fatalf("want ErrNotFound, got %v", err)
	}
}

func TestParseStatus(t *testing.T) {
	if status, ok := jobs.ParseStatus("in_progress"); !ok || status != jobs.StatusInProgress {
		t.Fatalf("in_progress should parse, got %q %v", status, ok)
	}
	if _, ok := jobs.ParseStatus("archived"); ok {
		t.Fatal("archived should not parse")
	}
}
