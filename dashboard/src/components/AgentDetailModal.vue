<template>
  <!-- Toast Notification -->
  <Teleport to="body">
    <transition name="toast">
      <div v-if="toast.show" :class="['toast-notification', toast.type]">
        <span class="toast-icon">{{ toast.type === 'success' ? '✓' : '✕' }}</span>
        <span class="toast-message">{{ toast.message }}</span>
      </div>
    </transition>
  </Teleport>
  
  <Teleport to="body">
    <div v-if="show" class="modal-overlay" @click.self="$emit('close')">
      <div class="modal-container agent-detail-modal">
        <!-- Header -->
        <div class="modal-header">
          <div class="d-flex align-items-center gap-3">
            <div 
              class="status-indicator" 
              :class="agent?.status === 'online' ? 'online' : 'offline'"
            ></div>
            <div>
              <div class="d-flex align-items-center gap-2">
                <!-- Editable Name (Admin Only) -->
                <template v-if="isEditingName && isAdmin">
                  <input 
                    ref="nameInput"
                    v-model="editedName"
                    class="form-control form-control-sm name-edit-input"
                    placeholder="Enter display name..."
                    @keyup.enter="saveName"
                    @keyup.escape="cancelNameEdit"
                  >
                  <button class="btn btn-sm btn-success" @click="saveName" title="Save">✓</button>
                  <button class="btn btn-sm btn-secondary" @click="cancelNameEdit" title="Cancel">✕</button>
                </template>
                <template v-else>
                  <h4 class="mb-0">{{ agent?.display_name || agent?.hostname }}</h4>
                  <button 
                    v-if="isAdmin"
                    class="btn btn-sm btn-link p-0 rename-btn" 
                    @click="startNameEdit" 
                    title="Rename scribe"
                  >✏️</button>
                </template>
                <span 
                  v-if="wsConnected" 
                  class="badge bg-success live-badge"
                  title="Live WebSocket connection"
                >
                  <span class="live-dot"></span> LIVE
                </span>
                <span 
                  v-if="agent?.enabled === false" 
                  class="badge bg-warning"
                >
                  DISABLED
                </span>
              </div>
              <div class="d-flex align-items-center gap-3 mt-1">
                <small class="text-secondary" :title="agent?.agent_id">
                  {{ agent?.display_name ? agent?.hostname : agent?.agent_id }}
                </small>
                <div v-if="agent?.public_ip" class="d-flex align-items-center gap-2">
                  <code class="text-primary small">{{ agent.public_ip }}</code>
                  <button 
                    class="btn btn-sm btn-link p-0" 
                    @click="copyToClipboard(agent.public_ip)"
                    title="Copy IP"
                  >
                    <span v-if="!copied">Copy</span>
                    <span v-else>✅</span>
                  </button>
                </div>
                <span v-if="agent?.os" class="badge bg-secondary" :title="'Operating System: ' + formatOS(agent.os)">
                  {{ getOSIcon(agent.os) }} {{ formatOS(agent.os) }}
                </span>
              </div>
            </div>
          </div>
          <div class="d-flex align-items-center gap-2">
            <!-- Admin-only action buttons -->
            <template v-if="isAdmin">
              <button 
                class="btn btn-sm btn-outline-info"
                @click="restartAgent"
                :disabled="restartLoading || agent?.status !== 'online'"
                :title="agent?.status !== 'online' ? 'Agent must be online to restart' : 'Restart agent'"
              >
                <span v-if="restartLoading" class="spinner-border spinner-border-sm me-1"></span>
                🔄 Restart
              </button>
              <button 
                class="btn btn-sm"
                :class="agent?.enabled === false ? 'btn-success' : 'btn-warning'"
                @click="toggleAgentStatus"
                :disabled="statusLoading"
              >
                <span v-if="statusLoading" class="spinner-border spinner-border-sm me-1"></span>
                {{ agent?.enabled === false ? '✓ Enable' : '⊗ Disable' }}
              </button>
              <button 
                class="btn btn-sm btn-danger" 
                @click="showDeleteConfirm = true"
              >
                🗑️
              </button>
            </template>
            <button class="btn-close btn-close-white ms-2" @click="$emit('close')"></button>
          </div>
        </div>

        <!-- Tabs -->
        <div class="modal-tabs">
          <button 
            class="tab-btn" 
            :class="{ active: activeTab === 'overview' }"
            @click="activeTab = 'overview'"
          >
            Overview
          </button>
          <button 
            class="tab-btn" 
            :class="{ active: activeTab === 'processes' }"
            @click="activeTab = 'processes'"
          >
            Processes
          </button>
          <button 
            class="tab-btn" 
            :class="{ active: activeTab === 'raw-logs' }"
            @click="activeTab = 'raw-logs'; fetchRawLogs()"
          >
            System Logs
          </button>
          <button 
            class="tab-btn position-relative" 
            :class="{ active: activeTab === 'alerts' }"
            @click="activeTab = 'alerts'; fetchAlertRules()"
          >
            Alerts
            <span 
              v-if="activeAlerts.length > 0" 
              class="alert-badge"
            >
              {{ activeAlerts.length }}
            </span>
          </button>
          <button 
            class="tab-btn" 
            :class="{ active: activeTab === 'log-settings' }"
            @click="activeTab = 'log-settings'; fetchLogSettings()"
          >
            Config
          </button>
        </div>

        <!-- Tab Content -->
        <div class="modal-body">
          <!-- Loading Overlay -->
          <div v-if="metricsLoading" class="metrics-loading-overlay">
            <div class="spinner-border text-primary mb-3" role="status"></div>
            <div class="text-secondary">Loading metrics data...</div>
          </div>

          <!-- Overview Tab -->
          <div v-show="activeTab === 'overview' && !metricsLoading" class="tab-content-pane">
            <!-- Offline Banner -->
            <div v-if="isOffline" class="offline-banner mb-3">
              <div class="offline-icon">⚫</div>
              <div class="offline-text">
                <strong>Agent Offline</strong>
                <span v-if="lastSeenDate">— Last seen {{ offlineDuration }} ({{ lastSeenDate.toLocaleString() }})</span>
              </div>
              <div class="offline-hint">Showing last known data</div>
            </div>

            <!-- Time Range Selector -->
            <div class="time-range-selector mb-3">
              <div class="btn-group" role="group">
                <button 
                  v-for="range in timeRanges" 
                  :key="range.value"
                  type="button"
                  class="btn btn-sm"
                  :class="selectedTimeRange === range.value ? 'btn-primary' : 'btn-outline-secondary'"
                  @click="selectTimeRange(range.value)"
                >
                  {{ range.label }}
                </button>
              </div>
              <span v-if="selectedTimeRange !== 'live'" class="text-secondary ms-3 small">
                {{ formatTimeRangeDisplay() }}
              </span>
            </div>

            <!-- System Overview Cards (compact summary) -->
            <div class="system-summary mb-4">
              <div class="summary-item">
                <span class="summary-label">CPU</span>
                <span class="summary-value" :class="getCpuColorClass()">{{ latestMetrics?.cpu_percent?.toFixed(0) || '0' }}%</span>
              </div>
              <div class="summary-item">
                <span class="summary-label">Memory</span>
                <span class="summary-value">{{ latestMetrics?.ram_percent?.toFixed(0) || '0' }}%</span>
              </div>
              <div class="summary-item" v-if="hasGPU">
                <span class="summary-label">GPU</span>
                <span class="summary-value gpu-value">{{ latestMetrics?.gpu_percent?.toFixed(0) || '0' }}%</span>
              </div>
              <div class="summary-item">
                <span class="summary-label">CPU Temp</span>
                <span class="summary-value" :class="getTempColorClass(latestMetrics?.cpu_temp)">{{ formatTemp(latestMetrics?.cpu_temp) }}</span>
              </div>
              <div class="summary-item" v-if="hasGPU && latestMetrics?.gpu_temp">
                <span class="summary-label">GPU Temp</span>
                <span class="summary-value" :class="getTempColorClass(latestMetrics?.gpu_temp)">{{ formatTemp(latestMetrics?.gpu_temp) }}</span>
              </div>
              <div class="summary-item">
                <span class="summary-label">Network</span>
                <span class="summary-value network-compact">
                  ↑{{ formatNetworkCompact(latestMetrics?.net_sent_bps) }} 
                  ↓{{ formatNetworkCompact(latestMetrics?.net_recv_bps) }}
                </span>
              </div>
              <div class="summary-item" v-if="latestMetrics?.is_vm">
                <span class="badge bg-info">VM</span>
              </div>
              <div class="hardware-stack" v-if="latestMetrics?.cpu_name || latestMetrics?.gpu_name">
                <div class="hardware-item" v-if="latestMetrics?.cpu_name" :title="latestMetrics?.cpu_name">
                  🖥️ {{ latestMetrics?.cpu_name }}
                </div>
                <div class="hardware-item" v-if="latestMetrics?.gpu_name" :title="latestMetrics?.gpu_name">
                  🎮 {{ latestMetrics?.gpu_name }}
                </div>
              </div>
            </div>

            <!-- 2x2 Charts Grid -->
            <div class="charts-grid-2x2">
              <!-- Top Left: Load Graph (CPU, Memory, GPU) -->
              <div class="chart-card">
                <h6 class="chart-title">System Load</h6>
                <div class="chart-container">
                  <Line v-if="chartData.labels?.length > 0" :data="loadChartData" :options="loadChartOptions" />
                  <div v-else-if="isOffline && !chartData.labels?.length" class="chart-placeholder text-secondary">
                    <div class="text-center">
                      <small>No recent data available</small>
                    </div>
                  </div>
                  <div v-else class="chart-placeholder">
                    <div class="spinner-border spinner-border-sm text-primary"></div>
                  </div>
                </div>
                <div class="chart-legend">
                  <span class="legend-item">
                    <span class="legend-dot" style="background: #8b5cf6;"></span>
                    CPU: {{ (latestMetrics?.cpu_percent || 0).toFixed(1) }}%
                  </span>
                  <span class="legend-item">
                    <span class="legend-dot" style="background: #06b6d4;"></span>
                    Memory: {{ (latestMetrics?.ram_percent || 0).toFixed(1) }}%
                  </span>
                  <span v-if="hasGPU" class="legend-item">
                    <span class="legend-dot" style="background: #f59e0b;"></span>
                    GPU: {{ (latestMetrics?.gpu_percent || 0).toFixed(1) }}%
                  </span>
                </div>
              </div>

              <!-- Top Right: Network Graph -->
              <div class="chart-card">
                <h6 class="chart-title">Network I/O</h6>
                <div class="chart-container">
                  <Line v-if="chartData.labels?.length > 0" :data="networkChartData" :options="networkChartOptions" />
                  <div v-else-if="isOffline && !chartData.labels?.length" class="chart-placeholder text-secondary">
                    <div class="text-center">
                      <small>No recent data available</small>
                    </div>
                  </div>
                  <div v-else class="chart-placeholder">
                    <div class="spinner-border spinner-border-sm text-primary"></div>
                  </div>
                </div>
                <div class="chart-legend">
                  <span class="legend-item">
                    <span class="legend-dot" style="background: #10b981;"></span>
                    Upload: {{ formatNetworkSpeedMbps(latestMetrics?.net_sent_bps) }}
                  </span>
                  <span class="legend-item">
                    <span class="legend-dot" style="background: #3b82f6;"></span>
                    Download: {{ formatNetworkSpeedMbps(latestMetrics?.net_recv_bps) }}
                  </span>
                </div>
              </div>

              <!-- Bottom Left: Thermals Graph -->
              <div class="chart-card">
                <h6 class="chart-title">Thermals</h6>
                <div class="chart-container">
                  <Line v-if="chartData.labels?.length > 0 && hasThermalData" :data="thermalsChartData" :options="thermalsChartOptions" />
                  <div v-else-if="!hasThermalData" class="chart-placeholder text-secondary">
                    <div class="text-center">
                      <small>{{ latestMetrics?.is_vm ? 'VM - No thermal sensors' : 'No thermal data available' }}</small>
                    </div>
                  </div>
                  <div v-else-if="isOffline && !chartData.labels?.length" class="chart-placeholder text-secondary">
                    <div class="text-center">
                      <small>No recent data available</small>
                    </div>
                  </div>
                  <div v-else class="chart-placeholder">
                    <div class="spinner-border spinner-border-sm text-primary"></div>
                  </div>
                </div>
                <div v-if="hasThermalData" class="chart-legend">
                  <span class="legend-item">
                    <span class="legend-dot" style="background: #ef4444;"></span>
                    CPU: {{ formatTemp(latestMetrics?.cpu_temp) }}
                  </span>
                  <span v-if="hasGPU && latestMetrics?.gpu_temp" class="legend-item">
                    <span class="legend-dot" style="background: #f97316;"></span>
                    GPU: {{ formatTemp(latestMetrics?.gpu_temp) }}
                  </span>
                </div>
              </div>

              <!-- Bottom Right: Storage Master -->
              <div class="chart-card storage-card">
                <div class="chart-header-with-toggles">
                  <h6 class="chart-title">Storage</h6>
                  <div class="drive-toggles" v-if="availableDrives.length > 1">
                    <button 
                      v-for="drive in availableDrives" 
                      :key="drive.mountpoint"
                      class="drive-chip"
                      :class="{ active: selectedDrive === drive.mountpoint }"
                      @click="selectedDrive = drive.mountpoint"
                    >
                      {{ formatDriveLabel(drive.mountpoint) }}
                    </button>
                  </div>
                </div>
                <div class="storage-overview">
                  <div class="storage-bar-container">
                    <div 
                      class="storage-bar" 
                      :style="{ width: getSelectedDriveUsage() + '%' }"
                      :class="getStorageColorClass(getSelectedDriveUsage())"
                    ></div>
                    <span class="storage-percent">{{ getSelectedDriveUsage().toFixed(1) }}%</span>
                  </div>
                  <div class="storage-io-stats">
                    <span class="io-stat">
                      <span class="io-label">Read:</span>
                      <span class="io-value">{{ formatDiskSpeed(getSelectedDriveReadBps()) }}</span>
                    </span>
                    <span class="io-stat">
                      <span class="io-label">Write:</span>
                      <span class="io-value">{{ formatDiskSpeed(getSelectedDriveWriteBps()) }}</span>
                    </span>
                  </div>
                </div>
                <div class="chart-container chart-container-short">
                  <Line v-if="chartData.labels?.length > 0" :data="storageChartData" :options="storageChartOptions" />
                </div>
              </div>
            </div>
          </div>

          <!-- Processes Tab -->
          <div v-show="activeTab === 'processes'" class="tab-content-pane">
            <div class="d-flex justify-content-between align-items-center mb-3">
              <h6 class="mb-0">Top Processes by {{ processSortKey === 'cpu_percent' ? 'CPU' : 'RAM' }}</h6>
              <div class="btn-group btn-group-sm">
                <button 
                  class="btn" 
                  :class="processSortKey === 'cpu_percent' ? 'btn-primary' : 'btn-outline-secondary'"
                  @click="processSortKey = 'cpu_percent'"
                >
                  CPU
                </button>
                <button 
                  class="btn" 
                  :class="processSortKey === 'ram_percent' ? 'btn-primary' : 'btn-outline-secondary'"
                  @click="processSortKey = 'ram_percent'"
                >
                  RAM
                </button>
              </div>
            </div>
            <div class="table-responsive">
              <table class="table table-dark table-hover table-sm process-table">
                <thead>
                  <tr>
                    <th style="width: 80px;">PID</th>
                    <th class="process-name-col">Name</th>
                    <th class="text-end" style="width: 90px;">CPU %</th>
                    <th class="text-end" style="width: 90px;">RAM %</th>
                  </tr>
                </thead>
                <tbody>
                  <tr 
                    v-for="proc in sortedProcesses" 
                    :key="proc.pid"
                    class="process-row"
                    @click="showProcessDetail(proc)"
                  >
                    <td class="text-secondary">{{ proc.pid }}</td>
                    <td class="process-name" :title="proc.name">{{ proc.name }}</td>
                    <td class="text-end">
                      <span :class="proc.cpu_percent > 50 ? 'text-warning' : ''">
                        {{ proc.cpu_percent?.toFixed(1) }}%
                      </span>
                    </td>
                    <td class="text-end">
                      <span :class="proc.ram_percent > 50 ? 'text-warning' : ''">
                        {{ proc.ram_percent?.toFixed(1) }}%
                      </span>
                    </td>
                  </tr>
                  <tr v-if="!sortedProcesses?.length">
                    <td colspan="4" class="text-center text-secondary py-4">
                      No process data available
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- Process Detail Modal -->
          <div v-if="selectedProcess" class="process-detail-overlay" @click.self="selectedProcess = null">
            <div class="process-detail-modal">
              <div class="process-detail-header">
                <h5><i class="bi bi-gear"></i> Process Details</h5>
                <button class="close-btn" @click="selectedProcess = null">&times;</button>
              </div>
              <div class="process-detail-body">
                <div class="process-info-grid">
                  <div class="info-item">
                    <label>Process ID (PID)</label>
                    <span class="value">{{ selectedProcess.pid }}</span>
                  </div>
                  <div class="info-item full-width">
                    <label>Process Name</label>
                    <span class="value name-value">{{ selectedProcess.name }}</span>
                  </div>
                  <div class="info-item">
                    <label>CPU Usage</label>
                    <span class="value" :class="selectedProcess.cpu_percent > 50 ? 'text-warning' : 'text-success'">
                      {{ selectedProcess.cpu_percent?.toFixed(2) }}%
                    </span>
                  </div>
                  <div class="info-item">
                    <label>RAM Usage</label>
                    <span class="value" :class="selectedProcess.ram_percent > 50 ? 'text-warning' : 'text-info'">
                      {{ selectedProcess.ram_percent?.toFixed(2) }}%
                    </span>
                  </div>
                </div>
                <div class="process-note">
                  <i class="bi bi-info-circle"></i>
                  <span>CPU percentage is measured per-core. On a multi-core system, each process can use up to 100% of a single core, so multiple processes can each show high percentages simultaneously.</span>
                </div>
              </div>
            </div>
          </div>

          <!-- Raw System Logs Tab -->
          <div v-show="activeTab === 'raw-logs'" class="tab-content-pane">
            <!-- Filters -->
            <div class="row g-2 mb-3">
              <div class="col-md-3">
                <select v-model="rawLogFilters.severity" class="form-select form-select-sm bg-dark text-light" @change="fetchRawLogs">
                  <option value="">All Severities</option>
                  <option value="CRITICAL">🔴 Critical</option>
                  <option value="ERROR">🟠 Error</option>
                  <option value="WARN,WARNING">🟡 Warning</option>
                  <option value="INFO">🔵 Info</option>
                </select>
              </div>
              <div class="col-md-3">
                <select v-model="rawLogFilters.source" class="form-select form-select-sm bg-dark text-light" @change="fetchRawLogs">
                  <option value="">All Sources</option>
                  <option value="System">System</option>
                  <option value="Security">Security</option>
                  <option value="Application">Application</option>
                  <option value="Docker">Docker</option>
                </select>
              </div>
              <div class="col-md-4">
                <input 
                  type="text" 
                  class="form-control form-control-sm bg-dark text-light"
                  v-model="rawLogFilters.search"
                  placeholder="Search messages..."
                  @keyup.enter="fetchRawLogs"
                >
              </div>
              <div class="col-md-2">
                <button class="btn btn-sm btn-primary w-100" @click="fetchRawLogs" :disabled="loadingRawLogs">
                  <span v-if="loadingRawLogs" class="spinner-border spinner-border-sm me-1"></span>
                  Search
                </button>
              </div>
            </div>

            <!-- Log Stats -->
            <div class="log-stats mb-3">
              <div class="stat-pill bg-danger bg-opacity-10 text-danger">
                <span class="stat-value">{{ rawLogStats.critical }}</span> Critical
              </div>
              <div class="stat-pill bg-warning bg-opacity-10 text-warning">
                <span class="stat-value">{{ rawLogStats.error }}</span> Error
              </div>
              <div class="stat-pill bg-info bg-opacity-10 text-info">
                <span class="stat-value">{{ rawLogStats.warning }}</span> Warning
              </div>
              <div class="stat-pill bg-secondary bg-opacity-10">
                <span class="stat-value">{{ rawLogStats.total }}</span> Total
              </div>
            </div>

            <!-- Logs Table -->
            <div class="logs-table-container">
              <table class="table table-dark table-hover table-sm mb-0">
                <thead class="sticky-top">
                  <tr>
                    <th style="width: 140px">Time</th>
                    <th style="width: 80px">Severity</th>
                    <th style="width: 90px">Source</th>
                    <th>Message</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-if="loadingRawLogs">
                    <td colspan="4" class="text-center py-4">
                      <div class="spinner-border spinner-border-sm text-primary"></div>
                    </td>
                  </tr>
                  <tr v-else-if="rawLogs.length === 0">
                    <td colspan="4" class="text-center py-4 text-secondary">
                      No logs found
                    </td>
                  </tr>
                  <tr v-for="log in rawLogs" :key="log.id">
                    <td class="text-secondary small">{{ formatLogTime(log.timestamp) }}</td>
                    <td>
                      <span class="badge" :class="getSeverityBadgeClass(log.severity)">
                        {{ log.severity }}
                      </span>
                    </td>
                    <td class="small">{{ log.source }}</td>
                    <td class="small text-break log-message">{{ log.message }}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <!-- Pagination -->
            <div v-if="rawLogsPagination.total_count > 0" class="d-flex justify-content-between align-items-center mt-3">
              <span class="text-secondary small">
                {{ rawLogsPagination.offset + 1 }} - {{ Math.min(rawLogsPagination.offset + rawLogs.length, rawLogsPagination.total_count) }} of {{ rawLogsPagination.total_count }}
              </span>
              <div class="btn-group btn-group-sm">
                <button 
                  class="btn btn-outline-secondary" 
                  @click="rawLogsPagination.offset = Math.max(0, rawLogsPagination.offset - 100); fetchRawLogs()"
                  :disabled="rawLogsPagination.offset === 0"
                >
                  ←
                </button>
                <button 
                  class="btn btn-outline-secondary" 
                  @click="rawLogsPagination.offset += 100; fetchRawLogs()"
                  :disabled="!rawLogsPagination.has_more"
                >
                  →
                </button>
              </div>
            </div>
          </div>

          <!-- Alerts Tab -->
          <div v-show="activeTab === 'alerts'" class="tab-content-pane">
            <div class="row">
              <!-- Effective Rules (V2 - Inherited + Agent-specific) -->
              <div v-if="isAdmin" class="col-12 mb-3">
                <div class="config-section">
                  <div class="section-header">
                    <h6 class="mb-0">📋 Alert Rules</h6>
                    <button 
                      class="btn btn-sm btn-outline-secondary"
                      @click="fetchEffectiveRules"
                      :disabled="loadingEffectiveRules"
                    >
                      <span v-if="loadingEffectiveRules" class="spinner-border spinner-border-sm"></span>
                      <span v-else>🔄</span>
                    </button>
                  </div>
                  <div class="section-body">
                    <div v-if="effectiveRules.length === 0 && !loadingEffectiveRules" class="text-center text-secondary py-3">
                      No alert rules configured. <router-link to="/settings?tab=alerts">Configure global rules</router-link>
                    </div>
                    
                    <div v-else class="effective-rules-list">
                      <div 
                        v-for="rule in effectiveRules" 
                        :key="rule.id"
                        class="effective-rule-item"
                        :class="{ disabled: rule.disabled }"
                      >
                        <div class="rule-status">
                          <span v-if="rule.scope === 'global'" class="badge bg-primary badge-sm" title="Inherited from global settings">Global</span>
                          <span v-else class="badge bg-success badge-sm">Agent</span>
                        </div>
                        <div class="rule-details">
                          <div class="rule-name">{{ rule.name }}</div>
                          <div class="rule-condition">{{ formatRuleCondition(rule) }}</div>
                        </div>
                        <div class="rule-channels" v-if="rule.channels?.length">
                          <span class="channels-indicator" :title="'Sends to ' + rule.channels.length + ' channel(s)'">
                            🔔 {{ rule.channels.length }}
                          </span>
                        </div>
                        <div class="rule-override" v-if="rule.scope === 'global'">
                          <button 
                            v-if="!rule.disabled"
                            class="btn btn-sm btn-outline-warning"
                            @click="toggleRuleOverride(rule, 'disable')"
                            title="Disable this rule for this agent"
                          >
                            Skip
                          </button>
                          <button 
                            v-else
                            class="btn btn-sm btn-outline-success"
                            @click="toggleRuleOverride(rule, 'enable')"
                            title="Re-enable this rule for this agent"
                          >
                            Enable
                          </button>
                        </div>
                      </div>
                    </div>
                    
                    <div class="mt-3 text-secondary small">
                      <i class="bi bi-info-circle me-1"></i>
                      Global rules apply to all agents. Use "Skip" to disable a rule for this agent only.
                    </div>
                  </div>
                </div>
              </div>
              
              <!-- Legacy Alert Thresholds (Backwards Compatibility) -->
              <div v-if="isAdmin" class="col-lg-6 mb-3">
                <div class="config-section">
                  <div class="section-header">
                    <h6 class="mb-0">⚙️ Quick Thresholds</h6>
                    <button 
                      class="btn btn-sm btn-primary"
                      @click="saveAlertRules"
                      :disabled="savingRules"
                    >
                      <span v-if="savingRules" class="spinner-border spinner-border-sm me-1"></span>
                      Save
                    </button>
                  </div>
                  <div class="section-body">
                    <!-- Uptime Monitor -->
                    <div class="form-check form-switch mb-3">
                      <input class="form-check-input" type="checkbox" v-model="alertRules.monitor_uptime" id="monitorUptime">
                      <label class="form-check-label" for="monitorUptime">
                        Monitor Uptime (alert if offline >5 min)
                      </label>
                    </div>

                    <!-- CPU Alert -->
                    <div class="alert-rule-item">
                      <div class="d-flex justify-content-between align-items-center">
                        <div class="form-check form-switch">
                          <input class="form-check-input" type="checkbox" v-model="cpuAlertEnabled" id="cpuAlert">
                          <label class="form-check-label" for="cpuAlert">CPU Usage Alert</label>
                        </div>
                        <div v-if="cpuAlertEnabled" class="threshold-input">
                          <input 
                            type="number" 
                            class="form-control form-control-sm"
                            v-model.number="alertRules.cpu_percent_threshold"
                            min="1" max="100"
                          >
                          <span>%</span>
                        </div>
                      </div>
                    </div>

                    <!-- RAM Alert -->
                    <div class="alert-rule-item">
                      <div class="d-flex justify-content-between align-items-center">
                        <div class="form-check form-switch">
                          <input class="form-check-input" type="checkbox" v-model="ramAlertEnabled" id="ramAlert">
                          <label class="form-check-label" for="ramAlert">Memory Usage Alert</label>
                        </div>
                        <div v-if="ramAlertEnabled" class="threshold-input">
                          <input 
                            type="number" 
                            class="form-control form-control-sm"
                            v-model.number="alertRules.ram_percent_threshold"
                            min="1" max="100"
                          >
                          <span>%</span>
                        </div>
                      </div>
                    </div>

                    <!-- Disk Alert -->
                    <div class="alert-rule-item">
                      <div class="d-flex justify-content-between align-items-center">
                        <div class="form-check form-switch">
                          <input class="form-check-input" type="checkbox" v-model="diskAlertEnabled" id="diskAlert">
                          <label class="form-check-label" for="diskAlert">Low Disk Space Alert</label>
                        </div>
                        <div v-if="diskAlertEnabled" class="threshold-input">
                          <span>&lt;</span>
                          <input 
                            type="number" 
                            class="form-control form-control-sm"
                            v-model.number="alertRules.disk_free_percent_threshold"
                            min="1" max="50"
                          >
                          <span>%</span>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <!-- Active Alerts -->
              <div :class="isAdmin ? 'col-lg-6' : 'col-12'" class="mb-3">
                <div class="config-section">
                  <div class="section-header">
                    <h6 class="mb-0">🚨 Active Alerts</h6>
                    <button 
                      class="btn btn-sm btn-outline-secondary"
                      @click="fetchActiveAlerts"
                      :disabled="loadingAlerts"
                    >
                      <span v-if="loadingAlerts" class="spinner-border spinner-border-sm"></span>
                      <span v-else>🔄</span>
                    </button>
                  </div>
                  <div class="section-body alerts-list">
                    <div v-if="activeAlerts.length === 0" class="text-center text-secondary py-4">
                      ✅ No active alerts
                    </div>
                    <div 
                      v-for="alert in activeAlerts" 
                      :key="alert.id"
                      class="alert-item"
                      :class="alert.resolved_at ? 'resolved' : ''"
                    >
                      <div class="alert-icon">
                        {{ getAlertIcon(alert.alert_type) }}
                      </div>
                      <div class="alert-info">
                        <div class="alert-type">{{ formatAlertType(alert.alert_type) }}</div>
                        <div class="alert-time text-secondary small">
                          {{ formatAlertTime(alert.triggered_at) }}
                        </div>
                      </div>
                      <button 
                        v-if="!alert.resolved_at && isAdmin"
                        class="btn btn-sm btn-outline-success"
                        @click="resolveAlert(alert.id)"
                      >
                        ✓
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Log Settings Tab -->
          <div v-show="activeTab === 'log-settings'" class="tab-content-pane">
            <!-- Admin View: Full Edit -->
            <template v-if="isAdmin">
              <div class="row">
              <div class="col-lg-6 mb-3">
                <div class="config-section">
                  <div class="section-header">
                    <h6 class="mb-0">Log Collection</h6>
                  </div>
                  <div class="section-body">
                    <!-- Master Toggle -->
                    <div class="form-check form-switch mb-3">
                      <input class="form-check-input" type="checkbox" v-model="logSettings.logging_enabled" id="loggingEnabled">
                      <label class="form-check-label" for="loggingEnabled">
                        <strong>Enable Log Collection</strong>
                      </label>
                    </div>

                    <!-- Troubleshooting Mode -->
                    <div v-if="logSettings.troubleshooting_mode" class="alert alert-warning py-2 mb-3">
                      Troubleshooting mode active - collecting ALL logs
                    </div>

                    <div class="form-check form-switch mb-3">
                      <input class="form-check-input" type="checkbox" v-model="logSettings.troubleshooting_mode" id="troubleshootingMode">
                      <label class="form-check-label" for="troubleshootingMode">
                        Troubleshooting Mode
                      </label>
                    </div>

                    <hr class="border-secondary">

                    <!-- Log Level -->
                    <div class="mb-3">
                      <label class="form-label small">Log Level Threshold</label>
                      <select v-model="logSettings.log_level_threshold" class="form-select form-select-sm bg-dark text-light" :disabled="logSettings.troubleshooting_mode">
                        <option value="INFO">Info+</option>
                        <option value="WARN">Warn+</option>
                        <option value="ERROR">Error+</option>
                        <option value="CRITICAL">Critical only</option>
                      </select>
                    </div>

                    <!-- Retention Override -->
                    <div class="mb-3">
                      <label class="form-label small d-flex align-items-center gap-2">
                        Log Retention
                        <span class="badge bg-info small" title="Overrides global default from Settings">Override</span>
                      </label>
                      <select v-model="logSettings.log_retention_days" class="form-select form-select-sm bg-dark text-light">
                        <option :value="null">Use global default</option>
                        <option :value="1">1 Day</option>
                        <option :value="3">3 Days</option>
                        <option :value="7">7 Days</option>
                        <option :value="14">14 Days</option>
                        <option :value="30">30 Days</option>
                        <option :value="60">60 Days</option>
                        <option :value="90">90 Days</option>
                      </select>
                      <small class="text-muted mt-1 d-block">Leave as "Use global default" unless this agent needs different retention.</small>
                    </div>
                  </div>
                </div>
              </div>

              <div class="col-lg-6">
                <div class="config-section">
                  <div class="section-header">
                    <h6 class="mb-0">Log Sources</h6>
                  </div>
                  <div class="section-body">
                    <div class="form-check form-switch mb-3">
                      <input class="form-check-input" type="checkbox" v-model="logSettings.watch_system_logs" id="watchSystem">
                      <label class="form-check-label" for="watchSystem">
                        System Logs
                      </label>
                    </div>
                    <div class="form-check form-switch mb-3">
                      <input class="form-check-input" type="checkbox" v-model="logSettings.watch_security_logs" id="watchSecurity">
                      <label class="form-check-label" for="watchSecurity">
                        Security Logs
                      </label>
                    </div>
                    <div class="form-check form-switch mb-3">
                      <input class="form-check-input" type="checkbox" v-model="logSettings.watch_docker_containers" id="watchDocker">
                      <label class="form-check-label" for="watchDocker">
                        Docker Logs
                      </label>
                    </div>
                  </div>
                </div>

                <!-- Tags Section -->
                <div class="config-section mt-3">
                  <div class="section-header">
                    <h6 class="mb-0">Tags</h6>
                    <span v-if="savingTags" class="badge bg-secondary">
                      <span class="spinner-border spinner-border-sm me-1" style="width: 0.7rem; height: 0.7rem;"></span>
                      Saving...
                    </span>
                  </div>
                  <div class="section-body">
                    <template v-if="isAdmin">
                      <TagInput 
                        v-model="localTags" 
                        placeholder="Type tag and press Enter..." 
                        @update:modelValue="onTagsChange"
                      />
                      <small class="text-muted mt-2 d-block">
                        Tags help organize scribes and can be used in Report Profiles to select multiple scribes at once.
                      </small>
                    </template>
                    <template v-else>
                      <div class="tag-display">
                        <span v-for="tag in localTags" :key="tag" class="badge bg-secondary me-1">{{ tag }}</span>
                        <span v-if="!localTags.length" class="text-muted">No tags</span>
                      </div>
                    </template>
                  </div>
                </div>

                <!-- Availability Window Section -->
                <div class="config-section mt-3">
                  <div class="section-header">
                    <h6 class="mb-0">Availability Window</h6>
                    <span v-if="savingUptimeWindow" class="badge bg-secondary">
                      <span class="spinner-border spinner-border-sm me-1" style="width: 0.7rem; height: 0.7rem;"></span>
                      Saving...
                    </span>
                  </div>
                  <div class="section-body">
                    <template v-if="isAdmin">
                      <select 
                        v-model="localUptimeWindow" 
                        class="form-select form-select-sm bg-dark text-light"
                        @change="onUptimeWindowChange"
                      >
                        <option value="daily">Daily (Last 24 hours)</option>
                        <option value="weekly">Weekly (Last 7 days)</option>
                        <option value="monthly">Monthly (Last 30 days)</option>
                        <option value="quarterly">Quarterly (Last 90 days)</option>
                        <option value="yearly">Yearly (Last 365 days)</option>
                      </select>
                      <small class="text-muted mt-2 d-block">
                        Time window used to calculate the scribe's availability percentage.
                      </small>
                    </template>
                    <template v-else>
                      <div class="text-light">{{ uptimeWindowLabel }}</div>
                    </template>
                  </div>
                </div>
              </div>
            </div>

            <!-- Save Button at Bottom (Admin only) -->
            <div class="d-flex justify-content-end mt-3">
              <button 
                class="btn btn-primary"
                @click="saveLogSettings"
                :disabled="savingLogSettings"
              >
                <span v-if="savingLogSettings" class="spinner-border spinner-border-sm me-1"></span>
                Save Configuration
              </button>
            </div>
            </template>

            <!-- Non-Admin View: Read-Only Summary -->
            <template v-else>
              <div class="row">
              <div class="col-12">
                <div class="config-section">
                  <div class="section-header">
                    <h6 class="mb-0">Log Settings (Read-Only)</h6>
                  </div>
                  <div class="section-body">
                    <p class="text-muted mb-2">
                      <span>Logging: </span>
                      <span :class="logSettings.logging_enabled ? 'text-success' : 'text-secondary'">
                        {{ logSettings.logging_enabled ? 'Enabled' : 'Disabled' }}
                      </span>
                    </p>
                    <p class="text-muted mb-2">
                      <span>Log Level: </span>
                      <span class="text-light">{{ logSettings.log_level_threshold || 'INFO' }}</span>
                    </p>
                    <p class="text-muted mb-0">
                      <span>Troubleshooting Mode: </span>
                      <span :class="logSettings.troubleshooting_mode ? 'text-warning' : 'text-secondary'">
                        {{ logSettings.troubleshooting_mode ? 'Active' : 'Off' }}
                      </span>
                    </p>
                  </div>
                </div>
                <!-- Tags (Read-Only) -->
                <div class="config-section mt-3">
                  <div class="section-header">
                    <h6 class="mb-0">Tags</h6>
                  </div>
                  <div class="section-body">
                    <div class="tag-display">
                      <span v-for="tag in localTags" :key="tag" class="badge bg-secondary me-1">{{ tag }}</span>
                      <span v-if="!localTags.length" class="text-muted">No tags</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
            </template>
          </div>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- Delete Confirmation -->
  <ConfirmDeleteModal 
    :show="showDeleteConfirm"
    :agent-name="agent?.hostname || 'Unknown'"
    @confirm="confirmDelete"
    @cancel="showDeleteConfirm = false"
  />
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import axios from 'axios'
import { Line } from 'vue-chartjs'
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler
} from 'chart.js'
import ConfirmDeleteModal from './ConfirmDeleteModal.vue'
import TagInput from './TagInput.vue'
import { isAdmin } from '../auth.js'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend, Filler)

