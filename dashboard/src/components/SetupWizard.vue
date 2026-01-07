<template>
  <div class="setup-wizard">
    <div class="setup-container">
      <!-- Header -->
      <div class="setup-header">
        <div class="logo">
          <i class="bi bi-book-half"></i>
        </div>
        <h1>Welcome to LogLibrarian</h1>
        <p class="subtitle">Let's get your monitoring system set up</p>
      </div>

      <!-- Setup Form -->
      <div class="setup-form">
        <h2><i class="bi bi-person-badge"></i> Create Admin Account</h2>
        
        <div class="form-section">
          <div class="form-group">
            <label for="username">
              <i class="bi bi-person"></i>
              Username
            </label>
            <input 
              id="username"
              type="text" 
              v-model="adminUsername"
              placeholder="Choose a username"
              :class="{ error: usernameError }"
              @keyup.enter="focusPassword"
            >
            <span v-if="usernameError" class="error-text">{{ usernameError }}</span>
          </div>
          
          <div class="form-group">
            <label for="password">
              <i class="bi bi-lock"></i>
              Password
            </label>
            <div class="password-input">
              <input 
                ref="passwordInput"
                id="password"
                :type="showPassword ? 'text' : 'password'"
                v-model="adminPassword"
                placeholder="Choose a strong password"
                :class="{ error: passwordError }"
                @keyup.enter="focusConfirm"
              >
              <button type="button" class="password-toggle" @click="showPassword = !showPassword">
                <i :class="showPassword ? 'bi bi-eye-slash' : 'bi bi-eye'"></i>
              </button>
            </div>
            <span v-if="passwordError" class="error-text">{{ passwordError }}</span>
            <div class="password-strength" v-if="adminPassword">
              <div class="strength-bar" :class="passwordStrength.class" :style="{ width: passwordStrength.percent + '%' }"></div>
              <span>{{ passwordStrength.label }}</span>
            </div>
          </div>
          
          <div class="form-group">
            <label for="confirmPassword">
              <i class="bi bi-lock-fill"></i>
              Confirm Password
            </label>
            <input 
              ref="confirmInput"
              id="confirmPassword"
              :type="showPassword ? 'text' : 'password'"
              v-model="confirmPassword"
              placeholder="Confirm your password"
              :class="{ error: confirmError }"
            >
            <span v-if="confirmError" class="error-text">{{ confirmError }}</span>
          </div>
        </div>
        
        <!-- API Key Section -->
        <div class="form-section api-key-section">
          <h3><i class="bi bi-key"></i> Instance API Key</h3>
          <p class="section-description">
            This API key is required for all Scribe agents to connect. 
            You'll use this key when installing Scribes on your systems.
          </p>
          
          <div class="form-group">
            <label for="apiKey">
              <i class="bi bi-shield-lock"></i>
              API Key
            </label>
            <div class="api-key-input">
              <input 
                id="apiKey"
                type="text"
                v-model="instanceApiKey"
                placeholder="Click Generate to create an API key"
                :class="{ error: apiKeyError }"
                readonly
              >
              <button type="button" class="btn btn-secondary generate-btn" @click="generateApiKey">
                <i class="bi bi-arrow-repeat"></i>
                Generate
              </button>
              <button type="button" class="btn btn-secondary copy-btn" @click="copyApiKey" :disabled="!instanceApiKey">
                <i class="bi bi-clipboard"></i>
              </button>
            </div>
            <span v-if="apiKeyError" class="error-text">{{ apiKeyError }}</span>
            <span v-if="apiKeyCopied" class="success-text"><i class="bi bi-check"></i> Copied!</span>
          </div>
          
          <div class="api-key-notice">
            <i class="bi bi-info-circle"></i>
            <span>Save this key! You'll need it to configure Scribe agents. It can be viewed later in Settings.</span>
          </div>
        </div>
        
        <!-- Server Address Section -->
        <div class="form-section server-section">
          <h3><i class="bi bi-hdd-network"></i> Server Address</h3>
          <p class="section-description">
            Enter the IP address or hostname that Scribe agents will use to connect to this server.
            This is typically your server's LAN IP or public IP.
          </p>
          
          <div class="form-group">
            <label for="serverAddress">
              <i class="bi bi-globe"></i>
              Server Address
            </label>
            <input 
              id="serverAddress"
              type="text"
              v-model="serverAddress"
              placeholder="e.g., 192.168.1.100 or myserver.local"
              :class="{ error: serverAddressError }"
            >
            <span v-if="serverAddressError" class="error-text">{{ serverAddressError }}</span>
            <span class="hint-text">
              <i class="bi bi-info-circle"></i>
              Don't include the port - it will be added automatically (8000)
            </span>
          </div>
        </div>
      </div>

      <!-- Error Display -->
      <div v-if="error" class="error-banner">
        <i class="bi bi-exclamation-triangle"></i>
        {{ error }}
      </div>

      <!-- Complete Setup Button -->
      <div class="setup-nav">
        <div class="nav-spacer"></div>
        <button 
          class="btn btn-success"
          @click="completeSetup"
          :disabled="loading || !canProceed"
        >
          <span v-if="loading" class="spinner"></span>
          <i v-else class="bi bi-check-lg"></i>
          Complete Setup
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import axios from 'axios'
import { useRouter } from 'vue-router'

