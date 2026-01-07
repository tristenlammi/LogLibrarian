<template>
  <div 
    class="agent-card"
    @click="$emit('select', agent.agent_id)"
  >
    <!-- Header -->
    <div class="d-flex justify-content-between align-items-start mb-2">
      <div class="flex-grow-1">
        <div class="d-flex align-items-center gap-2">
          <div 
            class="status-dot" 
            :class="agent.status === 'online' ? 'bg-success' : 'bg-danger'"
          ></div>
          <h6 class="mb-0">{{ agent.display_name || agent.hostname }}</h6>
        </div>
        <small class="text-secondary d-block mt-1" :title="agent.agent_id">
          {{ agent.display_name ? agent.hostname : agent.agent_id.substring(0, 8) + '...' }}
        </small>
      </div>
      <div class="d-flex flex-column align-items-end gap-1">
        <span class="badge" :class="agent.status === 'online' ? 'bg-success' : 'bg-danger'">
          {{ agent.status }}
        </span>
        <span 
          class="badge uptime-badge" 
          :class="uptimeBadgeClass"
          :title="availabilityTooltip"
        >
          {{ formattedUptime }} avail
        </span>
      </div>
    </div>

    <!-- Metrics Summary -->
    <div class="metrics-grid mb-3">
      <div class="metric-item">
        <div class="metric-label">CPU</div>
        <div class="metric-value">{{ latestCpu }}%</div>
      </div>
      <div class="metric-item">
        <div class="metric-label">RAM</div>
        <div class="metric-value">{{ latestRam }}%</div>
      </div>
      <div class="metric-item">
        <div class="metric-label">Disk</div>
        <div class="metric-value">{{ latestDisk }}%</div>
      </div>
    </div>

    <!-- Sparklines -->
    <div class="sparklines-container mb-2">
      <div class="sparkline-wrapper">
        <div class="sparkline-label">CPU Trend</div>
        <svg 
          v-if="cpuSparklineData.length > 0" 
          :viewBox="`0 0 ${width} ${height}`" 
          class="sparkline"
          preserveAspectRatio="none"
        >
          <path 
            :d="cpuSparklinePath" 
            fill="none" 
            stroke="#198754"
            stroke-width="2"
          />
        </svg>
        <div v-else class="sparkline-empty">No data</div>
      </div>
      <div class="sparkline-wrapper">
        <div class="sparkline-label">RAM Trend</div>
        <svg 
          v-if="ramSparklineData.length > 0" 
          :viewBox="`0 0 ${width} ${height}`" 
          class="sparkline"
          preserveAspectRatio="none"
        >
          <path 
            :d="ramSparklinePath" 
            fill="none" 
            stroke="#0d6efd"
            stroke-width="2"
          />
        </svg>
        <div v-else class="sparkline-empty">No data</div>
      </div>
    </div>

    <!-- Footer Info -->
    <div class="agent-footer">
      <small class="text-secondary">
        <span v-if="agent.public_ip">{{ agent.public_ip }} • </span>
        <span v-if="agent.connection_address" class="text-info">({{ agent.connection_address }}) • </span>
        Last seen: {{ formatTime(agent.last_seen) }}
      </small>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import axios from 'axios'

const props = defineProps({
  agent: {
    type: Object,
    required: true
  }
})

defineEmits(['select'])

// Sparkline dimensions
const width = 100
const height = 30

// Recent metrics for sparklines (last 10 data points)
const recentMetrics = ref([])

// Fetch recent metrics for sparklines
const fetchRecentMetrics = async () => {
  try {
    // Add cache-busting timestamp
    const timestamp = Date.now()
    const response = await axios.get(
      `/api/agents/${props.agent.agent_id}/metrics?limit=10&_t=${timestamp}`
    )
    if (response.data.metrics && response.data.metrics.length > 0) {
      // Reverse to get chronological order (oldest first)
      recentMetrics.value = response.data.metrics.reverse()
      console.log(`[AgentCard ${props.agent.hostname}] Updated metrics:`, {
        cpu: recentMetrics.value[recentMetrics.value.length - 1]?.cpu_percent,
        ram: recentMetrics.value[recentMetrics.value.length - 1]?.ram_percent,
        time: new Date().toLocaleTimeString()
      })
    }
  } catch (error) {
    console.error('Error fetching sparkline data:', error)
  }
}

// Latest values
const latestCpu = computed(() => {
  if (recentMetrics.value.length === 0) return 0
  return recentMetrics.value[recentMetrics.value.length - 1]?.cpu_percent.toFixed(1) || 0
})

const latestRam = computed(() => {
  if (recentMetrics.value.length === 0) return 0
  return recentMetrics.value[recentMetrics.value.length - 1]?.ram_percent.toFixed(1) || 0
})

const latestDisk = computed(() => {
  if (recentMetrics.value.length === 0) return 0
  return recentMetrics.value[recentMetrics.value.length - 1]?.disk_percent?.toFixed(1) || 0
})

// Sparkline data
const cpuSparklineData = computed(() => {
  return recentMetrics.value.map(m => m.cpu_percent || 0)
})

