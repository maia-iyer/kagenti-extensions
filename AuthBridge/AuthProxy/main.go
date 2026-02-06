package main

import (
	"bytes"
	"io"
	"log"
	"net/http"
	"net/url"
	"os"
)

const (
	defaultTargetServiceURL = "http://demo-app-service:8081"
	proxyPort               = "0.0.0.0:8080"
)

func main() {
	targetServiceURL := os.Getenv("TARGET_SERVICE_URL")
	if targetServiceURL == "" {
		targetServiceURL = defaultTargetServiceURL
	}

	http.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		proxyHandler(w, r, targetServiceURL)
	})
	log.Printf("Auth proxy starting on port %s", proxyPort)
	log.Printf("Forwarding requests to %s", targetServiceURL)
	log.Printf("JWT validation is handled by the inbound ext proc")
	log.Fatal(http.ListenAndServe(proxyPort, nil))
}

func proxyHandler(w http.ResponseWriter, r *http.Request, targetServiceURL string) {
	body, err := io.ReadAll(r.Body)
	if err != nil {
		http.Error(w, "Failed to read request body", http.StatusInternalServerError)
		return
	}
	defer r.Body.Close()

	targetURL, err := url.Parse(targetServiceURL + r.URL.Path)
	if err != nil {
		http.Error(w, "Invalid target URL", http.StatusInternalServerError)
		return
	}

	proxyReq, err := http.NewRequest(r.Method, targetURL.String(), bytes.NewReader(body))
	if err != nil {
		http.Error(w, "Failed to create proxy request", http.StatusInternalServerError)
		return
	}

	for key, values := range r.Header {
		for _, value := range values {
			proxyReq.Header.Add(key, value)
		}
	}

	client := &http.Client{}
	resp, err := client.Do(proxyReq)
	if err != nil {
		http.Error(w, "Failed to forward request", http.StatusBadGateway)
		return
	}
	defer resp.Body.Close()

	for key, values := range resp.Header {
		for _, value := range values {
			w.Header().Add(key, value)
		}
	}
	w.WriteHeader(resp.StatusCode)

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		http.Error(w, "Failed to read response", http.StatusInternalServerError)
		return
	}

	w.Write(respBody)

	log.Printf("Forwarded %s %s - Status: %d", r.Method, r.URL.Path, resp.StatusCode)
}
