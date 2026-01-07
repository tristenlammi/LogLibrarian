<template>
  <div class="login-page">
    <div class="login-card">
      <!-- Logo -->
      <div class="login-logo">
        <div class="logo-text">
          <span class="logo-line">Lab</span>
          <span class="logo-line">Librarian</span>
        </div>
      </div>

      <!-- Login Form -->
      <form @submit.prevent="handleLogin" class="login-form">
        <p class="login-subtitle" v-if="setupRequired">
          Enter the default credentials to get started
        </p>
        
        <div class="form-group">
          <label for="username">Username</label>
          <input
            type="text"
            id="username"
            v-model="username"
            placeholder="Enter username"
            required
            autocomplete="username"
            :disabled="loading"
          />
        </div>

        <div class="form-group">
          <label for="password">Password</label>
          <input
            type="password"
            id="password"
            v-model="password"
            placeholder="Enter password"
            required
            autocomplete="current-password"
            :disabled="loading"
          />
        </div>

        <div v-if="error" class="error-message">
          {{ error }}
        </div>

        <button type="submit" class="login-button" :disabled="loading">
          <span v-if="loading">Signing in...</span>
          <span v-else>Sign In</span>
        </button>

        <p v-if="setupRequired" class="default-creds">
          Default credentials: <code>admin</code> / <code>admin</code>
        </p>
      </form>
    </div>

    <!-- Setup Modal -->
    <div v-if="showSetupModal" class="modal-overlay" @click.self="closeSetupModal">
      <div class="modal-content setup-modal">
        <h2>Create Your Account</h2>
        <p class="setup-subtitle">
          Set up your admin account to secure your LogLibrarian instance.
        </p>

        <form @submit.prevent="handleSetup" class="setup-form">
          <div class="form-group">
            <label for="setup-username">Username</label>
            <input
              type="text"
              id="setup-username"
              v-model="setupUsername"
              placeholder="Choose a username (can be email)"
              required
              autocomplete="username"
              :disabled="setupLoading"
            />
          </div>

          <div class="form-group">
            <label for="setup-password">Password</label>
            <input
              type="password"
              id="setup-password"
              v-model="setupPassword"
              placeholder="Create a strong password"
              required
              autocomplete="new-password"
              :disabled="setupLoading"
              @input="validateSetupPassword"
            />
            <div class="password-requirements">
              <div :class="{ valid: requirements.length }">
                <span class="check">{{ requirements.length ? '✓' : '○' }}</span>
                At least 8 characters
              </div>
              <div :class="{ valid: requirements.number }">
                <span class="check">{{ requirements.number ? '✓' : '○' }}</span>
                Contains a number
              </div>
              <div :class="{ valid: requirements.special }">
                <span class="check">{{ requirements.special ? '✓' : '○' }}</span>
                Contains a special character
              </div>
            </div>
          </div>

          <div class="form-group">
            <label for="setup-confirm">Confirm Password</label>
            <input
              type="password"
              id="setup-confirm"
              v-model="setupConfirm"
              placeholder="Confirm your password"
              required
              autocomplete="new-password"
              :disabled="setupLoading"
            />
            <div v-if="setupConfirm && setupPassword !== setupConfirm" class="password-mismatch">
              Passwords do not match
            </div>
          </div>

          <div v-if="setupError" class="error-message">
            {{ setupError }}
          </div>

          <div class="modal-actions">
            <button type="submit" class="btn-primary" :disabled="!canSubmitSetup || setupLoading">
              <span v-if="setupLoading">Creating Account...</span>
              <span v-else>Create Account</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { login, setupAccount, checkAuthStatus, validatePassword } from '../auth.js'

const router = useRouter()

// Login form
const username = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')
const setupRequired = ref(false)

// Setup modal
const showSetupModal = ref(false)
const setupUsername = ref('')
const setupPassword = ref('')
const setupConfirm = ref('')
const setupLoading = ref(false)
const setupError = ref('')

// Password requirements tracking
const requirements = ref({
  length: false,
  number: false,
  special: false
})

