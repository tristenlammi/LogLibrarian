<template>
  <aside class="monitor-sidebar">
    <!-- Add New Button with Settings (Admin Only) -->
    <div v-if="isAdmin" class="sidebar-actions">
      <button class="add-monitor-btn" :class="{ active: isAdding }" @click="$emit('add-new')">
        <span class="add-icon">➕</span>
        <span>Add New Bookmark</span>
      </button>
      <button class="settings-btn" @click="goToSettings" title="Bookmark Settings">
        ⚙️
      </button>
    </div>

    <!-- Search -->
    <div class="sidebar-search">
      <input 
        v-model="searchQuery" 
        type="text" 
        placeholder="🔍 Search name, group, or tag..."
      />
    </div>

    <!-- Loading State -->
    <div v-if="loading" class="sidebar-loading">
      <div class="spinner"></div>
      <span>Loading bookmarks...</span>
    </div>

    <!-- Monitor List -->
    <div v-else class="monitor-list">
      <!-- Groups -->
      <div v-for="group in filteredGroups" :key="group.id" class="monitor-group">
        <div class="group-header" @click="toggleGroup(group.id)">
          <span class="group-chevron" :class="{ expanded: expandedGroups.has(group.id) }">▶</span>
          <span class="group-name">{{ group.name }}</span>
          <span class="group-count">{{ group.bookmarks?.length || 0 }}</span>
          <span class="group-status" :class="getGroupStatus(group.bookmarks)"></span>
        </div>
        <transition name="slide">
          <div v-show="expandedGroups.has(group.id)" class="group-monitors">
            <div 
              v-for="monitor in group.bookmarks" 
              :key="monitor.id"
              class="monitor-item"
              :class="{ active: selectedId === monitor.id }"
              @click="selectMonitor(monitor.id)"
            >
              <div class="monitor-status" :class="getStatusClass(monitor)"></div>
              <div class="monitor-info">
                <div class="monitor-name">{{ monitor.name }}</div>
                <div class="monitor-target">{{ formatTarget(monitor) }}</div>
              </div>
              <div class="monitor-uptime" :class="getUptimeClass(monitor)">
                {{ formatUptime(monitor) }}
              </div>
            </div>
          </div>
        </transition>
      </div>

      <!-- Ungrouped Monitors -->
      <div v-if="filteredUngrouped.length > 0" class="monitor-group">
        <div class="group-header ungrouped" @click="toggleGroup('ungrouped')">
          <span class="group-chevron" :class="{ expanded: expandedGroups.has('ungrouped') }">▶</span>
          <span class="group-name">Ungrouped</span>
          <span class="group-count">{{ filteredUngrouped.length }}</span>
          <span class="group-status" :class="getGroupStatus(filteredUngrouped)"></span>
        </div>
        <transition name="slide">
          <div v-show="expandedGroups.has('ungrouped')" class="group-monitors">
            <div 
              v-for="monitor in filteredUngrouped" 
              :key="monitor.id"
              class="monitor-item"
              :class="{ active: selectedId === monitor.id }"
              @click="selectMonitor(monitor.id)"
            >
              <div class="monitor-status" :class="getStatusClass(monitor)"></div>
              <div class="monitor-info">
                <div class="monitor-name">{{ monitor.name }}</div>
                <div class="monitor-target">{{ formatTarget(monitor) }}</div>
              </div>
              <div class="monitor-uptime" :class="getUptimeClass(monitor)">
                {{ formatUptime(monitor) }}
              </div>
            </div>
          </div>
        </transition>
      </div>

      <!-- Empty State -->
      <div v-if="filteredGroups.length === 0 && filteredUngrouped.length === 0" class="empty-state">
        <div v-if="searchQuery">
          <p>No bookmarks found matching "{{ searchQuery }}"</p>
        </div>
        <div v-else>
          <p>No bookmarks configured</p>
          <p class="hint">Click "Add New Bookmark" to get started</p>
        </div>
      </div>
    </div>

    <!-- Summary Footer -->
    <div class="sidebar-footer">
      <div class="summary-stats">
        <span class="stat up">
          <span class="stat-dot up"></span>
          {{ summary.up }} Up
        </span>
        <span class="stat down">
          <span class="stat-dot down"></span>
          {{ summary.down }} Down
        </span>
        <span class="stat unknown" v-if="summary.unknown > 0">
          <span class="stat-dot unknown"></span>
          {{ summary.unknown }} Unknown
        </span>
      </div>
    </div>
  </aside>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { isAdmin } from '../auth.js'

