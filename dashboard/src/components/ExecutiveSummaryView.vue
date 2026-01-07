<template>
  <div class="executive-summary-compact">
    <!-- Compact Header -->
    <div class="summary-header">
      <div class="header-left">
        <span class="header-icon">📊</span>
        <div>
          <h1>Executive Summary</h1>
          <span class="header-period">{{ selectedDays }}-Day Report • Generated {{ formatShortDate(report?.period?.generated_at) }}</span>
        </div>
      </div>
      <div class="header-controls">
        <select v-model="selectedDays" @change="fetchReport" class="period-select">
          <option :value="7">7 Days</option>
          <option :value="30">30 Days</option>
          <option :value="90">90 Days</option>
        </select>
        <button class="icon-btn" @click="printReport" title="Print">🖨️</button>
        <router-link to="/librarian" class="icon-btn" title="Back">✕</router-link>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="loading-compact">
      <div class="spinner"></div>
      <span>Loading...</span>
    </div>

    <!-- Main Content - Single Page Layout -->
    <div v-else-if="report" class="summary-grid">
      <!-- Top Row: Big Numbers -->
      <div class="top-metrics">
        <!-- Global Uptime - Hero -->
        <div class="metric-hero" :class="uptimeClass">
          <div class="hero-value">{{ formatUptime(report.global_uptime_percent) }}</div>
          <div class="hero-label">Global Availability</div>
        </div>
        
        <!-- SLA Status -->
        <div class="metric-badge" :class="report.sla_status.toLowerCase()">
          <div class="badge-icon">{{ report.sla_status === 'PASSED' ? '✓' : '✕' }}</div>
          <div class="badge-info">
            <span class="badge-title">SLA {{ report.sla_status === 'PASSED' ? 'Met' : 'Missed' }}</span>
            <span class="badge-sub">Target: {{ report.sla_target }}%</span>
          </div>
        </div>

        <!-- Incidents -->
        <div class="metric-badge" :class="report.perfect_health ? 'healthy' : 'warning'">
          <div class="badge-icon">{{ report.perfect_health ? '🏆' : '⚠️' }}</div>
          <div class="badge-info">
            <span class="badge-title">{{ report.incident_count }} Interruption{{ report.incident_count !== 1 ? 's' : '' }}</span>
            <span class="badge-sub">{{ report.perfect_health ? 'Perfect Record' : 'Review Needed' }}</span>
          </div>
        </div>

        <!-- Quick Stats -->
        <div class="quick-stats">
          <div class="stat"><span class="stat-value">{{ report.monitors_count }}</span><span class="stat-label">Services</span></div>
          <div class="stat"><span class="stat-value">{{ formatShortCount(report.theoretical_checks || report.total_checks) }}</span><span class="stat-label">Checks</span></div>
          <div class="stat"><span class="stat-value">{{ formatShortCount(report.logs_analyzed) }}</span><span class="stat-label">Logs Analyzed</span></div>
        </div>
      </div>

      <!-- Timeline Bar -->
      <div class="timeline-section">
        <div class="section-mini-header">
          <span>Availability Timeline</span>
          <div class="timeline-legend-inline">
            <span class="legend-dot up"></span>Up
            <span class="legend-dot degraded"></span>Degraded
            <span class="legend-dot down"></span>Down
          </div>
        </div>
        <div class="uptime-bar">
          <div 
            v-for="(seg, i) in report.uptime_segments" 
            :key="i"
            class="bar-segment"
            :class="seg.status"
            :title="`${seg.date}: ${seg.uptime_percent}%`"
          ></div>
        </div>
      </div>

      <!-- Two Column Layout -->
      <div class="two-columns">
        <!-- Services Table -->
        <div class="column-card">
          <div class="column-header">Service Performance</div>
          <div class="services-list">
            <div class="service-row header-row">
              <span>Service</span>
              <span>Uptime</span>
              <span>Trend</span>
              <span>Response</span>
              <span>Status</span>
            </div>
            <div 
              v-for="m in report.monitors_summary.slice(0, 8)" 
              :key="m.name"
              class="service-row"
            >
              <span class="service-name" :title="m.name">{{ truncate(m.name, 18) }}</span>
              <span class="service-uptime" :class="getUptimeClass(m.uptime_percent)">{{ m.uptime_percent }}%</span>
              <span class="service-sparkline">
                <svg v-if="m.latency_history && m.latency_history.length > 0" 
                     class="sparkline" 
                     :viewBox="`0 0 ${m.latency_history.length * 3} 20`"
                     preserveAspectRatio="none">
                  <polyline 
                    :points="getSparklinePoints(m.latency_history)"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.5"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  />
                </svg>
                <span v-else class="no-trend">—</span>
              </span>
              <span class="service-response">{{ formatResponseTime(m.avg_response_ms) }}</span>
              <span class="service-status" :class="m.health.toLowerCase()">
                {{ m.health === 'Healthy' ? '●' : '○' }}
              </span>
            </div>
            <div v-if="report.monitors_summary.length > 8" class="more-services">
              +{{ report.monitors_summary.length - 8 }} more services
            </div>
          </div>
        </div>

        <!-- Recommendations OR Log Analysis -->
        <div class="column-card">
          <!-- Show Recommendations if there are warnings/issues -->
          <template v-if="hasActiveRecommendations">
            <div class="column-header">Recommendations</div>
            <div class="recommendations-list">
              <div 
                v-for="(rec, i) in report.strategic_recommendations.slice(0, 4)" 
                :key="i"
                class="rec-item"
                :class="rec.type"
              >
                <span class="rec-icon">{{ rec.type === 'success' ? '✓' : rec.type === 'warning' ? '⚠' : 'ℹ' }}</span>
                <span class="rec-text">{{ rec.message }}</span>
              </div>
            </div>
          </template>
          
          <!-- Show Log Analysis when healthy -->
          <template v-else>
            <div class="column-header">Log Analysis</div>
            <div class="log-analysis-panel">
              <!-- Health Status -->
              <div class="log-stat highlight">
                <span class="log-stat-icon">✓</span>
                <span class="log-stat-text">All systems operating normally</span>
              </div>
              
              <!-- Total Volume -->
              <div class="log-stat">
                <span class="log-stat-icon">📊</span>
                <div class="log-stat-content">
                  <span class="log-stat-value">{{ report.log_analysis?.total_volume_display || '0 KB' }}</span>
                  <span class="log-stat-label">Data Processed</span>
                </div>
              </div>
              
              <!-- Top Sources -->
              <div v-if="report.log_analysis?.top_sources?.length > 0" class="log-sources">
                <div class="log-sources-title">Top Sources</div>
                <div 
                  v-for="(source, i) in report.log_analysis.top_sources.slice(0, 3)" 
                  :key="i"
                  class="log-source-item"
                >
                  <span class="source-rank">{{ i + 1 }}.</span>
                  <span class="source-name">{{ truncate(source.name, 15) }}</span>
                  <span class="source-count">{{ formatShortCount(source.count) }}</span>
                </div>
              </div>
              
              <!-- Threat Summary -->
              <div class="log-stat" :class="{ 'threat-clear': report.log_analysis?.critical_events === 0 }">
                <span class="log-stat-icon">🛡️</span>
                <div class="log-stat-content">
                  <span class="log-stat-value">{{ report.log_analysis?.critical_events || 0 }}</span>
                  <span class="log-stat-label">Critical Security Events</span>
                </div>
              </div>
            </div>
          </template>
        </div>
      </div>

      <!-- Footer -->
      <div class="summary-footer">
        <span>{{ report.period.start?.split('T')[0] }} to {{ report.period.end?.split('T')[0] }}</span>
        <span class="footer-brand">📚 LogLibrarian</span>
      </div>
    </div>

    <!-- No Data -->
    <div v-else class="no-data">
      <span>📊</span>
      <p>No monitoring data available</p>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'