const props = defineProps({
  show: Boolean,
  agent: Object
})

const emit = defineEmits(['close', 'deleted', 'status-changed'])

// Computed - Offline detection
const isOffline = computed(() => props.agent?.status !== 'online')

const lastSeenDate = computed(() => {
  if (!props.agent?.last_seen) return null
  return new Date(props.agent.last_seen)
})

const offlineDuration = computed(() => {
  if (!isOffline.value || !lastSeenDate.value) return ''
  const now = new Date()
  const diff = now - lastSeenDate.value
  const minutes = Math.floor(diff / 60000)
  const hours = Math.floor(minutes / 60)
  const days = Math.floor(hours / 24)
  
  if (days > 0) return `${days}d ${hours % 24}h ago`
  if (hours > 0) return `${hours}h ${minutes % 60}m ago`
  return `${minutes}m ago`
})

// State
const activeTab = ref('overview')
const copied = ref(false)
const wsConnected = ref(false)
const wsInstance = ref(null)
const statusLoading = ref(false)
const restartLoading = ref(false)
const showDeleteConfirm = ref(false)
const metricsLoading = ref(false)

// Rename state
const isEditingName = ref(false)
const editedName = ref('')
const nameInput = ref(null)

// Tags state
const localTags = ref('')
const savingTags = ref(false)

