<template>
  <div class="monitor-form-view compact">
    <!-- Toast Notification -->
    <transition name="toast">
      <div v-if="toast.show" :class="['toast', toast.type]">
        <span class="toast-icon">{{ toast.type === 'success' ? '✓' : '✕' }}</span>
        <span class="toast-message">{{ toast.message }}</span>
      </div>
    </transition>

    <!-- Header -->
    <div class="form-header-compact">
      <button class="back-btn-sm" @click="handleCancel" title="Go back">←</button>
      <h1>{{ isEdit ? 'Edit Bookmark' : 'Add New Bookmark' }}</h1>
    </div>

    <!-- Form -->
    <form @submit.prevent="handleSubmit" class="monitor-form-compact">
      <!-- Two Column Layout -->
      <div class="form-grid-2col">
        <!-- Left Column -->
        <div class="form-column">
          <!-- General Section -->
          <div class="form-section-compact">
            <h3 class="section-title-sm">
              General
              <div class="active-toggle">
                <input type="checkbox" id="active-checkbox" v-model="formData.active" />
                <label for="active-checkbox" class="toggle-label">{{ formData.active ? 'Active' : 'Paused' }}</label>
              </div>
            </h3>
            
            <div class="form-group-sm">
              <label>Monitor Type</label>
              <div class="type-selector-compact">
                <button 
                  type="button"
                  v-for="t in monitorTypes" 
                  :key="t.value"
                  class="type-btn-sm"
                  :class="{ active: formData.type === t.value }"
                  @click="formData.type = t.value"
                  :title="t.tooltip"
                >
                  <span class="type-icon-sm">{{ t.icon }}</span>
                  <span>{{ t.label }}</span>
                </button>
              </div>
              <span class="form-hint-sm">{{ currentTypeHint }}</span>
            </div>

            <div class="form-group-sm">
              <label>Friendly Name <span class="required">*</span></label>
              <input v-model="formData.name" type="text" required placeholder="My Plex Server" class="form-input-sm" />
            </div>

            <div class="form-group-sm">
              <label>{{ targetLabel }} <span class="required">*</span></label>
              <input v-model="formData.target" type="text" required :placeholder="targetPlaceholder" class="form-input-sm" />
              <span class="form-hint-sm">{{ targetHint }}</span>
            </div>

            <div class="form-group-sm" v-if="formData.type === 'tcp-port'">
              <label>Port <span class="required">*</span></label>
              <input v-model.number="formData.port" type="number" min="1" max="65535" placeholder="32400" class="form-input-sm" :required="formData.type === 'tcp-port'" />
              <span class="form-hint-sm">Common ports: 80 (HTTP), 443 (HTTPS), 22 (SSH), 32400 (Plex)</span>
            </div>
          </div>

          <!-- Monitoring Settings -->
          <div class="form-section-compact">
            <h3 class="section-title-sm">Monitoring Settings</h3>

            <div class="form-row-sm">
              <div class="form-group-sm">
                <label>
                  Check Interval <span class="required">*</span>
                  <span class="tooltip-icon" title="How often to check if the service is up. Lower = more checks but more resources used.">?</span>
                </label>
                <div class="input-unit-sm">
                  <input v-model.number="formData.interval_seconds" type="number" min="20" max="3600" class="form-input-sm" @blur="enforceMinInterval" />
                  <span>seconds</span>
                </div>
              </div>
              <div class="form-group-sm" v-if="formData.type === 'http'">
                <label>
                  Timeout
                  <span class="tooltip-icon" title="Max time to wait for a response before marking as DOWN.">?</span>
                </label>
                <div class="input-unit-sm">
                  <input v-model.number="formData.timeout_seconds" type="number" min="1" max="120" class="form-input-sm" />
                  <span>seconds</span>
                </div>
              </div>
            </div>

            <div class="form-group-sm" v-if="formData.type === 'http'">
              <label>HTTP Method</label>
              <select v-model="formData.method" class="form-input-sm">
                <option value="GET">GET (recommended)</option>
                <option value="HEAD">HEAD (faster, no body)</option>
                <option value="POST">POST</option>
              </select>
            </div>
          </div>
        </div>

        <!-- Right Column -->
        <div class="form-column">
          <!-- Organization -->
          <div class="form-section-compact">
            <h3 class="section-title-sm">Organization</h3>

            <div class="form-group-sm">
              <label>Group</label>
              <CreatableSelect
                v-model="selectedGroup"
                :options="groupOptions"
                placeholder="Select or create..."
                @create="handleGroupCreate"
                class="select-compact"
              />
              <span class="form-hint-sm">Organize bookmarks: Infrastructure, Services, External...</span>
            </div>

            <div class="form-group-sm">
              <label>Tags</label>
              <TagInput v-model="formData.tags" placeholder="Type tag and press Enter..." />
              <span class="form-hint-sm">Press Enter to add each tag</span>
            </div>

            <div class="form-group-sm">
              <label>Description</label>
              <input v-model="formData.description" type="text" placeholder="Optional note..." class="form-input-sm" />
            </div>
          </div>

          <!-- Advanced Section (Collapsible) -->
          <div class="form-section-compact advanced-section" :class="{ expanded: showAdvanced }">
            <h3 class="section-title-sm clickable" @click="showAdvanced = !showAdvanced">
              <span class="expand-icon">{{ showAdvanced ? '▼' : '▶' }}</span>
              Advanced
              <span class="badge-sm">Reliability</span>
              <span class="defaults-note" v-if="!showAdvanced">Using defaults</span>
            </h3>

            <div class="advanced-content" v-show="showAdvanced">
              <div class="form-row-sm">
                <div class="form-group-sm">
                  <label>
                    Max Retries
                    <span class="tooltip-icon" title="Number of retry attempts before marking as DOWN. Prevents false alarms from brief network glitches.">?</span>
                  </label>
                  <div class="input-unit-sm">
                    <input v-model.number="formData.max_retries" type="number" min="0" max="10" class="form-input-sm" />
                    <span>times</span>
                  </div>
                </div>
                <div class="form-group-sm">
                  <label>
                    Retry Delay
                    <span class="tooltip-icon" title="Wait time between retry attempts.">?</span>
                  </label>
                  <div class="input-unit-sm">
                    <input v-model.number="formData.retry_interval" type="number" min="5" max="300" class="form-input-sm" />
                    <span>seconds</span>
                  </div>
                </div>
              </div>

              <div class="form-group-sm">
                <label>
                  Notification Repeat
                  <span class="tooltip-icon" title="Re-send DOWN alert every N check cycles while still down. 0 = notify once only.">?</span>
                </label>
                <div class="input-unit-sm">
                  <input v-model.number="formData.resend_notification" type="number" min="0" max="100" class="form-input-sm" />
                  <span>cycles (0 = once)</span>
                </div>
              </div>

              <div class="form-group-sm upside-down-group">
                <label class="checkbox-label-sm">
                  <input type="checkbox" v-model="formData.upside_down" />
                  <span>Upside Down Mode</span>
                  <span class="badge-danger-sm">Inverted</span>
                  <span class="tooltip-icon" title="Inverts the logic: marks as DOWN when service returns success. Useful for detecting maintenance pages or 'service unavailable' responses that still return HTTP 200.">?</span>
                </label>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Actions -->
      <div class="form-actions-compact">
        <button type="button" class="btn-sm btn-secondary-sm" @click="handleCancel">Cancel</button>
        <button type="button" class="btn-sm btn-primary-sm" :disabled="saving" @click="() => { console.log('Button clicked!'); handleSubmit(); }">
          {{ saving ? 'Saving...' : (isEdit ? 'Save Changes' : 'Create Bookmark') }}
        </button>
      </div>
    </form>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import CreatableSelect from './CreatableSelect.vue'
