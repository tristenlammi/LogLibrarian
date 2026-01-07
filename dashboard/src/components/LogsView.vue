<template>
  <div class="logs-page">
    <!-- Filters Sidebar -->
    <div class="filters-panel">
      <div class="filter-section">
        <h6 class="filter-title">Device Filter</h6>
        <div class="device-filter">
          <div class="filter-actions mb-2">
            <button 
              class="btn btn-sm btn-outline-primary me-1" 
              @click="selectAllDevices"
              :disabled="filteredAgents.length === 0 || selectedDevices.length === filteredAgents.length"
            >
              All
            </button>
            <button 
              class="btn btn-sm btn-outline-secondary" 
              @click="clearDeviceFilter"
              :disabled="selectedDevices.length === 0"
            >
              None
            </button>
          </div>
          <!-- Device Search -->
          <div class="device-search mb-2">
            <input 
              v-model="deviceSearchQuery"
              type="text" 
              class="form-control form-control-sm bg-dark text-white border-secondary"
              placeholder="Find device..."
            />
          </div>
          <!-- Scrollable Device List -->
          <div class="device-list">
            <label 
              v-for="agent in filteredAgents" 
              :key="agent.agent_id"
              class="device-checkbox"
              :class="{ active: selectedDevices.includes(agent.agent_id) }"
            >
              <input 
                type="checkbox" 
                :value="agent.agent_id"
                v-model="selectedDevices"
                @change="onFilterChange"
              />
              <span class="device-name">{{ agent.display_name || agent.hostname }}</span>
            </label>
            <div v-if="filteredAgents.length === 0" class="text-secondary small p-2">
              No devices match "{{ deviceSearchQuery }}"
            </div>
          </div>
          <div v-if="agents.length > 0" class="device-count mt-1">
            <small class="text-secondary">{{ filteredAgents.length }} of {{ agents.length }} devices</small>
          </div>
        </div>
      </div>

      <div class="filter-section">
        <h6 class="filter-title">Severity</h6>
        <div class="severity-filter">
          <label 
            v-for="sev in severityOptions" 
            :key="sev.value"
            class="severity-checkbox"
            :class="[`severity-${sev.value.toLowerCase()}`, { active: selectedSeverities.includes(sev.value) }]"
          >
            <input 
              type="checkbox" 
              :value="sev.value"
              v-model="selectedSeverities"
              @change="onFilterChange"
            />
            <span class="severity-indicator" :class="`indicator-${sev.value.toLowerCase()}`"></span>
            <span class="severity-label">{{ sev.label }}</span>
          </label>
        </div>
      </div>

      <div class="filter-section">
        <h6 class="filter-title">Search</h6>
        <div class="search-box">
          <input 
            v-model="searchQuery"
            @input="onSearchInput"
            type="text" 
            class="form-control form-control-sm bg-dark text-white border-secondary"
            placeholder="Search messages..."
          />
          <button 
            v-if="searchQuery"
            class="clear-btn"
            @click="clearSearch"
          >
            ✕
          </button>
        </div>
      </div>

      <div class="filter-section">
        <h6 class="filter-title">Time Range</h6>
        <select 
          v-model="timeRange" 
          @change="onFilterChange"
          class="form-select form-select-sm bg-dark text-white border-secondary"
        >
          <option value="">All Time</option>
          <option value="1h">Last Hour</option>
          <option value="6h">Last 6 Hours</option>
          <option value="24h">Last 24 Hours</option>
          <option value="7d">Last 7 Days</option>
        </select>
      </div>

      <div class="filter-stats mt-3 pt-3 border-top border-secondary">
        <small class="text-secondary">
          Showing {{ logs.length }} of {{ totalCount }} logs
        </small>
      </div>
    </div>

    <!-- Main Log Table -->
    <div class="logs-main">
      <div class="logs-header">
        <h5 class="mb-0">
          {{ selectedDevices.length === agents.length || selectedDevices.length === 0 ? 'Global Feed' : 'Filtered View' }}
          <span v-if="liveTailActive" class="live-indicator">
            <span class="live-dot"></span>
            Live
          </span>
        </h5>
        <div class="header-actions">
          <!-- Live Tail Toggle -->
          <button 
            class="btn btn-sm me-2"
            :class="liveTailActive ? 'btn-success' : 'btn-outline-success'"
            @click="toggleLiveTail"
            :title="liveTailActive ? 'Stop live tail' : 'Start live tail'"
          >
            <span v-if="liveTailActive" class="live-pulse"></span>
            {{ liveTailActive ? '● Live' : '○ Live' }}
          </button>
          
          <!-- Density Toggle -->
          <div class="density-toggle me-3">
            <span class="density-label">Density:</span>
            <div class="btn-group btn-group-sm">
              <button 
                class="btn"
                :class="compactView ? 'btn-outline-secondary' : 'btn-secondary'"
                @click="compactView = false"
              >
                Comfortable
              </button>
              <button 
                class="btn"
                :class="compactView ? 'btn-secondary' : 'btn-outline-secondary'"
                @click="compactView = true"
              >
                Compact
              </button>
            </div>
          </div>
          
          <button 
            class="btn btn-sm btn-outline-primary me-2"
            @click="refreshLogs"
            :disabled="loading || liveTailActive"
          >
            🔄 Refresh
          </button>
          <button 
            class="btn btn-sm btn-outline-secondary"
            @click="clearAllFilters"
          >
            Clear Filters
          </button>
        </div>
      </div>

      <!-- Loading State -->
      <div v-if="loading && logs.length === 0" class="loading-state">
        <div class="spinner-border text-primary" role="status">
          <span class="visually-hidden">Loading...</span>
        </div>
        <div class="mt-2 text-secondary">Loading logs...</div>
      </div>

      <!-- Empty State -->
      <div v-else-if="logs.length === 0" class="empty-state">
        <div class="text-secondary" style="font-size: 3rem">📜</div>
        <div class="text-secondary mt-2">No logs found</div>
        <small class="text-secondary">Try adjusting your filters or waiting for logs to arrive</small>
      </div>

      <!-- Log Table -->
      <div v-else class="logs-table-container" ref="logContainer">
        <table class="logs-table" :class="{ 'compact-table': compactView }">
          <thead>
            <tr>
              <th class="col-timestamp">Timestamp</th>
              <th class="col-device">Device</th>
              <th class="col-severity">Severity</th>
              <th class="col-source">Source</th>
              <th class="col-message">Message</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="log in logs" :key="log.id">
              <tr 
                class="log-row"
                :class="[`severity-row-${(log.severity || 'info').toLowerCase()}`, { expanded: expandedLogs.has(log.id), 'compact-row': compactView }]"
                @click="toggleExpand(log.id)"
              >
                <td class="col-timestamp">
                  <span class="timestamp">{{ formatTimestamp(log.timestamp) }}</span>
                </td>
                <td class="col-device">
                  <span 
                    class="device-link"
                    @click.stop="filterByDevice(log.agent_id)"
                    :title="'Filter by ' + getDeviceName(log.agent_id)"
                  >
                    {{ getDeviceName(log.agent_id) }}
                  </span>
                </td>
                <td class="col-severity">
                  <span 
                    class="severity-badge"
                    :class="`badge-${(log.severity || 'info').toLowerCase()}`"
                  >
                    {{ log.severity || 'INFO' }}
                  </span>
                </td>
                <td class="col-source">
                  <span class="source-text">{{ log.source || '-' }}</span>
                </td>
                <td class="col-message">
                  <span class="message-preview">{{ truncateMessage(log.message) }}</span>
                  <span v-if="log.message && log.message.length > 100" class="expand-hint">...</span>
                </td>
              </tr>
              <!-- Expanded Row -->
              <tr v-if="expandedLogs.has(log.id)" class="expanded-row">
                <td colspan="5">
                  <div class="expanded-content">
                    <div class="expanded-header">
                      <span class="text-secondary">Full Message</span>
                      <button class="btn btn-sm btn-outline-secondary" @click.stop="copyMessage(log.message)">
                        📋 Copy
                      </button>
                    </div>
                    <pre class="expanded-message">{{ log.message }}</pre>
                    <div v-if="log.metadata" class="expanded-metadata mt-2">
                      <span class="text-secondary">Metadata:</span>
                      <pre class="metadata-json">{{ JSON.stringify(log.metadata, null, 2) }}</pre>
                    </div>
                  </div>
                </td>
              </tr>
            </template>
          </tbody>
        </table>

        <!-- Load More -->
        <div ref="loadMoreTrigger" class="load-more-trigger">
          <div v-if="loadingMore" class="text-center py-3">
            <div class="spinner-border spinner-border-sm text-primary" role="status"></div>
            <small class="text-secondary ms-2">Loading more...</small>
          </div>
          <div v-else-if="!hasMore && logs.length > 0" class="text-center py-3">
            <small class="text-secondary">─── End of logs ───</small>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, onActivated, nextTick } from 'vue'