// Uptime Window state
const localUptimeWindow = ref('monthly')
const savingUptimeWindow = ref(false)

// Time range
const selectedTimeRange = ref('live')
const timeRanges = [
  { label: 'Live', value: 'live' },
  { label: '1h', value: '1h' },
  { label: '24h', value: '24h' },
  { label: '7d', value: '7d' },
  { label: '30d', value: '30d' }
]

// Metrics data
const metricsBuffer = ref([])
const latestMetrics = ref(null)
const chartData = ref({ labels: [], datasets: [] })

// Processes
const processSortKey = ref('cpu_percent')
const processData = ref([])
const selectedProcess = ref(null)

const showProcessDetail = (proc) => {
  selectedProcess.value = proc
}

// Raw Logs
const rawLogs = ref([])
const loadingRawLogs = ref(false)
const rawLogFilters = ref({ severity: '', source: '', search: '' })
const rawLogsPagination = ref({ offset: 0, total_count: 0, has_more: false })
const rawLogStats = ref({ critical: 0, error: 0, warning: 0, total: 0 })

// Alerts
const alertRules = ref({
  monitor_uptime: true,
  cpu_percent_threshold: null,
  ram_percent_threshold: null,
  disk_free_percent_threshold: null
})
const activeAlerts = ref([])
const loadingAlerts = ref(false)
const savingRules = ref(false)

