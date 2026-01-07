<template>
  <div class="monitor-detail-view">
    <!-- Header Section -->
    <div class="detail-header">
      <div class="header-left">
        <div class="status-badge-large" :class="currentStatus">
          <span class="status-icon">{{ currentStatus === 'up' ? '✓' : currentStatus === 'down' ? '✕' : '?' }}</span>
          <span class="status-text">{{ statusText }}</span>
        </div>
        <div class="monitor-title">
          <div class="title-row">
            <h1>{{ monitor.name }}</h1>
            <div v-if="parsedTags.length > 0" class="title-tags">
              <span v-for="tag in parsedTags" :key="tag" class="title-tag">{{ tag }}</span>
            </div>
          </div>
          <a :href="monitor.target" target="_blank" class="monitor-url" v-if="monitor.type === 'http'">
            {{ monitor.target }}
            <span class="external-icon">↗</span>
          </a>
          <span class="monitor-url" v-else>
            {{ monitor.target }}{{ monitor.port ? `:${monitor.port}` : '' }}
          </span>
        </div>
      </div>
      <div class="header-actions">
        <template v-if="isAdmin">
          <button 
            class="action-btn" 
            :class="{ 'paused': !monitor.active }"
            @click="$emit('toggle-active')"
            :title="monitor.active ? 'Pause monitoring' : 'Resume monitoring'"
          >
            <span v-if="monitor.active">⏸️</span>
            <span v-else>▶️</span>
            {{ monitor.active ? 'Pause' : 'Resume' }}
          </button>
          <button class="action-btn" @click="$emit('edit')" title="Edit bookmark">
            ✏️ Edit
          </button>
          <button class="action-btn" @click="$emit('clone')" title="Clone bookmark">
            📋 Clone
          </button>
          <button class="action-btn danger" @click="$emit('delete')" title="Delete bookmark">
            🗑️ Delete
          </button>
        </template>
      </div>
    </div>

    <!-- Stats Row -->
    <div class="stats-row">
      <div class="stat-card highlight">
        <div class="stat-label">Current Ping</div>
        <div class="stat-value" :class="currentStatus">
          {{ currentPing !== null ? `${currentPing}` : '-' }}
          <span class="stat-unit" v-if="currentPing !== null">ms</span>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Avg. Ping (24h)</div>
        <div class="stat-value">
          {{ avgPing24h !== null ? `${avgPing24h}` : '-' }}
          <span class="stat-unit" v-if="avgPing24h !== null">ms</span>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Uptime (24h)</div>
        <div class="stat-value" :class="getUptimeClass(uptime24h)">
          {{ uptime24h !== null ? `${uptime24h}` : '-' }}
          <span class="stat-unit" v-if="uptime24h !== null">%</span>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Uptime (30d)</div>
        <div class="stat-value" :class="getUptimeClass(uptime30d)">
          {{ uptime30d !== null ? `${uptime30d}` : '-' }}
          <span class="stat-unit" v-if="uptime30d !== null">%</span>
        </div>
      </div>
    </div>

    <!-- Heartbeat Bar Section -->
    <div class="section-card">
      <div class="section-header">
        <h3>Heartbeat</h3>
        <span class="section-subtitle">Last {{ maxHeartbeats }} checks</span>
      </div>
      <HeartbeatBar :checks="checks" :max-pills="maxHeartbeats" />
      <div class="heartbeat-footer">
        <span class="time-label">{{ oldestCheckTime }}</span>
        <span class="time-label">Now</span>
      </div>
    </div>

    <!-- Response Time Chart Section -->
    <div class="section-card">
      <div class="section-header">
        <h3>Response Time</h3>
        <div class="time-range-selector">
          <button 
            v-for="range in timeRanges" 
            :key="range.value"
            class="range-btn"
            :class="{ active: selectedRange === range.value }"
            @click="selectedRange = range.value"
          >
            {{ range.label }}
          </button>
        </div>
      </div>
      <LatencyChart :checks="filteredChecksForChart" :hours="selectedRange" />
    </div>

    <!-- Recent Events Section -->
    <div class="section-card">
      <div class="section-header">
        <h3>Recent Events</h3>
        <span class="section-subtitle">Status changes & important events</span>
      </div>
      <div class="events-list" v-if="recentEvents.length > 0">
        <div 
          v-for="event in recentEvents" 
          :key="event.id" 
          class="event-item"
          :class="event.type"
        >
          <div class="event-icon">
            <span v-if="event.type === 'up'">🟢</span>
            <span v-else-if="event.type === 'down'">🔴</span>
            <span v-else>⚪</span>
          </div>
          <div class="event-details">
            <div class="event-message">{{ event.message }}</div>
            <div class="event-time">{{ event.time }}</div>
          </div>
          <div class="event-duration" v-if="event.duration">
            {{ event.duration }}
          </div>
        </div>
      </div>
      <div v-else class="no-events">
        <p>No status changes recorded yet</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import HeartbeatBar from './HeartbeatBar.vue'
