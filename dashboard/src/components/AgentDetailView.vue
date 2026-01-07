<template>
  <div class="agent-detail">
    <!-- Header -->
    <div class="detail-header">
      <button @click="$emit('close')" class="back-btn">
        ← Back to Agents
      </button>
      <div class="header-info">
        <h2>{{ agent.hostname }}</h2>
        <span :class="['status-badge', agent.status]">{{ agent.status }}</span>
      </div>
      <div class="header-meta">
        <span v-if="agent.public_ip">{{ agent.public_ip }}</span>
        <span v-if="agent.connection_address" class="text-info ms-2">({{ agent.connection_address }})</span>
        <span>Last seen: {{ formatTime(agent.last_seen) }}</span>
      </div>
    </div>

    <!-- Row 1: Vitals (CPU, RAM, Ping) -->
    <div class="metrics-row vitals-row">
      <div class="chart-card">
        <h3>CPU Usage</h3>
        <canvas ref="cpuChart"></canvas>
        <div class="current-value">{{ currentMetrics.cpu_percent?.toFixed(1) }}%</div>
      </div>
      <div class="chart-card">
        <h3>RAM Usage</h3>
        <canvas ref="ramChart"></canvas>
        <div class="current-value">{{ currentMetrics.ram_percent?.toFixed(1) }}%</div>
      </div>
      <div class="chart-card">
        <h3>Ping</h3>
        <canvas ref="pingChart"></canvas>
        <div class="current-value">{{ currentMetrics.ping?.toFixed(1) }} ms</div>
      </div>
    </div>

    <!-- Row 2: Network & Disk I/O -->
    <div class="metrics-row io-row">
      <div class="chart-card chart-wide">
        <h3>Network Traffic</h3>
        <canvas ref="networkChart"></canvas>
        <div class="legend">
          <span class="legend-item">
            <span class="legend-color" style="background: #10b981"></span>
            Upload: {{ formatBytes(currentMetrics.net_up) }}/s
          </span>
          <span class="legend-item">
            <span class="legend-color" style="background: #3b82f6"></span>
            Download: {{ formatBytes(currentMetrics.net_down) }}/s
          </span>
        </div>
      </div>
      <div class="chart-card chart-wide">
        <h3>Disk I/O</h3>
        <canvas ref="diskIoChart"></canvas>
        <div class="legend">
          <span class="legend-item">
            <span class="legend-color" style="background: #f97316"></span>
            Read: {{ formatBytes(currentMetrics.disk_read) }}/s
          </span>
          <span class="legend-item">
            <span class="legend-color" style="background: #ef4444"></span>
            Write: {{ formatBytes(currentMetrics.disk_write) }}/s
          </span>
        </div>
      </div>
    </div>

    <!-- Row 3: Storage -->
    <div class="storage-section">
      <h3>Storage</h3>
      <div v-if="disks.length > 0" class="disks-list">
        <div v-for="disk in disks" :key="disk.mount" class="disk-item">
          <div class="disk-header">
            <span class="disk-mount">{{ disk.mount }}</span>
            <span class="disk-device">{{ disk.device }}</span>
            <span class="disk-usage">{{ formatBytes(disk.used) }} / {{ formatBytes(disk.total) }}</span>
            <span class="disk-percent">{{ disk.percent.toFixed(1) }}%</span>
          </div>
          <div class="disk-bar">
            <div 
              class="disk-bar-fill" 
              :style="{ width: disk.percent + '%', backgroundColor: getDiskColor(disk.percent) }"
            ></div>
          </div>
          <div class="disk-meta">
            <span>Type: {{ disk.fstype }}</span>
            <span>Free: {{ formatBytes(disk.free) }}</span>
          </div>
        </div>
      </div>
      <div v-else class="no-data">
        <p>No storage data available</p>
      </div>
    </div>
  </div>
</template>

<script>
import { Chart, registerables } from 'chart.js';
Chart.register(...registerables);

