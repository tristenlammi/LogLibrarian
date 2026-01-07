<template>
  <div class="recent-logs-container">
    <div class="card">
      <div class="card-header d-flex justify-content-between align-items-center">
        <h5 class="mb-0">Recent Logs</h5>
        <span class="badge bg-primary">{{ logs.length }} entries</span>
      </div>
      <div class="card-body p-0">
        <div class="logs-table-wrapper">
          <table class="table logs-table mb-0">
            <thead>
              <tr>
                <th style="width: 180px">Timestamp</th>
                <th style="width: 150px">Service</th>
                <th style="width: 100px">Level</th>
                <th>Message</th>
              </tr>
            </thead>
            <tbody>
              <TransitionGroup name="log-entry">
                <tr 
                  v-for="log in logs" 
                  :key="log.id"
                  class="log-row"
                  :class="logLevelClass(log.level)"
                >
                  <td class="timestamp">{{ formatTimestamp(log.timestamp) }}</td>
                  <td class="service">{{ log.service }}</td>
                  <td>
                    <span class="badge log-level-badge" :class="levelBadgeClass(log.level)">
                      {{ log.level }}
                    </span>
                  </td>
                  <td class="message">{{ truncateMessage(log.message) }}</td>
                </tr>
              </TransitionGroup>
              
              <!-- Empty State -->
              <tr v-if="logs.length === 0" class="empty-state">
                <td colspan="4" class="text-center py-4">
                  <div class="text-secondary">
                    <div class="mb-2" style="font-size: 2rem">📭</div>
                    <div>No logs yet. Waiting for data...</div>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'

const props = defineProps({
  maxLogs: {
    type: Number,
    default: 10
  }
})

const logs = ref([])

// Sample log data for demonstration
const sampleLogs = [
  { id: 1, timestamp: new Date(), service: 'nginx', level: 'INFO', message: 'Server started on port 80' },
  { id: 2, timestamp: new Date(Date.now() - 60000), service: 'api', level: 'ERROR', message: 'Connection to database failed: timeout after 30s' },
  { id: 3, timestamp: new Date(Date.now() - 120000), service: 'worker', level: 'WARN', message: 'High memory usage detected: 85%' },
  { id: 4, timestamp: new Date(Date.now() - 180000), service: 'auth', level: 'INFO', message: 'User authentication successful' },
]

// Load initial logs
onMounted(() => {
  logs.value = [...sampleLogs]
})

// Format timestamp
const formatTimestamp = (timestamp) => {
  const date = new Date(timestamp)
  const now = new Date()
  const diff = Math.floor((now - date) / 1000) // seconds

  if (diff < 60) return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  
  return date.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}

// Truncate long messages
const truncateMessage = (message, maxLength = 80) => {
  if (message.length <= maxLength) return message
  return message.substring(0, maxLength) + '...'
}

// Get CSS class based on log level
const logLevelClass = (level) => {
  const classes = {
    ERROR: 'log-error',
    WARN: 'log-warn',
    INFO: 'log-info'
  }
  return classes[level] || ''
}

// Get badge class based on level
const levelBadgeClass = (level) => {
  const classes = {
    ERROR: 'bg-danger',
    WARN: 'bg-warning',
    INFO: 'bg-success'
  }
  return classes[level] || 'bg-secondary'
}

// Add new log (for real-time updates)
const addLog = (log) => {
  logs.value.unshift(log)
  if (logs.value.length > props.maxLogs) {
    logs.value.pop()
  }
}

// Expose method for parent components
defineExpose({ addLog })
</script>

<style scoped>
.recent-logs-container {
  width: 100%;
}

.logs-table-wrapper {
  overflow-x: auto;
}

.logs-table {
  width: 100%;
  color: var(--text-primary);
}

.logs-table thead {
  background-color: rgba(88, 166, 255, 0.1);
  border-bottom: 2px solid var(--border-color);
}

.logs-table thead th {
  padding: 0.75rem 1rem;
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--text-secondary);
  border: none;
}

.logs-table tbody tr {
  border-bottom: 1px solid var(--border-color);
  transition: background-color 0.2s ease;
}

.logs-table tbody tr:hover {
  background-color: rgba(88, 166, 255, 0.05);
}

.logs-table tbody td {
  padding: 0.875rem 1rem;
  vertical-align: middle;
  border: none;
}

.timestamp {
  color: var(--text-secondary);
  font-size: 0.875rem;
  font-family: 'Courier New', monospace;
}

.service {
  font-weight: 600;
  color: var(--text-primary);
}

.message {
  color: var(--text-primary);
  font-size: 0.9rem;
}

/* Log level indicators */
.log-row.log-error {
  border-left: 3px solid var(--danger);
}

.log-row.log-warn {
  border-left: 3px solid var(--warning);
}

.log-row.log-info {
  border-left: 3px solid var(--success);
}

.log-level-badge {
  font-size: 0.7rem;
  padding: 0.25rem 0.5rem;
  font-weight: 600;
}

/* TransitionGroup animations */
.log-entry-enter-active {
  transition: all 0.5s ease;
}

.log-entry-leave-active {
  transition: all 0.3s ease;
}

.log-entry-enter-from {
  opacity: 0;
  transform: translateY(-20px);
}

.log-entry-leave-to {
  opacity: 0;
  transform: translateX(20px);
}

.log-entry-move {
  transition: transform 0.5s ease;
}

/* Empty state */
.empty-state td {
  background-color: transparent;
}
</style>
