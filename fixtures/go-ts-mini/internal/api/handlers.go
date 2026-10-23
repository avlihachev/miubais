package api

import (
	"encoding/json"
	"errors"
	"net/http"
	"strings"

	"example.com/go-ts-mini/internal/jobs"
)

const (
	maxHoursEstimate   = 1000
	maxTranslatorChars = 64
)

type Handler struct {
	svc *jobs.Service
}

func NewHandler(svc *jobs.Service) *Handler {
	return &Handler{svc: svc}
}

func (h *Handler) Routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /jobs", h.list)
	mux.HandleFunc("POST /jobs", h.create)
	mux.HandleFunc("GET /jobs/{id}", h.get)
	mux.HandleFunc("POST /jobs/{id}/cancel", h.cancel)
	return mux
}

type createRequest struct {
	Reference     string  `json:"reference"`
	SourceLang    string  `json:"source_lang"`
	TargetLang    string  `json:"target_lang"`
	HoursEstimate float64 `json:"hours_estimate"`
	Translator    string  `json:"translator"`
}

type listResponse struct {
	Jobs []jobs.Job `json:"jobs"`
}

func (r createRequest) validate() error {
	switch {
	case strings.TrimSpace(r.Reference) == "":
		return errors.New("reference is required")
	case strings.TrimSpace(r.SourceLang) == "" || strings.TrimSpace(r.TargetLang) == "":
		return errors.New("source_lang and target_lang are required")
	case r.SourceLang == r.TargetLang:
		return errors.New("source_lang and target_lang must differ")
	case r.HoursEstimate <= 0 || r.HoursEstimate > maxHoursEstimate:
		return errors.New("hours_estimate must be between 0 and 1000")
	case len(r.Translator) > maxTranslatorChars:
		return errors.New("translator is too long")
	}
	return nil
}

func decode(r *http.Request, dst any) error {
	dec := json.NewDecoder(r.Body)
	dec.DisallowUnknownFields()
	return dec.Decode(dst)
}

func (h *Handler) create(w http.ResponseWriter, r *http.Request) {
	var req createRequest
	if err := decode(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid_json", "request body must be a job object")
		return
	}
	if err := req.validate(); err != nil {
		writeError(w, http.StatusBadRequest, "invalid_input", err.Error())
		return
	}
	job, err := h.svc.Create(jobs.NewJob{
		Reference:     req.Reference,
		SourceLang:    req.SourceLang,
		TargetLang:    req.TargetLang,
		HoursEstimate: req.HoursEstimate,
		Translator:    req.Translator,
	})
	if err != nil {
		writeServiceError(w, err)
		return
	}
	writeJSON(w, http.StatusCreated, job)
}

func (h *Handler) list(w http.ResponseWriter, r *http.Request) {
	raw := r.URL.Query().Get("status")
	status, ok := jobs.ParseStatus(raw)
	if raw != "" && !ok {
		writeError(w, http.StatusBadRequest, "invalid_input", "unknown status "+raw)
		return
	}
	items, err := h.svc.List(status)
	if err != nil {
		writeServiceError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, listResponse{Jobs: items})
}

func (h *Handler) get(w http.ResponseWriter, r *http.Request) {
	job, err := h.svc.Get(r.PathValue("id"))
	if err != nil {
		writeServiceError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, job)
}

func (h *Handler) cancel(w http.ResponseWriter, r *http.Request) {
	job, err := h.svc.Cancel(r.PathValue("id"))
	if err != nil {
		writeServiceError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, job)
}