// V2 Alert Rules (inherited and agent-specific)
const effectiveRules = ref([])
const loadingEffectiveRules = ref(false)
const notificationChannels = ref([])

// Log Settings
const logSettings = ref({
  logging_enabled: false,
  log_level_threshold: 'ERROR',
  log_retention_days: null,  // null = use global default
  watch_docker_containers: false,
  watch_system_logs: true,
  watch_security_logs: false,
  troubleshooting_mode: false
})
const savingLogSettings = ref(false)

// Toast notification
const toast = ref({
  show: false,
  type: 'success',
  message: ''
})

const showToast = (type, message) => {
  toast.value = { show: true, type, message }
  setTimeout(() => {
    toast.value.show = false
  }, 3000)
}

// System Info state


// Storage Master state
const selectedDrive = ref('')

// Computed - GPU/VM detection
const hasGPU = computed(() => {
  // Check if we have GPU data in buffer or latest metrics
  return (latestMetrics.value?.gpu_percent > 0 || latestMetrics.value?.gpu_name) ||
         metricsBuffer.value.some(m => m.gpu_percent > 0 || m.gpu_name)
})

const hasThermalData = computed(() => {
  // Check if we have any thermal data
  return latestMetrics.value?.cpu_temp > 0 || latestMetrics.value?.gpu_temp > 0 ||
         metricsBuffer.value.some(m => m.cpu_temp > 0 || m.gpu_temp > 0)
})

const availableDrives = computed(() => {
  const disks = latestMetrics.value?.disks || []
  return disks.length > 0 ? disks : [{ mountpoint: '/', usage_percent: 0 }]
})

// Computed - Alert settings
const cpuAlertEnabled = computed({
  get: () => alertRules.value.cpu_percent_threshold !== null,
  set: (val) => alertRules.value.cpu_percent_threshold = val ? 90 : null
})

const ramAlertEnabled = computed({
  get: () => alertRules.value.ram_percent_threshold !== null,
  set: (val) => alertRules.value.ram_percent_threshold = val ? 85 : null
})

const diskAlertEnabled = computed({
  get: () => alertRules.value.disk_free_percent_threshold !== null,
  set: (val) => alertRules.value.disk_free_percent_threshold = val ? 10 : null
})

const sortedProcesses = computed(() => {
  if (!processData.value?.length) return []
  return [...processData.value].sort((a, b) => 
    (b[processSortKey.value] || 0) - (a[processSortKey.value] || 0)
  ).slice(0, 15)
})

// Load Chart (CPU, Memory, GPU)
const loadChartData = computed(() => {
  const datasets = [
    {
      label: 'CPU %',
      data: chartData.value.cpu || [],
      borderColor: '#8b5cf6',
      backgroundColor: 'rgba(139, 92, 246, 0.15)',
      fill: true,
      tension: 0.4,
      borderWidth: 2,
      pointRadius: 0,
      pointHoverRadius: 4
    },
    {
      label: 'Memory %',
      data: chartData.value.ram || [],
      borderColor: '#06b6d4',
      backgroundColor: 'rgba(6, 182, 212, 0.15)',
      fill: true,
      tension: 0.4,
      borderWidth: 2,
      pointRadius: 0,
      pointHoverRadius: 4
    }
  ]
  
  // Add GPU if available
  if (hasGPU.value) {
    datasets.push({
      label: 'GPU %',
      data: chartData.value.gpu || [],
      borderColor: '#f59e0b',
      backgroundColor: 'rgba(245, 158, 11, 0.15)',
      fill: true,
      tension: 0.4,
      borderWidth: 2,
      pointRadius: 0,
      pointHoverRadius: 4
    })
  }
  
  return {
    labels: chartData.value.labels || [],
    datasets
  }
})

const networkChartData = computed(() => ({
  labels: chartData.value.labels || [],
  datasets: [
    {
      label: 'Upload (Mbps)',
      data: chartData.value.netSent || [],
      borderColor: '#10b981',
      backgroundColor: 'rgba(16, 185, 129, 0.15)',
      fill: true,
      tension: 0.4,
      borderWidth: 2,
      pointRadius: 0,
      pointHoverRadius: 4
    },
    {
      label: 'Download (Mbps)',
      data: chartData.value.netRecv || [],
      borderColor: '#3b82f6',
      backgroundColor: 'rgba(59, 130, 246, 0.15)',
      fill: true,
      tension: 0.4,
      borderWidth: 2,
      pointRadius: 0,
      pointHoverRadius: 4
    }
  ]
}))

// Thermals Chart (CPU Temp, GPU Temp)
const thermalsChartData = computed(() => {
  const datasets = [
    {
      label: 'CPU Temp',
      data: chartData.value.cpuTemp || [],
      borderColor: '#ef4444',
      backgroundColor: 'rgba(239, 68, 68, 0.15)',
      fill: true,
      tension: 0.4,
      borderWidth: 2,
      pointRadius: 0,
      pointHoverRadius: 4
    }
  ]
  
  // Add GPU temp if available
  if (hasGPU.value && metricsBuffer.value.some(m => m.gpu_temp > 0)) {
    datasets.push({
      label: 'GPU Temp',
      data: chartData.value.gpuTemp || [],
      borderColor: '#f97316',
      backgroundColor: 'rgba(249, 115, 22, 0.15)',
      fill: true,
      tension: 0.4,
      borderWidth: 2,
      pointRadius: 0,
      pointHoverRadius: 4
    })
  }
  
  return {
    labels: chartData.value.labels || [],
    datasets
  }
})

// Storage Chart (per-drive usage over time)
const storageChartData = computed(() => {
  return {
    labels: chartData.value.labels || [],
    datasets: [
      {
        label: 'Usage %',
        data: chartData.value.diskUsage || [],
        borderColor: '#a855f7',
        backgroundColor: 'rgba(168, 85, 247, 0.2)',
        fill: true,
        tension: 0.4,
        borderWidth: 2,
        pointRadius: 0,
        pointHoverRadius: 4,
        yAxisID: 'y'
      },
      {
        label: 'Read MB/s',
        data: chartData.value.diskRead || [],
        borderColor: '#22c55e',
        backgroundColor: 'transparent',
        fill: false,
        tension: 0.4,
        borderWidth: 1.5,
        pointRadius: 0,
        pointHoverRadius: 3,
        yAxisID: 'y1'
      },
      {
        label: 'Write MB/s',
        data: chartData.value.diskWrite || [],
        borderColor: '#f43f5e',
        backgroundColor: 'transparent',
        fill: false,
        tension: 0.4,
        borderWidth: 1.5,
        pointRadius: 0,
        pointHoverRadius: 3,
        yAxisID: 'y1'
      }
    ]
  }
})

const loadChartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  animation: false,
  plugins: {
    legend: { display: false },
    tooltip: {
      mode: 'index',
      intersect: false,
      backgroundColor: 'rgba(0, 0, 0, 0.8)',
      titleColor: '#fff',
      bodyColor: '#fff',
      borderColor: '#333',
      borderWidth: 1,
      padding: 10,
      displayColors: true,
      callbacks: {
        label: (context) => `${context.dataset.label}: ${context.parsed.y.toFixed(1)}%`
      }
    }
  },
  scales: {
    x: { display: false },
    y: { 
      beginAtZero: true,
      max: 100,
      grid: { color: 'rgba(255, 255, 255, 0.05)', drawBorder: false },
      ticks: { color: '#8b949e', font: { size: 10 }, callback: (v) => v + '%' }
    }
  },
  interaction: { mode: 'nearest', axis: 'x', intersect: false }
}

const networkChartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  animation: false,
  plugins: {
    legend: { display: false },
    tooltip: {
      mode: 'index',
      intersect: false,
      backgroundColor: 'rgba(0, 0, 0, 0.8)',
      titleColor: '#fff',
      bodyColor: '#fff',
      borderColor: '#333',
      borderWidth: 1,
      padding: 10,
      displayColors: true,
      callbacks: {
        label: (context) => `${context.dataset.label}: ${context.parsed.y.toFixed(2)} Mbps`
      }
    }
  },
  scales: {
    x: { display: false },
    y: { 
      beginAtZero: true,
      grid: { color: 'rgba(255, 255, 255, 0.05)', drawBorder: false },
      ticks: { color: '#8b949e', font: { size: 10 }, callback: (v) => v.toFixed(1) + ' Mbps' }
    }
  },
  interaction: { mode: 'nearest', axis: 'x', intersect: false }
}

const thermalsChartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  animation: false,
  plugins: {
    legend: { display: false },
    tooltip: {
      mode: 'index',
      intersect: false,
      backgroundColor: 'rgba(0, 0, 0, 0.8)',
      titleColor: '#fff',
      bodyColor: '#fff',
      borderColor: '#333',
      borderWidth: 1,
      padding: 10,
      displayColors: true,
      callbacks: {
        label: (context) => `${context.dataset.label}: ${context.parsed.y.toFixed(0)}°C`
      }
    }
  },
  scales: {
    x: { display: false },
    y: { 
      beginAtZero: true,
      suggestedMax: 100,
      grid: { color: 'rgba(255, 255, 255, 0.05)', drawBorder: false },
      ticks: { color: '#8b949e', font: { size: 10 }, callback: (v) => v + '°C' }
    }
  },
  interaction: { mode: 'nearest', axis: 'x', intersect: false }
}

const storageChartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  animation: false,
  plugins: {
    legend: { display: false },
    tooltip: {
      mode: 'index',
      intersect: false,
      backgroundColor: 'rgba(0, 0, 0, 0.8)',
      titleColor: '#fff',
      bodyColor: '#fff',
      borderColor: '#333',
      borderWidth: 1,
      padding: 10,
      displayColors: true,
      callbacks: {
        label: (context) => {
          if (context.dataset.yAxisID === 'y1') {
            return `${context.dataset.label}: ${context.parsed.y.toFixed(2)} MB/s`
          }
          return `${context.dataset.label}: ${context.parsed.y.toFixed(1)}%`
        }
      }
    }
  },
  scales: {
    x: { display: false },
    y: { 
      type: 'linear',
      position: 'left',
      beginAtZero: true,
      max: 100,
      grid: { color: 'rgba(255, 255, 255, 0.05)', drawBorder: false },
      ticks: { color: '#a855f7', font: { size: 9 }, callback: (v) => v + '%' }
    },
    y1: {
      type: 'linear',
      position: 'right',
      beginAtZero: true,
      grid: { display: false },
      ticks: { color: '#8b949e', font: { size: 9 }, callback: (v) => v.toFixed(0) + ' MB/s' }
    }
  },
  interaction: { mode: 'nearest', axis: 'x', intersect: false }
}

// Methods
const copyToClipboard = async (text) => {
  try {
    // Try modern clipboard API first
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
    } else {
      // Fallback for non-HTTPS contexts
      const textArea = document.createElement('textarea')
      textArea.value = text
      textArea.style.position = 'fixed'
      textArea.style.left = '-999999px'
      textArea.style.top = '-999999px'
      document.body.appendChild(textArea)
      textArea.focus()
      textArea.select()
      const success = document.execCommand('copy')
      document.body.removeChild(textArea)
      if (!success) throw new Error('execCommand copy failed')
    }
    copied.value = true
    setTimeout(() => copied.value = false, 2000)
  } catch (err) {
    console.error('Failed to copy:', err)
    alert('Failed to copy to clipboard')
  }
}

const getPrimaryDiskUsage = () => {
  const disks = latestMetrics.value?.disks
  if (!disks?.length) return 0
  return disks[0].usage_percent?.toFixed(0) || 0
}

const formatNetworkSpeed = (bytesPerSec) => {
  if (!bytesPerSec || bytesPerSec === 0) return '0 B/s'
  const k = 1024
  const sizes = ['B/s', 'KB/s', 'MB/s', 'GB/s']
  const i = Math.floor(Math.log(bytesPerSec) / Math.log(k))
  return (bytesPerSec / Math.pow(k, i)).toFixed(1) + ' ' + sizes[i]
}

const formatNetworkSpeedMbps = (bytesPerSec) => {
  if (!bytesPerSec || bytesPerSec === 0) return '0 Mbps'
  const mbps = (bytesPerSec * 8) / 1000000
  if (mbps < 0.01) return '< 0.01 Mbps'
  return mbps.toFixed(2) + ' Mbps'
}

const getCpuTemp = () => {
  const temp = latestMetrics.value?.cpu_temp
  if (!temp || temp === 0) return 'N/A'
  return temp.toFixed(0) + '°C'
}

const getCpuTrend = () => {
  if (metricsBuffer.value.length < 2) return ''
  const recent = metricsBuffer.value.slice(-5)
  const avg = recent.reduce((s, m) => s + (m.cpu_percent || 0), 0) / recent.length
  const latest = recent[recent.length - 1]?.cpu_percent || 0
  if (latest > avg * 1.1) return '↑'
  if (latest < avg * 0.9) return '↓'
  return '→'
}

const getCpuTrendClass = () => {
  const trend = getCpuTrend()
  if (trend === '↑') return 'trend-up'
  if (trend === '↓') return 'trend-down'
  return ''
}

// New 2x2 Grid Helper Methods
const formatTemp = (temp) => {
  if (!temp || temp === 0) return 'N/A'
  return temp.toFixed(0) + '°C'
}

const formatNetworkCompact = (bytesPerSec) => {
  if (!bytesPerSec || bytesPerSec === 0) return '0'
  const mbps = (bytesPerSec * 8) / 1000000
  if (mbps < 1) return mbps.toFixed(1)
  return mbps.toFixed(0)
}

const formatDiskSpeed = (bytesPerSec) => {
  if (!bytesPerSec || bytesPerSec === 0) return '0 B/s'
  const k = 1024
  const sizes = ['B/s', 'KB/s', 'MB/s', 'GB/s']
  const i = Math.floor(Math.log(bytesPerSec) / Math.log(k))
  return (bytesPerSec / Math.pow(k, i)).toFixed(1) + ' ' + sizes[i]
}

const formatDriveLabel = (mountpoint) => {
  if (!mountpoint) return 'Unknown'
  // Windows: C:, D:, etc
  if (mountpoint.match(/^[A-Z]:$/i)) return mountpoint
  // Linux: / becomes "Root", /home becomes "home"
  if (mountpoint === '/') return 'Root'
  return mountpoint.split('/').pop() || mountpoint
}