import TagInput from './TagInput.vue'

const props = defineProps({
  monitorId: {
    type: [String, Number],
    default: null
  },
  groups: {
    type: Array,
    default: () => []
  },
  cloneData: {
    type: Object,
    default: null
  }
})

const emit = defineEmits(['save', 'cancel'])

const route = useRoute()
const router = useRouter()

const API_BASE = import.meta.env.VITE_API_URL || ''

const saving = ref(false)
const loading = ref(false)
const showAdvanced = ref(false)

// Toast notification
const toast = ref({
  show: false,
  type: 'success',
  message: ''
})

const showToast = (type, message) => {
  toast.value = { show: true, type, message }
  setTimeout(() => {
    toast.value.show = false
  }, 3000)
}

// Group selection state
const selectedGroup = ref(null)
const pendingNewGroupName = ref(null)

// Transform groups for CreatableSelect
const groupOptions = computed(() => {
  return props.groups.map(g => ({
    value: g.id,
    label: g.name
  }))
})

const monitorTypes = [
  { 
    value: 'http', 
    label: 'HTTP(s)', 
    icon: '🌐',
    tooltip: 'Best for web services like Plex, Jellyfin, Home Assistant, Nextcloud, or any service with a web UI',
    hint: 'Monitor web apps and services with HTTP/HTTPS endpoints'
  },
  { 
    value: 'icmp', 
    label: 'Ping', 
    icon: '📡',
    tooltip: 'Best for network infrastructure: routers, switches, NAS devices, Proxmox hosts, or checking if a machine is online',
    hint: 'Check if devices are reachable on your network (ICMP ping)'
  },
  { 
    value: 'tcp-port', 
    label: 'TCP Port', 
    icon: '🔌',
    tooltip: 'Best for services without HTTP: databases, game servers, SSH, MQTT brokers, or custom applications',
    hint: 'Verify a specific port is open and accepting connections'
  }
]

