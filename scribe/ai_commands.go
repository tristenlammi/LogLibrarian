package main

import (
	"context"
	"encoding/json"
	"log"
	"time"
)

// AI command handlers for WebSocket commands from the server

// handleAIStatusCommand sends AI status back to the server
func handleAIStatusCommand() {
	manager := GetAIManager()
	status := manager.GetStatus()

	// Send status back via WebSocket
	sendAIResponse("ai_status", map[string]interface{}{
		"status": status,
		"models": manager.GetModels(),
		"config": manager.GetConfig(),
	})
}

// handleAIEnableCommand enables AI with a specific model
func handleAIEnableCommand(params map[string]interface{}) {
	modelID, ok := params["model_id"].(string)
	if !ok || modelID == "" {
		sendAIResponse("ai_enable", map[string]interface{}{
			"success": false,
			"error":   "model_id is required",
		})
		return
	}

	manager := GetAIManager()
	if err := manager.Enable(modelID); err != nil {
		sendAIResponse("ai_enable", map[string]interface{}{
			"success": false,
			"error":   err.Error(),
		})
		return
	}

	sendAIResponse("ai_enable", map[string]interface{}{
		"success":  true,
		"model_id": modelID,
		"status":   manager.GetStatus(),
	})
}

// handleAIDisableCommand disables AI
func handleAIDisableCommand() {
	manager := GetAIManager()
	if err := manager.Disable(); err != nil {
		sendAIResponse("ai_disable", map[string]interface{}{
			"success": false,
			"error":   err.Error(),
		})
		return
	}

	sendAIResponse("ai_disable", map[string]interface{}{
		"success": true,
		"status":  manager.GetStatus(),
	})
}

// handleAIDownloadModelCommand starts model download
func handleAIDownloadModelCommand(params map[string]interface{}) {
	modelID, ok := params["model_id"].(string)
	if !ok || modelID == "" {
		sendAIResponse("ai_download_model", map[string]interface{}{
			"success": false,
			"error":   "model_id is required",
		})
		return
	}

	manager := GetAIManager()

	// Start download in background
	go func() {
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Minute)
		defer cancel()

		if err := manager.DownloadModel(ctx, modelID); err != nil {
			log.Printf("Model download failed: %v", err)
			sendAIResponse("ai_download_complete", map[string]interface{}{
				"success":  false,
				"model_id": modelID,
				"error":    err.Error(),
			})
			return
		}

		sendAIResponse("ai_download_complete", map[string]interface{}{
			"success":  true,
			"model_id": modelID,
			"models":   manager.GetModels(),
		})
	}()

	sendAIResponse("ai_download_model", map[string]interface{}{
		"success":  true,
		"message":  "Download started",
		"model_id": modelID,
	})
}

// handleAIDownloadRunnerCommand starts runner download
func handleAIDownloadRunnerCommand() {
	manager := GetAIManager()

	// Start download in background
	go func() {
		ctx, cancel := context.WithTimeout(context.Background(), 15*time.Minute)
		defer cancel()

		if err := manager.DownloadRunner(ctx); err != nil {
			log.Printf("Runner download failed: %v", err)
			sendAIResponse("ai_runner_download_complete", map[string]interface{}{
				"success": false,
				"error":   err.Error(),
			})
			return
		}

		sendAIResponse("ai_runner_download_complete", map[string]interface{}{
			"success": true,
			"status":  manager.GetStatus(),
		})
	}()

	sendAIResponse("ai_download_runner", map[string]interface{}{
		"success": true,
		"message": "Runner download started",
	})
}

// handleAIGenerateCommand handles text generation requests
func handleAIGenerateCommand(params map[string]interface{}) {
	prompt, ok := params["prompt"].(string)
	if !ok || prompt == "" {
		sendAIResponse("ai_generate", map[string]interface{}{
			"success": false,
			"error":   "prompt is required",
		})
		return
	}

	requestID, _ := params["request_id"].(string)

	manager := GetAIManager()

	// Generate in background for long-running requests
	go func() {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Minute)
		defer cancel()

		result, err := manager.GenerateSimple(ctx, prompt)
		if err != nil {
			sendAIResponse("ai_generate_complete", map[string]interface{}{
				"success":    false,
				"request_id": requestID,
				"error":      err.Error(),
			})
			return
		}

		sendAIResponse("ai_generate_complete", map[string]interface{}{
			"success":    true,
			"request_id": requestID,
			"content":    result,
			"model_id":   manager.GetStatus().ModelID,
		})
	}()

	sendAIResponse("ai_generate", map[string]interface{}{
		"success":    true,
		"request_id": requestID,
		"message":    "Generation started",
	})
}

// sendAIResponse sends an AI response back via WebSocket
func sendAIResponse(responseType string, data map[string]interface{}) {
	wsConnMutex.Lock()
	conn := wsConn
	connected := wsConnected
	wsConnMutex.Unlock()

	if !connected || conn == nil {
		log.Printf("Cannot send AI response: WebSocket not connected")
		return
	}

	response := map[string]interface{}{
		"type":      responseType,
		"agent_id":  GetAgentID(),
		"timestamp": time.Now().UTC().Format(time.RFC3339),
		"data":      data,
	}

	jsonData, err := json.Marshal(response)
	if err != nil {
		log.Printf("Failed to marshal AI response: %v", err)
		return
	}

	wsConnMutex.Lock()
	err = conn.WriteMessage(1, jsonData) // TextMessage = 1
	wsConnMutex.Unlock()

	if err != nil {
		log.Printf("Failed to send AI response: %v", err)
	}
}

// GetAgentID returns the current agent ID (from metrics.go)
func GetAgentID() string {
	return agentID
}
