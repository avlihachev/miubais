package jobs

import (
	"errors"
	"time"
)

type Status string

const (
	StatusPending    Status = "pending"
	StatusInProgress Status = "in_progress"
	StatusDelivered  Status = "delivered"
	StatusCancelled  Status = "cancelled"
)

var (
	ErrNotFound      = errors.New("job not found")
	ErrInvalidStatus = errors.New("invalid status transition")
)

type Job struct {
	ID            string     `json:"id"`
	Reference     string     `json:"reference"`
	SourceLang    string     `json:"source_lang"`
	TargetLang    string     `json:"target_lang"`
	HoursEstimate float64    `json:"hours_estimate"`
	Translator    string     `json:"translator,omitempty"`
	Status        Status     `json:"status"`
	DueAt         *time.Time `json:"due_at,omitempty"`
	CreatedAt     time.Time  `json:"created_at"`
}

type NewJob struct {
	Reference     string
	SourceLang    string
	TargetLang    string
	HoursEstimate float64
	Translator    string
}

func ParseStatus(value string) (Status, bool) {
	switch status := Status(value); status {
	case StatusPending, StatusInProgress, StatusDelivered, StatusCancelled:
		return status, true
	}
	return "", false
}