import LatencyChart from './LatencyChart.vue'
import { formatDate, formatRelativeTime } from '../utils/timezone.js'
import { isAdmin } from '../auth.js'

const props = defineProps({
  monitor: {
    type: Object,
    required: true
  },
  checks: {
    type: Array,
    default: () => []
  },
  history: {
    type: Object,
    default: () => ({})
  }
})

const emit = defineEmits(['edit', 'delete', 'clone', 'toggle-active', 'check-now'])

// State
const maxHeartbeats = ref(90)
const selectedRange = ref(24)
const timeRanges = [
  { label: '3h', value: 3 },
  { label: '6h', value: 6 },
  { label: '12h', value: 12 },
  { label: '24h', value: 24 }
]

// Computed: Parse tags from comma-separated string
const parsedTags = computed(() => {
  if (!props.monitor.tags) return []
  return props.monitor.tags.split(',').map(t => t.trim()).filter(t => t)
})

// Computed: Current status
const currentStatus = computed(() => {
  if (!props.checks || props.checks.length === 0) return 'pending'
  const latest = props.checks[0]
  return latest.status === 1 ? 'up' : 'down'
})

const statusText = computed(() => {
  if (currentStatus.value === 'up') return 'Up'
  if (currentStatus.value === 'down') return 'Down'
  return 'Pending'
})

// Computed: Current ping
const currentPing = computed(() => {
  if (!props.checks || props.checks.length === 0) return null
  const latest = props.checks[0]
  return latest.status === 1 ? latest.latency_ms : null
})

// Computed: Average ping (24h)
const avgPing24h = computed(() => {
  if (!props.checks || props.checks.length === 0) return null
  
  const now = new Date()
  const cutoff = new Date(now.getTime() - 24 * 60 * 60 * 1000)
  
  const validChecks = props.checks.filter(c => {
    const checkTime = new Date(c.created_at)
    return c.status === 1 && c.latency_ms !== null && checkTime >= cutoff
  })
  
  if (validChecks.length === 0) return null
  
  const sum = validChecks.reduce((acc, c) => acc + c.latency_ms, 0)
  return Math.round(sum / validChecks.length)
})

// Computed: Uptime percentages
const uptime24h = computed(() => {
  return calculateUptime(24)
})

const uptime30d = computed(() => {
  // Use history data if available, otherwise calculate from checks
  if (props.history?.uptime_percent !== undefined) {
    return props.history.uptime_percent
  }
  return calculateUptime(24 * 30)
})

const calculateUptime = (hours) => {
  if (!props.checks || props.checks.length === 0) return null
  
  const now = new Date()
  const cutoff = new Date(now.getTime() - hours * 60 * 60 * 1000)
  
  const checksInRange = props.checks.filter(c => {
    const checkTime = new Date(c.created_at)
    return checkTime >= cutoff
  })
  
  if (checksInRange.length === 0) return null
  
  const upCount = checksInRange.filter(c => c.status === 1).length
  return Math.round((upCount / checksInRange.length) * 1000) / 10
}

// Computed: Filtered checks for chart based on selected time range
const filteredChecksForChart = computed(() => {
  if (!props.checks || props.checks.length === 0) return []
  
  const now = new Date()
  const cutoff = new Date(now.getTime() - selectedRange.value * 60 * 60 * 1000)
  
  return props.checks.filter(c => {
    const checkTime = new Date(c.created_at)
    return checkTime >= cutoff
  })
})