const router = useRouter()

const loading = ref(false)
const error = ref('')

// Admin account
const adminUsername = ref('')
const adminPassword = ref('')
const confirmPassword = ref('')
const showPassword = ref(false)

// Instance API Key
const instanceApiKey = ref('')
const apiKeyCopied = ref(false)

// Server Address
const serverAddress = ref('')

// Refs for focus management
const passwordInput = ref(null)
const confirmInput = ref(null)

const focusPassword = () => passwordInput.value?.focus()
const focusConfirm = () => confirmInput.value?.focus()

// Generate a secure API key
function generateApiKey() {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
  const prefix = 'll_'  // LogLibrarian prefix for easy identification
  let key = prefix
  
  // Generate 45 random characters (48 total with prefix)
  const array = new Uint8Array(45)
  crypto.getRandomValues(array)
  for (let i = 0; i < 45; i++) {
    key += chars[array[i] % chars.length]
  }
  
  instanceApiKey.value = key
  apiKeyCopied.value = false
}

// Copy API key to clipboard
async function copyApiKey() {
  if (!instanceApiKey.value) return
  try {
    await navigator.clipboard.writeText(instanceApiKey.value)
    apiKeyCopied.value = true
    setTimeout(() => apiKeyCopied.value = false, 2000)
  } catch (e) {
    console.error('Failed to copy:', e)
  }
}

// Validation
const apiKeyError = computed(() => {
  if (!instanceApiKey.value) return 'API key is required - click Generate'
  if (instanceApiKey.value.length < 32) return 'API key must be at least 32 characters'
  return ''
})

const serverAddressError = computed(() => {
  if (!serverAddress.value) return 'Server address is required'
  // Basic validation - no spaces, no protocol
  if (serverAddress.value.includes(' ')) return 'Server address cannot contain spaces'
  if (serverAddress.value.startsWith('http://') || serverAddress.value.startsWith('https://')) {
    return 'Enter just the IP or hostname (without http://)'
  }
  return ''
})

const usernameError = computed(() => {
  if (!adminUsername.value) return ''
  if (adminUsername.value.length < 3) return 'Username must be at least 3 characters'
  if (!/^[a-zA-Z0-9_@.\-]+$/.test(adminUsername.value)) return 'Invalid characters in username'
  return ''
})

const passwordError = computed(() => {
  if (!adminPassword.value) return ''
  if (adminPassword.value.length < 6) return 'Password must be at least 6 characters'
  return ''
})

const confirmError = computed(() => {
  if (!confirmPassword.value) return ''
  if (confirmPassword.value !== adminPassword.value) return 'Passwords do not match'
  return ''
})