const API_BASE = import.meta.env.VITE_API_URL || ''

const loading = ref(true)
const report = ref(null)
const selectedDays = ref(30)

const uptimeClass = computed(() => {
  if (!report.value) return ''
  const u = report.value.global_uptime_percent
  if (u >= 99.9) return 'excellent'
  if (u >= 99) return 'good'
  if (u >= 95) return 'warning'
  return 'critical'
})

// Check if there are active recommendations (warnings/errors, not just success)
const hasActiveRecommendations = computed(() => {
  if (!report.value?.strategic_recommendations) return false
  return report.value.strategic_recommendations.some(r => r.type === 'warning' || r.type === 'info')
})

const fetchReport = async () => {
  loading.value = true
  try {
    const res = await fetch(`${API_BASE}/api/reports/executive-summary?days=${selectedDays.value}`)
    const data = await res.json()
    if (data.success) report.value = data.data
  } catch (e) {
    console.error('Error:', e)
  } finally {
    loading.value = false
  }
}

const formatUptime = (v) => v == null ? 'N/A' : `${v.toFixed(2)}%`
const formatShortCount = (n) => {
  if (n == null) return '0'
  if (n >= 1e6) return `${(n/1e6).toFixed(1)}m`
  if (n >= 1e3) return `${(n/1e3).toFixed(1)}k`
  return n.toLocaleString()
}