import axios from 'axios'

// State
const logs = ref([])
const agents = ref([])
const loading = ref(false)
const loadingMore = ref(false)
const totalCount = ref(0)
const hasMore = ref(true)
const offset = ref(0)
const limit = 100

// Filters
const selectedDevices = ref([])
const selectedSeverities = ref([])
const searchQuery = ref('')
const timeRange = ref('')
const deviceSearchQuery = ref('')

// UI State
const expandedLogs = ref(new Set())
const liveTailActive = ref(false)
const compactView = ref(false)
let liveTailInterval = null

// Refs
const logContainer = ref(null)
const loadMoreTrigger = ref(null)

// Computed: Filtered agents for device search
const filteredAgents = computed(() => {
  if (!deviceSearchQuery.value) return agents.value
  const query = deviceSearchQuery.value.toLowerCase()
  return agents.value.filter(agent => {
    const name = (agent.display_name || agent.hostname || '').toLowerCase()
    return name.includes(query)
  })
})

// Options
const severityOptions = [
  { value: 'CRITICAL', label: 'Critical' },
  { value: 'ERROR', label: 'Error' },
  { value: 'WARN', label: 'Warning' },
  { value: 'INFO', label: 'Info' },
  { value: 'DEBUG', label: 'Debug' }
]

// Observer and timeout refs
let observer = null
let searchTimeout = null