// Dynamic hint based on selected type
const currentTypeHint = computed(() => {
  const type = monitorTypes.find(t => t.value === formData.value.type)
  return type?.hint || ''
})

const formData = ref({
  name: '',
  type: 'http',
  target: '',
  port: null,
  group_id: null,
  interval_seconds: 60,
  timeout_seconds: 30,
  max_retries: 1,
  retry_interval: 30,
  resend_notification: 0,
  upside_down: false,
  method: 'GET',
  active: true,
  tags: '',
  description: ''
})

// Enforce minimum interval of 20 seconds
const enforceMinInterval = () => {
  if (formData.value.interval_seconds < 20) {
    formData.value.interval_seconds = 20
  }
}

const isEdit = computed(() => !!props.monitorId)

const targetLabel = computed(() => {
  switch (formData.value.type) {
    case 'http': return 'URL'
    case 'icmp': return 'Hostname / IP'
    case 'tcp-port': return 'Hostname / IP'
    default: return 'Target'
  }
})

const targetPlaceholder = computed(() => {
  switch (formData.value.type) {
    case 'http': return 'https://example.com'
    case 'icmp': return '192.168.1.1 or hostname'
    case 'tcp-port': return '192.168.1.1'
    default: return ''
  }
})

const targetHint = computed(() => {
  switch (formData.value.type) {
    case 'http': return 'Full URL including protocol (http:// or https://)'
    case 'icmp': return 'Server IP address or hostname to ping'
    case 'tcp-port': return 'Server IP address or hostname'
    default: return ''
  }
})

const fetchMonitorDetails = async (id) => {
  if (!id) return
  loading.value = true
  try {
    const response = await fetch(`${API_BASE}/api/bookmarks/${id}`)
    const data = await response.json()
    if (data.success && data.data) {
      const monitor = data.data
      formData.value = {
        name: monitor.name || '',
        type: monitor.type || 'http',
        target: monitor.target || '',
        port: monitor.port || null,
        group_id: monitor.group_id || null,
        interval_seconds: monitor.interval_seconds || 60,
        timeout_seconds: monitor.timeout_seconds || 30,
        max_retries: monitor.max_retries ?? 1,
        retry_interval: monitor.retry_interval ?? 30,
        resend_notification: monitor.resend_notification ?? 0,
        upside_down: monitor.upside_down === 1 || monitor.upside_down === true,
        method: monitor.method || 'GET',
        active: monitor.active === 1 || monitor.active === true,
        tags: monitor.tags || '',
        description: monitor.description || ''
      }
      // Set selected group for CreatableSelect
      selectedGroup.value = monitor.group_id || null
    }
  } catch (error) {
    console.error('Error fetching monitor:', error)
  } finally {
    loading.value = false
  }
}