// System Info Helper Methods
const formatBytes = (bytes) => {
  if (!bytes || bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return (bytes / Math.pow(k, i)).toFixed(2) + ' ' + sizes[i]
}

const formatUptime = (seconds) => {
  if (!seconds) return 'Unknown'
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const mins = Math.floor((seconds % 3600) / 60)
  if (days > 0) return `${days}d ${hours}h ${mins}m`
  if (hours > 0) return `${hours}h ${mins}m`
  return `${mins}m`
}

const formatFrequency = (mhz) => {
  if (!mhz) return 'Unknown'
  if (mhz >= 1000) return (mhz / 1000).toFixed(2) + ' GHz'
  return mhz.toFixed(0) + ' MHz'
}

const formatCacheSize = (bytes) => {
  if (!bytes) return 'Unknown'
  const kb = bytes / 1024
  if (kb >= 1024) return (kb / 1024).toFixed(1) + ' MB'
  return kb.toFixed(0) + ' KB'
}

const formatDateTime = (isoString) => {
  if (!isoString) return ''
  try {
    const date = new Date(isoString)
    return date.toLocaleString()
  } catch {
    return isoString
  }
}

const getDiskUsagePercent = (disk) => {
  if (!disk.total_bytes || disk.total_bytes === 0) return 0
  return ((disk.total_bytes - disk.free_bytes) / disk.total_bytes) * 100
}

const getDiskUsageClass = (disk) => {
  const percent = getDiskUsagePercent(disk)
  if (percent > 90) return 'bg-danger'
  if (percent > 75) return 'bg-warning'
  return 'bg-success'
}

const truncateIPv6 = (ipv6) => {
  if (!ipv6) return ''
  if (ipv6.length <= 20) return ipv6
  return ipv6.substring(0, 17) + '...'
}

// OS display helpers
const formatOS = (os) => {
  if (!os) return ''
  const osMap = {
    'windows': 'Windows',
    'linux': 'Linux',
    'darwin': 'macOS',
    'freebsd': 'FreeBSD',
    'openbsd': 'OpenBSD',
    'netbsd': 'NetBSD'
  }
  return osMap[os.toLowerCase()] || os
}

const getOSIcon = (os) => {
  if (!os) return '💻'
  const lower = os.toLowerCase()
  if (lower === 'windows') return '🪟'
  if (lower === 'linux') return '🐧'
  if (lower === 'darwin') return '🍎'
  return '💻'
}

const getCpuColorClass = () => {
  const cpu = latestMetrics.value?.cpu_percent || 0
  if (cpu > 90) return 'text-danger'
  if (cpu > 70) return 'text-warning'
  return ''
}

const getTempColorClass = (temp) => {
  if (!temp || temp === 0) return 'text-secondary'
  if (temp > 85) return 'text-danger'
  if (temp > 70) return 'text-warning'
  return ''
}

const getStorageColorClass = (percent) => {
  if (percent > 90) return 'storage-critical'
  if (percent > 75) return 'storage-warning'
  return 'storage-ok'
}

const getSelectedDriveUsage = () => {
  const disks = latestMetrics.value?.disks || []
  if (!disks.length) return 0
  
  // Auto-select first drive if none selected
  if (!selectedDrive.value && disks.length > 0) {
    selectedDrive.value = disks[0].mountpoint
  }
  
  const drive = disks.find(d => d.mountpoint === selectedDrive.value)
  return drive?.usage_percent || 0
}

const getSelectedDriveReadBps = () => {
  const disks = latestMetrics.value?.disks || []
  const drive = disks.find(d => d.mountpoint === selectedDrive.value)
  return drive?.read_bps || 0
}

const getSelectedDriveWriteBps = () => {
  const disks = latestMetrics.value?.disks || []
  const drive = disks.find(d => d.mountpoint === selectedDrive.value)
  return drive?.write_bps || 0
}

const selectTimeRange = async (range) => {
  selectedTimeRange.value = range
  if (range === 'live') {
    // For offline agents, 'live' shows the last known data (same as 1h from last_seen)
    if (isOffline.value) {
      // Fetch last hour before the agent went offline
      await fetchOfflineMetrics('1h')
      return
    }
    // Reset to live WebSocket data
    if (metricsBuffer.value.length > 0) {
      updateChartFromData(metricsBuffer.value)
    }
    return
  }
  
  // For offline agents, calculate time ranges relative to last_seen
  // For online agents, use current time
  const endTime = isOffline.value && lastSeenDate.value ? lastSeenDate.value : new Date()
  let startTime, downsample
  
  switch (range) {
    case '1h':
      startTime = new Date(endTime - 60 * 60 * 1000) // 1 hour before end
      downsample = null // Raw data
      break
    case '24h':
      startTime = new Date(endTime - 24 * 60 * 60 * 1000) // 24 hours before end
      downsample = '10min' // Aggregate by 10 minutes
      break
    case '7d':
      startTime = new Date(endTime - 7 * 24 * 60 * 60 * 1000) // 7 days before end
      downsample = 'hour' // Aggregate by hour
      break
    case '30d':
      startTime = new Date(endTime - 30 * 24 * 60 * 60 * 1000) // 30 days before end
      downsample = 'day' // Aggregate by day
      break
    default:
      return
  }
  
  // Build query params
  const params = new URLSearchParams()
  params.append('start_time', startTime.toISOString())
  params.append('end_time', endTime.toISOString())
  if (downsample) {
    params.append('downsample', downsample)
  }
  
  // Fetch historical data
  try {
    const response = await axios.get(`/api/agents/${props.agent.agent_id}/metrics?${params}`)
    const data = response.data.metrics || []
    // Data comes from backend in ASC order (oldest to newest), ready for chart display
    updateChartFromData(data)
    
    // For offline agents, set the latest metric if we have data
    if (isOffline.value && data.length > 0) {
      latestMetrics.value = data[data.length - 1]
    }
  } catch (err) {
    console.error('Error fetching history:', err)
  }
}

// Fetch metrics for offline agents (relative to last_seen)
const fetchOfflineMetrics = async (range = '1h') => {
  if (!lastSeenDate.value) return
  
  const endTime = lastSeenDate.value
  const rangeMs = { '1h': 60 * 60 * 1000, '10m': 10 * 60 * 1000 }
  const startTime = new Date(endTime - (rangeMs[range] || rangeMs['1h']))
  
  const params = new URLSearchParams()
  params.append('start_time', startTime.toISOString())
  params.append('end_time', endTime.toISOString())
  
  try {
    const response = await axios.get(`/api/agents/${props.agent.agent_id}/metrics?${params}`)
    const data = response.data.metrics || []
    if (data.length > 0) {
      metricsBuffer.value = data
      updateChartFromData(data)
      latestMetrics.value = data[data.length - 1]
    }
  } catch (err) {
    console.error('Error fetching offline metrics:', err)
  }
}

const formatTimeRangeDisplay = () => {
  // For offline agents, show time range relative to last_seen
  const endTime = isOffline.value && lastSeenDate.value ? lastSeenDate.value : new Date()
  const rangeHours = { '1h': 1, '24h': 24, '7d': 168, '30d': 720 }
  const hours = rangeHours[selectedTimeRange.value] || 1
  const start = new Date(endTime - hours * 60 * 60 * 1000)
  
  if (isOffline.value) {
    return `${start.toLocaleString()} - ${endTime.toLocaleString()} (last active)`
  }
  return `${start.toLocaleString()} - ${endTime.toLocaleString()}`
}

const updateChartFromData = (data) => {
  const labels = data.map(m => new Date(m.timestamp).toLocaleTimeString())
  
  // Get selected drive's data for storage chart
  const getDriveData = (metric, field) => {
    const disks = metric.disks || []
    const drive = disks.find(d => d.mountpoint === selectedDrive.value) || disks[0]
    return drive ? (drive[field] || 0) : 0
  }
  
  chartData.value = {
    labels,
    // Load chart
    cpu: data.map(m => m.cpu_percent || 0),
    ram: data.map(m => m.ram_percent || 0),
    gpu: data.map(m => m.gpu_percent || 0),
    // Network chart - Convert bytes/sec to Mbps (bytes * 8 / 1,000,000)
    netSent: data.map(m => ((m.net_sent_bps || 0) * 8) / 1000000),
    netRecv: data.map(m => ((m.net_recv_bps || 0) * 8) / 1000000),
    // Thermals chart
    cpuTemp: data.map(m => m.cpu_temp || 0),
    gpuTemp: data.map(m => m.gpu_temp || 0),
    // Storage chart - Convert bytes/sec to MB/s
    diskUsage: data.map(m => getDriveData(m, 'usage_percent')),
    diskRead: data.map(m => (getDriveData(m, 'read_bps') || m.disk_read_bps || 0) / (1024 * 1024)),
    diskWrite: data.map(m => (getDriveData(m, 'write_bps') || m.disk_write_bps || 0) / (1024 * 1024))
  }
}

const formatLogTime = (ts) => new Date(ts).toLocaleString()

const getSeverityBadgeClass = (severity) => {
  const s = (severity || '').toUpperCase()
  if (s === 'CRITICAL') return 'bg-danger'
  if (s === 'ERROR') return 'bg-warning text-dark'
  if (s.includes('WARN')) return 'bg-info text-dark'
  return 'bg-secondary'
}

const getAlertIcon = (type) => {
  const icons = {
    'agent_offline': '●',
    'cpu_high': '●',
    'ram_high': '●',
    'disk_low': '●'
  }
  return icons[type] || '●'
}

const formatAlertType = (type) => {
  const names = {
    'agent_offline': 'Agent Offline',
    'cpu_high': 'High CPU',
    'ram_high': 'High Memory',
    'disk_low': 'Low Disk Space'
  }
  return names[type] || type
}

const formatAlertTime = (ts) => {
  const date = new Date(ts)
  const diff = (Date.now() - date) / 60000
  if (diff < 60) return `${Math.floor(diff)}m ago`
  if (diff < 1440) return `${Math.floor(diff / 60)}h ago`
  return date.toLocaleDateString()
}

// API Methods
const fetchRawLogs = async () => {
  if (!props.agent?.agent_id) return
  loadingRawLogs.value = true
  try {
    const params = new URLSearchParams({ limit: 100, offset: rawLogsPagination.value.offset })
    if (rawLogFilters.value.severity) params.append('severity', rawLogFilters.value.severity)
    if (rawLogFilters.value.source) params.append('source', rawLogFilters.value.source)
    if (rawLogFilters.value.search) params.append('search', rawLogFilters.value.search)
    
    const response = await axios.get(`/api/agents/${props.agent.agent_id}/raw-logs?${params}`)
    rawLogs.value = response.data.logs || []
    rawLogsPagination.value.total_count = response.data.total_count || 0
    rawLogsPagination.value.has_more = response.data.has_more || false
    
    // Fetch stats
    const statsRes = await axios.get(`/api/agents/${props.agent.agent_id}/log-stats`)
    rawLogStats.value = {
      critical: statsRes.data.by_severity?.CRITICAL || 0,
      error: statsRes.data.by_severity?.ERROR || 0,
      warning: (statsRes.data.by_severity?.WARN || 0) + (statsRes.data.by_severity?.WARNING || 0),
      total: statsRes.data.total_logs || 0
    }
  } catch (err) {
    console.error('Error fetching logs:', err)
  } finally {
    loadingRawLogs.value = false
  }
}

const fetchAlertRules = async () => {
  if (!props.agent?.agent_id) return
  try {
    const response = await axios.get(`/api/agents/${props.agent.agent_id}/alert-rules`)
    // Handle null response - use defaults if no rules exist
    alertRules.value = response.data || {
      monitor_uptime: true,
      cpu_percent_threshold: null,
      ram_percent_threshold: null,
      disk_free_percent_threshold: null
    }
  } catch (err) {
    console.error('Error fetching alert rules:', err)
  }
  fetchActiveAlerts()
  fetchEffectiveRules()
}

const fetchEffectiveRules = async () => {
  if (!props.agent?.agent_id) return
  loadingEffectiveRules.value = true
  try {
    const [rulesRes, channelsRes] = await Promise.all([
      axios.get(`/api/agents/${props.agent.agent_id}/effective-rules`),
      axios.get('/api/notifications/channels')
    ])
    effectiveRules.value = rulesRes.data.rules || []
    notificationChannels.value = channelsRes.data.channels || []
  } catch (err) {
    console.error('Error fetching effective rules:', err)
  } finally {
    loadingEffectiveRules.value = false
  }
}

const toggleRuleOverride = async (rule, action) => {
  try {
    if (action === 'disable') {
      await axios.put(`/api/agents/${props.agent.agent_id}/rule-overrides/${rule.id}`, {
        disabled: true
      })
    } else if (action === 'enable') {
      await axios.delete(`/api/agents/${props.agent.agent_id}/rule-overrides/${rule.id}`)
    }
    await fetchEffectiveRules()
  } catch (err) {
    console.error('Error toggling rule override:', err)
  }
}

const formatRuleCondition = (rule) => {
  const metricNames = {
    cpu: 'CPU',
    ram: 'Memory',
    disk: 'Disk',
    disk_free: 'Free disk',
    cpu_temp: 'CPU temp',
    net_bandwidth: 'Network',
    status: 'Offline'
  }
  const opSymbols = {
    gt: '>',
    gte: '≥',
    lt: '<',
    lte: '≤',
    eq: '=',
    ne: '≠'
  }
  const units = {
    cpu: '%',
    ram: '%',
    disk: '%',
    disk_free: '%',
    cpu_temp: '°C'
  }
  
  const metric = metricNames[rule.metric] || rule.metric
  const op = opSymbols[rule.operator] || rule.operator
  const unit = units[rule.metric] || ''
  
  return `${metric} ${op} ${rule.threshold}${unit}`
}

const fetchActiveAlerts = async () => {
  if (!props.agent?.agent_id) return
  loadingAlerts.value = true
  try {
    const response = await axios.get(`/api/agents/${props.agent.agent_id}/alerts`)
    activeAlerts.value = response.data.alerts || []
  } catch (err) {
    console.error('Error fetching alerts:', err)
  } finally {
    loadingAlerts.value = false
  }
}

const saveAlertRules = async () => {
  savingRules.value = true
  try {
    await axios.put(`/api/agents/${props.agent.agent_id}/alert-rules`, alertRules.value)
  } catch (err) {
    console.error('Error saving rules:', err)
  } finally {
    savingRules.value = false
  }
}

const resolveAlert = async (alertId) => {
  try {
    await axios.post(`/api/alerts/${alertId}/resolve`)
    fetchActiveAlerts()
  } catch (err) {
    console.error('Error resolving alert:', err)
  }
}

const fetchLogSettings = async () => {
  if (!props.agent?.agent_id) return
  try {
    const response = await axios.get(`/api/agents/${props.agent.agent_id}/log-settings`)
    // Handle null response - use defaults if no settings exist
    logSettings.value = response.data || {
      logging_enabled: false,
      log_level_threshold: 'ERROR',
      log_retention_days: null,
      watch_docker_containers: false,
      watch_system_logs: true,
      watch_security_logs: false,
      troubleshooting_mode: false
    }
  } catch (err) {
    console.error('Error fetching log settings:', err)
  }
}

const saveLogSettings = async () => {
  savingLogSettings.value = true
  try {
    await axios.put(`/api/agents/${props.agent.agent_id}/log-settings`, logSettings.value)
    showToast('success', 'Configuration saved!')
  } catch (err) {
    console.error('Error saving log settings:', err)
    showToast('error', 'Failed to save configuration')
  } finally {
    savingLogSettings.value = false
  }
}

const toggleAgentStatus = async () => {
  statusLoading.value = true
  try {
    const newEnabled = props.agent.enabled === false
    await axios.patch(`/api/agents/${props.agent.agent_id}`, { enabled: newEnabled })
    emit('status-changed', props.agent.agent_id, newEnabled)
  } catch (err) {
    console.error('Error toggling status:', err)
  } finally {
    statusLoading.value = false
  }
}

const restartAgent = async () => {
  restartLoading.value = true
  try {
    await axios.post(`/api/agents/${props.agent.agent_id}/restart`)
    // The agent will disconnect and reconnect
  } catch (err) {
    console.error('Error restarting agent:', err)
    alert('Failed to restart agent: ' + (err.response?.data?.detail || err.message))
  } finally {
    restartLoading.value = false
  }
}

// Rename functionality
const startNameEdit = () => {
  editedName.value = props.agent?.display_name || ''
  isEditingName.value = true
  // Focus input after DOM update
  setTimeout(() => nameInput.value?.focus(), 50)
}

const cancelNameEdit = () => {
  isEditingName.value = false
  editedName.value = ''
}

const saveName = async () => {
  try {
    await axios.put(`/api/agents/${props.agent.agent_id}/rename`, { 
      display_name: editedName.value.trim() 
    })
    // Update local agent object
    if (props.agent) {
      props.agent.display_name = editedName.value.trim()
    }
    isEditingName.value = false
  } catch (err) {
    console.error('Error renaming agent:', err)
  }
}

// Tags functionality - auto-save on change
const onTagsChange = async (newTags) => {
  if (!props.agent?.agent_id) return
  
  // Only save if different from current
  if (newTags === props.agent.tags) return
  
  savingTags.value = true
  try {
    await axios.put(`/api/agents/${props.agent.agent_id}/tags`, { 
      tags: newTags 
    })
    // Update local agent object
    if (props.agent) {
      props.agent.tags = newTags
    }
  } catch (err) {
    console.error('Error updating tags:', err)
  } finally {
    savingTags.value = false
  }
}

// Initialize localTags when agent changes
watch(() => props.agent?.tags, (newVal) => {
  localTags.value = newVal || ''
}, { immediate: true })

// Initialize localUptimeWindow when agent changes
watch(() => props.agent?.uptime_window, (newVal) => {
  localUptimeWindow.value = newVal || 'monthly'
}, { immediate: true })

// Computed label for uptime window
const uptimeWindowLabel = computed(() => {
  const labels = {
    'daily': 'Daily (Last 24 hours)',
    'weekly': 'Weekly (Last 7 days)',
    'monthly': 'Monthly (Last 30 days)',
    'quarterly': 'Quarterly (Last 90 days)',
    'yearly': 'Yearly (Last 365 days)'
  }
  return labels[localUptimeWindow.value] || labels['monthly']
})

// Handle uptime window changes
const onUptimeWindowChange = async () => {
  if (!props.agent?.agent_id) return
  
  savingUptimeWindow.value = true
  try {
    await axios.put(`/api/agents/${props.agent.agent_id}/uptime-window`, {
      uptime_window: localUptimeWindow.value
    })
    // Emit refresh event so parent can update agent data
    emit('refresh')
  } catch (err) {
    console.error('Error updating uptime window:', err)
    // Revert on error
    localUptimeWindow.value = props.agent.uptime_window || 'monthly'
  } finally {
    savingUptimeWindow.value = false
  }
}

const confirmDelete = async () => {
  try {
    await axios.delete(`/api/agents/${props.agent.agent_id}`)
    showDeleteConfirm.value = false
    emit('deleted', props.agent.agent_id)
    emit('close')
  } catch (err) {
    console.error('Error deleting agent:', err)
  }
}

// WebSocket Management
const wsReconnectAttempts = ref(0)
const wsMaxReconnectAttempts = 10
const wsReconnectDelay = ref(1000)
let wsReconnectTimeout = null

const connectWebSocket = () => {
  if (!props.agent?.agent_id) return
  
  // Clear any pending reconnect
  if (wsReconnectTimeout) {
    clearTimeout(wsReconnectTimeout)
    wsReconnectTimeout = null
  }
  
  // Don't connect if already connected or connecting
  if (wsInstance.value?.readyState === WebSocket.OPEN || wsInstance.value?.readyState === WebSocket.CONNECTING) {
    console.log('WebSocket already connected/connecting, skipping')
    return
  }
  
  // Build WebSocket URL dynamically based on current location
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const wsUrl = `${protocol}//${window.location.host}/api/ws/ui/${props.agent.agent_id}`
  wsInstance.value = new WebSocket(wsUrl)
  
  wsInstance.value.onopen = () => {
    wsConnected.value = true
    wsReconnectAttempts.value = 0
    wsReconnectDelay.value = 1000
    console.log('WebSocket connected')
  }
  
  wsInstance.value.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      
      // Backend sends flat metric object, not wrapped in metrics array
      if (data.cpu_percent !== undefined) {
        // Transform to expected metric format
        const metric = {
          timestamp: data.timestamp,
          cpu_percent: data.cpu_percent,
          ram_percent: data.ram_percent,
          net_sent_bps: data.net_up || 0,
          net_recv_bps: data.net_down || 0,
          disk_read_bps: data.disk_read || 0,
          disk_write_bps: data.disk_write || 0,
          cpu_temp: data.cpu_temp,
          cpu_name: data.cpu_name || '',
          gpu_percent: data.gpu_percent || 0,
          gpu_temp: data.gpu_temp || 0,
          gpu_name: data.gpu_name || '',
          is_vm: data.is_vm || false,
          disks: data.disks || [],
          ping_latency_ms: data.ping
        }
        
        latestMetrics.value = metric
        metricsBuffer.value.push(metric)
        if (metricsBuffer.value.length > 60) metricsBuffer.value.shift()
        
        // Auto-select first drive if not set
        if (!selectedDrive.value && metric.disks?.length > 0) {
          selectedDrive.value = metric.disks[0].mountpoint
        }
        
        if (selectedTimeRange.value === 'live') {
          updateChartFromData(metricsBuffer.value)
        }
      }
      
      if (data.processes) {
        processData.value = data.processes
      }
    } catch (err) {
      console.error('Error parsing WS message:', err)
    }
  }
  
  wsInstance.value.onclose = (event) => {
    wsConnected.value = false
    wsInstance.value = null
    
    // Auto-reconnect with exponential backoff (only if modal is still open and agent is online)
    if (props.agent && !event.wasClean && wsReconnectAttempts.value < wsMaxReconnectAttempts) {
      wsReconnectAttempts.value++
      const delay = Math.min(wsReconnectDelay.value * Math.pow(2, wsReconnectAttempts.value - 1), 30000)
      console.log(`WebSocket closed, reconnecting in ${delay}ms (attempt ${wsReconnectAttempts.value}/${wsMaxReconnectAttempts})`)
      wsReconnectTimeout = setTimeout(() => {
        if (props.agent && props.agent.status === 'online') {
          connectWebSocket()
        }
      }, delay)
    }
  }
  
  wsInstance.value.onerror = (error) => {
    console.error('WebSocket error:', error)
  }
}