export default {
  name: 'AgentDetailView',
  props: {
    agent: {
      type: Object,
      required: true
    }
  },
  data() {
    return {
      metrics: [],
      currentMetrics: {},
      disks: [],
      charts: {},
      refreshInterval: null
    };
  },
  mounted() {
    this.fetchMetrics();
    this.refreshInterval = setInterval(() => {
      this.fetchMetrics();
    }, 10000); // Refresh every 10 seconds
  },
  beforeUnmount() {
    if (this.refreshInterval) {
      clearInterval(this.refreshInterval);
    }
    // Destroy all charts
    Object.values(this.charts).forEach(chart => chart.destroy());
  },
  methods: {
    async fetchMetrics() {
      try {
        const response = await fetch(`/api/agents/${this.agent.agent_id}/metrics?limit=60`);
        const data = await response.json();
        
        this.metrics = data.metrics || [];
        
        if (this.metrics.length > 0) {
          this.currentMetrics = this.metrics[0];
          
          // Parse disk_json
          if (this.currentMetrics.disk_json) {
            try {
              this.disks = JSON.parse(this.currentMetrics.disk_json);
            } catch (e) {
              console.error('Failed to parse disk_json:', e);
              this.disks = [];
            }
          }
        }
        
        this.updateCharts();
      } catch (error) {
        console.error('Failed to fetch metrics:', error);
      }
    },
    
    updateCharts() {
      if (this.metrics.length === 0) return;
      
      const timestamps = this.metrics.slice().reverse().map((m, i) => i);
      
      // CPU Chart
      this.updateChart('cpuChart', 'cpu', {
        label: 'CPU %',
        data: this.metrics.slice().reverse().map(m => m.cpu_percent),
        borderColor: '#8b5cf6',
        backgroundColor: 'rgba(139, 92, 246, 0.1)',
        max: 100,
        unit: '%'
      }, timestamps);
      
      // RAM Chart
      this.updateChart('ramChart', 'ram', {
        label: 'RAM %',
        data: this.metrics.slice().reverse().map(m => m.ram_percent),
        borderColor: '#06b6d4',
        backgroundColor: 'rgba(6, 182, 212, 0.1)',
        max: 100,
        unit: '%'
      }, timestamps);
      
      // Ping Chart
      this.updateChart('pingChart', 'ping', {
        label: 'Ping (ms)',
        data: this.metrics.slice().reverse().map(m => m.ping || 0),
        borderColor: '#f59e0b',
        backgroundColor: 'rgba(245, 158, 11, 0.1)',
        max: null,
        unit: 'ms'
      }, timestamps);
      
      // Network Chart (dual line)
      this.updateDualChart('networkChart', 'network', [
        {
          label: 'Upload',
          data: this.metrics.slice().reverse().map(m => m.net_up || 0),
          borderColor: '#10b981',
          backgroundColor: 'rgba(16, 185, 129, 0.1)'
        },
        {
          label: 'Download',
          data: this.metrics.slice().reverse().map(m => m.net_down || 0),
          borderColor: '#3b82f6',
          backgroundColor: 'rgba(59, 130, 246, 0.1)'
        }
      ], timestamps, 'bytes');
      
      // Disk I/O Chart (dual line)
      this.updateDualChart('diskIoChart', 'diskIo', [
        {
          label: 'Read',
          data: this.metrics.slice().reverse().map(m => m.disk_read || 0),
          borderColor: '#f97316',
          backgroundColor: 'rgba(249, 115, 22, 0.1)'
        },
        {
          label: 'Write',
          data: this.metrics.slice().reverse().map(m => m.disk_write || 0),
          borderColor: '#ef4444',
          backgroundColor: 'rgba(239, 68, 68, 0.1)'
        }
      ], timestamps, 'bytes');
    },
    
    updateChart(ref, key, config, timestamps) {
      const canvas = this.$refs[ref];
      if (!canvas) return;
      
      if (this.charts[key]) {
        this.charts[key].destroy();
      }
      
      const ctx = canvas.getContext('2d');
      this.charts[key] = new Chart(ctx, {
        type: 'line',
        data: {
          labels: timestamps,
          datasets: [{
            label: config.label,
            data: config.data,
            borderColor: config.borderColor,
            backgroundColor: config.backgroundColor,
            borderWidth: 2,
            fill: true,
            tension: 0.4,
            pointRadius: 0,
            pointHoverRadius: 4
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: {
              display: false
            },
            tooltip: {
              mode: 'index',
              intersect: false,
              callbacks: {
                label: (context) => {
                  return `${config.label}: ${context.parsed.y.toFixed(1)}${config.unit}`;
                }
              }
            }
          },
          scales: {
            x: {
              display: false
            },
            y: {
              beginAtZero: true,
              max: config.max,
              ticks: {
                callback: (value) => value + config.unit
              }
            }
          },
          interaction: {
            mode: 'nearest',
            axis: 'x',
            intersect: false
          }
        }
      });
    },
    
    updateDualChart(ref, key, datasets, timestamps, unit) {
      const canvas = this.$refs[ref];
      if (!canvas) return;
      
      if (this.charts[key]) {
        this.charts[key].destroy();
      }
      
      const ctx = canvas.getContext('2d');
      this.charts[key] = new Chart(ctx, {
        type: 'line',
        data: {
          labels: timestamps,
          datasets: datasets.map(ds => ({
            label: ds.label,
            data: ds.data,
            borderColor: ds.borderColor,
            backgroundColor: ds.backgroundColor,
            borderWidth: 2,
            fill: true,
            tension: 0.4,
            pointRadius: 0,
            pointHoverRadius: 4
          }))
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: {
              display: false
            },
            tooltip: {
              mode: 'index',
              intersect: false,
              callbacks: {
                label: (context) => {
                  const value = unit === 'bytes' 
                    ? this.formatBytes(context.parsed.y) + '/s'
                    : context.parsed.y.toFixed(1);
                  return `${context.dataset.label}: ${value}`;
                }
              }
            }
          },
          scales: {
            x: {
              display: false
            },
            y: {
              beginAtZero: true,
              ticks: {
                callback: (value) => {
                  return unit === 'bytes' ? this.formatBytes(value) + '/s' : value;
                }
              }
            }
          },
          interaction: {
            mode: 'nearest',
            axis: 'x',
            intersect: false
          }
        }
      });
    },
    
    formatBytes(bytes) {
      if (!bytes || bytes === 0) return '0 B';
      const k = 1024;
      const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
      const i = Math.floor(Math.log(bytes) / Math.log(k));
      return (bytes / Math.pow(k, i)).toFixed(1) + ' ' + sizes[i];
    },
    
    formatTime(timestamp) {
      if (!timestamp) return 'Unknown';
      const date = new Date(timestamp);
      const now = new Date();
      const diff = now - date;
      
      if (diff < 60000) return 'Just now';
      if (diff < 3600000) return Math.floor(diff / 60000) + ' minutes ago';
      if (diff < 86400000) return Math.floor(diff / 3600000) + ' hours ago';
      return date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
    },
    
    getDiskColor(percent) {
      if (percent >= 90) return '#ef4444'; // red
      if (percent >= 75) return '#f59e0b'; // orange
      return '#10b981'; // green
    }
  }
};
</script>