// Fetch agents for filter dropdown
const fetchAgents = async () => {
  try {
    const response = await axios.get('/api/agents')
    agents.value = response.data.agents || []
  } catch (error) {
    console.error('Error fetching agents:', error)
  }
}

// Build time filter params
const getTimeParams = () => {
  if (!timeRange.value) return {}
  
  const now = new Date()
  let startTime
  
  switch (timeRange.value) {
    case '1h':
      startTime = new Date(now - 60 * 60 * 1000)
      break
    case '6h':
      startTime = new Date(now - 6 * 60 * 60 * 1000)
      break
    case '24h':
      startTime = new Date(now - 24 * 60 * 60 * 1000)
      break
    case '7d':
      startTime = new Date(now - 7 * 24 * 60 * 60 * 1000)
      break
    default:
      return {}
  }
  
  return { start_time: startTime.toISOString() }
}

// Fetch logs
const fetchLogs = async (append = false) => {
  if (append) {
    loadingMore.value = true
  } else {
    loading.value = true
    logs.value = []
    offset.value = 0
    expandedLogs.value = new Set()
  }

  try {
    const params = {
      limit,
      offset: offset.value
    }

    // Device filter - support multiple devices
    if (selectedDevices.value.length > 0 && selectedDevices.value.length < agents.value.length) {
      // Pass all selected devices as comma-separated list
      params.agent_ids = selectedDevices.value.join(',')
    }

    // Severity filter
    if (selectedSeverities.value.length > 0) {
      params.severity = selectedSeverities.value.join(',')
    }

    // Search filter
    if (searchQuery.value) {
      params.search = searchQuery.value
    }

    // Time filter
    const timeParams = getTimeParams()
    Object.assign(params, timeParams)

    const response = await axios.get('/api/raw-logs', { params })
    
    if (append) {
      logs.value.push(...response.data.logs)
    } else {
      logs.value = response.data.logs
    }

    totalCount.value = response.data.total_count
    hasMore.value = response.data.has_more
    offset.value += limit

  } catch (error) {
    console.error('Error fetching logs:', error)
  } finally {
    loading.value = false
    loadingMore.value = false
  }
}

