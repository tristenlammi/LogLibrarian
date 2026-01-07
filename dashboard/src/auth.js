import { ref, computed } from 'vue'

// Auth state
const user = ref(null)
const token = ref(localStorage.getItem('auth_token') || null)
const isAuthenticated = computed(() => !!token.value && !!user.value)
const isAdmin = computed(() => user.value?.role === 'admin')
const setupRequired = ref(false)

// API base URL - all auth endpoints now under /api/auth
const API_BASE = import.meta.env.VITE_API_URL || ''

/**
 * Check authentication status with the server
 */
export async function checkAuthStatus() {
  try {
    const headers = {}
    if (token.value) {
      headers['Authorization'] = `Bearer ${token.value}`
    }
    
    const response = await fetch(`${API_BASE}/api/auth/status`, { headers })
    const data = await response.json()
    
    setupRequired.value = data.setup_required
    
    if (data.authenticated && data.user) {
      user.value = data.user
      return { authenticated: true, setupRequired: false }
    }
    
    // Clear invalid token
    if (token.value && !data.authenticated) {
      logout()
    }
    
    return { authenticated: false, setupRequired: data.setup_required }
  } catch (error) {
    console.error('Auth status check failed:', error)
    return { authenticated: false, setupRequired: false }
  }
}

/**
 * Login with username and password
 */
export async function login(username, password) {
  try {
    const response = await fetch(`${API_BASE}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password })
    })
    
    const data = await response.json()
    
    if (!response.ok) {
      throw new Error(data.detail || 'Login failed')
    }
    
    // Check if setup is required (default credentials used)
    if (data.setup_required) {
      setupRequired.value = true
      return { success: true, setupRequired: true }
    }
    
    // Normal login success
    token.value = data.token
    user.value = data.user
    localStorage.setItem('auth_token', data.token)
    setupRequired.value = false
    
    return { success: true, setupRequired: false }
  } catch (error) {
    throw error
  }
}

/**
 * Setup first account (creates admin user)
 */
export async function setupAccount(username, password) {
  try {
    const response = await fetch(`${API_BASE}/api/auth/setup`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password })
    })
    
    const data = await response.json()
    
    if (!response.ok) {
      throw new Error(data.detail || 'Setup failed')
    }
    
    // Login successful after setup
    token.value = data.token
    user.value = data.user
    localStorage.setItem('auth_token', data.token)
    setupRequired.value = false
    
    return { success: true }
  } catch (error) {
    throw error
  }
}

/**
 * Logout and clear session
 */
export async function logout() {
  try {
    const headers = {}
    if (token.value) {
      headers['Authorization'] = `Bearer ${token.value}`
    }
    
    await fetch(`${API_BASE}/api/auth/logout`, {
      method: 'POST',
      headers
    })
  } catch (error) {
    console.error('Logout error:', error)
  }
  
  // Clear local state regardless of server response
  token.value = null
  user.value = null
  localStorage.removeItem('auth_token')
}

/**
 * Get all users (admin only)
 */
export async function getUsers() {
  const response = await fetch(`${API_BASE}/api/auth/users`, {
    headers: { 'Authorization': `Bearer ${token.value}` }
  })
  
  if (!response.ok) {
    const data = await response.json()
    throw new Error(data.detail || 'Failed to fetch users')
  }
  
  return await response.json()
}

/**
 * Add a new user (admin only)
 */
export async function addUser(username, password, role = 'user', assignedProfileId = null) {
  const body = { username, password, role }
  if (assignedProfileId) {
    body.assigned_profile_id = assignedProfileId
  }
  
  const response = await fetch(`${API_BASE}/api/auth/users`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token.value}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(body)
  })
  
  const data = await response.json()
  
  if (!response.ok) {
    throw new Error(data.detail || 'Failed to add user')
  }
  
  return data
}

/**
 * Delete a user (admin only)
 */
export async function deleteUser(userId) {
  const response = await fetch(`${API_BASE}/api/auth/users/${userId}`, {
    method: 'DELETE',
    headers: { 'Authorization': `Bearer ${token.value}` }
  })
  
  if (!response.ok) {
    const data = await response.json()
    throw new Error(data.detail || 'Failed to delete user')
  }
  
  return await response.json()
}

/**
 * Change current user's password
 */
export async function changePassword(currentPassword, newPassword) {
  const response = await fetch(`${API_BASE}/api/auth/change-password`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token.value}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword })
  })
  
  const data = await response.json()
  
  if (!response.ok) {
    throw new Error(data.detail || 'Failed to change password')
  }
  
  return data
}

/**
 * Update a user's role and profile (admin only)
 */
export async function updateUser(userId, updates) {
  const response = await fetch(`${API_BASE}/api/auth/users/${userId}`, {
    method: 'PUT',
    headers: {
      'Authorization': `Bearer ${token.value}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(updates)
  })
  
  const data = await response.json()
  
  if (!response.ok) {
    throw new Error(data.detail || 'Failed to update user')
  }
  
  return data
}

/**
 * Validate password meets requirements
 */
export function validatePassword(password) {
  const errors = []
  
  if (password.length < 8) {
    errors.push('Must be at least 8 characters')
  }
  if (!/\d/.test(password)) {
    errors.push('Must contain at least one number')
  }
  if (!/[!@#$%^&*(),.?":{}|<>`~\-_=+\[\]\\;'\/]/.test(password)) {
    errors.push('Must contain at least one special character')
  }
  
  return {
    valid: errors.length === 0,
    errors
  }
}

/**
 * Get auth header for API requests
 */
export function getAuthHeader() {
  if (token.value) {
    return { 'Authorization': `Bearer ${token.value}` }
  }
  return {}
}

// Export reactive state
export { user, token, isAuthenticated, isAdmin, setupRequired }