// Format response time - show "<1ms" instead of "0ms"
const formatResponseTime = (ms) => {
  if (ms == null || ms === 0) return '<1ms'
  if (ms < 1) return '<1ms'
  return `${Math.round(ms)}ms`
}

// Generate SVG polyline points for sparkline
const getSparklinePoints = (history) => {
  if (!history || history.length === 0) return ''
  
  // Filter out nulls and get valid values
  const validValues = history.filter(v => v !== null && v !== undefined)
  if (validValues.length === 0) return ''
  
  const max = Math.max(...validValues, 1)
  const min = Math.min(...validValues, 0)
  const range = max - min || 1
  
  const width = history.length * 3
  const height = 20
  const padding = 2
  
  return history.map((val, i) => {
    const x = (i / (history.length - 1 || 1)) * (width - padding * 2) + padding
    // If null, use the average or middle point
    const y = val !== null 
      ? height - padding - ((val - min) / range) * (height - padding * 2)
      : height / 2
    return `${x},${y}`
  }).join(' ')
}

const formatShortDate = (d) => d ? new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : ''
const truncate = (s, n) => s?.length > n ? s.slice(0, n) + '…' : s
const getUptimeClass = (u) => u >= 99.9 ? 'excellent' : u >= 99 ? 'good' : u >= 95 ? 'warning' : 'critical'
const printReport = () => window.print()

onMounted(fetchReport)
</script>

<style scoped>
.executive-summary-compact {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--bg-color);
  overflow: hidden;
}

/* Header */
.summary-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.75rem 1.5rem;
  background: var(--card-bg);
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.header-icon {
  font-size: 1.5rem;
}

.header-left h1 {
  margin: 0;
  font-size: 1.25rem;
  font-weight: 600;
}

.header-period {
  font-size: 0.75rem;
  color: var(--text-secondary);
}

.header-controls {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.period-select {
  padding: 0.35rem 0.75rem;
  border-radius: 6px;
  background: var(--bg-color);
  border: 1px solid var(--border-color);
  color: var(--text-color);
  font-size: 0.8rem;
}

.icon-btn {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-color);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  cursor: pointer;
  text-decoration: none;
  font-size: 1rem;
  transition: all 0.15s;
}

.icon-btn:hover {
  background: var(--border-color);
}

/* Loading */
.loading-compact {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  color: var(--text-secondary);
}

