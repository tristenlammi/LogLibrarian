<template>
  <div class="status-card" :class="{ online: status === 'online' }">
    <div class="card-content">
      <!-- Status Header -->
      <div class="d-flex align-items-center justify-content-between mb-3">
        <h6 class="mb-0 server-name">{{ serverName }}</h6>
        <span class="badge" :class="statusClass">
          {{ statusText }}
        </span>
      </div>

      <!-- Ping Info -->
      <div class="ping-info mb-3">
        <small class="text-secondary">Response Time</small>
        <div class="d-flex align-items-baseline">
          <span class="ping-value">{{ ping }}</span>
          <small class="text-secondary ms-1">ms</small>
        </div>
      </div>

      <!-- Sparkline (Dummy CSS bars) -->
      <div class="sparkline">
        <div 
          v-for="(bar, index) in sparklineData" 
          :key="index"
          class="sparkline-bar"
          :style="{ height: bar + '%' }"
        ></div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  serverName: {
    type: String,
    required: true
  },
  status: {
    type: String,
    required: true,
    validator: (value) => ['online', 'offline'].includes(value)
  },
  ping: {
    type: Number,
    required: true
  }
})

const statusClass = computed(() => {
  return props.status === 'online' ? 'bg-success' : 'bg-danger'
})

const statusText = computed(() => {
  return props.status === 'online' ? 'Online' : 'Offline'
})

// Generate random sparkline data for visual effect
const sparklineData = ref(
  Array.from({ length: 20 }, () => Math.random() * 60 + 40)
)
</script>

<style scoped>
.status-card {
  background-color: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: var(--radius);
  padding: 1.25rem;
  transition: all 0.3s ease;
  cursor: pointer;
  position: relative;
  overflow: hidden;
}

.status-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  height: 100%;
  width: 3px;
  background-color: var(--danger);
  transition: background-color 0.3s ease;
}

.status-card.online::before {
  background-color: var(--success);
}

.status-card:hover {
  border-color: var(--primary);
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
}

.server-name {
  font-weight: 600;
  color: var(--text-primary);
  font-size: 1rem;
}

.ping-info {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.ping-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--primary);
}

/* Sparkline Visualization */
.sparkline {
  display: flex;
  align-items: flex-end;
  gap: 2px;
  height: 40px;
  margin-top: 0.5rem;
}

.sparkline-bar {
  flex: 1;
  background: linear-gradient(to top, var(--primary), rgba(88, 166, 255, 0.5));
  border-radius: 2px;
  transition: all 0.3s ease;
  min-height: 20%;
}

.status-card.online .sparkline-bar {
  background: linear-gradient(to top, var(--success), rgba(63, 185, 80, 0.5));
}

.sparkline-bar:hover {
  opacity: 0.8;
}
</style>