// Computed: Oldest check time for heartbeat footer
const oldestCheckTime = computed(() => {
  if (!props.checks || props.checks.length === 0) return 'No data'
  
  const displayedChecks = props.checks.slice(0, maxHeartbeats.value)
  if (displayedChecks.length === 0) return 'No data'
  
  const oldest = displayedChecks[displayedChecks.length - 1]
  return formatRelativeTime(oldest.created_at)
})

// Computed: Recent events (status changes)
const recentEvents = computed(() => {
  if (!props.checks || props.checks.length < 2) return []
  
  const events = []
  let lastStatus = null
  let downStartTime = null
  
  // Process checks from oldest to newest
  const sortedChecks = [...props.checks].reverse()
  
  for (let i = 0; i < sortedChecks.length; i++) {
    const check = sortedChecks[i]
    const currentStat = check.status === 1 ? 'up' : 'down'
    
    if (lastStatus !== null && lastStatus !== currentStat) {
      const checkTime = new Date(check.created_at)
      
      if (currentStat === 'down') {
        downStartTime = checkTime
        events.push({
          id: `down-${i}`,
          type: 'down',
          message: `Monitor went DOWN`,
          time: formatEventTime(checkTime),
          duration: null
        })
      } else {
        // Went up
        let duration = null
        if (downStartTime) {
          const downMs = checkTime - downStartTime
          duration = formatDuration(downMs)
        }
        events.push({
          id: `up-${i}`,
          type: 'up',
          message: `Monitor is UP`,
          time: formatEventTime(checkTime),
          duration: duration ? `Down for ${duration}` : null
        })
        downStartTime = null
      }
    }
    
    lastStatus = currentStat
  }
  
  // Return most recent events first
  return events.reverse().slice(0, 10)
})

// Helper: Get uptime class
const getUptimeClass = (uptime) => {
  if (uptime === null) return ''
  if (uptime >= 99) return 'excellent'
  if (uptime >= 95) return 'good'
  if (uptime >= 90) return 'warning'
  return 'danger'
}

// Helper: Format event time
const formatEventTime = (date) => {
  const now = new Date()
  const diffMs = now - date
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMins / 60)
  const diffDays = Math.floor(diffHours / 24)
  
  if (diffMins < 1) return 'Just now'
  if (diffMins < 60) return `${diffMins} min ago`
  if (diffHours < 24) return `${diffHours} hour${diffHours > 1 ? 's' : ''} ago`
  if (diffDays < 7) return `${diffDays} day${diffDays > 1 ? 's' : ''} ago`
  
  return formatDate(date)
}

// Helper: Format duration
const formatDuration = (ms) => {
  const seconds = Math.floor(ms / 1000)
  const minutes = Math.floor(seconds / 60)
  const hours = Math.floor(minutes / 60)
  
  if (hours > 0) {
    return `${hours}h ${minutes % 60}m`
  }
  if (minutes > 0) {
    return `${minutes}m ${seconds % 60}s`
  }
  return `${seconds}s`
}
</script>

<style scoped>
.monitor-detail-view {
  max-width: 1200px;
}

/* Header Section */
.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 1.5rem;
  gap: 1rem;
  flex-wrap: wrap;
}

.header-left {
  display: flex;
  align-items: flex-start;
  gap: 1rem;
}

.status-badge-large {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem 1.25rem;
  border-radius: 12px;
  font-weight: 700;
  font-size: 1.1rem;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.status-badge-large.up {
  background: linear-gradient(135deg, rgba(74, 222, 128, 0.2) 0%, rgba(34, 197, 94, 0.2) 100%);
  color: #4ade80;
  border: 1px solid rgba(74, 222, 128, 0.3);
}

.status-badge-large.down {
  background: linear-gradient(135deg, rgba(248, 113, 113, 0.2) 0%, rgba(239, 68, 68, 0.2) 100%);
  color: #f87171;
  border: 1px solid rgba(248, 113, 113, 0.3);
}

.status-badge-large.pending {
  background: rgba(107, 114, 128, 0.2);
  color: #9ca3af;
  border: 1px solid rgba(107, 114, 128, 0.3);
}

.status-icon {
  font-size: 1.25rem;
}

.monitor-title h1 {
  margin: 0;
  font-size: 1.75rem;
  font-weight: 700;
}

.title-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
  margin-bottom: 0.25rem;
}

.title-tags {
  display: flex;
  gap: 0.4rem;
  flex-wrap: wrap;
  align-items: center;
}