const router = useRouter()

const props = defineProps({
  selectedId: {
    type: [String, Number],
    default: null
  },
  isAdding: {
    type: Boolean,
    default: false
  },
  monitorCache: {
    type: Object,
    default: () => ({})
  }
})

const emit = defineEmits(['select', 'add-new'])

const API_BASE = import.meta.env.VITE_API_URL || ''

// State
const loading = ref(true)
const searchQuery = ref('')
const tree = ref({ groups: [], ungrouped: [] })
// Check localStorage for user preference on default group state
const groupsStartExpanded = JSON.parse(localStorage.getItem('bookmarkGroupsExpanded') || 'false')
const expandedGroups = ref(new Set()) // Will be populated based on user preference
const refreshInterval = ref(null)

// Navigate to settings
const goToSettings = () => {
  router.push('/bookmarks/settings')
}

// Computed

// Helper function to check if a monitor matches search query
const monitorMatchesQuery = (monitor, query) => {
  // Match by name
  if (monitor.name.toLowerCase().includes(query)) return true
  
  // Match by target/URL
  if (monitor.target.toLowerCase().includes(query)) return true
  
  // Match by tags (comma-separated string)
  if (monitor.tags) {
    const tags = monitor.tags.split(',').map(t => t.trim().toLowerCase())
    if (tags.some(tag => tag.includes(query))) return true
  }
  
  // Match by description
  if (monitor.description && monitor.description.toLowerCase().includes(query)) return true
  
  return false
}

// Helper to check if a group name matches
const groupMatchesQuery = (groupName, query) => {
  return groupName.toLowerCase().includes(query)
}

const filteredGroups = computed(() => {
  if (!searchQuery.value) return tree.value.groups
  
  const query = searchQuery.value.toLowerCase()
  
  return tree.value.groups
    .map(group => {
      // If group name matches, include ALL bookmarks in that group
      if (groupMatchesQuery(group.name, query)) {
        return { ...group }
      }
      
      // Otherwise, filter bookmarks by the query
      return {
        ...group,
        bookmarks: (group.bookmarks || []).filter(m => monitorMatchesQuery(m, query))
      }
    })
    .filter(group => group.bookmarks.length > 0)
})

const filteredUngrouped = computed(() => {
  if (!searchQuery.value) return tree.value.ungrouped || []
  
  const query = searchQuery.value.toLowerCase()
  return (tree.value.ungrouped || []).filter(m => monitorMatchesQuery(m, query))
})

const summary = computed(() => {
  let up = 0, down = 0, unknown = 0
  
  const allMonitors = [
    ...(tree.value.ungrouped || []),
    ...tree.value.groups.flatMap(g => g.bookmarks || [])
  ]
  
  for (const m of allMonitors) {
    const status = m.latest_check?.status ?? m.last_status
    if (status === 1) up++
    else if (status === 0) down++
    else unknown++
  }
  
  return { up, down, unknown }
})

// Methods
const fetchTree = async () => {
  try {
    const response = await fetch(`${API_BASE}/api/bookmarks/tree`, {
      credentials: 'include'
    })
    const data = await response.json()
    if (data.success) {
      tree.value = data.data
      // Initialize expanded state based on user preference
      if (groupsStartExpanded && expandedGroups.value.size === 0) {
        // Expand all groups on first load if user prefers expanded
        for (const group of data.data.groups || []) {
          expandedGroups.value.add(group.id)
        }
        if (data.data.ungrouped?.length > 0) {
          expandedGroups.value.add('ungrouped')
        }
      }
    }
  } catch (error) {
    console.error('Error fetching monitors:', error)
  } finally {
    loading.value = false
  }
}

// Calculate group health status based on worst child status
const getGroupStatus = (monitors) => {
  if (!monitors || monitors.length === 0) return 'unknown'
  
  let hasDown = false
  let hasUnknown = false
  
  for (const m of monitors) {
    const status = m.latest_check?.status ?? m.last_status
    if (status === 0) {
      hasDown = true
      break // No need to check further, DOWN is worst
    } else if (status !== 1) {
      hasUnknown = true
    }
  }
  
  if (hasDown) return 'down'
  if (hasUnknown) return 'unknown'
  return 'up'
}

