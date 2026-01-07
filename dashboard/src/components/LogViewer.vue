<template>
  <div class="log-viewer">
    <!-- Filters -->
    <div class="log-filters mb-3">
      <div class="row g-3">
        <div class="col-md-3">
          <label class="form-label small text-secondary">Log Level</label>
          <select 
            v-model="filters.level" 
            @change="onFilterChange"
            class="form-select form-select-sm bg-dark text-white border-secondary"
          >
            <option value="">All Levels</option>
            <option value="error">ERROR</option>
            <option value="warning">WARNING</option>
            <option value="info">INFO</option>
            <option value="debug">DEBUG</option>
          </select>
        </div>
        <div class="col-md-9">
          <label class="form-label small text-secondary">Search</label>
          <div class="input-group input-group-sm">
            <input 
              v-model="filters.search"
              @input="onSearchInput"
              type="text" 
              class="form-control bg-dark text-white border-secondary"
              placeholder="Search log messages..."
            />
            <button 
              v-if="filters.search"
              class="btn btn-outline-secondary"
              @click="clearSearch"
              type="button"
            >
              ✕
            </button>
          </div>
        </div>
      </div>
      
      <!-- Stats -->
      <div class="mt-2 d-flex justify-content-between align-items-center">
        <small class="text-secondary">
          <span v-if="loading && logs.length === 0">Loading logs...</span>
          <span v-else>
            Showing {{ logs.length }} of {{ totalCount }} logs
            <span v-if="filters.level || filters.search" class="text-warning">(filtered)</span>
          </span>
        </small>
        <button 
          v-if="logs.length > 0"
          class="btn btn-sm btn-outline-primary"
          @click="scrollToTop"
        >
          ⬆️ Scroll to Top
        </button>
      </div>
    </div>

    <!-- Log List -->
    <div class="log-list-container" ref="logContainer">
      <div v-if="loading && logs.length === 0" class="text-center py-5">
        <div class="spinner-border text-primary" role="status">
          <span class="visually-hidden">Loading...</span>
        </div>
        <div class="mt-2 text-secondary">Loading logs...</div>
      </div>

      <div v-else-if="logs.length === 0" class="text-center py-5">
        <div class="text-secondary" style="font-size: 3rem">📜</div>
        <div class="text-secondary mt-2">No logs found</div>
        <small class="text-secondary">Try adjusting your filters</small>
      </div>

      <div v-else class="log-list">
        <div 
          v-for="log in logs" 
          :key="log.id"
          class="log-entry"
          :class="`log-level-${log.level.toLowerCase()}`"
        >
          <div class="log-header">
            <span class="log-level-badge" :class="`badge-${log.level.toLowerCase()}`">
              {{ log.level }}
            </span>
            <span class="log-timestamp">
              {{ formatTimestamp(log.timestamp) }}
            </span>
            <span class="log-id text-secondary">
              #{{ log.id }}
            </span>
          </div>
          <div class="log-message">
            {{ log.message }}
          </div>
          <div v-if="log.variables && log.variables.length > 0" class="log-variables">
            <small class="text-secondary">
              Variables: <code>{{ log.variables.join(', ') }}</code>
            </small>
          </div>
        </div>

        <!-- Loading Indicator for Infinite Scroll -->
        <div v-if="loadingMore" class="text-center py-3">
          <div class="spinner-border spinner-border-sm text-primary" role="status">
            <span class="visually-hidden">Loading more...</span>
          </div>
          <small class="text-secondary ms-2">Loading more logs...</small>
        </div>

        <!-- Intersection Observer Target -->
        <div ref="loadMoreTrigger" class="load-more-trigger"></div>

        <!-- End of Logs Message -->
        <div v-if="!hasMore && logs.length > 0" class="text-center py-3">
          <small class="text-secondary">
            ─── End of logs ───
          </small>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import axios from 'axios'

const props = defineProps({
  agentId: {
    type: String,
    default: null
  }
})

// State
const logs = ref([])
const loading = ref(false)
const loadingMore = ref(false)
const totalCount = ref(0)
const hasMore = ref(true)
const offset = ref(0)
const limit = 50

// Filters
const filters = ref({
  level: '',
  search: ''
})

// Refs
const logContainer = ref(null)
const loadMoreTrigger = ref(null)

// Intersection Observer for infinite scroll
let observer = null
let searchTimeout = null

