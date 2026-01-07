<template>
  <Teleport to="body">
    <div v-if="show" class="modal-overlay" @click.self="$emit('close')">
      <div class="modal-container install-modal">
        <!-- Header -->
        <div class="modal-header">
          <div class="d-flex align-items-center gap-3">
            <div class="modal-icon">➕</div>
            <div>
              <h4 class="mb-0">Install a New Scribe</h4>
              <small class="text-secondary">Deploy an agent to start monitoring</small>
            </div>
          </div>
          <button class="btn-close btn-close-white" @click="$emit('close')"></button>
        </div>

        <!-- Platform Selector -->
        <div class="modal-body">
          <div class="platform-selector mb-4">
            <button 
              class="platform-btn" 
              :class="{ active: selectedPlatform === 'linux' }"
              @click="selectedPlatform = 'linux'"
            >
              <div class="platform-icon">🐧</div>
              <div class="platform-name">Linux</div>
              <div class="platform-desc">Ubuntu, Debian, CentOS, RHEL</div>
            </button>
            <button 
              class="platform-btn" 
              :class="{ active: selectedPlatform === 'windows' }"
              @click="selectedPlatform = 'windows'"
            >
              <div class="platform-icon">🪟</div>
              <div class="platform-name">Windows</div>
              <div class="platform-desc">Windows 10/11, Server 2016+</div>
            </button>
          </div>

          <!-- Installation Command -->
          <div class="install-section">
            <div class="section-header">
              <h6 class="mb-0">
                {{ selectedPlatform === 'linux' ? '🖥️ Terminal Command' : '💻 PowerShell Command' }}
              </h6>
              <span class="badge bg-info">One-liner install</span>
            </div>

            <!-- Loading State -->
            <div v-if="loading" class="text-info small mb-2">
              <span class="spinner-border spinner-border-sm me-1"></span>
              Loading install command...
            </div>
            <div v-else-if="error" class="alert alert-danger mb-2 py-2">
              <small>{{ error }}</small>
              <button class="btn btn-link btn-sm p-0 ms-2" @click="fetchInstallScript">Retry</button>
            </div>

            <div class="code-block">
              <code>{{ installCommand }}</code>
              <button 
                class="copy-btn" 
                @click="copyCommand"
                :title="copied ? 'Copied!' : 'Copy to clipboard'"
                :disabled="loading"
              >
                <span v-if="!copied">📋</span>
                <span v-else>✅</span>
              </button>
            </div>

            <div class="helper-text">
              <template v-if="selectedPlatform === 'linux'">
                <span class="badge bg-warning text-dark me-2">⚠️</span>
                Run this command in your <strong>Terminal</strong> with sudo privileges
              </template>
              <template v-else>
                <span class="badge bg-warning text-dark me-2">⚠️</span>
                Run this in <strong>PowerShell as Administrator</strong>
              </template>
            </div>
          </div>

          <!-- What happens next -->
          <div class="info-section mt-4">
            <h6 class="mb-3">📋 What happens next?</h6>
            <div class="steps-list">
              <div class="step">
                <div class="step-number">1</div>
                <div class="step-content">
                  <strong>Download & Install</strong>
                  <p class="mb-0 text-secondary small">The script downloads and installs the Scribe agent</p>
                </div>
              </div>
              <div class="step">
                <div class="step-number">2</div>
                <div class="step-content">
                  <strong>Auto-Configure</strong>
                  <p class="mb-0 text-secondary small">
                    Agent is pre-configured with this server's address and API key
                  </p>
                </div>
              </div>
              <div class="step">
                <div class="step-number">3</div>
                <div class="step-content">
                  <strong>Start Monitoring</strong>
                  <p class="mb-0 text-secondary small">
                    The agent appears in your dashboard within seconds
                  </p>
                </div>
              </div>
            </div>
          </div>

          <!-- Quick Download Option -->
          <div class="download-section mt-4">
            <h6 class="mb-3">📦 Quick Download (Recommended for Windows)</h6>
            <p class="text-secondary small mb-3">
              Download a pre-configured agent package with your API key already embedded:
            </p>
            <div class="d-flex gap-2 flex-wrap">
              <a href="/api/download/scribe-windows-configured" class="btn btn-primary" download>
                <span class="me-2">⬇️</span>
                Download Windows Package (.zip)
              </a>
              <a href="/api/download/scribe-config" class="btn btn-outline-primary" download>
                <span class="me-2">⚙️</span>
                Config Only
              </a>
            </div>
            <div class="form-text mt-2">
              <i class="bi bi-info-circle me-1"></i>
              Extract the ZIP and run <code>scribe.exe</code> - no additional configuration needed!
            </div>
          </div>

          <!-- Manual Download Option -->
          <div class="manual-section mt-4">
            <details>
              <summary class="text-secondary">
                <small>📥 Manual installation (advanced)</small>
              </summary>
              <div class="mt-3">
                <p class="text-secondary small mb-2">
                  Download the agent binary directly and configure manually:
                </p>
                <div class="d-flex gap-2 flex-wrap">
                  <a :href="`${baseUrl}/api/download/scribe-linux-amd64`" class="btn btn-sm btn-outline-secondary">
                    Linux (amd64)
                  </a>
                  <a :href="`${baseUrl}/api/download/scribe-linux-arm64`" class="btn btn-sm btn-outline-secondary">
                    Linux (arm64)
                  </a>
                  <a :href="`${baseUrl}/api/download/scribe-windows-amd64.exe`" class="btn btn-sm btn-outline-secondary">
                    Windows (amd64)
                  </a>
                </div>
              </div>
            </details>
          </div>
        </div>

        <!-- Footer -->
        <div class="modal-footer">
          <button class="btn btn-secondary" @click="$emit('close')">
            Close
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import axios from 'axios'