const disconnectWebSocket = () => {
  // Clear any pending reconnect
  if (wsReconnectTimeout) {
    clearTimeout(wsReconnectTimeout)
    wsReconnectTimeout = null
  }
  wsReconnectAttempts.value = 0
  
  if (wsInstance.value) {
    console.log('Disconnecting WebSocket for agent:', props.agent?.agent_id)
    wsInstance.value.close(1000, 'Modal closed')  // Normal closure with reason
    wsInstance.value = null
    wsConnected.value = false
  }
}

// Fetch initial metrics to populate charts immediately
const fetchInitialMetrics = async () => {
  if (!props.agent?.agent_id) return
  metricsLoading.value = true
  try {
    let startTime, endTime
    
    if (isOffline.value && lastSeenDate.value) {
      // For offline agents, fetch the last hour before they went offline
      endTime = lastSeenDate.value
      startTime = new Date(endTime - 60 * 60 * 1000) // 1 hour before last_seen
    } else {
      // For online agents, fetch last 10 minutes
      endTime = new Date()
      startTime = new Date(endTime - 10 * 60 * 1000)
    }
    
    const params = new URLSearchParams()
    params.append('start_time', startTime.toISOString())
    params.append('end_time', endTime.toISOString())
    
    const response = await axios.get(`/api/agents/${props.agent.agent_id}/metrics?${params}`)
    const data = response.data.metrics || []
    if (data.length > 0) {
      // Data comes in ASC order (oldest to newest), ready for chart
      metricsBuffer.value = data
      updateChartFromData(data)
      // Set latest metric for the stat cards (last item is newest)
      latestMetrics.value = data[data.length - 1]
      
      // Auto-select first drive if available
      if (!selectedDrive.value && latestMetrics.value?.disks?.length > 0) {
        selectedDrive.value = latestMetrics.value.disks[0].mountpoint
      }
    }
  } catch (err) {
    console.error('Error fetching initial metrics:', err)
  } finally {
    metricsLoading.value = false
  }
}

// Lifecycle
watch(() => props.show, async (newVal) => {
  if (newVal && props.agent) {
    activeTab.value = 'overview'
    selectedTimeRange.value = 'live'
    // Don't clear chart data immediately - keep old data visible while loading new
    // metricsBuffer and chartData will be updated when new data arrives
    metricsBuffer.value = []
    await fetchInitialMetrics()
    
    // Only connect WebSocket for online agents
    if (!isOffline.value) {
      connectWebSocket()
    }
    fetchActiveAlerts()
  } else {
    disconnectWebSocket()
  }
})

// Watch for agent changes while modal is open (switching between agents)
watch(() => props.agent?.agent_id, async (newId, oldId) => {
  if (newId && newId !== oldId && props.show) {
    // Agent changed while modal is open - refresh data smoothly
    metricsBuffer.value = []
    disconnectWebSocket()
    await fetchInitialMetrics()
    if (!isOffline.value) {
      connectWebSocket()
    }
    fetchActiveAlerts()
  }
})

