package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"runtime"
)

// Schedule represents the fetch schedule returned by the server.
type Schedule struct {
	FetchURL        string            `json:"fetch_url"`
	IntervalSeconds int               `json:"interval_seconds"`
	OffsetSeconds   int               `json:"offset_seconds"`
	Headers         map[string]string `json:"headers"`
}

// tryRegister sends a POST /agents/register request to the server.
// Registration is idempotent — if the agent is already known the server
// returns the current status. Returns nil on success.
func tryRegister(cfg *Config) error {
	hostname, _ := os.Hostname()
	systemInfo := fmt.Sprintf("%s/%s %s", runtime.GOOS, runtime.GOARCH, hostname)

	payload := map[string]string{
		"name":        cfg.name,
		"public_key":  cfg.publicPEM,
		"system_info": systemInfo,
	}
	body, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("marshal register payload: %w", err)
	}

	url := cfg.server + "/agents/register"
	resp, err := http.Post(url, "application/json", bytes.NewReader(body))
	if err != nil {
		return fmt.Errorf("register request: %w", err)
	}
	defer resp.Body.Close()

	respBody, _ := io.ReadAll(resp.Body)
	if resp.StatusCode != 200 {
		return fmt.Errorf("register HTTP %d: %s", resp.StatusCode, respBody)
	}

	var result struct {
		AgentID string `json:"agent_id"`
		Status  string `json:"status"`
	}
	if err := json.Unmarshal(respBody, &result); err != nil {
		return fmt.Errorf("parse register response: %w", err)
	}

	log.Printf("Registered: agent_id=%s status=%s", result.AgentID, result.Status)
	return nil
}

// register calls tryRegister and fatals on error. Used by the interactive
// wizard where failure should be immediately visible.
func register(cfg *Config) {
	if err := tryRegister(cfg); err != nil {
		log.Fatalf("Registration failed: %v", err)
	}
}

// checkin sends a POST /agents/checkin request and returns the schedule and status.
func checkin(cfg *Config) (Schedule, string, error) {
	body := []byte("{}")
	ts := currentTimestamp()
	sig, err := signPayload(cfg.key, body, ts)
	if err != nil {
		return Schedule{}, "", fmt.Errorf("sign checkin: %w", err)
	}

	req, err := http.NewRequest("POST", cfg.server+"/agents/checkin", bytes.NewReader(body))
	if err != nil {
		return Schedule{}, "", fmt.Errorf("create checkin request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Agent-Id", cfg.agentID)
	req.Header.Set("X-Agent-Ts", ts)
	req.Header.Set("X-Agent-Sig", sig)

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return Schedule{}, "", fmt.Errorf("checkin request: %w", err)
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return Schedule{}, "", fmt.Errorf("read checkin response: %w", err)
	}

	// Handle 403 — pending or revoked
	if resp.StatusCode == 403 {
		var errResp struct {
			Status  string `json:"status"`
			Message string `json:"message"`
		}
		if err := json.Unmarshal(respBody, &errResp); err != nil {
			return Schedule{}, "", fmt.Errorf("parse 403 response: %w", err)
		}
		return Schedule{}, errResp.Status, nil
	}

	if resp.StatusCode != 200 {
		return Schedule{}, "", fmt.Errorf("checkin HTTP %d: %s", resp.StatusCode, respBody)
	}

	var schedule Schedule
	if err := json.Unmarshal(respBody, &schedule); err != nil {
		return Schedule{}, "", fmt.Errorf("parse schedule: %w", err)
	}

	return schedule, "approved", nil
}

// report sends a POST /agents/report with the AVL data body, signed.
// Returns the updated schedule.
func report(cfg *Config, data []byte) (Schedule, error) {
	ts := currentTimestamp()
	sig, err := signPayload(cfg.key, data, ts)
	if err != nil {
		return Schedule{}, fmt.Errorf("sign report: %w", err)
	}

	req, err := http.NewRequest("POST", cfg.server+"/agents/report", bytes.NewReader(data))
	if err != nil {
		return Schedule{}, fmt.Errorf("create report request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Agent-Id", cfg.agentID)
	req.Header.Set("X-Agent-Ts", ts)
	req.Header.Set("X-Agent-Sig", sig)

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return Schedule{}, fmt.Errorf("report request: %w", err)
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return Schedule{}, fmt.Errorf("read report response: %w", err)
	}

	if resp.StatusCode != 200 {
		return Schedule{}, fmt.Errorf("report HTTP %d: %s", resp.StatusCode, respBody)
	}

	var schedule Schedule
	if err := json.Unmarshal(respBody, &schedule); err != nil {
		return Schedule{}, fmt.Errorf("parse report schedule: %w", err)
	}

	return schedule, nil
}