const props = defineProps({
  show: Boolean
})

const emit = defineEmits(['close'])

const selectedPlatform = ref('linux')
const copied = ref(false)

// Install script state
const installData = ref(null)
const loading = ref(false)
const error = ref(null)

const baseUrl = computed(() => {
  return window.location.origin
})

// Fetch install script when modal opens
watch(() => props.show, async (newVal) => {
  if (newVal) {
    await fetchInstallScript()
  } else {
    // Reset when closing
    installData.value = null
    error.value = null
  }
}, { immediate: true })

async function fetchInstallScript() {
  loading.value = true
  error.value = null
  
  try {
    const response = await axios.get('/api/install-script')
    installData.value = response.data
  } catch (err) {
    console.error('Failed to fetch install script:', err)
    error.value = err.response?.data?.detail || 'Failed to load install command'
    installData.value = null
  } finally {
    loading.value = false
  }
}

const installCommand = computed(() => {
  if (!installData.value?.commands) {
    // Fallback while loading
    if (selectedPlatform.value === 'linux') {
      return `curl -sSL "${baseUrl.value}/api/scripts/install-linux" | sudo bash`
    } else {
      return `iwr -useb "${baseUrl.value}/api/scripts/install-windows" | iex`
    }
  }
  
  return selectedPlatform.value === 'linux' 
    ? installData.value.commands.linux 
    : installData.value.commands.windows
})

// Copy to clipboard with fallback for non-HTTPS
const copyToClipboard = (text) => {
  // Try modern clipboard API first
  if (navigator.clipboard && window.isSecureContext) {
    return navigator.clipboard.writeText(text)
  }
  
  // Fallback for non-HTTPS contexts
  const textArea = document.createElement('textarea')
  textArea.value = text
  textArea.style.position = 'fixed'
  textArea.style.left = '-999999px'
  textArea.style.top = '-999999px'
  document.body.appendChild(textArea)
  textArea.focus()
  textArea.select()
  
  return new Promise((resolve, reject) => {
    const success = document.execCommand('copy')
    document.body.removeChild(textArea)
    if (success) {
      resolve()
    } else {
      reject(new Error('execCommand copy failed'))
    }
  })
}

const copyCommand = async () => {
  try {
    await copyToClipboard(installCommand.value)
    copied.value = true
    setTimeout(() => {
      copied.value = false
    }, 2000)
  } catch (err) {
    console.error('Failed to copy:', err)
    alert('Failed to copy to clipboard')
  }
}
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.8);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1050;
  backdrop-filter: blur(4px);
}