.spinner {
  width: 24px;
  height: 24px;
  border: 2px solid var(--border-color);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin { to { transform: rotate(360deg); } }

/* Main Grid */
.summary-grid {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 1rem 1.5rem;
  gap: 0.75rem;
  overflow: hidden;
}

/* Top Metrics Row */
.top-metrics {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr 1fr;
  gap: 0.75rem;
}

.metric-hero {
  background: linear-gradient(135deg, var(--card-bg) 0%, rgba(0,0,0,0.3) 100%);
  border: 2px solid var(--border-color);
  border-radius: 12px;
  padding: 1rem;
  text-align: center;
}

.metric-hero.excellent { border-color: #10b981; }
.metric-hero.good { border-color: #3b82f6; }
.metric-hero.warning { border-color: #f59e0b; }
.metric-hero.critical { border-color: #ef4444; }

.hero-value {
  font-size: 2rem;
  font-weight: 800;
  background: linear-gradient(135deg, #10b981, #3b82f6);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.metric-hero.excellent .hero-value { background: linear-gradient(135deg, #10b981, #34d399); -webkit-background-clip: text; background-clip: text; }
.metric-hero.warning .hero-value { background: linear-gradient(135deg, #f59e0b, #fbbf24); -webkit-background-clip: text; background-clip: text; }
.metric-hero.critical .hero-value { background: linear-gradient(135deg, #ef4444, #f87171); -webkit-background-clip: text; background-clip: text; }

.hero-label {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--text-secondary);
  margin-top: 0.25rem;
}

.metric-badge {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 0.75rem 1rem;
}

.metric-badge.passed { border-color: #10b981; background: linear-gradient(135deg, rgba(16,185,129,0.1), transparent); }
.metric-badge.failed { border-color: #ef4444; background: linear-gradient(135deg, rgba(239,68,68,0.1), transparent); }
.metric-badge.healthy { border-color: #10b981; }
.metric-badge.warning { border-color: #f59e0b; }

.badge-icon {
  font-size: 1.5rem;
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: rgba(0,0,0,0.2);
}

.metric-badge.passed .badge-icon { color: #10b981; }
.metric-badge.failed .badge-icon { color: #ef4444; }

.badge-info {
  display: flex;
  flex-direction: column;
}

.badge-title {
  font-weight: 600;
  font-size: 0.9rem;
}

.badge-sub {
  font-size: 0.7rem;
  color: var(--text-secondary);
}

.quick-stats {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 0.25rem;
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 0.5rem 1rem;
}

.stat {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.stat-value {
  font-weight: 700;
  font-size: 0.9rem;
}

.stat-label {
  font-size: 0.7rem;
  color: var(--text-secondary);
}

/* Timeline */
.timeline-section {
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 0.5rem 1rem;
}

.section-mini-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.75rem;
  color: var(--text-secondary);
  margin-bottom: 0.5rem;
}

.timeline-legend-inline {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.65rem;
}

.legend-dot {
  width: 8px;
  height: 8px;
  border-radius: 2px;
  margin-left: 0.5rem;
}

.legend-dot.up { background: #10b981; }
.legend-dot.degraded { background: #f59e0b; }
.legend-dot.down { background: #ef4444; }

.uptime-bar {
  display: flex;
  gap: 1px;
  height: 20px;
  background: var(--bg-color);
  border-radius: 4px;
  overflow: hidden;
}

.bar-segment {
  flex: 1;
  transition: transform 0.15s;
}

.bar-segment:hover { transform: scaleY(1.2); }
.bar-segment.up { background: #10b981; }
.bar-segment.degraded { background: #f59e0b; }
.bar-segment.down { background: #ef4444; }
.bar-segment.no_data { background: var(--border-color); }

/* Two Columns */
.two-columns {
  flex: 1;
  display: grid;
  grid-template-columns: 1.5fr 1fr;
  gap: 0.75rem;
  min-height: 0;
}

.column-card {
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.column-header {
  padding: 0.5rem 0.75rem;
  font-size: 0.8rem;
  font-weight: 600;
  border-bottom: 1px solid var(--border-color);
  background: rgba(0,0,0,0.1);
}

.services-list {
  flex: 1;
  overflow-y: auto;
  font-size: 0.75rem;
}

.service-row {
  display: grid;
  grid-template-columns: 1.8fr 0.8fr 1fr 0.8fr 0.4fr;
  gap: 0.4rem;
  padding: 0.4rem 0.75rem;
  border-bottom: 1px solid var(--border-color);
  align-items: center;
}

.service-row.header-row {
  background: rgba(0,0,0,0.1);
  font-weight: 500;
  color: var(--text-secondary);
  font-size: 0.65rem;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.service-name {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.service-uptime {
  font-weight: 600;
}

.service-uptime.excellent { color: #10b981; }
.service-uptime.good { color: #3b82f6; }
.service-uptime.warning { color: #f59e0b; }
.service-uptime.critical { color: #ef4444; }

/* Sparkline styles */
.service-sparkline {
  display: flex;
  align-items: center;
  justify-content: center;
}

.sparkline {
  width: 100%;
  height: 16px;
  color: #3b82f6;
}

.no-trend {
  color: var(--text-secondary);
  font-size: 0.7rem;
}

.service-response {
  color: var(--text-secondary);
  font-size: 0.7rem;
}

.service-status {
  text-align: center;
}

.service-status.healthy { color: #10b981; }
.service-status.needs-attention, .service-status.pending { color: #f59e0b; }

.more-services {
  padding: 0.5rem;
  text-align: center;
  color: var(--text-secondary);
  font-size: 0.7rem;
  background: rgba(0,0,0,0.05);
}

.recommendations-list {
  flex: 1;
  padding: 0.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  overflow-y: auto;
}

.rec-item {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  padding: 0.5rem;
  border-radius: 6px;
  background: var(--bg-color);
  font-size: 0.75rem;
}

.rec-item.success { border-left: 3px solid #10b981; }
.rec-item.warning { border-left: 3px solid #f59e0b; }
.rec-item.info { border-left: 3px solid #3b82f6; }

.rec-icon {
  flex-shrink: 0;
}

.rec-text {
  line-height: 1.3;
}

.no-recs {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem;
  background: rgba(16,185,129,0.1);
  border-radius: 6px;
  color: #10b981;
  font-size: 0.8rem;
}

/* Log Analysis Panel */
.log-analysis-panel {
  flex: 1;
  padding: 0.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  overflow-y: auto;
}

.log-stat {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem;
  border-radius: 6px;
  background: var(--bg-color);
  font-size: 0.75rem;
}

.log-stat.highlight {
  background: rgba(16,185,129,0.1);
  border-left: 3px solid #10b981;
  color: #10b981;
}

.log-stat.threat-clear {
  border-left: 3px solid #10b981;
}

.log-stat-icon {
  flex-shrink: 0;
  font-size: 1rem;
}

.log-stat-content {
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
}

.log-stat-text {
  font-weight: 500;
}

.log-stat-value {
  font-weight: 700;
  font-size: 0.9rem;
}

.log-stat-label {
  font-size: 0.65rem;
  color: var(--text-secondary);
}

.log-sources {
  padding: 0.5rem;
  background: var(--bg-color);
  border-radius: 6px;
}

.log-sources-title {
  font-size: 0.65rem;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 0.35rem;
}

.log-source-item {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.75rem;
  padding: 0.2rem 0;
}

.source-rank {
  color: var(--text-secondary);
  font-size: 0.65rem;
  width: 1rem;
}

.source-name {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.source-count {
  font-weight: 600;
  color: var(--text-secondary);
  font-size: 0.7rem;
}

/* Footer */
.summary-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.5rem 0;
  font-size: 0.7rem;
  color: var(--text-secondary);
  border-top: 1px solid var(--border-color);
  flex-shrink: 0;
}

.footer-brand {
  font-weight: 500;
}

/* No Data */
.no-data {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--text-secondary);
}

.no-data span {
  font-size: 3rem;
  margin-bottom: 0.5rem;
}

/* Print */
@media print {
  .executive-summary-compact {
    height: auto;
  }
  .header-controls, .icon-btn {
    display: none;
  }
}

/* Responsive */
@media (max-width: 1200px) {
  .top-metrics {
    grid-template-columns: 1fr 1fr;
  }
  .two-columns {
    grid-template-columns: 1fr;
  }
}
</style>