const validateSetupPassword = () => {
  requirements.value = {
    length: setupPassword.value.length >= 8,
    number: /\d/.test(setupPassword.value),
    special: /[!@#$%^&*(),.?":{}|<>`~\-_=+\[\]\\;'\/]/.test(setupPassword.value)
  }
}

const canSubmitSetup = computed(() => {
  return setupUsername.value.trim() &&
         requirements.value.length &&
         requirements.value.number &&
         requirements.value.special &&
         setupPassword.value === setupConfirm.value
})

const handleLogin = async () => {
  error.value = ''
  loading.value = true

  try {
    const result = await login(username.value, password.value)
    
    if (result.setupRequired) {
      // Show setup modal
      showSetupModal.value = true
      setupUsername.value = '' // Don't pre-fill, let them choose
    } else {
      // Redirect to dashboard
      router.push('/')
    }
  } catch (err) {
    error.value = err.message || 'Login failed'
  } finally {
    loading.value = false
  }
}

const handleSetup = async () => {
  setupError.value = ''
  setupLoading.value = true

  try {
    await setupAccount(setupUsername.value, setupPassword.value)
    // Redirect to dashboard
    router.push('/')
  } catch (err) {
    setupError.value = err.message || 'Setup failed'
  } finally {
    setupLoading.value = false
  }
}

const closeSetupModal = () => {
  // Don't allow closing - must complete setup
}

onMounted(async () => {
  // Check if already authenticated
  const status = await checkAuthStatus()
  if (status.authenticated) {
    router.push('/')
  }
  setupRequired.value = status.setupRequired
})
</script>

<style scoped>
.login-page {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-primary);
  padding: 1rem;
  z-index: 1000;
}

.login-card {
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 2.5rem;
  width: 100%;
  max-width: 400px;
}

.login-logo {
  text-align: center;
  margin-bottom: 2rem;
}

.login-logo .logo-text {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0;
}

.login-logo .logo-line {
  font-size: 1.8rem;
  font-weight: 700;
  line-height: 1.1;
  color: #58A6FF;
}

.login-form h2 {
  margin: 0 0 0.5rem 0;
  font-size: 1.5rem;
  color: var(--text-primary);
}

.login-subtitle {
  color: var(--text-secondary);
  margin-bottom: 1.5rem;
  font-size: 0.9rem;
}

.form-group {
  margin-bottom: 1.25rem;
}

.form-group label {
  display: block;
  margin-bottom: 0.5rem;
  font-size: 0.9rem;
  color: var(--text-secondary);
}

.form-group input {
  width: 100%;
  padding: 0.75rem 1rem;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-secondary);
  color: var(--text-primary);
  font-size: 1rem;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.form-group input:focus {
  outline: none;
  border-color: var(--primary-color);
  box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
}

.form-group input:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.error-message {
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.3);
  color: #ef4444;
  padding: 0.75rem 1rem;
  border-radius: 8px;
  margin-bottom: 1rem;
  font-size: 0.9rem;
}

.login-button {
  width: 100%;
  padding: 0.875rem 1rem;
  background: var(--primary-color);
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 1rem;
  font-weight: 600;
  cursor: pointer;
  transition: background-color 0.2s, transform 0.1s;
}

.login-button:hover:not(:disabled) {
  background: var(--primary-hover);
}

.login-button:active:not(:disabled) {
  transform: scale(0.98);
}

.login-button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.default-creds {
  margin-top: 1.5rem;
  text-align: center;
  color: var(--text-secondary);
  font-size: 0.85rem;
}

.default-creds code {
  background: var(--bg-secondary);
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  font-family: monospace;
}

/* Modal Styles */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 1rem;
}

.modal-content {
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 2rem;
  width: 100%;
  max-width: 450px;
  max-height: 90vh;
  overflow-y: auto;
}

.setup-modal h2 {
  margin: 0 0 0.5rem 0;
  font-size: 1.5rem;
  color: var(--text-primary);
}

.setup-subtitle {
  color: var(--text-secondary);
  margin-bottom: 1.5rem;
  font-size: 0.9rem;
}

.password-requirements {
  margin-top: 0.75rem;
  font-size: 0.85rem;
  color: var(--text-secondary);
}

.password-requirements > div {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.25rem;
  transition: color 0.2s;
}

.password-requirements > div.valid {
  color: #10b981;
}

.password-requirements .check {
  font-size: 0.75rem;
}

.password-mismatch {
  margin-top: 0.5rem;
  font-size: 0.85rem;
  color: #ef4444;
}

.modal-actions {
  margin-top: 1.5rem;
}

.btn-primary {
  width: 100%;
  padding: 0.875rem 1rem;
  background: var(--primary-color);
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 1rem;
  font-weight: 600;
  cursor: pointer;
  transition: background-color 0.2s;
}

.btn-primary:hover:not(:disabled) {
  background: var(--primary-hover);
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