.modal-container {
  background: var(--bg-card, #1e1e1e);
  border-radius: 12px;
  width: 100%;
  max-width: 600px;
  max-height: 90vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border-color, #333);
  box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1.25rem 1.5rem;
  border-bottom: 1px solid var(--border-color, #333);
  background: linear-gradient(135deg, rgba(88, 166, 255, 0.1), transparent);
}

.modal-icon {
  font-size: 2rem;
  width: 50px;
  height: 50px;
  background: var(--primary, #58a6ff);
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.modal-body {
  padding: 1.5rem;
  overflow-y: auto;
  flex: 1;
}

.modal-footer {
  padding: 1rem 1.5rem;
  border-top: 1px solid var(--border-color, #333);
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
}

/* Platform Selector */
.platform-selector {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
}

.platform-btn {
  background: var(--bg-secondary, #2d2d2d);
  border: 2px solid var(--border-color, #333);
  border-radius: 12px;
  padding: 1.5rem;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s ease;
  color: inherit;
}

.platform-btn:hover {
  border-color: var(--primary, #58a6ff);
  background: rgba(88, 166, 255, 0.1);
}

.platform-btn.active {
  border-color: var(--primary, #58a6ff);
  background: rgba(88, 166, 255, 0.15);
  box-shadow: 0 0 20px rgba(88, 166, 255, 0.2);
}

.platform-icon {
  font-size: 2.5rem;
  margin-bottom: 0.5rem;
}

.platform-name {
  font-weight: 600;
  font-size: 1.1rem;
  margin-bottom: 0.25rem;
}

.platform-desc {
  font-size: 0.75rem;
  color: var(--text-secondary, #888);
}

/* Install Section */
.install-section {
  background: var(--bg-secondary, #2d2d2d);
  border-radius: 12px;
  padding: 1rem;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
}

.code-block {
  background: #0d1117;
  border: 1px solid var(--border-color, #333);
  border-radius: 8px;
  padding: 1rem;
  font-family: 'SF Mono', 'Consolas', monospace;
  font-size: 0.85rem;
  position: relative;
  overflow-x: auto;
  word-break: break-all;
}

.code-block code {
  color: #7ee787;
}

.copy-btn {
  position: absolute;
  top: 0.5rem;
  right: 0.5rem;
  background: var(--bg-secondary, #2d2d2d);
  border: 1px solid var(--border-color, #333);
  border-radius: 6px;
  padding: 0.25rem 0.5rem;
  cursor: pointer;
  transition: all 0.2s ease;
}

.copy-btn:hover {
  background: var(--primary, #58a6ff);
}

.copy-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.key-status {
  padding: 0.5rem 0.75rem;
  background: rgba(0, 0, 0, 0.2);
  border-radius: 6px;
}

.helper-text {
  margin-top: 1rem;
  padding: 0.75rem;
  background: rgba(255, 193, 7, 0.1);
  border-radius: 8px;
  font-size: 0.875rem;
}

/* Info Section */
.info-section {
  background: var(--bg-secondary, #2d2d2d);
  border-radius: 12px;
  padding: 1rem;
}

.steps-list {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.step {
  display: flex;
  gap: 1rem;
  align-items: flex-start;
}

.step-number {
  width: 28px;
  height: 28px;
  background: var(--primary, #58a6ff);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
  font-size: 0.875rem;
  flex-shrink: 0;
}

.step-content {
  flex: 1;
}

/* Download Section */
.download-section {
  background: var(--bg-secondary, #252525);
  border-radius: 12px;
  padding: 1.25rem;
  border: 1px solid rgba(88, 166, 255, 0.3);
}

.download-section code {
  background: rgba(0,0,0,0.3);
  padding: 0.15rem 0.4rem;
  border-radius: 4px;
  color: #7ee787;
}

/* Manual Section */
.manual-section {
  border-top: 1px solid var(--border-color, #333);
  padding-top: 1rem;
}

.manual-section summary {
  cursor: pointer;
  user-select: none;
}

.manual-section summary:hover {
  color: var(--primary, #58a6ff);
}
</style>