const ramSparklineData = computed(() => {
  return recentMetrics.value.map(m => m.ram_percent || 0)
})

// Generate SVG path for sparkline
const generateSparklinePath = (data) => {
  if (data.length === 0) return ''
  
  const max = Math.max(...data, 1) // Prevent division by zero
  const min = Math.min(...data, 0)
  const range = max - min || 1
  
  const points = data.map((value, index) => {
    const x = (index / (data.length - 1)) * width
    const y = height - ((value - min) / range) * height
    return `${x},${y}`
  })
  
  return `M ${points.join(' L ')}`
}

const cpuSparklinePath = computed(() => generateSparklinePath(cpuSparklineData.value))
const ramSparklinePath = computed(() => generateSparklinePath(ramSparklineData.value))

// Format time helper
const formatTime = (timestamp) => {
  const now = new Date()
  const then = new Date(timestamp)
  const diff = Math.floor((now - then) / 1000) // seconds
  
  if (diff < 60) return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

// Format uptime duration
const formatUptime = (seconds) => {
  if (!seconds) return '0s'
  
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  
  if (days > 0) return `${days}d ${hours}h`
  if (hours > 0) return `${hours}h ${minutes}m`
  return `${minutes}m`
}

// Calculate displayed uptime percentage with grace period
const displayedUptimePercentage = computed(() => {
  // If backend returned null (no heartbeat data), return null
  if (props.agent.uptime_percentage === null || props.agent.uptime_percentage === undefined) {
    // Check grace period for brand new agents
    if (props.agent.first_seen) {
      const firstSeen = new Date(props.agent.first_seen)
      const now = new Date()
      const ageSeconds = (now - firstSeen) / 1000
      
      // Grace period: agents less than 60 seconds old show 100%
      if (ageSeconds < 60) {
        return 100.0
      }
    }
    // Return null to indicate no data available
    return null
  }
  
  // Use backend-calculated percentage
  return props.agent.uptime_percentage
})

// Formatted uptime for display
const formattedUptime = computed(() => {
  const pct = displayedUptimePercentage.value
  if (pct === null) return 'N/A'
  return `${pct.toFixed(1)}%`
})

// Uptime badge color based on percentage
const uptimeBadgeClass = computed(() => {
  const pct = displayedUptimePercentage.value
  if (pct === null) return 'bg-secondary'
  if (pct >= 99) return 'bg-success'
  if (pct >= 95) return 'bg-info'
  if (pct >= 90) return 'bg-warning'
  return 'bg-danger'
})

// Availability tooltip showing the configured window
const availabilityTooltip = computed(() => {
  const windowLabels = {
    'daily': 'Last 24 hours',
    'weekly': 'Last 7 days',
    'monthly': 'Last 30 days',
    'quarterly': 'Last 90 days',
    'yearly': 'Last 365 days'
  }
  const window = props.agent.uptime_window || 'monthly'
  const windowLabel = windowLabels[window] || windowLabels['monthly']
  return `Availability (${windowLabel})`
})

// Store interval ID for cleanup
let metricsInterval = null

// Fetch sparkline data on mount
onMounted(() => {
  console.log(`[AgentCard ${props.agent.hostname}] Component mounted, starting refresh`)
  fetchRecentMetrics()
  // Refresh every 10 seconds
  metricsInterval = setInterval(fetchRecentMetrics, 10000)
})

// Watch for agent changes and refetch
watch(() => props.agent.last_seen, () => {
  fetchRecentMetrics()
})

// Clean up interval on unmount to prevent memory leaks
onUnmounted(() => {
  console.log(`[AgentCard ${props.agent.hostname}] Component unmounting, cleaning up`)
  if (metricsInterval) {
    clearInterval(metricsInterval)
  }
})
</script>

<style scoped>
.agent-card {
  background-color: rgba(88, 166, 255, 0.05);
  border: 1px solid var(--border-color);
  border-radius: var(--radius);
  padding: 1rem;
  cursor: pointer;
  transition: all 0.2s ease;
}

.agent-card:hover {
  border-color: var(--primary);
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.5rem;
  padding: 0.75rem;
  background-color: rgba(0, 0, 0, 0.2);
  border-radius: 4px;
}

.metric-item {
  text-align: center;
}

.metric-label {
  font-size: 0.7rem;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.metric-value {
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--primary);
  margin-top: 0.25rem;
}

.sparklines-container {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 0.75rem;
}

.sparkline-wrapper {
  background-color: rgba(0, 0, 0, 0.2);
  border-radius: 4px;
  padding: 0.5rem;
}

.sparkline-label {
  font-size: 0.65rem;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 0.25rem;
}

.sparkline {
  width: 100%;
  height: 30px;
  display: block;
}

.sparkline-empty {
  width: 100%;
  height: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.7rem;
  color: var(--text-secondary);
  opacity: 0.5;
}

.agent-footer {
  padding-top: 0.75rem;
  border-top: 1px solid var(--border-color);
}

.uptime-badge {
  font-size: 0.65rem;
  font-weight: 500;
  opacity: 0.9;
}
</style>