// Filter handlers
const onFilterChange = () => {
  fetchLogs(false)
}

const onSearchInput = () => {
  clearTimeout(searchTimeout)
  searchTimeout = setTimeout(() => {
    fetchLogs(false)
  }, 500)
}

const clearSearch = () => {
  searchQuery.value = ''
  fetchLogs(false)
}

const selectAllDevices = () => {
  // Select all currently visible (filtered) devices
  const filteredIds = filteredAgents.value.map(a => a.agent_id)
  // Merge with existing selections (in case some are outside filter)
  const newSelection = [...new Set([...selectedDevices.value, ...filteredIds])]
  selectedDevices.value = newSelection
  fetchLogs(false)
}

const clearDeviceFilter = () => {
  selectedDevices.value = []
  fetchLogs(false)
}

const clearAllFilters = () => {
  selectedDevices.value = []
  selectedSeverities.value = []
  searchQuery.value = ''
  timeRange.value = ''
  fetchLogs(false)
}

const refreshLogs = () => {
  fetchLogs(false)
}

// Click device name to filter
const filterByDevice = (agentId) => {
  selectedDevices.value = [agentId]
  fetchLogs(false)
}

// Get device display name
const getDeviceName = (agentId) => {
  const agent = agents.value.find(a => a.agent_id === agentId)
  return agent ? (agent.display_name || agent.hostname) : agentId
}

// Expand/collapse row
const toggleExpand = (logId) => {
  if (expandedLogs.value.has(logId)) {
    expandedLogs.value.delete(logId)
  } else {
    expandedLogs.value.add(logId)
  }
  // Force reactivity
  expandedLogs.value = new Set(expandedLogs.value)
}

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

// Copy message to clipboard
const copyMessage = async (message) => {
  try {
    await copyToClipboard(message)
    // Optional: show feedback
  } catch (err) {
    console.error('Failed to copy:', err)
    alert('Failed to copy to clipboard')
  }
}

// Truncate message for preview
const truncateMessage = (message) => {
  if (!message) return '-'
  return message.length > 100 ? message.substring(0, 100) : message
}

// Robust timestamp formatter that handles multiple date formats
const formatTimestamp = (timestamp) => {
  if (!timestamp) return '-'
  
  let date = null
  
  // 1. Check if it's already a valid Date object or ISO string
  date = new Date(timestamp)
  if (!isNaN(date.getTime())) {
    return formatDate(date)
  }
  
  // 2. Handle PowerShell /Date(milliseconds)/ format
  const psDateMatch = String(timestamp).match(/\/Date\((\d+)([+-]\d+)?\)\//)
  if (psDateMatch) {
    date = new Date(parseInt(psDateMatch[1], 10))
    if (!isNaN(date.getTime())) {
      return formatDate(date)
    }
  }
  
  // 3. Handle Unix timestamp (seconds or milliseconds)
  if (typeof timestamp === 'number' || /^\d+$/.test(timestamp)) {
    const ts = parseInt(timestamp, 10)
    // If it's in seconds (before year 3000 in seconds), convert to ms
    date = new Date(ts < 100000000000 ? ts * 1000 : ts)
    if (!isNaN(date.getTime())) {
      return formatDate(date)
    }
  }
  
  // 4. Try various common date string formats
  const formats = [
    // ISO 8601 variations
    timestamp,
    timestamp.replace(' ', 'T'),
    timestamp + 'Z',
    // Windows culture-specific formats (MM/DD/YYYY, DD/MM/YYYY)
    timestamp.replace(/(\d+)\/(\d+)\/(\d+)/, '$3-$1-$2'),
  ]
  
  for (const fmt of formats) {
    date = new Date(fmt)
    if (!isNaN(date.getTime())) {
      return formatDate(date)
    }
  }
  
  // 5. Handle Windows WMI datetime format: yyyyMMddHHmmss.ffffff+offset
  const wmiMatch = String(timestamp).match(/^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})/)
  if (wmiMatch) {
    const [, year, month, day, hour, min, sec] = wmiMatch
    date = new Date(`${year}-${month}-${day}T${hour}:${min}:${sec}`)
    if (!isNaN(date.getTime())) {
      return formatDate(date)
    }
  }
  
  // 6. If all parsing fails, return the raw string for debugging
  console.warn('Unable to parse timestamp:', timestamp)
  return String(timestamp).substring(0, 20) + '...'
}

