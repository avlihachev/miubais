package jobs

import (
	"fmt"
	"sync/atomic"
	"time"
)

type Repository interface {
	Get(id string) (Job, error)
	Put(j Job) error
	List() ([]Job, error)
}

type Service struct {
	repo Repository
	now  func() time.Time
	seq  atomic.Int64
}

func NewService(repo Repository, now func() time.Time) *Service {
	return &Service{repo: repo, now: now}
}

func (s *Service) Create(in NewJob) (Job, error) {
	job := Job{
		ID:            fmt.Sprintf("job-%04d", s.seq.Add(1)),
		Reference:     in.Reference,
		SourceLang:    in.SourceLang,
		TargetLang:    in.TargetLang,
		HoursEstimate: in.HoursEstimate,
		Translator:    in.Translator,
		Status:        StatusPending,
		CreatedAt:     s.now().UTC(),
	}
	if err := s.repo.Put(job); err != nil {
		return Job{}, fmt.Errorf("store job: %w", err)
	}
	return job, nil
}

func (s *Service) Get(id string) (Job, error) {
	return s.repo.Get(id)
}

func (s *Service) List(status Status) ([]Job, error) {
	all, err := s.repo.List()
	if err != nil {
		return nil, fmt.Errorf("list jobs: %w", err)
	}
	if status == "" {
		return all, nil
	}
	matching := make([]Job, 0, len(all))
	for _, job := range all {
		if job.Status == status {
			matching = append(matching, job)
		}
	}
	return matching, nil
}

func (s *Service) Cancel(id string) (Job, error) {
	job, err := s.repo.Get(id)
	if err != nil {
		return Job{}, err
	}
	if job.Status != StatusPending {
		return Job{}, ErrInvalidStatus
	}
	job.Status = StatusCancelled
	if err := s.repo.Put(job); err != nil {
		return Job{}, fmt.Errorf("store job: %w", err)
	}
	return job, nil
}