const passwordStrength = computed(() => {
  const pwd = adminPassword.value
  if (!pwd) return { percent: 0, label: '', class: '' }
  
  let strength = 0
  if (pwd.length >= 6) strength += 20
  if (pwd.length >= 8) strength += 20
  if (pwd.length >= 12) strength += 10
  if (/[a-z]/.test(pwd)) strength += 15
  if (/[A-Z]/.test(pwd)) strength += 15
  if (/[0-9]/.test(pwd)) strength += 10
  if (/[^a-zA-Z0-9]/.test(pwd)) strength += 10
  
  if (strength < 40) return { percent: strength, label: 'Weak', class: 'weak' }
  if (strength < 70) return { percent: strength, label: 'Fair', class: 'fair' }
  if (strength < 90) return { percent: strength, label: 'Good', class: 'good' }
  return { percent: 100, label: 'Strong', class: 'strong' }
})

const canProceed = computed(() => {
  return adminUsername.value.length >= 3 && 
         adminPassword.value.length >= 6 && 
         adminPassword.value === confirmPassword.value &&
         instanceApiKey.value.length >= 32 &&
         serverAddress.value.length > 0 &&
         !usernameError.value && !passwordError.value && !apiKeyError.value && !serverAddressError.value
})

async function completeSetup() {
  if (!canProceed.value) return
  
  loading.value = true
  error.value = ''
  
  try {
    const response = await axios.post('/api/setup/complete', {
      admin_username: adminUsername.value,
      admin_password: adminPassword.value,
      instance_name: 'LogLibrarian',
      deployment_profile: 'custom',
      default_retention_days: 30,
      timezone: 'UTC',
      instance_api_key: instanceApiKey.value,
      server_address: serverAddress.value
    })
    
    if (response.data.success) {
      // Store token if provided
      if (response.data.token) {
        localStorage.setItem('auth_token', response.data.token)
      }
      
      // Redirect to dashboard
      router.push('/')
    } else {
      error.value = response.data.error || 'Setup failed'
    }
  } catch (e) {
    error.value = e.response?.data?.detail || 'Failed to complete setup'
  } finally {
    loading.value = false
  }
}

async function loadSetupStatus() {
  try {
    const response = await axios.get('/api/setup/status')
    
    if (response.data.setup_complete) {
      // Already set up, redirect to dashboard
      router.push('/')
      return
    }
  } catch (e) {
    console.error('Failed to load setup status:', e)
    error.value = 'Failed to load setup configuration'
  }
}

onMounted(() => {
  loadSetupStatus()
})
</script>