.title-tag {
  background: rgba(59, 130, 246, 0.15);
  color: #60a5fa;
  border: 1px solid rgba(59, 130, 246, 0.3);
  padding: 0.15rem 0.5rem;
  border-radius: 10px;
  font-size: 0.7rem;
  font-weight: 500;
  letter-spacing: 0.02em;
}

.monitor-url {
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 0.9rem;
  display: flex;
  align-items: center;
  gap: 0.25rem;
}

.monitor-url:hover {
  color: var(--primary);
}

.external-icon {
  font-size: 0.75rem;
}

/* Header Actions */
.header-actions {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.action-btn {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.5rem 1rem;
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  color: var(--text-primary);
  font-size: 0.85rem;
  cursor: pointer;
  transition: all 0.2s;
}

.action-btn:hover {
  background: var(--border-color);
}

.action-btn.paused {
  border-color: var(--warning);
  color: var(--warning);
}

.action-btn.danger:hover {
  background: rgba(239, 68, 68, 0.1);
  border-color: var(--danger);
  color: var(--danger);
}

/* Stats Row */
.stats-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 1rem;
  margin-bottom: 1.5rem;
}

.stat-card {
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 1.25rem;
  text-align: center;
}

.stat-card.highlight {
  border-color: var(--primary);
  background: linear-gradient(135deg, rgba(88, 166, 255, 0.05) 0%, rgba(88, 166, 255, 0.02) 100%);
}

.stat-label {
  font-size: 0.75rem;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 0.5rem;
}

.stat-value {
  font-size: 2rem;
  font-weight: 700;
  line-height: 1;
}

.stat-value.up {
  color: var(--success);
}

.stat-value.down {
  color: var(--danger);
}

.stat-value.excellent {
  color: var(--success);
}

.stat-value.good {
  color: #84cc16;
}

.stat-value.warning {
  color: var(--warning);
}

.stat-value.danger {
  color: var(--danger);
}

.stat-unit {
  font-size: 1rem;
  font-weight: 500;
  color: var(--text-secondary);
  margin-left: 0.125rem;
}

/* Section Card */
.section-card {
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 1.5rem;
  margin-bottom: 1.5rem;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
}

.section-header h3 {
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
}

.section-subtitle {
  font-size: 0.8rem;
  color: var(--text-secondary);
}

/* Heartbeat Footer */
.heartbeat-footer {
  display: flex;
  justify-content: space-between;
  margin-top: 0.5rem;
}

.time-label {
  font-size: 0.7rem;
  color: var(--text-secondary);
}

/* Time Range Selector */
.time-range-selector {
  display: flex;
  gap: 0.25rem;
  background: var(--bg-color);
  padding: 0.25rem;
  border-radius: 8px;
}

.range-btn {
  padding: 0.375rem 0.75rem;
  background: transparent;
  border: none;
  border-radius: 6px;
  color: var(--text-secondary);
  font-size: 0.75rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.range-btn:hover {
  color: var(--text-primary);
}

.range-btn.active {
  background: var(--primary);
  color: #000;
}

/* Events List */
.events-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.event-item {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 0.75rem 1rem;
  background: var(--bg-color);
  border-radius: 8px;
  border-left: 3px solid transparent;
}

.event-item.up {
  border-left-color: var(--success);
}

.event-item.down {
  border-left-color: var(--danger);
}

.event-icon {
  font-size: 1rem;
}

.event-details {
  flex: 1;
}

.event-message {
  font-weight: 500;
  margin-bottom: 0.125rem;
}

.event-time {
  font-size: 0.75rem;
  color: var(--text-secondary);
}

.event-duration {
  font-size: 0.8rem;
  color: var(--warning);
  background: rgba(210, 153, 34, 0.1);
  padding: 0.25rem 0.5rem;
  border-radius: 4px;
}

.no-events {
  text-align: center;
  padding: 2rem;
  color: var(--text-secondary);
}

.no-events p {
  margin: 0;
}

/* Responsive */
@media (max-width: 768px) {
  .detail-header {
    flex-direction: column;
  }
  
  .header-left {
    flex-direction: column;
    align-items: flex-start;
  }
  
  .stats-row {
    grid-template-columns: repeat(2, 1fr);
  }
  
  .stat-value {
    font-size: 1.5rem;
  }
}
</style>