// Handle new group creation in dropdown
const handleGroupCreate = (groupName) => {
  pendingNewGroupName.value = groupName
}

// Create a new group via API
const createGroup = async (name) => {
  try {
    const response = await fetch(`${API_BASE}/api/bookmarks/groups`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ name })
    })
    const data = await response.json()
    if (data.success) {
      return data.id
    }
    return null
  } catch (error) {
    console.error('Error creating group:', error)
    return null
  }
}

const handleSubmit = async () => {
  console.log('=== handleSubmit START ===')
  console.log('formData:', JSON.stringify(formData.value))
  console.log('selectedGroup:', selectedGroup.value)
  console.log('isEdit:', isEdit.value)
  
  saving.value = true
  try {
    // Resolve the group_id
    let finalGroupId = null
    
    if (selectedGroup.value) {
      if (typeof selectedGroup.value === 'object' && selectedGroup.value.__isNew) {
        // Create new group first
        console.log('Creating new group:', selectedGroup.value.label)
        showToast('success', 'Creating new group...')
        finalGroupId = await createGroup(selectedGroup.value.label)
        if (!finalGroupId) {
          showToast('error', 'Failed to create group')
          saving.value = false
          return
        }
      } else {
        // Existing group ID
        console.log('Using existing group:', selectedGroup.value)
        finalGroupId = selectedGroup.value
      }
    }
    
    // Prepare submission data with resolved group_id
    const submitData = {
      ...formData.value,
      group_id: finalGroupId
    }
    
    console.log('Final submitData:', JSON.stringify(submitData))
    
    const url = isEdit.value 
      ? `${API_BASE}/api/bookmarks/${props.monitorId}`
      : `${API_BASE}/api/bookmarks`
    const method = isEdit.value ? 'PUT' : 'POST'
    
    console.log('Fetching URL:', url, 'Method:', method)
    
    const response = await fetch(url, {
      method,
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(submitData)
    })
    
    const data = await response.json()
    console.log('Response:', data)
    if (data.success) {
      const newId = data.id || props.monitorId
      showToast('success', isEdit.value ? 'Bookmark updated!' : 'Bookmark created!')
      emit('save', { id: newId, isNew: !isEdit.value })
      // Short delay to show success message before navigating
      setTimeout(() => {
        router.push(`/bookmarks/${newId}`)
      }, 500)
    } else {
      showToast('error', data.detail || 'Failed to save bookmark')
      console.error('API error:', data)
    }
  } catch (error) {
    showToast('error', 'Connection error. Please try again.')
    console.error('Error saving monitor:', error)
  } finally {
    saving.value = false
  }
}

const handleCancel = () => {
  emit('cancel')
  if (props.monitorId) {
    router.push(`/bookmarks/${props.monitorId}`)
  } else {
    router.push('/bookmarks')
  }
}

// Initialize form with clone data if provided
watch(() => props.cloneData, (data) => {
  if (data) {
    formData.value = {
      name: `${data.name} (Copy)`,
      type: data.type || 'http',
      target: data.target || '',
      port: data.port || null,
      group_id: data.group_id || null,
      interval_seconds: data.interval_seconds || 60,
      timeout_seconds: data.timeout_seconds || 30,
      max_retries: data.max_retries ?? 1,
      retry_interval: data.retry_interval ?? 30,
      resend_notification: data.resend_notification ?? 0,
      upside_down: data.upside_down === 1 || data.upside_down === true,
      method: data.method || 'GET',
      active: true,
      tags: data.tags || '',
      description: data.description || ''
    }
    // Set selected group for CreatableSelect
    selectedGroup.value = data.group_id || null
  }
}, { immediate: true })