// Helper to format a valid Date object
const formatDate = (date) => {
  return date.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
  })
}

// Load more handler
const loadMore = () => {
  if (!loadingMore.value && hasMore.value) {
    fetchLogs(true)
  }
}

// Setup intersection observer
const setupObserver = () => {
  if (!loadMoreTrigger.value) return

  observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting && !loadingMore.value && hasMore.value) {
          loadMore()
        }
      })
    },
    {
      root: logContainer.value,
      rootMargin: '100px',
      threshold: 0.1
    }
  )

  observer.observe(loadMoreTrigger.value)
}

// Live Tail functionality
const toggleLiveTail = () => {
  liveTailActive.value = !liveTailActive.value
  
  if (liveTailActive.value) {
    startLiveTail()
  } else {
    stopLiveTail()
  }
}

const startLiveTail = () => {
  // Initial fetch
  fetchNewLogs()
  
  // Poll every 3 seconds
  liveTailInterval = setInterval(() => {
    fetchNewLogs()
  }, 3000)
}

const stopLiveTail = () => {
  if (liveTailInterval) {
    clearInterval(liveTailInterval)
    liveTailInterval = null
  }
}

const fetchNewLogs = async () => {
  try {
    const params = {
      limit: 50,
      offset: 0
    }

    // Apply same filters as main fetch
    if (selectedDevices.value.length > 0 && selectedDevices.value.length < agents.value.length) {
      params.agent_id = selectedDevices.value[0]
    }
    if (selectedSeverities.value.length > 0) {
      params.severity = selectedSeverities.value.join(',')
    }
    if (searchQuery.value) {
      params.search = searchQuery.value
    }
    const timeParams = getTimeParams()
    Object.assign(params, timeParams)

    const response = await axios.get('/api/raw-logs', { params })
    const newLogs = response.data.logs || []
    
    if (newLogs.length > 0) {
      // Find logs that are newer than what we have
      const existingIds = new Set(logs.value.map(l => l.id))
      const trulyNewLogs = newLogs.filter(l => !existingIds.has(l.id))
      
      if (trulyNewLogs.length > 0) {
        // Prepend new logs to the list
        logs.value = [...trulyNewLogs, ...logs.value]
        totalCount.value += trulyNewLogs.length
        
        // Auto-scroll to top if enabled
        if (logContainer.value) {
          logContainer.value.scrollTop = 0
        }
      }
    }
  } catch (error) {
    console.error('Error fetching new logs:', error)
  }
}

// Lifecycle - fetch data on mount and when route becomes active
const fetchData = async () => {
  try {
    await fetchAgents()
    await fetchLogs(false)
    await nextTick()
    setupObserver()
  } catch (e) {
    console.error('Failed to fetch logs:', e)
  }
}

onMounted(async () => {
  await fetchData()
})

// Refetch when navigating back to this view (works with keep-alive)
onActivated(() => {
  fetchData()
})

onUnmounted(() => {
  if (observer) {
    observer.disconnect()
  }
  clearTimeout(searchTimeout)
  stopLiveTail()
})
</script>

<style scoped>
.logs-page {
  display: flex;
  gap: 1.5rem;
  height: calc(100vh - 200px);
  min-height: 600px;
}

/* Filters Panel */
.filters-panel {
  width: 250px;
  flex-shrink: 0;
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: var(--radius);
  padding: 1rem;
  overflow-y: auto;
}

.filter-section {
  margin-bottom: 1.5rem;
}

.filter-title {
  color: var(--text-secondary);
  font-size: 0.85rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 0.75rem;
}

.device-list {
  max-height: 256px;
  overflow-y: auto;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  padding: 0.25rem;
}

.device-checkbox,
.severity-checkbox {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.4rem 0.6rem;
  margin-bottom: 0.25rem;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.2s;
  font-size: 0.9rem;
}

