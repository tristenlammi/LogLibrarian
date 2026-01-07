package main

import (
	"log"
)

// Logging helpers

func logInfo(format string, args ...interface{}) {
	log.Printf("[INFO] "+format, args...)
}

func logError(format string, args ...interface{}) {
	log.Printf("[ERROR] "+format, args...)
}

func logWarn(format string, args ...interface{}) {
	log.Printf("[WARN] "+format, args...)
}

func logDebug(format string, args ...interface{}) {
	// Could be conditional based on debug flag
	log.Printf("[DEBUG] "+format, args...)
}