onUnmounted(() => {
  disconnectWebSocket()
})
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.85);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1050;
  backdrop-filter: blur(8px);
  padding: 2rem;
  animation: fadeIn 0.15s ease-out;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.modal-container {
  background: var(--bg-card, #161b22);
  animation: slideIn 0.15s ease-out;
  border-radius: 16px;
  width: 100%;
  max-width: 1200px;
  height: calc(100vh - 4rem);
  max-height: 900px;
  min-height: 700px;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border-color, #30363d);
  box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
}

@keyframes slideIn {
  from { 
    opacity: 0;
    transform: scale(0.95) translateY(-10px);
  }
  to { 
    opacity: 1;
    transform: scale(1) translateY(0);
  }
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem 1.5rem;
  border-bottom: 1px solid var(--border-color, #30363d);
  background: linear-gradient(135deg, rgba(88, 166, 255, 0.05), transparent);
}

.status-indicator {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  flex-shrink: 0;
}

.status-indicator.online {
  background: #3fb950;
  box-shadow: 0 0 10px rgba(63, 185, 80, 0.5);
}

.status-indicator.offline {
  background: #f85149;
}

/* Offline Banner */
.offline-banner {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem 1rem;
  background: linear-gradient(135deg, rgba(248, 81, 73, 0.15), rgba(248, 81, 73, 0.05));
  border: 1px solid rgba(248, 81, 73, 0.3);
  border-radius: 8px;
  color: #f8d7da;
}

.offline-icon {
  font-size: 1.25rem;
}

.offline-text {
  flex: 1;
  font-size: 0.9rem;
}

.offline-text strong {
  color: #f85149;
}

.offline-text span {
  color: #9ca3af;
}

.offline-hint {
  font-size: 0.75rem;
  color: #6b7280;
  font-style: italic;
}

.live-badge {
  font-size: 0.7rem;
  padding: 0.25rem 0.5rem;
  display: flex;
  align-items: center;
  gap: 0.25rem;
}

.live-dot {
  width: 6px;
  height: 6px;
  background: currentColor;
  border-radius: 50%;
  animation: pulse 1.5s infinite;
}

/* Rename input */
.name-edit-input {
  background: var(--bg-secondary, #0d1117);
  border: 1px solid var(--accent-color, #58a6ff);
  color: var(--text-primary, #c9d1d9);
  max-width: 200px;
}

.name-edit-input:focus {
  background: var(--bg-secondary, #0d1117);
  border-color: var(--accent-color, #58a6ff);
  color: var(--text-primary, #c9d1d9);
  box-shadow: 0 0 0 2px rgba(88, 166, 255, 0.2);
}

.rename-btn {
  opacity: 0.5;
  transition: opacity 0.2s;
  font-size: 0.9rem;
}

.rename-btn:hover {
  opacity: 1;
}

/* Tags styling */
.tags-row {
  padding-top: 0.25rem;
}

.tags-label {
  font-size: 0.8rem;
  color: var(--text-muted, #8b949e);
}

.tags-display {
  display: flex;
  align-items: center;
  cursor: pointer;
  padding: 0.25rem 0.5rem;
  border-radius: 4px;
  transition: background 0.15s;
}

.tags-display:hover {
  background: rgba(255, 255, 255, 0.05);
}

.tag-badge {
  display: inline-block;
  background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
  color: white;
  padding: 0.15rem 0.5rem;
  border-radius: 12px;
  font-size: 0.75rem;
  font-weight: 500;
}

.edit-tags-btn {
  opacity: 0.4;
  transition: opacity 0.2s;
  font-size: 0.85rem;
}

.tags-display:hover .edit-tags-btn {
  opacity: 1;
}

.tags-edit-input {
  background: var(--bg-secondary, #0d1117);
  border: 1px solid var(--accent-color, #58a6ff);
  color: var(--text-primary, #c9d1d9);
  min-width: 200px;
  max-width: 300px;
}

.tags-edit-input:focus {
  background: var(--bg-secondary, #0d1117);
  border-color: var(--accent-color, #58a6ff);
  color: var(--text-primary, #c9d1d9);
  box-shadow: 0 0 0 2px rgba(88, 166, 255, 0.2);
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.modal-tabs {
  display: flex;
  gap: 0.25rem;
  padding: 0.5rem 1rem;
  background: var(--bg-secondary, #0d1117);
  overflow-x: auto;
}

.tab-btn {
  background: transparent;
  border: none;
  color: var(--text-secondary, #8b949e);
  padding: 0.5rem 1rem;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
  position: relative;
}

.tab-btn:hover {
  background: rgba(255, 255, 255, 0.05);
  color: var(--text-primary, #c9d1d9);
}

.tab-btn.active {
  background: var(--primary, #58a6ff);
  color: white;
}

.alert-badge {
  position: absolute;
  top: 0;
  right: 0;
  transform: translate(50%, -50%);
  background: #f85149;
  color: white;
  font-size: 0.65rem;
  padding: 0.1rem 0.4rem;
  border-radius: 10px;
  min-width: 16px;
  text-align: center;
}

.modal-body {
  flex: 1;
  overflow-y: auto;
  padding: 1.5rem;
  position: relative;
}

.metrics-loading-overlay {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 4rem 2rem;
  text-align: center;
}

.tab-content-pane {
  animation: fadeIn 0.2s ease;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

/* Metrics Overview */
.metrics-overview {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 1rem;
}

.metric-card {
  background: var(--bg-secondary, #0d1117);
  border: 1px solid var(--border-color, #30363d);
  border-radius: 12px;
  padding: 1rem;
  display: flex;
  align-items: center;
  gap: 1rem;
}

.metric-icon {
  font-size: 1.5rem;
  opacity: 0.8;
}

.metric-info {
  flex: 1;
}

.metric-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--primary, #58a6ff);
}

.metric-label {
  font-size: 0.75rem;
  color: var(--text-secondary, #8b949e);
}

.metric-trend {
  font-size: 1.25rem;
  font-weight: 700;
}

.trend-up { color: #f85149; }
.trend-down { color: #3fb950; }

/* Network card combined styles */
.network-info {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.network-row {
  display: flex;
  align-items: center;
  gap: 0.35rem;
}

.network-label {
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--text-secondary, #8b949e);
  width: 1rem;
}

.network-value {
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--primary, #58a6ff);
}

/* Charts */
.charts-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
  gap: 1rem;
}

.chart-card {
  background: var(--bg-secondary, #0d1117);
  border: 1px solid var(--border-color, #30363d);
  border-radius: 12px;
  padding: 1.25rem;
}

.chart-title {
  margin-bottom: 0.75rem;
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-primary, #e6edf3);
}

.chart-container {
  height: 200px;
}

.chart-placeholder {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.chart-legend {
  display: flex;
  gap: 1.5rem;
  margin-top: 0.75rem;
  padding-top: 0.75rem;
  border-top: 1px solid var(--border-color, #30363d);
  font-size: 0.85rem;
  color: var(--text-secondary, #8b949e);
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.legend-dot {
  width: 10px;
  height: 10px;
  border-radius: 2px;
  flex-shrink: 0;
}

/* Log Stats */
.log-stats {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.stat-pill {
  padding: 0.35rem 0.75rem;
  border-radius: 20px;
  font-size: 0.8rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.stat-pill .stat-value {
  font-weight: 700;
}

/* Logs Table */
.logs-table-container {
  max-height: 400px;
  overflow-y: auto;
  border-radius: 8px;
  border: 1px solid var(--border-color, #30363d);
}

.log-message {
  max-width: 500px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Config Sections */
.config-section {
  background: var(--bg-secondary, #0d1117);
  border: 1px solid var(--border-color, #30363d);
  border-radius: 12px;
  overflow: hidden;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.75rem 1rem;
  background: rgba(255, 255, 255, 0.02);
  border-bottom: 1px solid var(--border-color, #30363d);
}

.section-body {
  padding: 1rem;
}

/* Alert Rules */
.alert-rule-item {
  padding: 0.75rem 0;
  border-bottom: 1px solid var(--border-color, #30363d);
}

.alert-rule-item:last-child {
  border-bottom: none;
}

.threshold-input {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.threshold-input input {
  width: 70px;
  text-align: center;
}

/* Alerts List */
.alerts-list {
  max-height: 300px;
  overflow-y: auto;
}

.alert-item {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 0.75rem;
  border-radius: 8px;
  background: rgba(248, 81, 73, 0.1);
  margin-bottom: 0.5rem;
}

.alert-item.resolved {
  opacity: 0.5;
  background: rgba(255, 255, 255, 0.02);
}

.alert-icon {
  font-size: 1.25rem;
}

.alert-info {
  flex: 1;
}

.alert-type {
  font-weight: 600;
}

/* Time Range Selector */
.time-range-selector {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.5rem;
}

/* System Summary Bar */
.system-summary {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 1rem;
  padding: 0.75rem 1rem;
  background: var(--bg-secondary, #0d1117);
  border: 1px solid var(--border-color, #30363d);
  border-radius: 10px;
}

.summary-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.summary-label {
  font-size: 0.75rem;
  color: var(--text-secondary, #8b949e);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.summary-value {
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--primary, #58a6ff);
}

.summary-value.gpu-value {
  color: #f59e0b;
}

.summary-value.network-compact {
  font-size: 0.85rem;
  font-family: 'Monaco', 'Menlo', monospace;
}

/* Hardware names stacked */
.hardware-stack {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0.15rem;
  margin-left: auto;
}

.hardware-item {
  font-size: 0.7rem;
  color: var(--text-secondary, #8b949e);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 250px;
}

/* 2x2 Charts Grid */
.charts-grid-2x2 {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  grid-template-rows: auto auto;
  gap: 1rem;
}

@media (max-width: 900px) {
  .charts-grid-2x2 {
    grid-template-columns: 1fr;
  }
}

.charts-grid-2x2 .chart-card {
  background: var(--bg-secondary, #0d1117);
  border: 1px solid var(--border-color, #30363d);
  border-radius: 12px;
  padding: 1rem;
}

.charts-grid-2x2 .chart-title {
  margin-bottom: 0.5rem;
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--text-primary, #e6edf3);
}

.charts-grid-2x2 .chart-container {
  height: 160px;
}

.chart-container-short {
  height: 100px !important;
}

.charts-grid-2x2 .chart-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  margin-top: 0.5rem;
  padding-top: 0.5rem;
  border-top: 1px solid var(--border-color, #30363d);
  font-size: 0.8rem;
  color: var(--text-secondary, #8b949e);
}

/* Storage Card Specifics */
.storage-card {
  display: flex;
  flex-direction: column;
}

.chart-header-with-toggles {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.5rem;
}

.drive-toggles {
  display: flex;
  gap: 0.35rem;
  flex-wrap: wrap;
}

.drive-chip {
  padding: 0.2rem 0.6rem;
  font-size: 0.7rem;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid var(--border-color, #30363d);
  border-radius: 12px;
  color: var(--text-secondary, #8b949e);
  cursor: pointer;
  transition: all 0.2s;
}

.drive-chip:hover {
  background: rgba(255, 255, 255, 0.1);
}

.drive-chip.active {
  background: var(--primary, #58a6ff);
  border-color: var(--primary, #58a6ff);
  color: white;
}

.storage-overview {
  margin-bottom: 0.75rem;
}

.storage-bar-container {
  position: relative;
  height: 24px;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 6px;
  overflow: hidden;
  margin-bottom: 0.5rem;
}

.storage-bar {
  height: 100%;
  border-radius: 6px;
  transition: width 0.3s ease;
}

.storage-bar.storage-ok {
  background: linear-gradient(90deg, #22c55e, #16a34a);
}

.storage-bar.storage-warning {
  background: linear-gradient(90deg, #f59e0b, #d97706);
}

.storage-bar.storage-critical {
  background: linear-gradient(90deg, #ef4444, #dc2626);
}

.storage-percent {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  font-size: 0.75rem;
  font-weight: 700;
  color: white;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.5);
}

.storage-io-stats {
  display: flex;
  gap: 1.5rem;
  font-size: 0.75rem;
}

.io-stat {
  display: flex;
  align-items: center;
  gap: 0.35rem;
}

.io-label {
  color: var(--text-secondary, #8b949e);
}

.io-value {
  font-weight: 600;
  color: var(--text-primary, #e6edf3);
  font-family: 'Monaco', 'Menlo', monospace;
}

/* System Info Cards */
.info-card {
  background: var(--bg-secondary, #0d1117);
  border: 1px solid var(--border-color, #30363d);
  border-radius: 12px;
  overflow: hidden;
  height: 100%;
}

.info-card-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem 1rem;
  background: rgba(255, 255, 255, 0.02);
  border-bottom: 1px solid var(--border-color, #30363d);
}

.info-card-header h6 {
  margin: 0;
  font-weight: 600;
}

.info-icon {
  font-size: 1.1rem;
}

.info-card-body {
  padding: 1rem;
}

.info-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  padding: 0.4rem 0;
  border-bottom: 1px solid rgba(48, 54, 61, 0.5);
}

.info-row:last-child {
  border-bottom: none;
}

.info-label {
  color: var(--text-secondary, #8b949e);
  font-size: 0.85rem;
}

.info-value {
  color: var(--text-primary, #e6edf3);
  font-weight: 500;
  text-align: right;
  word-break: break-word;
  max-width: 60%;
}

.info-card .table {
  margin: 0;
}

.info-card .table th {
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--text-secondary, #8b949e);
  padding: 0.6rem 0.75rem;
  border-bottom: 1px solid var(--border-color, #30363d);
}

.info-card .table td {
  padding: 0.5rem 0.75rem;
  font-size: 0.85rem;
  vertical-align: middle;
  border-bottom: 1px solid rgba(48, 54, 61, 0.3);
}

.info-card .table tr:last-child td {
  border-bottom: none;
}

/* Process Table Styles */
.process-table {
  table-layout: fixed;
  width: 100%;
}

.process-name-col {
  width: auto;
}

.process-name {
  max-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.process-row {
  cursor: pointer;
  transition: background-color 0.15s ease;
}

.process-row:hover {
  background-color: rgba(139, 92, 246, 0.15) !important;
}

/* Process Detail Modal */
.process-detail-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2100;
}

.process-detail-modal {
  background: var(--card-bg, #161b22);
  border: 1px solid var(--border-color, #30363d);
  border-radius: 12px;
  width: 90%;
  max-width: 500px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5);
}

.process-detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem 1.25rem;
  border-bottom: 1px solid var(--border-color, #30363d);
}

.process-detail-header h5 {
  margin: 0;
  font-size: 1rem;
  color: var(--text-primary, #e6edf3);
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.process-detail-header .close-btn {
  background: none;
  border: none;
  color: var(--text-secondary, #8b949e);
  font-size: 1.5rem;
  cursor: pointer;
  padding: 0;
  line-height: 1;
}

.process-detail-header .close-btn:hover {
  color: var(--text-primary, #e6edf3);
}

.process-detail-body {
  padding: 1.25rem;
}

.process-info-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
}

.process-info-grid .info-item {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.process-info-grid .info-item.full-width {
  grid-column: 1 / -1;
}

.process-info-grid .info-item label {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: var(--text-secondary, #8b949e);
}

.process-info-grid .info-item .value {
  font-size: 1rem;
  color: var(--text-primary, #e6edf3);
  font-weight: 500;
}

.process-info-grid .info-item .name-value {
  word-break: break-all;
  line-height: 1.4;
}

.process-note {
  margin-top: 1.25rem;
  padding: 0.75rem 1rem;
  background: rgba(139, 92, 246, 0.1);
  border: 1px solid rgba(139, 92, 246, 0.2);
  border-radius: 8px;
  display: flex;
  gap: 0.75rem;
  align-items: flex-start;
  font-size: 0.8rem;
  color: var(--text-secondary, #8b949e);
}

.process-note i {
  color: #8b5cf6;
  flex-shrink: 0;
  margin-top: 2px;
}

/* Effective Rules List */
.effective-rules-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.effective-rule-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.6rem 0.75rem;
  background: rgba(0,0,0,0.2);
  border-radius: 6px;
  border: 1px solid transparent;
}

.effective-rule-item.disabled {
  opacity: 0.5;
  border-color: var(--border-color, #30363d);
}

.rule-status .badge-sm {
  font-size: 0.65rem;
  padding: 0.2rem 0.4rem;
  text-transform: uppercase;
  font-weight: 600;
}

.rule-details {
  flex: 1;
  min-width: 0;
}

.rule-name {
  font-weight: 500;
  font-size: 0.9rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.rule-condition {
  font-size: 0.75rem;
  color: var(--text-secondary, #8b949e);
}

.rule-channels {
  flex-shrink: 0;
}

.channels-indicator {
  font-size: 0.8rem;
  color: var(--text-secondary, #8b949e);
}

.rule-override {
  flex-shrink: 0;
}

.rule-override .btn {
  padding: 0.2rem 0.5rem;
  font-size: 0.75rem;
}

/* Toast Notification */
.toast-notification {
  position: fixed;
  top: 20px;
  right: 20px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 20px;
  border-radius: 8px;
  font-size: 0.9rem;
  font-weight: 500;
  z-index: 10000;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
}

.toast-notification.success {
  background: #28a745;
  color: white;
}

.toast-notification.error {
  background: #dc3545;
  color: white;
}

.toast-icon {
  font-size: 1.1rem;
  font-weight: bold;
}

.toast-enter-active,
.toast-leave-active {
  transition: all 0.3s ease;
}

.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateX(50px);
}
</style>