// Watch for monitorId changes - reset form when switching to "new" mode
watch(() => props.monitorId, (newId, oldId) => {
  if (newId) {
    // Switching to edit mode - fetch the monitor details
    fetchMonitorDetails(newId)
  } else if (oldId && !newId && !props.cloneData) {
    // Switching from edit to new mode (and not cloning) - reset form to defaults
    formData.value = {
      name: '',
      type: 'http',
      target: '',
      port: null,
      group_id: null,
      interval_seconds: 60,
      timeout_seconds: 30,
      max_retries: 1,
      retry_interval: 30,
      resend_notification: 0,
      upside_down: false,
      method: 'GET',
      active: true,
      tags: '',
      description: ''
    }
    selectedGroup.value = null
  }
})

onMounted(() => {
  if (props.monitorId) {
    fetchMonitorDetails(props.monitorId)
  }
})
</script>

<style scoped>
/* Compact Monitor Form */
.monitor-form-view.compact {
  max-width: 900px;
  margin: 0 auto;
}

.form-header-compact {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 1rem;
  padding-bottom: 0.75rem;
  border-bottom: 1px solid var(--border-color);
}

.back-btn-sm {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 1.1rem;
  transition: all 0.2s;
}

.back-btn-sm:hover {
  background: var(--border-color);
  color: var(--text-primary);
}

.form-header-compact h1 {
  margin: 0;
  font-size: 1.25rem;
  font-weight: 600;
}

/* Two Column Grid */
.form-grid-2col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
  align-items: start;
}

@media (max-width: 768px) {
  .form-grid-2col {
    grid-template-columns: 1fr;
  }
}

