package main

import (
	"log"
	"net/http"
	"os"
	"time"

	"example.com/go-ts-mini/internal/api"
	"example.com/go-ts-mini/internal/jobs"
	"example.com/go-ts-mini/internal/store"
)

func main() {
	addr := os.Getenv("ADDR")
	if addr == "" {
		addr = ":8080"
	}
	svc := jobs.NewService(store.NewMemory(), time.Now)
	log.Printf("translation jobs service listening on %s", addr)
	log.Fatal(http.ListenAndServe(addr, api.NewHandler(svc).Routes()))
}
