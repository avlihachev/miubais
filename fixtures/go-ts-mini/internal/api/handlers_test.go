package api

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"example.com/go-ts-mini/internal/jobs"
	"example.com/go-ts-mini/internal/store"
)

const validBody = `{"reference":"REF-1","source_lang":"en","target_lang":"de","hours_estimate":12.5}`

func newServer() http.Handler {
	now := func() time.Time { return time.Date(2026, 10, 1, 9, 30, 0, 0, time.UTC) }
	return NewHandler(jobs.NewService(store.NewMemory(), now)).Routes()
}

func do(t *testing.T, srv http.Handler, method, path, body string) *httptest.ResponseRecorder {
	t.Helper()
	rec := httptest.NewRecorder()
	srv.ServeHTTP(rec, httptest.NewRequest(method, path, strings.NewReader(body)))
	return rec
}

func errorCode(t *testing.T, rec *httptest.ResponseRecorder) string {
	t.Helper()
	var body errorBody
	if err := json.NewDecoder(rec.Body).Decode(&body); err != nil {
		t.Fatalf("error body is not JSON: %v", err)
	}
	return body.Error.Code
}

func TestCreateReturnsJob(t *testing.T) {
	rec := do(t, newServer(), http.MethodPost, "/jobs", validBody)
	if rec.Code != http.StatusCreated {
		t.Fatalf("want 201, got %d: %s", rec.Code, rec.Body)
	}
	var got jobs.Job
	if err := json.NewDecoder(rec.Body).Decode(&got); err != nil {
		t.Fatal(err)
	}
	if got.ID != "job-0001" || got.Status != jobs.StatusPending {
		t.Fatalf("unexpected job %+v", got)
	}
}

func TestCreateRejectsInvalidInput(t *testing.T) {
	cases := map[string]string{
		"missing reference": `{"source_lang":"en","target_lang":"de","hours_estimate":1}`,
		"same languages":    `{"reference":"R","source_lang":"en","target_lang":"en","hours_estimate":1}`,
		"zero hours":        `{"reference":"R","source_lang":"en","target_lang":"de","hours_estimate":0}`,
		"unknown field":     `{"reference":"R","source_lang":"en","target_lang":"de","hours_estimate":1,"x":1}`,
	}
	for name, body := range cases {
		rec := do(t, newServer(), http.MethodPost, "/jobs", body)
		if rec.Code != http.StatusBadRequest {
			t.Errorf("%s: want 400, got %d", name, rec.Code)
			continue
		}
		if code := errorCode(t, rec); code != "invalid_input" && code != "invalid_json" {
			t.Errorf("%s: unexpected error code %q", name, code)
		}
	}
}

func TestGetUnknownJobReturns404(t *testing.T) {
	rec := do(t, newServer(), http.MethodGet, "/jobs/job-9999", "")
	if rec.Code != http.StatusNotFound || errorCode(t, rec) != "not_found" {
		t.Fatalf("want 404 not_found, got %d", rec.Code)
	}
}

func TestCancelUnknownJobReturns404(t *testing.T) {
	rec := do(t, newServer(), http.MethodPost, "/jobs/job-9999/cancel", "")
	if rec.Code != http.StatusNotFound || errorCode(t, rec) != "not_found" {
		t.Fatalf("want 404 not_found, got %d", rec.Code)
	}
}

func TestCancelTwiceReturns409(t *testing.T) {
	srv := newServer()
	do(t, srv, http.MethodPost, "/jobs", validBody)
	if rec := do(t, srv, http.MethodPost, "/jobs/job-0001/cancel", ""); rec.Code != http.StatusOK {
		t.Fatalf("first cancel: want 200, got %d", rec.Code)
	}
	rec := do(t, srv, http.MethodPost, "/jobs/job-0001/cancel", "")
	if rec.Code != http.StatusConflict || errorCode(t, rec) != "invalid_status" {
		t.Fatalf("second cancel: want 409 invalid_status, got %d", rec.Code)
	}
}

func TestListRejectsUnknownStatus(t *testing.T) {
	rec := do(t, newServer(), http.MethodGet, "/jobs?status=archived", "")
	if rec.Code != http.StatusBadRequest || errorCode(t, rec) != "invalid_input" {
		t.Fatalf("want 400 invalid_input, got %d", rec.Code)
	}
}

func TestListFiltersByStatus(t *testing.T) {
	srv := newServer()
	do(t, srv, http.MethodPost, "/jobs", validBody)
	do(t, srv, http.MethodPost, "/jobs", strings.Replace(validBody, "REF-1", "REF-2", 1))
	do(t, srv, http.MethodPost, "/jobs/job-0002/cancel", "")
	rec := do(t, srv, http.MethodGet, "/jobs?status=pending", "")
	var body listResponse
	if err := json.NewDecoder(rec.Body).Decode(&body); err != nil {
		t.Fatal(err)
	}
	if len(body.Jobs) != 1 || body.Jobs[0].ID != "job-0001" {
		t.Fatalf("want only job-0001, got %+v", body.Jobs)
	}
}