const toggleGroup = (groupId) => {
  if (expandedGroups.value.has(groupId)) {
    expandedGroups.value.delete(groupId)
  } else {
    expandedGroups.value.add(groupId)
  }
}

const selectMonitor = (id) => {
  emit('select', id)
}

const getStatusClass = (monitor) => {
  // First check cache for most up-to-date status
  const cached = props.monitorCache[monitor.id]?.details
  
  // Use cached status if available (detail endpoint uses 'checks' array)
  if (cached) {
    const status = cached.checks?.[0]?.status ?? cached.latest_check?.status ?? cached.last_status
    if (status === 1) return 'up'
    if (status === 0) return 'down'
    return 'unknown'
  }
  
  // Fallback to tree data (which already has last_status from API)
  const status = monitor.latest_check?.status ?? monitor.last_status
  if (status === 1) return 'up'
  if (status === 0) return 'down'
  return 'unknown'
}

const getUptimeClass = (monitor) => {
  const cached = props.monitorCache[monitor.id]?.details
  
  // Use cached status if available (detail endpoint uses 'checks' array), else tree data
  const status = cached 
    ? (cached.checks?.[0]?.status ?? cached.latest_check?.status ?? cached.last_status)
    : (monitor.latest_check?.status ?? monitor.last_status)
    
  if (status === 1) return 'up'
  if (status === 0) return 'down'
  return 'unknown'
}

const formatUptime = (monitor) => {
  const cached = props.monitorCache[monitor.id]?.details
  
  // Use cached latency if available (detail endpoint uses 'checks' array), else tree data
  const latency = cached 
    ? (cached.checks?.[0]?.latency_ms ?? cached.latest_check?.latency_ms ?? cached.last_latency)
    : (monitor.latest_check?.latency_ms ?? monitor.last_latency)
    
  if (latency !== null && latency !== undefined) {
    return `${latency}ms`
  }
  return '-'
}

const formatTarget = (monitor) => {
  let target = monitor.target
  // Truncate long URLs
  if (target.length > 30) {
    target = target.substring(0, 30) + '...'
  }
  if (monitor.type === 'tcp-port' && monitor.port) {
    return `${target}:${monitor.port}`
  }
  return target
}

// Lifecycle
onMounted(() => {
  fetchTree()
  // Refresh every 30 seconds
  refreshInterval.value = setInterval(fetchTree, 30000)
})

onUnmounted(() => {
  if (refreshInterval.value) {
    clearInterval(refreshInterval.value)
  }
})

// Expose refresh method for parent
defineExpose({ refresh: fetchTree })
</script>

<style scoped>
.monitor-sidebar {
  width: 300px;
  min-width: 300px;
  background: var(--card-bg);
  border-right: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

/* Sidebar Actions Row */
.sidebar-actions {
  display: flex;
  gap: 0.5rem;
  padding: 0.75rem;
  align-items: stretch;
}

/* Add Button */
.add-monitor-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  flex: 1;
  padding: 0.875rem;
  background: var(--primary);
  color: #000;
  border: none;
  border-radius: var(--radius);
  font-size: 0.9rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.add-monitor-btn:hover {
  background: #4A96E6;
  transform: translateY(-1px);
}

.add-monitor-btn.active {
  background: #4A96E6;
  box-shadow: 0 0 0 2px var(--bg-color), 0 0 0 4px var(--primary);
}

.add-icon {
  font-size: 1rem;
}

/* Settings Button */
.settings-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  background: var(--bg-color);
  border: 1px solid var(--border-color);
  border-radius: var(--radius);
  font-size: 1.1rem;
  cursor: pointer;
  transition: all 0.2s;
}

.settings-btn:hover {
  background: var(--card-bg);
  border-color: var(--primary);
}

/* Search */
.sidebar-search {
  padding: 0 0.75rem 0.75rem;
}

.sidebar-search input {
  width: 100%;
  padding: 0.625rem 0.875rem;
  background: var(--bg-color);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  color: var(--text-primary);
  font-size: 0.875rem;
}

.sidebar-search input:focus {
  outline: none;
  border-color: var(--primary);
}

