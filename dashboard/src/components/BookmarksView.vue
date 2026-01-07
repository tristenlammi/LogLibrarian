<template>
  <div class="bookmarks-container">
    <!-- Split Pane Layout -->
    <div class="bookmarks-layout">
      <!-- Left Sidebar -->
      <MonitorSidebar 
        ref="sidebarRef"
        :selected-id="selectedMonitorId"
        :is-adding="isAddingNew"
        :monitor-cache="monitorCache"
        @select="handleMonitorSelect"
        @add-new="navigateToNew"
      />

      <!-- Main Content Area -->
      <div class="monitor-content">
        <!-- Add/Edit Form View -->
        <MonitorFormView 
          v-if="showForm"
          :monitor-id="editingMonitorId"
          :groups="groups"
          :clone-data="cloneData"
          @save="handleFormSave"
          @cancel="handleFormCancel"
        />

        <!-- Pre-rendered Monitor Detail Views - all monitors loaded, just show/hide -->
        <template v-if="!showForm">
          <MonitorDetailView 
            v-for="(cached, monitorId) in monitorCache"
            v-show="String(selectedMonitorId) === String(monitorId) && cached.details"
            :key="monitorId"
            :monitor="cached.details"
            :checks="cached.details?.checks || []"
            :history="cached.history || {}"
            @edit="navigateToEdit"
            @delete="confirmDelete"
            @clone="cloneMonitor"
            @toggle-active="toggleMonitorActive"
            @check-now="triggerCheck"
          />
        </template>

        <!-- Loading State - when monitor is selected but not yet in cache -->
        <div v-if="!showForm && selectedMonitorId && !monitorCache[selectedMonitorId]?.details" class="monitor-loading">
          <div class="loading-content">
            <div class="spinner-border text-primary mb-3"></div>
            <div class="text-secondary">Loading monitor...</div>
          </div>
        </div>

        <!-- No Selection State -->
        <div v-if="!showForm && !selectedMonitorId" class="no-selection">
          <div class="no-selection-content">
            <div class="no-selection-icon">📡</div>
            <h3>Select a Monitor</h3>
            <p>Choose a monitor from the sidebar to view its details and history.</p>
            <button v-if="isAdmin" class="btn btn-primary" @click="navigateToNew">
              ➕ Add New Monitor
            </button>
            <!-- Debug: Remove this after testing -->
            <p class="mt-3 text-secondary small">
              <span v-if="prefetchComplete" class="text-success">✓ Cache ready</span>
              <span v-else>⏳ Loading cache...</span>
              ({{ Object.keys(monitorCache).length }} monitors cached)
            </p>
          </div>
        </div>
      </div>
    </div>

    <!-- Delete Confirmation Modal (keep this as modal since it's a quick action) -->
    <div v-if="showDeleteModal" class="modal-overlay" @click.self="closeDeleteModal">
      <div class="modal-content modal-small">
        <div class="modal-header">
          <h3>Delete Monitor</h3>
          <button class="modal-close" @click="closeDeleteModal">&times;</button>
        </div>
        <p>Are you sure you want to delete <strong>{{ monitorCache[selectedMonitorId]?.details?.name }}</strong>?</p>
        <p class="text-secondary">This will also delete all check history.</p>
        <div class="delete-confirm-input">
          <label>Type <strong>delete</strong> to confirm:</label>
          <input 
            v-model="deleteConfirmText" 
            type="text" 
            placeholder="delete"
            @keyup.enter="deleteConfirmText.toLowerCase() === 'delete' && deleteMonitor()"
          />
        </div>
        <div class="modal-actions">
          <button class="btn btn-secondary" @click="closeDeleteModal">Cancel</button>
          <button 
            class="btn btn-danger" 
            @click="deleteMonitor" 
            :disabled="deleteConfirmText.toLowerCase() !== 'delete'"
          >Delete</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import MonitorSidebar from './MonitorSidebar.vue'
import MonitorDetailView from './MonitorDetailView.vue'
import MonitorFormView from './MonitorFormView.vue'
import { isAdmin } from '../auth.js'

const route = useRoute()
const router = useRouter()

const API_BASE = import.meta.env.VITE_API_URL || ''

// Refs
const sidebarRef = ref(null)

// State
const selectedMonitorId = ref(null)
const groups = ref([])
const checking = ref(false)
const showDeleteModal = ref(false)
const deleteConfirmText = ref('')
const refreshInterval = ref(null)
const cloneData = ref(null)
const prefetchComplete = ref(false)

// Prefetch cache - stores monitor details and history for instant switching
// All monitors are pre-rendered using this cache
const monitorCache = ref({}) // { [id]: { details: {...}, history: {...} } }

// Computed - determine view mode from route
const isAddingNew = computed(() => route.name === 'BookmarkNew')
const isEditing = computed(() => route.name === 'BookmarkEdit')
const showForm = computed(() => isAddingNew.value || isEditing.value)
const editingMonitorId = computed(() => isEditing.value ? route.params.id : null)

// Methods
const fetchMonitorDetails = async (id) => {
  if (!id) return
  
  try {
    // Fetch with more check history
    const response = await fetch(`${API_BASE}/api/bookmarks/${id}?limit=200`)
    const data = await response.json()
    if (data.success) {
      // Update cache only - components read from cache
      if (!monitorCache.value[id]) monitorCache.value[id] = {}
      monitorCache.value[id].details = data.data
    }
  } catch (error) {
    console.error('Error fetching monitor details:', error)
  }
}

const fetchMonitorHistory = async (id) => {
  if (!id) return
  
  try {
    // Fetch 30 day history for uptime calculation
    const response = await fetch(`${API_BASE}/api/bookmarks/${id}/history?hours=720`)
    const data = await response.json()
    if (data.success) {
      // Update cache only - components read from cache
      if (!monitorCache.value[id]) monitorCache.value[id] = {}
      monitorCache.value[id].history = data.data
    }
  } catch (error) {
    console.error('Error fetching monitor history:', error)
  }
}

// AbortController for cancelling background fetches on navigation
const abortController = ref(null)

// Helper to delay execution (for throttling background requests)
const delay = (ms) => new Promise(resolve => setTimeout(resolve, ms))

// Prefetch all monitors' data for instant switching
const prefetchAllMonitors = async () => {
  try {
    // Reset controller
    if (abortController.value) {
      abortController.value.abort()
    }
    abortController.value = new AbortController()
    const signal = abortController.value.signal

    // Get all monitors from the tree
    const response = await fetch(`${API_BASE}/api/bookmarks/tree`, {
      credentials: 'include',
      signal
    })
    const data = await response.json()
    if (!data.success) {
      prefetchComplete.value = true
      return
    }
    
    // Collect all monitor IDs
    const monitorIds = []
    
    // From groups
    if (data.data.groups) {
      data.data.groups.forEach(group => {
        if (group.bookmarks) {
          group.bookmarks.forEach(bm => monitorIds.push(bm.id))
        }
      })
    }
    
    // From ungrouped
    if (data.data.ungrouped) {
      data.data.ungrouped.forEach(bm => monitorIds.push(bm.id))
    }
    
    console.log(`[Prefetch] Starting prefetch for ${monitorIds.length} monitors`)

    // PHASE 1: Immediate Load (Top 10 visible)
    // ----------------------------------------
    const IMMEDIATE_BATCH_SIZE = 10
    const initialBatch = monitorIds.slice(0, IMMEDIATE_BATCH_SIZE)
    
    await fetchBatch(initialBatch, signal)

    // PHASE 2: Background Load (Chunked)
    // ----------------------------------
    const BACKGROUND_BATCH_SIZE = 5
    const BATCH_DELAY_MS = 200
    
    const remainingIds = monitorIds.slice(IMMEDIATE_BATCH_SIZE)
    
    // Process remaining in chunks
    for (let i = 0; i < remainingIds.length; i += BACKGROUND_BATCH_SIZE) {
      if (signal.aborted) break
      
      const chunk = remainingIds.slice(i, i + BACKGROUND_BATCH_SIZE)
      await fetchBatch(chunk, signal)
      
      // Artificial delay to prevent network saturation
      await delay(BATCH_DELAY_MS)
    }
    
    if (!signal.aborted) {
      console.log(`[Prefetch] Complete. Cache keys:`, Object.keys(monitorCache.value))
      prefetchComplete.value = true
    }
  } catch (error) {
    if (error.name === 'AbortError') {
      console.log('[Prefetch] Aborted')
    } else {
      console.error('Error prefetching monitors:', error)
      prefetchComplete.value = true
    }
  }
}

// Helper to fetch a batch of monitors
const fetchBatch = async (ids, signal) => {
  if (ids.length === 0) return

  await Promise.all(ids.map(async (id) => {
    if (signal?.aborted) return

    try {
      // Check if already cached (could be clicked by user)
      if (monitorCache.value[id]?.details) return

      const [detailsRes, historyRes] = await Promise.all([
        fetch(`${API_BASE}/api/bookmarks/${id}?limit=200`, { signal }),
        fetch(`${API_BASE}/api/bookmarks/${id}/history?hours=720`, { signal })
      ])
      
      const [detailsData, historyData] = await Promise.all([
        detailsRes.json(),
        historyRes.json()
      ])
      
      if (!monitorCache.value[id]) monitorCache.value[id] = {}
      if (detailsData.success) monitorCache.value[id].details = detailsData.data
      if (historyData.success) monitorCache.value[id].history = historyData.data
      
    } catch (err) {
      if (err.name !== 'AbortError') {
        console.error(`Error prefetching monitor ${id}:`, err)
      }
    }
  }))
}

const fetchGroups = async () => {
  try {
    const response = await fetch(`${API_BASE}/api/bookmarks/groups`)
    const data = await response.json()
    if (data.success) {
      groups.value = data.data
    }
  } catch (error) {
    console.error('Error fetching groups:', error)
  }
}

const handleMonitorSelect = (id) => {
  cloneData.value = null
  
  // Just set the ID - the pre-rendered views will show/hide based on this
  selectedMonitorId.value = id
  
  // Navigate
  router.push(`/bookmarks/${id}`)
  
  // Fetch fresh data in background to update the cache
  fetchMonitorDetails(id)
  fetchMonitorHistory(id)
}

// Navigation methods
const navigateToNew = () => {
  cloneData.value = null
  router.push('/bookmarks/new')
}

const navigateToEdit = () => {
  if (selectedMonitorId.value) {
    router.push(`/bookmarks/${selectedMonitorId.value}/edit`)
  }
}

const triggerCheck = async () => {
  if (!selectedMonitorId.value || checking.value) return
  checking.value = true
  try {
    const response = await fetch(`${API_BASE}/api/bookmarks/${selectedMonitorId.value}/check`, {
      method: 'POST'
    })
    const data = await response.json()
    if (data.success) {
      // Refresh monitor details
      await fetchMonitorDetails(selectedMonitorId.value)
      // Refresh sidebar
      if (sidebarRef.value?.refresh) {
        sidebarRef.value.refresh()
      }
    }
  } catch (error) {
    console.error('Error triggering check:', error)
  } finally {
    checking.value = false
  }
}

const toggleMonitorActive = async () => {
  const currentMonitor = monitorCache.value[selectedMonitorId.value]?.details
  if (!currentMonitor) return
  try {
    const response = await fetch(`${API_BASE}/api/bookmarks/${selectedMonitorId.value}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ active: !currentMonitor.active })
    })
    const data = await response.json()
    if (data.success) {
      await fetchMonitorDetails(selectedMonitorId.value)
      if (sidebarRef.value?.refresh) {
        sidebarRef.value.refresh()
      }
    }
  } catch (error) {
    console.error('Error toggling monitor:', error)
  }
}

const cloneMonitor = () => {
  const currentMonitor = monitorCache.value[selectedMonitorId.value]?.details
  if (!currentMonitor) return
  // Set clone data and navigate to new form
  cloneData.value = {
    name: currentMonitor.name,
    type: currentMonitor.type,
    target: currentMonitor.target,
    port: currentMonitor.port,
    group_id: currentMonitor.group_id,
    interval_seconds: currentMonitor.interval_seconds,
    tags: currentMonitor.tags,
    description: currentMonitor.description
  }
  router.push('/bookmarks/new')
}

// Form event handlers
const handleFormSave = ({ id, isNew }) => {
  cloneData.value = null
  // Refresh sidebar
  if (sidebarRef.value?.refresh) {
    sidebarRef.value.refresh()
  }
  // Clear cache for this monitor to force fresh fetch
  if (id && monitorCache.value[id]) {
    delete monitorCache.value[id]
  }
  // Navigate to the saved monitor
  if (id) {
    selectedMonitorId.value = id
    fetchMonitorDetails(id)
    fetchMonitorHistory(id)
  }
}

const handleFormCancel = () => {
  cloneData.value = null
}

const confirmDelete = () => {
  deleteConfirmText.value = ''
  showDeleteModal.value = true
}

const closeDeleteModal = () => {
  showDeleteModal.value = false
  deleteConfirmText.value = ''
}

const deleteMonitor = async () => {
  try {
    const deletingId = selectedMonitorId.value
    const response = await fetch(`${API_BASE}/api/bookmarks/${deletingId}`, {
      method: 'DELETE'
    })
    const data = await response.json()
    if (data.success) {
      showDeleteModal.value = false
      selectedMonitorId.value = null
      // Remove from cache
      delete monitorCache.value[deletingId]
      router.push('/bookmarks')
      // Refresh sidebar
      if (sidebarRef.value?.refresh) {
        sidebarRef.value.refresh()
      }
    }
  } catch (error) {
    console.error('Error deleting monitor:', error)
  }
}

// Auto-refresh selected monitor
const startAutoRefresh = () => {
  refreshInterval.value = setInterval(() => {
    if (selectedMonitorId.value) {
      fetchMonitorDetails(selectedMonitorId.value, false) // Fresh fetch, updates cache
    }
  }, 30000) // Refresh every 30 seconds
}

// Handle ?open=<monitor_id> query parameter from dashboard
const checkOpenQuery = () => {
  const openId = route.query.open
  if (openId) {
    // Navigate to the monitor detail page
    selectedMonitorId.value = openId
    router.replace({ path: `/bookmarks/${openId}`, query: {} })
    // Fetch data
    fetchMonitorDetails(openId)
    fetchMonitorHistory(openId)
  }
}

// Watch for route changes - just set the ID, pre-rendered views handle display
watch(() => route.params.id, (newId) => {
  if (newId && !isAddingNew.value && !isEditing.value) {
    selectedMonitorId.value = newId
    // Fetch fresh data in background
    fetchMonitorDetails(newId)
    fetchMonitorHistory(newId)
  }
}, { immediate: true })

// Watch for route name changes (switching between detail/edit/new)
watch(() => route.name, (newName) => {
  if (newName === 'Bookmarks') {
    // Reset to base state
    selectedMonitorId.value = null
    cloneData.value = null
  } else if (newName === 'BookmarkNew') {
    // Adding new - clear selection
    selectedMonitorId.value = null
  }
}, { flush: 'post' })

onMounted(() => {
  fetchGroups()
  startAutoRefresh()
  
  // Prefetch all monitors for instant switching - this populates the cache
  // and pre-renders all MonitorDetailView components
  prefetchAllMonitors()
  
  // Check for ?open= query parameter from dashboard navigation
  checkOpenQuery()
  
  // Set initial selection from route (watcher will handle data fetching)
  if (route.params.id) {
    selectedMonitorId.value = route.params.id
  }
})

// Watch for query parameter changes (in case user navigates from dashboard)
watch(() => route.query.open, (newVal) => {
  if (newVal) {
    checkOpenQuery()
  }
})

onUnmounted(() => {
  if (refreshInterval.value) {
    clearInterval(refreshInterval.value)
  }
  // Cancel any pending prefetch
  if (abortController.value) {
    abortController.value.abort()
  }
})

// Cancel prefetch if user navigates away
import { onBeforeRouteLeave } from 'vue-router'
onBeforeRouteLeave(() => {
  if (abortController.value) {
    abortController.value.abort()
  }
})
</script>

<style scoped>
.bookmarks-container {
  margin: -1.5rem;
  height: calc(100vh - 100px);
}

.bookmarks-layout {
  display: flex;
  height: 100%;
}

.monitor-content {
  flex: 1;
  overflow-y: auto;
  padding: 1.5rem;
  background: var(--bg-color);
}

/* Loading State */
.monitor-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  min-height: 400px;
}

.loading-content {
  text-align: center;
  padding: 2rem;
}

/* No Selection State */
.no-selection {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  min-height: 400px;
}

.no-selection-content {
  text-align: center;
  padding: 2rem;
}

.no-selection-icon {
  font-size: 4rem;
  margin-bottom: 1rem;
  opacity: 0.5;
}

.no-selection h3 {
  margin-bottom: 0.5rem;
}

.no-selection p {
  color: var(--text-secondary);
  margin-bottom: 1.5rem;
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
}

.modal-content {
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: var(--radius);
  width: 100%;
  max-width: 500px;
  max-height: 90vh;
  overflow-y: auto;
}

.modal-content.modal-small {
  max-width: 400px;
}

.delete-confirm-input {
  padding: 0 1.5rem 1rem;
}

.delete-confirm-input label {
  display: block;
  margin-bottom: 0.5rem;
  color: var(--text-secondary);
  font-size: 0.9rem;
}

.delete-confirm-input input {
  width: 100%;
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  background: var(--bg-secondary);
  color: var(--text-primary);
  font-size: 0.9rem;
}

.delete-confirm-input input:focus {
  outline: none;
  border-color: var(--accent-color);
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1.25rem 1.5rem;
  border-bottom: 1px solid var(--border-color);
}

.modal-header h3 {
  margin: 0;
}

.modal-close {
  background: none;
  border: none;
  font-size: 1.5rem;
  color: var(--text-secondary);
  cursor: pointer;
  line-height: 1;
}

.modal-close:hover {
  color: var(--text-primary);
}

.modal-content form,
.modal-content > p {
  padding: 1.5rem;
}

.modal-content > p {
  padding-bottom: 0;
}

.form-group {
  margin-bottom: 1rem;
}

.form-group label {
  display: block;
  margin-bottom: 0.5rem;
  font-size: 0.875rem;
  color: var(--text-secondary);
}

.form-group input,
.form-group select {
  width: 100%;
  padding: 0.75rem;
  background: var(--bg-color);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  color: var(--text-primary);
  font-size: 1rem;
}

.form-group input:focus,
.form-group select:focus {
  outline: none;
  border-color: var(--primary);
}

.checkbox-group label {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  cursor: pointer;
}

.checkbox-group input[type="checkbox"] {
  width: auto;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
  padding: 1.25rem 1.5rem;
  border-top: 1px solid var(--border-color);
}

/* Button Styles */
.btn {
  padding: 0.5rem 1rem;
  border-radius: 6px;
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  border: 1px solid transparent;
  transition: all 0.2s;
}

.btn-sm {
  padding: 0.375rem 0.75rem;
  font-size: 0.8rem;
}

.btn-primary {
  background: var(--primary);
  color: #000;
}

.btn-primary:hover {
  background: #4A96E6;
}

.btn-secondary {
  background: var(--border-color);
  color: var(--text-primary);
}

.btn-secondary:hover {
  background: #3d444d;
}

.btn-outline-primary {
  background: transparent;
  border-color: var(--primary);
  color: var(--primary);
}

.btn-outline-primary:hover {
  background: var(--primary);
  color: #000;
}

.btn-outline-secondary {
  background: transparent;
  border-color: var(--border-color);
  color: var(--text-secondary);
}

.btn-outline-secondary:hover {
  background: var(--border-color);
  color: var(--text-primary);
}

.btn-outline-danger {
  background: transparent;
  border-color: var(--danger);
  color: var(--danger);
}

.btn-outline-danger:hover {
  background: var(--danger);
  color: #fff;
}

.btn-danger {
  background: var(--danger);
  color: #fff;
}

.btn-danger:hover {
  background: #c53030;
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Utility */
.text-success { color: var(--success) !important; }
.text-warning { color: var(--warning) !important; }
.text-danger { color: var(--danger) !important; }
.text-secondary { color: var(--text-secondary) !important; }
</style>
