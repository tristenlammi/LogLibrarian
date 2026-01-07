<template>
  <tr 
    class="agent-list-row"
    @click="$emit('select', agent.agent_id)"
  >
    <!-- Status -->
    <td>
      <div 
        class="status-dot" 
        :class="agent.status === 'online' ? 'bg-success' : 'bg-danger'"
        :title="agent.status"
      ></div>
    </td>

    <!-- Hostname -->
    <td class="hostname-cell">
      <div class="fw-semibold">{{ agent.display_name || agent.hostname }}</div>
      <small class="text-secondary" :title="agent.agent_id">
        {{ agent.display_name ? agent.hostname : agent.agent_id.substring(0, 12) + '...' }}
      </small>
    </td>

    <!-- Public IP -->
    <td>
      <div>
        <code v-if="agent.public_ip" class="text-primary">{{ agent.public_ip }}</code>
        <span v-else class="text-secondary">—</span>
      </div>
      <div v-if="agent.connection_address" class="small text-info">
        <span title="Current connection address">({{ agent.connection_address }})</span>
      </div>
    </td>

    <!-- CPU % with progress bar -->
    <td>
      <div class="metric-cell">
        <span class="metric-value" :class="getCpuClass(latestCpu)">
          {{ latestCpu }}%
        </span>
        <div class="progress-bar-mini">
          <div 
            class="progress-bar-fill" 
            :class="getCpuClass(latestCpu)"
            :style="{ width: `${Math.min(latestCpu, 100)}%` }"
          ></div>
        </div>
      </div>
    </td>

    <!-- RAM % with progress bar -->
    <td>
      <div class="metric-cell">
        <span class="metric-value" :class="getRamClass(latestRam)">
          {{ latestRam }}%
        </span>
        <div class="progress-bar-mini">
          <div 
            class="progress-bar-fill" 
            :class="getRamClass(latestRam)"
            :style="{ width: `${Math.min(latestRam, 100)}%` }"
          ></div>
        </div>
      </div>
    </td>

    <!-- Disk % -->
    <td>
      <span 
        class="badge" 
        :class="getDiskBadgeClass(latestDisk)"
      >
        {{ latestDisk }}%
      </span>
    </td>

    <!-- Availability -->
    <td>
      <small 
        class="text-secondary" 
        :title="availabilityTooltip"
      >
        {{ agent.uptime_percentage != null ? agent.uptime_percentage.toFixed(1) + '%' : 'N/A' }}
      </small>
    </td>

    <!-- Last Seen -->
    <td>
      <small class="text-secondary">{{ formatTime(agent.last_seen) }}</small>
    </td>
  </tr>
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

// Recent metrics for latest values
const recentMetrics = ref([])

// Fetch recent metrics
const fetchRecentMetrics = async () => {
  try {
    // Add cache-busting timestamp
    const timestamp = Date.now()
    const response = await axios.get(
      `/api/agents/${props.agent.agent_id}/metrics?limit=1&_t=${timestamp}`
    )
    if (response.data.metrics && response.data.metrics.length > 0) {
      recentMetrics.value = response.data.metrics
      console.log(`[AgentListRow ${props.agent.hostname}] Updated metrics:`, {
        cpu: response.data.metrics[0]?.cpu_percent,
        ram: response.data.metrics[0]?.ram_percent,
        time: new Date().toLocaleTimeString()
      })
    }
  } catch (error) {
    console.error('Error fetching metrics:', error)
  }
}

// Latest values
const latestCpu = computed(() => {
  if (recentMetrics.value.length === 0) return 0
  return recentMetrics.value[0]?.cpu_percent.toFixed(1) || 0
})

const latestRam = computed(() => {
  if (recentMetrics.value.length === 0) return 0
  return recentMetrics.value[0]?.ram_percent.toFixed(1) || 0
})

const latestDisk = computed(() => {
  if (recentMetrics.value.length === 0) return 0
  return recentMetrics.value[0]?.disk_percent?.toFixed(1) || 0
})

// Helper functions for styling
const getCpuClass = (percent) => {
  if (percent > 80) return 'text-danger'
  if (percent > 50) return 'text-warning'
  return 'text-success'
}

const getRamClass = (percent) => {
  if (percent > 85) return 'text-danger'
  if (percent > 70) return 'text-warning'
  return 'text-info'
}

const getDiskBadgeClass = (percent) => {
  if (percent > 90) return 'bg-danger'
  if (percent > 75) return 'bg-warning'
  return 'bg-secondary'
}

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

// Store interval ID for cleanup
let metricsInterval = null

// Fetch metrics on mount
onMounted(() => {
  console.log(`[AgentListRow ${props.agent.hostname}] Component mounted, starting refresh`)
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
  console.log(`[AgentListRow ${props.agent.hostname}] Component unmounting, cleaning up`)
  if (metricsInterval) {
    clearInterval(metricsInterval)
  }
})
</script>

<style scoped>
.agent-list-row {
  cursor: pointer;
  transition: background-color 0.2s ease;
}

.agent-list-row:hover {
  background-color: rgba(88, 166, 255, 0.1) !important;
}

.status-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
  margin: 0 auto;
}

.hostname-cell {
  min-width: 180px;
}

.metric-cell {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  min-width: 80px;
}

.metric-value {
  font-weight: 600;
  font-size: 0.9rem;
}

.progress-bar-mini {
  width: 100%;
  height: 4px;
  background-color: rgba(255, 255, 255, 0.1);
  border-radius: 2px;
  overflow: hidden;
}

.progress-bar-fill {
  height: 100%;
  transition: width 0.3s ease;
  border-radius: 2px;
}

.progress-bar-fill.text-success {
  background-color: var(--success);
}

.progress-bar-fill.text-info {
  background-color: var(--info);
}

.progress-bar-fill.text-warning {
  background-color: var(--warning);
}

.progress-bar-fill.text-danger {
  background-color: var(--danger);
}

code {
  background-color: rgba(88, 166, 255, 0.1);
  padding: 0.2rem 0.4rem;
  border-radius: 3px;
  font-size: 0.85em;
}
</style>
