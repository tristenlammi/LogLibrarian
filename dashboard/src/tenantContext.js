/**
 * Simple API Configuration
 * 
 * This module re-exports from api.js for backward compatibility.
 * New code should import directly from './api.js'
 */

import api, { isOffline, lastError, clearError } from './api'

// Re-export the configured axios instance as 'axios' for backward compatibility
export { api as axios, isOffline, lastError, clearError }

// Default export for direct import
export default {
  axios: api,
  isOffline,
  lastError,
  clearError
}
