package store

import (
	"slices"
	"strings"
	"sync"

	"example.com/go-ts-mini/internal/jobs"
)

type Memory struct {
	mu   sync.RWMutex
	rows map[string]jobs.Job
}

func NewMemory() *Memory {
	return &Memory{rows: map[string]jobs.Job{}}
}

func (m *Memory) Get(id string) (jobs.Job, error) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	job, ok := m.rows[id]
	if !ok {
		return jobs.Job{}, jobs.ErrNotFound
	}
	return job, nil
}

func (m *Memory) Put(job jobs.Job) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.rows[job.ID] = job
	return nil
}

func (m *Memory) List() ([]jobs.Job, error) {
	m.mu.RLock()
	defer m.mu.RUnlock()
	all := make([]jobs.Job, 0, len(m.rows))
	for _, job := range m.rows {
		all = append(all, job)
	}
	slices.SortFunc(all, func(a, b jobs.Job) int {
		return strings.Compare(a.ID, b.ID)
	})
	return all, nil
}