<style scoped>
.setup-wizard {
  min-height: 100vh;
  background: linear-gradient(135deg, #0f0f23 0%, #1a1a2e 50%, #16213e 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 2rem;
}

.setup-container {
  width: 100%;
  max-width: 500px;
  background: rgba(30, 30, 50, 0.8);
  border-radius: 16px;
  padding: 2.5rem;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
  border: 1px solid rgba(255, 255, 255, 0.1);
}

.setup-header {
  text-align: center;
  margin-bottom: 2rem;
}

.setup-header .logo {
  width: 80px;
  height: 80px;
  background: linear-gradient(135deg, #6366f1, #8b5cf6);
  border-radius: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 1.5rem;
  font-size: 2.5rem;
  color: white;
}

.setup-header h1 {
  color: white;
  font-size: 1.75rem;
  font-weight: 600;
  margin-bottom: 0.5rem;
}

.setup-header .subtitle {
  color: rgba(255, 255, 255, 0.6);
  font-size: 1rem;
}

/* Setup Form */
.setup-form h2 {
  color: white;
  font-size: 1.25rem;
  margin-bottom: 1.5rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding-bottom: 1rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

/* Form Styles */
.form-section {
  margin-bottom: 1.5rem;
}

.form-group {
  margin-bottom: 1.25rem;
}

.form-group label {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  color: rgba(255, 255, 255, 0.8);
  font-weight: 500;
  margin-bottom: 0.5rem;
  font-size: 0.9rem;
}

.form-group input {
  width: 100%;
  padding: 0.75rem 1rem;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 8px;
  color: white;
  font-size: 0.95rem;
  transition: all 0.3s ease;
}

.form-group input:focus {
  outline: none;
  border-color: #6366f1;
  background: rgba(255, 255, 255, 0.08);
}

.form-group input.error {
  border-color: #ef4444;
}

.form-group input::placeholder {
  color: rgba(255, 255, 255, 0.4);
}

.password-input {
  position: relative;
}

.password-input input {
  padding-right: 3rem;
}

.password-toggle {
  position: absolute;
  right: 1rem;
  top: 50%;
  transform: translateY(-50%);
  background: none;
  border: none;
  color: rgba(255, 255, 255, 0.5);
  cursor: pointer;
  padding: 0;
}

.password-toggle:hover {
  color: white;
}

.error-text {
  color: #ef4444;
  font-size: 0.8rem;
  margin-top: 0.5rem;
  display: block;
}

.password-strength {
  margin-top: 0.5rem;
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.strength-bar {
  height: 4px;
  border-radius: 2px;
  transition: all 0.3s ease;
  flex: 1;
  max-width: 150px;
}

.strength-bar.weak { background: #ef4444; }
.strength-bar.fair { background: #f59e0b; }
.strength-bar.good { background: #10b981; }
.strength-bar.strong { background: #6366f1; }

.password-strength span {
  font-size: 0.75rem;
  color: rgba(255, 255, 255, 0.6);
}

/* API Key Section */
.api-key-section {
  margin-top: 1.5rem;
  padding-top: 1.5rem;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
}

.api-key-section h3 {
  color: white;
  font-size: 1.1rem;
  font-weight: 600;
  margin-bottom: 0.5rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.section-description {
  color: rgba(255, 255, 255, 0.6);
  font-size: 0.85rem;
  margin-bottom: 1.25rem;
  line-height: 1.5;
}

.api-key-input {
  display: flex;
  gap: 0.5rem;
}

.api-key-input input {
  flex: 1;
  font-family: monospace;
  font-size: 0.8rem;
}

.generate-btn, .copy-btn {
  padding: 0.75rem 0.875rem;
  white-space: nowrap;
  font-size: 0.85rem;
}

.copy-btn {
  padding: 0.75rem 0.625rem;
}

.api-key-notice {
  margin-top: 1rem;
  padding: 0.75rem 1rem;
  background: rgba(99, 102, 241, 0.1);
  border: 1px solid rgba(99, 102, 241, 0.3);
  border-radius: 8px;
  color: rgba(255, 255, 255, 0.8);
  font-size: 0.8rem;
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
}

.api-key-notice i {
  color: #6366f1;
  margin-top: 0.1rem;
}

.success-text {
  color: #10b981;
  font-size: 0.85rem;
  margin-top: 0.5rem;
  display: flex;
  align-items: center;
  gap: 0.25rem;
}

/* Server Section */
.server-section {
  margin-top: 1.5rem;
  padding-top: 1.5rem;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
}

.server-section h3 {
  color: white;
  font-size: 1.1rem;
  font-weight: 600;
  margin-bottom: 0.5rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.hint-text {
  color: rgba(255, 255, 255, 0.5);
  font-size: 0.8rem;
  margin-top: 0.5rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.hint-text i {
  color: rgba(255, 255, 255, 0.4);
}

/* Error Banner */
.error-banner {
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: 8px;
  padding: 1rem;
  color: #ef4444;
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 1.5rem;
}

/* Navigation */
.setup-nav {
  display: flex;
  align-items: center;
  margin-top: 2rem;
  padding-top: 1.5rem;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
}

.nav-spacer {
  flex: 1;
}

.btn {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem 1.25rem;
  border-radius: 8px;
  font-weight: 500;
  font-size: 0.95rem;
  cursor: pointer;
  transition: all 0.3s ease;
  border: none;
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-secondary {
  background: rgba(255, 255, 255, 0.1);
  color: white;
}

.btn-secondary:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.15);
}

.btn-success {
  background: linear-gradient(135deg, #10b981, #059669);
  color: white;
}

.btn-success:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 15px rgba(16, 185, 129, 0.4);
}

.spinner {
  width: 18px;
  height: 18px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* Responsive */
@media (max-width: 600px) {
  .setup-container {
    padding: 1.5rem;
  }
  
  .api-key-input {
    flex-wrap: wrap;
  }
  
  .api-key-input input {
    width: 100%;
  }
}
</style>
