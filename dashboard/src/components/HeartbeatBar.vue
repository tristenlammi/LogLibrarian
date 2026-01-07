<template>
  <div class="heartbeat-bar-container">
    <div class="heartbeat-pills">
      <div 
        v-for="(pill, index) in displayPills" 
        :key="index"
        class="heartbeat-pill"
        :class="pill.status"
        :style="{ animationDelay: `${index * 15}ms` }"
        @mouseenter="showTooltip($event, pill, index)"
        @mouseleave="hideTooltip"
      >
        <div class="pill-inner"></div>
      </div>
    </div>
    
    <!-- Custom Tooltip -->
    <Teleport to="body">
      <div 
        v-if="tooltip.visible" 
        class="heartbeat-tooltip"
        :style="{ left: tooltip.x + 'px', top: tooltip.y + 'px' }"
      >
        <div class="tooltip-time">{{ tooltip.time }}</div>
        <div class="tooltip-status" :class="tooltip.status">
          {{ tooltip.statusText }}
        </div>
        <div class="tooltip-latency" v-if="tooltip.latency !== null">
          {{ tooltip.latency }}ms
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { formatDateTime } from '../utils/timezone.js'

const props = defineProps({
  checks: {
    type: Array,
    default: () => []
  },
  maxPills: {
    type: Number,
    default: 60
  }
})

// Tooltip state
const tooltip = ref({
  visible: false,
  x: 0,
  y: 0,
  time: '',
  status: 'pending',
  statusText: '',
  latency: null
})

// Computed pills with padding for missing entries
const displayPills = computed(() => {
  const pills = []
  const checks = props.checks || []
  
  // Reverse to show oldest on left, newest on right
  const reversedChecks = [...checks].slice(0, props.maxPills).reverse()
  
  // Pad with pending pills if we don't have enough
  const pendingCount = Math.max(0, props.maxPills - reversedChecks.length)
  
  for (let i = 0; i < pendingCount; i++) {
    pills.push({
      status: 'pending',
      time: null,
      latency: null,
      statusText: 'No data'
    })
  }
  
  // Add actual check data
  for (const check of reversedChecks) {
    pills.push({
      status: check.status === 1 ? 'up' : 'down',
      time: check.created_at,
      latency: check.latency_ms,
      statusText: check.status === 1 ? 'Up' : 'Down',
      message: check.message
    })
  }
  
  return pills
})

// Format time for tooltip
const formatTooltipTime = (timestamp) => {
  if (!timestamp) return 'No data yet'
  return formatDateTime(timestamp, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
}

// Show tooltip
const showTooltip = (event, pill, index) => {
  const rect = event.target.getBoundingClientRect()
  tooltip.value = {
    visible: true,
    x: rect.left + rect.width / 2,
    y: rect.top - 10,
    time: formatTooltipTime(pill.time),
    status: pill.status,
    statusText: pill.statusText,
    latency: pill.latency
  }
}

// Hide tooltip
const hideTooltip = () => {
  tooltip.value.visible = false
}
</script>

<style scoped>
.heartbeat-bar-container {
  width: 100%;
  padding: 0.5rem 0;
}

.heartbeat-pills {
  display: flex;
  gap: 2px;
  height: 32px;
  align-items: stretch;
}

.heartbeat-pill {
  flex: 1;
  min-width: 3px;
  max-width: 10px;
  border-radius: 3px;
  cursor: pointer;
  transition: transform 0.15s ease, opacity 0.15s ease;
  animation: pillFadeIn 0.3s ease forwards;
  opacity: 0;
  overflow: hidden;
}

.heartbeat-pill:hover {
  transform: scaleY(1.15);
  z-index: 1;
}

.pill-inner {
  width: 100%;
  height: 100%;
  border-radius: 3px;
}

/* Status Colors */
.heartbeat-pill.up .pill-inner {
  background: linear-gradient(180deg, #4ade80 0%, #22c55e 100%);
  box-shadow: 0 0 6px rgba(74, 222, 128, 0.4);
}

.heartbeat-pill.down .pill-inner {
  background: linear-gradient(180deg, #f87171 0%, #ef4444 100%);
  box-shadow: 0 0 6px rgba(248, 113, 113, 0.4);
}

.heartbeat-pill.pending .pill-inner {
  background: linear-gradient(180deg, #6b7280 0%, #4b5563 100%);
  opacity: 0.4;
}

/* Fade-in animation */
@keyframes pillFadeIn {
  from {
    opacity: 0;
    transform: scaleY(0.5);
  }
  to {
    opacity: 1;
    transform: scaleY(1);
  }
}

/* Tooltip styles - positioned via Teleport */
.heartbeat-tooltip {
  position: fixed;
  transform: translateX(-50%) translateY(-100%);
  background: #1f2937;
  border: 1px solid #374151;
  border-radius: 8px;
  padding: 0.5rem 0.75rem;
  font-size: 0.75rem;
  z-index: 9999;
  pointer-events: none;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
  white-space: nowrap;
  text-align: center;
}

.heartbeat-tooltip::after {
  content: '';
  position: absolute;
  top: 100%;
  left: 50%;
  transform: translateX(-50%);
  border: 6px solid transparent;
  border-top-color: #374151;
}

.tooltip-time {
  color: #9ca3af;
  margin-bottom: 0.25rem;
}

.tooltip-status {
  font-weight: 600;
  margin-bottom: 0.125rem;
}

.tooltip-status.up {
  color: #4ade80;
}

.tooltip-status.down {
  color: #f87171;
}

.tooltip-status.pending {
  color: #6b7280;
}

.tooltip-latency {
  color: #60a5fa;
  font-weight: 500;
}
</style>