.device-checkbox:hover,
.severity-checkbox:hover {
  background: rgba(255, 255, 255, 0.05);
}

.device-checkbox.active {
  background: rgba(88, 166, 255, 0.15);
}

.device-checkbox input,
.severity-checkbox input {
  accent-color: var(--primary);
  display: none;
}

/* Severity Filter Enhanced Styles */
.severity-filter {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.severity-checkbox {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
  border: 1px solid transparent;
}

.severity-indicator {
  width: 12px;
  height: 12px;
  border-radius: 3px;
  flex-shrink: 0;
  transition: all 0.2s;
}

/* Severity indicator colors (always visible) */
.indicator-critical { background: #ef4444; }
.indicator-error { background: #eab308; }
.indicator-warn,
.indicator-warning { background: #06b6d4; }
.indicator-info { background: #64748b; }
.indicator-debug { background: #22c55e; }

/* Default (unselected) state */
.severity-checkbox {
  background: rgba(255, 255, 255, 0.02);
  opacity: 0.6;
}

.severity-checkbox:hover {
  opacity: 0.8;
  background: rgba(255, 255, 255, 0.05);
}

/* Active (selected) state */
.severity-checkbox.active {
  opacity: 1;
  border-color: currentColor;
}

.severity-checkbox.severity-critical.active { 
  background: rgba(239, 68, 68, 0.1); 
  color: #ef4444; 
  border-color: rgba(239, 68, 68, 0.3);
}
.severity-checkbox.severity-error.active { 
  background: rgba(234, 179, 8, 0.1); 
  color: #eab308; 
  border-color: rgba(234, 179, 8, 0.3);
}
.severity-checkbox.severity-warn.active,
.severity-checkbox.severity-warning.active { 
  background: rgba(6, 182, 212, 0.1); 
  color: #06b6d4; 
  border-color: rgba(6, 182, 212, 0.3);
}
.severity-checkbox.severity-info.active { 
  background: rgba(148, 163, 184, 0.1); 
  color: #94a3b8; 
  border-color: rgba(148, 163, 184, 0.3);
}
.severity-checkbox.severity-debug.active { 
  background: rgba(34, 197, 94, 0.1); 
  color: #22c55e; 
  border-color: rgba(34, 197, 94, 0.3);
}

.severity-checkbox.active .severity-indicator {
  box-shadow: 0 0 8px currentColor;
}

.severity-label {
  font-weight: 500;
  font-size: 0.9rem;
}

.search-box {
  position: relative;
}

.search-box .clear-btn {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  background: none;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  padding: 0;
  font-size: 0.8rem;
}

/* Main Content */
.logs-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.logs-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
  padding-bottom: 0.75rem;
  border-bottom: 1px solid var(--border-color);
}

.loading-state,
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 4rem;
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: var(--radius);
}

/* Log Table */
.logs-table-container {
  flex: 1;
  overflow-y: auto;
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: var(--radius);
}

.logs-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.9rem;
}

.logs-table thead {
  position: sticky;
  top: 0;
  background: #1a1f2e;
  z-index: 10;
}

.logs-table th {
  padding: 0.75rem 1rem;
  text-align: left;
  font-weight: 600;
  color: var(--text-secondary);
  border-bottom: 1px solid var(--border-color);
  font-size: 0.85rem;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.logs-table td {
  padding: 0.6rem 1rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  vertical-align: top;
}

/* Column widths */
.col-timestamp { width: 140px; }
.col-device { width: 130px; }
.col-severity { width: 90px; }
.col-source { width: 100px; }
.col-message { width: auto; }

/* Row styling */
.log-row {
  cursor: pointer;
  transition: background 0.2s;
}

.log-row:hover {
  background: rgba(255, 255, 255, 0.03);
}

.log-row.expanded {
  background: rgba(88, 166, 255, 0.05);
}

/* Severity row colors */
.severity-row-critical { border-left: 3px solid #ef4444; }
.severity-row-error { border-left: 3px solid #eab308; }
.severity-row-warn,
.severity-row-warning { border-left: 3px solid #06b6d4; }
.severity-row-info { border-left: 3px solid #94a3b8; }
.severity-row-debug { border-left: 3px solid #22c55e; }

/* Cell styling */
.timestamp {
  font-family: monospace;
  color: var(--text-secondary);
  font-size: 0.85rem;
}

.device-link {
  color: var(--primary);
  cursor: pointer;
  text-decoration: none;
  font-weight: 500;
}

.device-link:hover {
  text-decoration: underline;
}

.severity-badge {
  display: inline-block;
  padding: 0.2rem 0.5rem;
  border-radius: 3px;
  font-weight: 600;
  font-size: 0.75rem;
  letter-spacing: 0.5px;
}

.badge-critical { background: rgba(239, 68, 68, 0.15); color: #ef4444; }
.badge-error { background: rgba(234, 179, 8, 0.15); color: #eab308; }
.badge-warn,
.badge-warning { background: rgba(6, 182, 212, 0.15); color: #06b6d4; }
.badge-info { background: rgba(148, 163, 184, 0.15); color: #94a3b8; }
.badge-debug { background: rgba(34, 197, 94, 0.15); color: #22c55e; }

.source-text {
  color: var(--text-secondary);
  font-size: 0.85rem;
}

.message-preview {
  color: var(--text-primary);
  font-family: monospace;
  font-size: 0.85rem;
}

.expand-hint {
  color: var(--primary);
  font-weight: bold;
}

/* Expanded row */
.expanded-row td {
  background: #0d1117;
  padding: 0;
}

.expanded-content {
  padding: 1rem;
  border-left: 3px solid var(--primary);
}

.expanded-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.5rem;
}

.expanded-message {
  background: rgba(0, 0, 0, 0.3);
  padding: 1rem;
  border-radius: 4px;
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: monospace;
  font-size: 0.85rem;
  color: var(--text-primary);
  max-height: 300px;
  overflow-y: auto;
}

.metadata-json {
  background: rgba(0, 0, 0, 0.3);
  padding: 0.75rem;
  border-radius: 4px;
  margin: 0.5rem 0 0 0;
  font-size: 0.8rem;
  color: var(--text-secondary);
}

.load-more-trigger {
  min-height: 50px;
}

/* Live Tail Styles */
.live-indicator {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  margin-left: 0.75rem;
  font-size: 0.75rem;
  font-weight: 600;
  color: #22c55e;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.live-dot {
  width: 8px;
  height: 8px;
  background: #22c55e;
  border-radius: 50%;
  animation: pulse 1.5s ease-in-out infinite;
}

.live-pulse {
  display: inline-block;
  width: 8px;
  height: 8px;
  background: #22c55e;
  border-radius: 50%;
  margin-right: 0.25rem;
  animation: pulse 1.5s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% {
    opacity: 1;
    transform: scale(1);
    box-shadow: 0 0 0 0 rgba(34, 197, 94, 0.4);
  }
  50% {
    opacity: 0.7;
    transform: scale(1.1);
    box-shadow: 0 0 0 6px rgba(34, 197, 94, 0);
  }
}

/* Density Toggle */
.density-toggle {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.density-label {
  font-size: 0.8rem;
  color: var(--text-secondary);
}

.header-actions {
  display: flex;
  align-items: center;
}

/* Compact View Styles */
.compact-table th {
  padding: 0.4rem 0.75rem;
  font-size: 0.75rem;
}

.compact-table td {
  padding: 0.25rem 0.75rem;
}

.compact-row .timestamp,
.compact-row .source-text,
.compact-row .device-link,
.compact-row .message-preview {
  font-size: 0.75rem;
  line-height: 1.3;
}

.compact-row .severity-badge {
  padding: 0.1rem 0.35rem;
  font-size: 0.65rem;
}

/* Scrollbar */
.logs-table-container::-webkit-scrollbar,
.device-list::-webkit-scrollbar {
  width: 8px;
}

.logs-table-container::-webkit-scrollbar-track,
.device-list::-webkit-scrollbar-track {
  background: rgba(255, 255, 255, 0.05);
}

.logs-table-container::-webkit-scrollbar-thumb,
.device-list::-webkit-scrollbar-thumb {
  background: var(--primary);
  border-radius: 4px;
}
</style>