.sidebar-search input::placeholder {
  color: var(--text-secondary);
}

/* Loading */
.sidebar-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 2rem;
  color: var(--text-secondary);
  gap: 0.75rem;
}

.spinner {
  width: 24px;
  height: 24px;
  border: 2px solid var(--border-color);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* Monitor List */
.monitor-list {
  flex: 1;
  overflow-y: auto;
  padding: 0 0.5rem;
}

/* Group */
.monitor-group {
  margin-bottom: 0.25rem;
}

.group-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.625rem 0.5rem;
  cursor: pointer;
  border-radius: 6px;
  transition: background 0.2s;
  user-select: none;
}

.group-header:hover {
  background: rgba(255, 255, 255, 0.05);
}

.group-chevron {
  font-size: 0.65rem;
  color: var(--text-secondary);
  transition: transform 0.2s;
}

.group-chevron.expanded {
  transform: rotate(90deg);
}

.group-name {
  flex: 1;
  font-size: 0.8rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--text-secondary);
}

.group-header.ungrouped .group-name {
  color: var(--text-secondary);
  opacity: 0.7;
}

.group-count {
  background: var(--border-color);
  padding: 0.125rem 0.5rem;
  border-radius: 10px;
  font-size: 0.7rem;
  color: var(--text-secondary);
}

.group-status {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
  margin-left: 0.25rem;
}

.group-status.up {
  background: var(--success);
  box-shadow: 0 0 4px var(--success);
}

.group-status.down {
  background: var(--danger);
  box-shadow: 0 0 6px var(--danger);
  animation: pulse-danger 1.5s ease-in-out infinite;
}

.group-status.unknown {
  background: var(--text-secondary);
  opacity: 0.6;
}

@keyframes pulse-danger {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

/* Group Monitors */
.group-monitors {
  padding-left: 0.25rem;
}

/* Monitor Item */
.monitor-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem;
  margin: 0.125rem 0;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  border: 1px solid transparent;
}

.monitor-item:hover {
  background: rgba(255, 255, 255, 0.05);
}

.monitor-item.active {
  background: rgba(88, 166, 255, 0.15);
  border-color: var(--primary);
}

.monitor-status {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

.monitor-status.up {
  background: var(--success);
  box-shadow: 0 0 6px var(--success);
}

.monitor-status.down {
  background: var(--danger);
  box-shadow: 0 0 6px var(--danger);
}

.monitor-status.unknown {
  background: var(--text-secondary);
}

.monitor-status.pending {
  background: transparent;
  border: 1px solid var(--text-secondary);
  opacity: 0.5;
}

.monitor-info {
  flex: 1;
  min-width: 0;
}

.monitor-name {
  font-size: 0.9rem;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.monitor-target {
  font-size: 0.75rem;
  color: var(--text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.monitor-uptime {
  font-size: 0.8rem;
  font-weight: 600;
  padding: 0.25rem 0.5rem;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.05);
}

.monitor-uptime.up {
  color: var(--success);
}

.monitor-uptime.down {
  color: var(--danger);
}

.monitor-uptime.unknown {
  color: var(--text-secondary);
}

/* Empty State */
.empty-state {
  text-align: center;
  padding: 2rem 1rem;
  color: var(--text-secondary);
}

.empty-state .hint {
  font-size: 0.8rem;
  margin-top: 0.5rem;
  opacity: 0.7;
}

/* Footer */
.sidebar-footer {
  border-top: 1px solid var(--border-color);
  padding: 0.75rem;
  background: var(--card-bg);
}

.summary-stats {
  display: flex;
  justify-content: center;
  gap: 1rem;
}

.stat {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.8rem;
  font-weight: 500;
}

.stat.up { color: var(--success); }
.stat.down { color: var(--danger); }
.stat.unknown { color: var(--text-secondary); }

.stat-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.stat-dot.up { background: var(--success); }
.stat-dot.down { background: var(--danger); }
.stat-dot.unknown { background: var(--text-secondary); }

/* Slide Transition */
.slide-enter-active,
.slide-leave-active {
  transition: all 0.2s ease;
  overflow: hidden;
}

.slide-enter-from,
.slide-leave-to {
  opacity: 0;
  max-height: 0;
}

.slide-enter-to,
.slide-leave-from {
  opacity: 1;
  max-height: 1000px;
}
</style>