<style scoped>
.agent-detail {
  padding: 24px;
  max-width: 1600px;
  margin: 0 auto;
}

.detail-header {
  margin-bottom: 32px;
}

.back-btn {
  background: none;
  border: none;
  color: #3b82f6;
  font-size: 14px;
  cursor: pointer;
  padding: 8px 0;
  margin-bottom: 16px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.back-btn:hover {
  color: #2563eb;
}

.header-info {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 8px;
}

.header-info h2 {
  margin: 0;
  font-size: 28px;
  font-weight: 600;
}

.status-badge {
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 500;
  text-transform: uppercase;
}

.status-badge.online {
  background: #dcfce7;
  color: #16a34a;
}

.status-badge.offline {
  background: #fee2e2;
  color: #dc2626;
}

.header-meta {
  display: flex;
  gap: 24px;
  color: #6b7280;
  font-size: 14px;
}

.metrics-row {
  display: grid;
  gap: 20px;
  margin-bottom: 20px;
}

.vitals-row {
  grid-template-columns: repeat(3, 1fr);
}

.io-row {
  grid-template-columns: repeat(2, 1fr);
}

.chart-card {
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  padding: 20px;
  position: relative;
}

.chart-card h3 {
  margin: 0 0 16px 0;
  font-size: 16px;
  font-weight: 600;
  color: #1f2937;
}

.chart-card canvas {
  height: 180px !important;
}

.chart-wide canvas {
  height: 240px !important;
}

.current-value {
  position: absolute;
  top: 20px;
  right: 20px;
  font-size: 24px;
  font-weight: 700;
  color: #1f2937;
}

.legend {
  display: flex;
  gap: 24px;
  margin-top: 12px;
  font-size: 13px;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #6b7280;
}

.legend-color {
  width: 12px;
  height: 12px;
  border-radius: 2px;
}

.storage-section {
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  padding: 24px;
}

.storage-section h3 {
  margin: 0 0 20px 0;
  font-size: 18px;
  font-weight: 600;
  color: #1f2937;
}

.disks-list {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.disk-item {
  padding: 16px;
  background: #f9fafb;
  border-radius: 8px;
  border: 1px solid #e5e7eb;
}

.disk-header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 8px;
  font-size: 14px;
}

.disk-mount {
  font-weight: 600;
  color: #1f2937;
  min-width: 100px;
}

.disk-device {
  color: #6b7280;
  font-family: monospace;
  font-size: 12px;
}

.disk-usage {
  color: #6b7280;
  margin-left: auto;
}

.disk-percent {
  font-weight: 600;
  color: #1f2937;
  min-width: 60px;
  text-align: right;
}

.disk-bar {
  height: 8px;
  background: #e5e7eb;
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 8px;
}

.disk-bar-fill {
  height: 100%;
  transition: width 0.3s ease, background-color 0.3s ease;
  border-radius: 4px;
}

.disk-meta {
  display: flex;
  gap: 16px;
  font-size: 12px;
  color: #9ca3af;
}

.no-data {
  text-align: center;
  padding: 40px;
  color: #9ca3af;
}

@media (max-width: 1024px) {
  .vitals-row {
    grid-template-columns: 1fr;
  }
  
  .io-row {
    grid-template-columns: 1fr;
  }
}
</style>