.form-column {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

/* Compact Sections */
.form-section-compact {
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: var(--radius);
  padding: 1rem;
}

.section-title-sm {
  margin: 0 0 0.75rem 0;
  font-size: 0.875rem;
  font-weight: 600;
  color: var(--text-primary);
  padding-bottom: 0.5rem;
  border-bottom: 1px solid var(--border-color);
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

/* Active Toggle in Header */
.active-toggle {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin-left: auto;
  font-size: 0.7rem;
  font-weight: 500;
  cursor: pointer;
}

.active-toggle input[type="checkbox"] {
  width: 14px;
  height: 14px;
  cursor: pointer;
  accent-color: var(--success);
}

.active-toggle .toggle-label {
  color: var(--text-secondary);
}

.active-toggle input:checked + .toggle-label {
  color: var(--success);
}

/* Badges */
.badge-sm {
  font-size: 0.6rem;
  font-weight: 500;
  padding: 0.15rem 0.4rem;
  background: rgba(56, 139, 219, 0.15);
  color: var(--primary);
  border-radius: 3px;
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

.badge-danger-sm {
  font-size: 0.6rem;
  font-weight: 600;
  padding: 0.15rem 0.35rem;
  background: rgba(218, 54, 51, 0.15);
  color: var(--danger);
  border-radius: 3px;
  text-transform: uppercase;
}

/* Tooltip Icon */
.tooltip-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  font-size: 0.6rem;
  font-weight: 600;
  background: var(--border-color);
  color: var(--text-secondary);
  border-radius: 50%;
  cursor: help;
  margin-left: 0.25rem;
  vertical-align: middle;
}

.tooltip-icon:hover {
  background: var(--primary);
  color: #000;
}

/* Type Selector Compact */
.type-selector-compact {
  display: flex;
  gap: 0.5rem;
}

.type-btn-sm {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.5rem 0.75rem;
  background: var(--bg-color);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
  font-size: 0.8rem;
  color: var(--text-primary);
  position: relative;
}

.type-btn-sm:hover {
  border-color: var(--primary);
  background: rgba(56, 139, 219, 0.1);
}

.type-btn-sm.active {
  border-color: var(--primary);
  background: rgba(56, 139, 219, 0.15);
}

.type-icon-sm {
  font-size: 1rem;
}

/* Compact Form Groups */
.form-group-sm {
  margin-bottom: 0.75rem;
}

.form-group-sm:last-child {
  margin-bottom: 0;
}

.form-group-sm label {
  display: block;
  margin-bottom: 0.35rem;
  font-size: 0.75rem;
  font-weight: 500;
  color: var(--text-secondary);
}

.required {
  color: var(--danger);
}

.form-input-sm {
  width: 100%;
  padding: 0.5rem 0.75rem;
  background: var(--bg-color);
  border: 1px solid var(--border-color);
  border-radius: 5px;
  color: var(--text-primary);
  font-size: 0.875rem;
  transition: border-color 0.2s;
}

.form-input-sm:focus {
  outline: none;
  border-color: var(--primary);
}

.form-input-sm::placeholder {
  color: var(--text-secondary);
  opacity: 0.6;
}

textarea.form-input-sm {
  resize: vertical;
  min-height: 50px;
}

.form-hint-sm {
  display: block;
  margin-top: 0.25rem;
  font-size: 0.65rem;
  color: var(--text-secondary);
  opacity: 0.8;
}

/* Form Row */
.form-row-sm {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.75rem;
}

/* Input with unit */
.input-unit-sm {
  display: flex;
  align-items: center;
  gap: 0.35rem;
}

.input-unit-sm .form-input-sm {
  flex: 1;
  min-width: 0;
}

.input-unit-sm span {
  font-size: 0.7rem;
  color: var(--text-secondary);
  white-space: nowrap;
}

/* Checkbox Compact */
.checkbox-label-sm {
  display: flex !important;
  align-items: center;
  gap: 0.5rem;
  cursor: pointer;
  font-size: 0.875rem;
  color: var(--text-primary);
}

.checkbox-label-sm input[type="checkbox"] {
  width: 16px;
  height: 16px;
  cursor: pointer;
}

/* Advanced Section (Collapsible) */
.advanced-section {
  border-color: var(--border-color);
}

.advanced-section .section-title-sm {
  cursor: pointer;
  user-select: none;
  margin-bottom: 0;
  border-bottom: none;
  padding-bottom: 0;
}

.advanced-section.expanded .section-title-sm {
  margin-bottom: 0.75rem;
  border-bottom: 1px solid var(--border-color);
  padding-bottom: 0.5rem;
}

.advanced-section .section-title-sm.clickable:hover {
  color: var(--primary);
}

.expand-icon {
  font-size: 0.65rem;
  color: var(--text-secondary);
  transition: transform 0.2s;
}

.defaults-note {
  margin-left: auto;
  font-size: 0.65rem;
  font-weight: 400;
  color: var(--text-secondary);
  opacity: 0.7;
}

.advanced-content {
  padding-top: 0.5rem;
}

.upside-down-group .checkbox-label-sm {
  flex-wrap: wrap;
  gap: 0.4rem;
}

/* Form Actions Compact */
.form-actions-compact {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
  margin-top: 1rem;
  padding-top: 1rem;
  border-top: 1px solid var(--border-color);
}

.btn-sm {
  padding: 0.5rem 1rem;
  border-radius: 5px;
  font-size: 0.8rem;
  font-weight: 500;
  cursor: pointer;
  border: 1px solid transparent;
  transition: all 0.2s;
}

.btn-primary-sm {
  background: var(--primary);
  color: #000;
}

.btn-primary-sm:hover {
  background: #4A96E6;
}

.btn-primary-sm:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-secondary-sm {
  background: var(--card-bg);
  border-color: var(--border-color);
  color: var(--text-primary);
}

.btn-secondary-sm:hover {
  background: var(--border-color);
}

/* CreatableSelect compact override */
.select-compact :deep(.creatable-select) {
  font-size: 0.875rem;
}

.select-compact :deep(.select-input) {
  padding: 0.5rem 0.75rem;
}

/* Toast Notification */
.toast {
  position: fixed;
  top: 20px;
  right: 20px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 20px;
  border-radius: 8px;
  font-size: 0.9rem;
  font-weight: 500;
  z-index: 1000;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
}

.toast.success {
  background: #28a745;
  color: white;
}

.toast.error {
  background: #dc3545;
  color: white;
}

.toast-icon {
  font-size: 1.1rem;
  font-weight: bold;
}

.toast-enter-active,
.toast-leave-active {
  transition: all 0.3s ease;
}

.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateX(50px);
}
</style>
