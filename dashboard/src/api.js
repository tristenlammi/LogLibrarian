/**
 * Global API Configuration with Error Handling
 * 
 * This module provides a configured axios instance with:
 * - Base URL configuration
 * - Auth token injection
 * - Global error handling (401, 500, network)
 * - Offline detection
 */

import axios from 'axios'
import { ref } from 'vue'

// Reactive state for UI indicators
export const isOffline = ref(false)
export const lastError = ref(null)

// Configure axios base URL from environment or window location
const API_BASE_URL = import.meta.env.VITE_API_URL || ''

// Create configured axios instance
const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json'
  }
})

// Request interceptor - inject auth token
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('auth_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// Response interceptor - handle errors globally
api.interceptors.response.use(
  (response) => {
    // Clear offline state on successful response
    isOffline.value = false
    return response
  },
  (error) => {
    // Network error (no response)
    if (!error.response) {
      isOffline.value = true
      lastError.value = {
        type: 'network',
        message: 'Unable to connect to server. Please check your connection.',
        timestamp: Date.now()
      }
      console.error('Network error:', error.message)
      return Promise.reject(error)
    }

    // Server responded with error
    isOffline.value = false
    const status = error.response.status

    switch (status) {
      case 401:
        // Unauthorized - clear token and redirect to login
        lastError.value = {
          type: 'auth',
          message: 'Session expired. Please log in again.',
          timestamp: Date.now()
        }
        localStorage.removeItem('auth_token')
        // Only redirect if not already on login/setup page
        if (!window.location.pathname.includes('/login') && 
            !window.location.pathname.includes('/setup')) {
          window.location.href = '/login'
        }
        break

      case 403:
        lastError.value = {
          type: 'forbidden',
          message: 'You do not have permission to perform this action.',
          timestamp: Date.now()
        }
        break

      case 500:
      case 502:
      case 503:
      case 504:
        lastError.value = {
          type: 'server',
          message: `Server error (${status}). Please try again later.`,
          timestamp: Date.now()
        }
        console.error('Server error:', status, error.response.data)
        break

      default:
        // Let specific error messages through
        lastError.value = {
          type: 'error',
          message: error.response.data?.detail || `Request failed (${status})`,
          timestamp: Date.now()
        }
    }

    return Promise.reject(error)
  }
)

// Helper to clear error state
export function clearError() {
  lastError.value = null
}

// Helper to check if we should show offline indicator
export function checkOnlineStatus() {
  return navigator.onLine
}

// Listen for browser online/offline events
if (typeof window !== 'undefined') {
  window.addEventListener('online', () => {
    isOffline.value = false
  })
  window.addEventListener('offline', () => {
    isOffline.value = true
  })
}

export default api