// Fetch logs
const fetchLogs = async (append = false) => {
  if (append) {
    loadingMore.value = true
  } else {
    loading.value = true
    logs.value = []
    offset.value = 0
  }

  try {
    const params = {
      limit,
      offset: offset.value
    }

    if (props.agentId) {
      params.agent_id = props.agentId
    }

    if (filters.value.level) {
      params.level = filters.value.level
    }

    if (filters.value.search) {
      params.search = filters.value.search
    }

    const response = await axios.get('/api/logs', { params })
    
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

// Load more logs
const loadMore = () => {
  if (!loadingMore.value && hasMore.value) {
    fetchLogs(true)
  }
}

// Filter change handler
const onFilterChange = () => {
  fetchLogs(false)
}

// Search input handler with debounce
const onSearchInput = () => {
  clearTimeout(searchTimeout)
  searchTimeout = setTimeout(() => {
    fetchLogs(false)
  }, 500) // 500ms debounce
}

// Clear search
const clearSearch = () => {
  filters.value.search = ''
  fetchLogs(false)
}

// Scroll to top
const scrollToTop = () => {
  if (logContainer.value) {
    logContainer.value.scrollTop = 0
  }
}

// Format timestamp
const formatTimestamp = (timestamp) => {
  const date = new Date(timestamp)
  return date.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
  })
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

// Lifecycle hooks
onMounted(async () => {
  await fetchLogs(false)
  await nextTick()
  setupObserver()
})

onUnmounted(() => {
  if (observer) {
    observer.disconnect()
  }
  clearTimeout(searchTimeout)
})
</script>

<style scoped>
.log-viewer {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.log-filters {
  flex-shrink: 0;
}

.log-list-container {
  flex: 1;
  overflow-y: auto;
  background-color: #0d1117;
  border: 1px solid var(--border-color);
  border-radius: var(--radius);
  padding: 1rem;
  max-height: 600px;
}

.log-list {
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 0.9rem;
}

.log-entry {
  background-color: rgba(255, 255, 255, 0.02);
  border-left: 3px solid var(--border-color);
  padding: 0.75rem;
  margin-bottom: 0.5rem;
  border-radius: 4px;
  transition: all 0.2s ease;
}

.log-entry:hover {
  background-color: rgba(255, 255, 255, 0.05);
  border-left-color: var(--primary);
}

/* Log level styling */
.log-entry.log-level-error {
  border-left-color: var(--danger);
  background-color: rgba(220, 53, 69, 0.05);
}

.log-entry.log-level-warning {
  border-left-color: var(--warning);
  background-color: rgba(255, 193, 7, 0.05);
}

.log-entry.log-level-info {
  border-left-color: var(--info);
  background-color: rgba(13, 202, 240, 0.05);
}

.log-entry.log-level-debug {
  border-left-color: var(--success);
  background-color: rgba(25, 135, 84, 0.05);
}

.log-header {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 0.5rem;
  font-size: 0.85rem;
}

.log-level-badge {
  display: inline-block;
  padding: 0.25rem 0.5rem;
  border-radius: 3px;
  font-weight: 600;
  font-size: 0.75rem;
  letter-spacing: 0.5px;
}

.log-level-badge.badge-error {
  background-color: var(--danger);
  color: white;
}

.log-level-badge.badge-warning {
  background-color: var(--warning);
  color: #000;
}

.log-level-badge.badge-info {
  background-color: var(--info);
  color: #000;
}

.log-level-badge.badge-debug {
  background-color: var(--success);
  color: white;
}

.log-timestamp {
  color: var(--text-secondary);
  font-family: monospace;
}

.log-id {
  margin-left: auto;
  font-size: 0.75rem;
}

.log-message {
  color: var(--text-primary);
  word-wrap: break-word;
  white-space: pre-wrap;
  line-height: 1.5;
}

.log-variables {
  margin-top: 0.5rem;
  padding-top: 0.5rem;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
}

.log-variables code {
  background-color: rgba(88, 166, 255, 0.1);
  padding: 0.2rem 0.4rem;
  border-radius: 3px;
  font-size: 0.85em;
}

.load-more-trigger {
  height: 1px;
  visibility: hidden;
}

/* Custom scrollbar */
.log-list-container::-webkit-scrollbar {
  width: 8px;
}

.log-list-container::-webkit-scrollbar-track {
  background: rgba(255, 255, 255, 0.05);
  border-radius: 4px;
}

.log-list-container::-webkit-scrollbar-thumb {
  background: var(--primary);
  border-radius: 4px;
}

.log-list-container::-webkit-scrollbar-thumb:hover {
  background: #4a9eff;
}
</style>
