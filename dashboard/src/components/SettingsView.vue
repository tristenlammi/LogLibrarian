<template>
  <div class="settings-view">
    <!-- Tab Navigation -->
    <div class="settings-tabs">
      <button 
        v-for="tab in tabs" 
        :key="tab.id"
        class="tab-btn"
        :class="{ active: activeTab === tab.id }"
        @click="activeTab = tab.id"
      >
        <i :class="tab.icon" class="me-2"></i>
        {{ tab.label }}
      </button>
    </div>

    <!-- Tab Content -->
    <div class="settings-tab-content">
      
      <!-- General Tab -->
      <div v-if="activeTab === 'general'" class="settings-panel">
        <!-- Instance API Key Section -->
        <div class="settings-section">
          <div class="section-header">
            <i class="bi bi-key"></i>
            <div>
              <h5>Instance API Key</h5>
              <p>This key is required for all Scribe agents to connect</p>
            </div>
          </div>
          <div class="section-content">
            <div class="form-group">
              <label>API Key</label>
              <div class="d-flex gap-2 align-items-center">
                <input 
                  type="text" 
                  class="form-control font-monospace" 
                  :value="showInstanceApiKey ? instanceApiKey : maskedApiKey"
                  readonly
                  style="background: var(--bg-secondary); flex: 1;"
                >
                <button 
                  class="btn btn-outline-secondary" 
                  @click="showInstanceApiKey = !showInstanceApiKey"
                  :title="showInstanceApiKey ? 'Hide API Key' : 'Show API Key'"
                >
                  <i :class="showInstanceApiKey ? 'bi bi-eye-slash' : 'bi bi-eye'"></i>
                </button>
                <button 
                  class="btn btn-outline-secondary" 
                  @click="copyApiKey"
                  :title="apiKeyCopied ? 'Copied!' : 'Copy to clipboard'"
                >
                  <i :class="apiKeyCopied ? 'bi bi-check' : 'bi bi-clipboard'"></i>
                </button>
              </div>
              <span class="form-hint">
                <i class="bi bi-info-circle me-1"></i>
                All Scribe agents must use this key to connect. Keep it secure!
              </span>
            </div>
          </div>
        </div>

        <div class="settings-section">
          <div class="section-header">
            <i class="bi bi-globe"></i>
            <div>
              <h5>Public URL</h5>
              <p>Configure the URL agents use to connect to this server</p>
            </div>
          </div>
          <div class="section-content">
            <div class="form-group">
              <label>Public App URL</label>
              <input 
                type="text" 
                class="form-control" 
                v-model="settings.public_app_url"
                placeholder="https://loglibrarian.yourdomain.com"
              >
              <span class="form-hint">
                Leave empty to auto-detect from request. Set when behind a reverse proxy.
              </span>
            </div>
          </div>
          <div class="section-actions">
            <button class="btn btn-primary" @click="saveGeneralSettings" :disabled="savingGeneral">
              <span v-if="savingGeneral" class="spinner-border spinner-border-sm me-2"></span>
              <i v-else class="bi bi-check-lg me-1"></i>
              {{ savingGeneral ? 'Saving...' : 'Save' }}
            </button>
            <span v-if="generalMessage" :class="generalMessageClass">{{ generalMessage }}</span>
          </div>
        </div>

        <!-- Timezone Section -->
        <div class="settings-section">
          <div class="section-header">
            <i class="bi bi-clock"></i>
            <div>
              <h5>Timezone</h5>
              <p>Set the timezone for displaying timestamps</p>
            </div>
          </div>
          <div class="section-content">
            <div class="form-group">
              <label>Display Timezone</label>
              <div class="timezone-selector" ref="timezoneSelectorRef">
                <input 
                  type="text" 
                  class="form-control timezone-search" 
                  v-model="timezoneSearch" 
                  placeholder="Search timezones..."
                  @focus="openTimezoneDropdown"
                />
              </div>
              <Teleport to="body">
                <div 
                  v-if="timezoneDropdownOpen" 
                  class="timezone-dropdown"
                  :style="timezoneDropdownStyle"
                >
                  <div 
                    class="timezone-option" 
                    :class="{ selected: selectedTimezone === 'local' }"
                    @click="selectTimezone('local')"
                  >
                    <span class="tz-label">Browser Local Time</span>
                    <span class="tz-value">{{ browserTimezone }}</span>
                  </div>
                  <div 
                    class="timezone-option"
                    :class="{ selected: selectedTimezone === 'UTC' }"
                    @click="selectTimezone('UTC')"
                  >
                    <span class="tz-label">UTC</span>
                    <span class="tz-value">Coordinated Universal Time</span>
                  </div>
                  <div class="timezone-divider"></div>
                  <div 
                    v-for="tz in filteredTimezones" 
                    :key="tz.value"
                    class="timezone-option"
                    :class="{ selected: selectedTimezone === tz.value }"
                    @click="selectTimezone(tz.value)"
                  >
                    <span class="tz-label">{{ tz.label }}</span>
                    <span class="tz-value">{{ tz.value }}</span>
                  </div>
                  <div v-if="filteredTimezones.length === 0 && timezoneSearch" class="timezone-empty">
                    No timezones matching "{{ timezoneSearch }}"
                  </div>
                </div>
              </Teleport>
              <div class="selected-timezone" v-if="selectedTimezone">
                <strong>Selected:</strong> {{ selectedTimezoneLabel }}
              </div>
              <span class="form-hint">
                Current time: {{ currentTimeDisplay }}
              </span>
            </div>
          </div>
        </div>

        <!-- Tags Section -->
        <div class="settings-section">
          <div class="section-header">
            <i class="bi bi-tags"></i>
            <div>
              <h5>Tag Management</h5>
              <p>Manage tags used across agents and bookmarks</p>
            </div>
          </div>
          <div class="section-content">
            <div class="form-group">
              <label>Create New Tag</label>
              <div class="tag-create-row">
                <input 
                  type="text" 
                  class="form-control" 
                  v-model="newTagName"
                  placeholder="Enter tag name..."
                  @keydown.enter="createTag"
                />
                <button 
                  class="btn btn-primary" 
                  @click="createTag"
                  :disabled="!newTagName.trim() || creatingTag"
                >
                  <span v-if="creatingTag" class="spinner-border spinner-border-sm me-1"></span>
                  <i v-else class="bi bi-plus-lg me-1"></i>
                  Add
                </button>
              </div>
              <span v-if="tagCreateError" class="form-hint text-danger">{{ tagCreateError }}</span>
            </div>
            
            <div class="form-group mt-3">
              <label>Existing Tags ({{ allTags.length }})</label>
              <div v-if="loadingTags" class="tags-loading">
                <span class="spinner-border spinner-border-sm me-2"></span>
                Loading tags...
              </div>
              <div v-else-if="allTags.length === 0" class="tags-empty">
                <i class="bi bi-tag me-2"></i>
                No tags have been created yet
              </div>
              <div v-else class="tags-list">
                <div 
                  v-for="tag in allTags" 
                  :key="tag" 
                  class="tag-item"
                >
                  <span class="tag-name">{{ tag }}</span>
                  <button 
                    type="button"
                    class="tag-delete-btn" 
                    @click.stop.prevent="confirmDeleteTag(tag)"
                  >×</button>
                </div>
              </div>
              <span class="form-hint mt-2">
                Deleting a tag removes it from all agents and bookmarks.
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- Users Tab -->
      <div v-if="activeTab === 'users'" class="settings-panel">
        <div class="settings-section">
          <div class="section-header">
            <i class="bi bi-person-circle"></i>
            <div>
              <h5>Your Account</h5>
              <p>Manage your password and account settings</p>
            </div>
          </div>
          <div class="section-content">
            <div class="current-user-info">
              <div class="user-avatar">
                <i class="bi bi-person-fill"></i>
              </div>
              <div class="user-details">
                <strong>{{ currentUser?.username || 'Unknown' }}</strong>
                <span class="user-role" :class="{ admin: currentUser?.role === 'admin' }">
                  {{ currentUser?.role === 'admin' ? 'Administrator' : 'User' }}
                </span>
              </div>
            </div>
            <button class="btn btn-outline-primary mt-3" @click="showChangePasswordModal = true">
              <i class="bi bi-key me-1"></i>Change Password
            </button>
          </div>
        </div>

        <div class="settings-section" v-if="currentUser?.role === 'admin'">
          <div class="section-header">
            <i class="bi bi-people"></i>
            <div>
              <h5>User Management</h5>
              <p>Add and manage users who can access LogLibrarian</p>
            </div>
          </div>
          <div class="section-content">
            <div class="users-list">
              <div v-if="loadingUsers" class="loading-users">
                <span class="spinner-border spinner-border-sm me-2"></span>
                Loading users...
              </div>
              <div v-else-if="users.length === 0" class="no-users">
                No users found.
              </div>
              <div v-else class="user-item" v-for="user in users" :key="user.id">
                <div class="user-info">
                  <div class="user-avatar small">
                    <i class="bi bi-person-fill"></i>
                  </div>
                  <div class="user-info-details">
                    <div class="user-name-row">
                      <strong>{{ user.username }}</strong>
                      <span class="user-role" :class="{ admin: user.role === 'admin' }">
                        {{ user.role === 'admin' ? 'Admin' : 'User' }}
                      </span>
                    </div>
                    <div class="user-profile" v-if="user.role !== 'admin' && user.assigned_profile_id">
                      <i class="bi bi-collection me-1"></i>
                      <span>{{ getProfileName(user.assigned_profile_id) }}</span>
                    </div>
                    <div class="user-profile text-muted" v-else-if="user.role !== 'admin'">
                      <i class="bi bi-collection me-1"></i>
                      <span>No profile assigned</span>
                    </div>
                  </div>
                </div>
                <div class="user-actions">
                  <button 
                    class="btn btn-sm btn-outline-primary me-2" 
                    @click="openEditUserModal(user)"
                    :disabled="user.id === currentUser?.user_id"
                    title="Edit user role and profile"
                  >
                    ✏️ Edit
                  </button>
                  <button 
                    class="btn btn-sm btn-outline-danger" 
                    @click="confirmDeleteUser(user)"
                    :disabled="user.id === currentUser?.user_id || user.id === 1"
                    :title="user.id === 1 ? 'Primary admin cannot be deleted' : (user.id === currentUser?.user_id ? 'Cannot delete yourself' : 'Delete user')"
                  >
                    🗑️ Delete
                  </button>
                </div>
              </div>
            </div>
            <button class="btn btn-primary mt-3" @click="showAddUserModal = true">
              <i class="bi bi-person-plus me-1"></i>Add User
            </button>
          </div>
        </div>

        <div class="settings-section">
          <div class="section-header">
            <i class="bi bi-box-arrow-right"></i>
            <div>
              <h5>Sign Out</h5>
              <p>End your current session</p>
            </div>
          </div>
          <div class="section-content">
            <button class="btn btn-outline-danger" @click="handleLogout">
              <i class="bi bi-box-arrow-right me-1"></i>Sign Out
            </button>
          </div>
        </div>
      </div>

      <!-- Connection Tab -->
      <div v-if="activeTab === 'connection'" class="settings-panel">
        <div class="settings-section">
          <div class="section-header">
            <i class="bi bi-hdd-network"></i>
            <div>
              <h5>Agent Connection</h5>
              <p>Configure how Scribe agents connect to this server</p>
            </div>
          </div>
          <div class="section-content">
            <div class="form-group">
              <label>Preferred LAN IP</label>
              <div class="input-group">
                <select class="form-select" v-model="selectedLanIpOption" @change="onLanIpOptionChange">
                  <option value="">Auto (Best LAN IP)</option>
                  <option v-for="ip in lanIps" :key="ip" :value="ip">{{ ip }}</option>
                  <option value="custom">Custom IP...</option>
                </select>
                <input 
                  v-if="selectedLanIpOption === 'custom'"
                  type="text" 
                  class="form-control" 
                  v-model="customLanIp"
                  placeholder="192.168.1.100"
                  @blur="onCustomLanIpBlur"
                >
              </div>
              <span class="form-hint">
                Your server's LAN IP. Auto-detect may show container IPs in Docker.
              </span>
            </div>
            <div class="form-group">
              <label>Custom Public URL (DNS)</label>
              <input 
                type="text" 
                class="form-control" 
                v-model="agentSettings.custom_url"
                placeholder="https://loglibrarian.yourdomain.com"
              >
            </div>
            <div class="form-group">
              <label>Fallback Order</label>
              <select class="form-select" v-model="agentSettings.fallback_order">
                <option value="lan_first">LAN First, then DNS</option>
                <option value="dns_first">DNS First, then LAN</option>
              </select>
            </div>
          </div>
          <div class="section-actions">
            <button class="btn btn-primary" @click="saveAgentSettings" :disabled="savingAgent">
              <span v-if="savingAgent" class="spinner-border spinner-border-sm me-2"></span>
              <i v-else class="bi bi-check-lg me-1"></i>
              {{ savingAgent ? 'Saving...' : 'Save' }}
            </button>
            <span v-if="agentMessage" :class="agentMessageClass">{{ agentMessage }}</span>
          </div>
        </div>
      </div>

      <!-- Storage Tab -->
      <div v-if="activeTab === 'storage'" class="settings-panel storage-compact">
        <!-- Panic Alert -->
        <div v-if="janitorStatus.panic_switch?.active" class="panic-alert">
          <i class="bi bi-exclamation-triangle-fill"></i>
          <div>
            <strong>PANIC MODE ACTIVE</strong>
            <p>Data ingestion blocked due to low disk space. Free up space to resume.</p>
          </div>
        </div>

        <!-- Combined Status Row -->
        <div class="status-row-compact">
          <div class="status-card-compact">
            <div class="status-card-header">
              <i class="bi bi-hdd"></i>
              <span>Disk</span>
              <button class="btn-icon-sm" @click="loadJanitorStatus" :disabled="loadingJanitor">
                <i class="bi bi-arrow-clockwise" :class="{ spin: loadingJanitor }"></i>
              </button>
            </div>
            <div class="disk-bar-compact">
              <div 
                class="disk-used" 
                :style="{ width: (janitorStatus.disk?.used_percent || 0) + '%' }"
                :class="diskClass"
              ></div>
            </div>
            <div class="disk-stats-compact">
              <span>{{ janitorStatus.disk?.used_gb || 0 }}GB used</span>
              <span>{{ janitorStatus.disk?.free_gb || 0 }}GB free</span>
            </div>
          </div>
          <div class="status-card-compact">
            <div class="status-card-header">
              <i class="bi bi-database"></i>
              <span>Database</span>
            </div>
            <div class="stats-row-compact">
              <div class="stat-compact">
                <span class="val">{{ formatSize(janitorStatus.storage?.file_size_bytes) }}</span>
                <span class="lbl">Size</span>
              </div>
              <div class="stat-compact">
                <span class="val">{{ (janitorStatus.storage?.row_counts?.raw_logs || 0).toLocaleString() }}</span>
                <span class="lbl">Logs</span>
              </div>
              <div class="stat-compact">
                <span class="val">{{ (janitorStatus.storage?.row_counts?.metrics || 0).toLocaleString() }}</span>
                <span class="lbl">Metrics</span>
              </div>
              <div class="stat-compact">
                <span class="val highlight">{{ janitorStatus.janitor?.status || '?' }}</span>
                <span class="lbl">Janitor</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Two Column Layout for Settings -->
        <div class="settings-grid-2col">
          <!-- Left Column: Storage Limits + Data Retention -->
          <div class="settings-column">
            <div class="section-header-compact">
              <i class="bi bi-sliders"></i>
              <h5>Storage Limits</h5>
            </div>
            <div class="slider-group">
              <label>Max DB Size <span class="value-badge-sm">{{ janitorSettings.max_storage_gb }} GB</span></label>
              <input type="range" class="form-range" v-model.number="janitorSettings.max_storage_gb" min="1" max="100" step="1">
            </div>
            <div class="slider-group">
              <label>Min Free Disk <span class="value-badge-sm">{{ janitorSettings.min_free_space_gb }} GB</span></label>
              <input type="range" class="form-range" v-model.number="janitorSettings.min_free_space_gb" min="0.5" max="20" step="0.5">
            </div>

            <div class="section-header-compact mt-3">
              <i class="bi bi-clock-history"></i>
              <h5>Data Retention</h5>
            </div>
            <div class="slider-group">
              <label>Raw Logs <span class="value-badge-sm">{{ janitorSettings.retention_raw_logs_days }}d</span></label>
              <input type="range" class="form-range" v-model.number="janitorSettings.retention_raw_logs_days" min="1" max="90" step="1">
            </div>
            <div class="slider-group">
              <label>Metrics <span class="value-badge-sm">{{ janitorSettings.retention_metrics_days }}d</span></label>
              <input type="range" class="form-range" v-model.number="janitorSettings.retention_metrics_days" min="1" max="30" step="1">
            </div>
            <div class="slider-group">
              <label>Snapshots <span class="value-badge-sm">{{ janitorSettings.retention_process_snapshots_days }}d</span></label>
              <input type="range" class="form-range" v-model.number="janitorSettings.retention_process_snapshots_days" min="1" max="30" step="1">
            </div>
          </div>

          <!-- Right Column: AI Retention + Report Storage + Estimate -->
          <div class="settings-column">
            <div class="section-header-compact">
              <i class="bi bi-robot"></i>
              <h5>AI Data Retention</h5>
            </div>
            <div class="slider-group">
              <label>Briefings <span class="value-badge-sm">{{ janitorSettings.retention_ai_briefings_days }}d</span></label>
              <input type="range" class="form-range" v-model.number="janitorSettings.retention_ai_briefings_days" min="7" max="365" step="1">
            </div>

            <div class="section-header-compact mt-3">
              <i class="bi bi-file-earmark-bar-graph"></i>
              <h5>Executive Reports</h5>
            </div>
            <div class="slider-group">
              <label>Max Reports/Profile <span class="value-badge-sm">{{ janitorSettings.max_exec_reports_per_profile }}</span></label>
              <input type="range" class="form-range" v-model.number="janitorSettings.max_exec_reports_per_profile" min="1" max="365" step="1">
            </div>
            <div class="exec-report-estimate">
              <span class="estimate-formula">
                {{ profileCount }} profiles × {{ janitorSettings.max_exec_reports_per_profile }} reports × ~2MB
              </span>
              <span class="estimate-result">≈ {{ execReportStorageEstimate }}</span>
            </div>

            <!-- Compact Storage Estimate -->
            <div class="storage-estimate-compact" :class="storageWarningLevel">
              <div class="estimate-header-compact">
                <i class="bi bi-calculator"></i>
                <span>Estimated Usage</span>
                <div class="estimate-agents-compact">
                  <input 
                    type="number" 
                    class="agent-input-sm"
                    :value="agentCountOverride || agentCount"
                    @input="agentCountOverride = $event.target.value ? parseInt($event.target.value) : null"
                    min="1" max="100" :placeholder="agentCount"
                  >
                  <span>agents</span>
                </div>
              </div>
              <div class="estimate-value-compact">~{{ estimatedStorageGB }} GB</div>
              <div class="estimate-breakdown">
                <span class="breakdown-item">DB: ~{{ estimatedDBStorageGB }} GB</span>
                <span class="breakdown-item">Reports: ~{{ execReportStorageEstimate }}</span>
              </div>
              <div v-if="storageWarningLevel !== 'ok'" class="estimate-warning-compact">
                <i :class="storageWarningLevel === 'danger' ? 'bi bi-exclamation-triangle-fill' : 'bi bi-exclamation-triangle'"></i>
                {{ storageWarningLevel === 'danger' ? 'Exceeds limit!' : 'Approaching limit' }}
              </div>
            </div>
          </div>
        </div>

        <!-- Actions Row -->
        <div class="actions-row-compact">
          <button class="btn btn-primary" @click="saveJanitorSettings" :disabled="savingJanitor">
            <span v-if="savingJanitor" class="spinner-border spinner-border-sm me-1"></span>
            <i v-else class="bi bi-check-lg me-1"></i>
            {{ savingJanitor ? 'Saving...' : 'Save Settings' }}
          </button>
          <button class="btn btn-warning" @click="runCleanup" :disabled="runningCleanup">
            <span v-if="runningCleanup" class="spinner-border spinner-border-sm me-1"></span>
            <i v-else class="bi bi-trash me-1"></i>
            {{ runningCleanup ? 'Running...' : 'Run Cleanup' }}
          </button>
          <span v-if="janitorMessage" :class="janitorMessageClass" class="ms-2">{{ janitorMessage }}</span>
        </div>
      </div>

      <!-- Alerts Tab -->
      <div v-if="activeTab === 'alerts'" class="settings-panel alerts-panel">
        <!-- Alerts Sub-tabs -->
        <div class="alerts-subtabs">
          <button 
            class="subtab-btn" 
            :class="{ active: alertsSubTab === 'channels' }"
            @click="alertsSubTab = 'channels'"
          >
            <i class="bi bi-broadcast me-2"></i>Notification Channels
          </button>
          <button 
            class="subtab-btn" 
            :class="{ active: alertsSubTab === 'rules' }"
            @click="alertsSubTab = 'rules'"
          >
            <i class="bi bi-exclamation-triangle me-2"></i>Alert Rules
          </button>
          <button 
            class="subtab-btn" 
            :class="{ active: alertsSubTab === 'history' }"
            @click="alertsSubTab = 'history'"
          >
            <i class="bi bi-clock-history me-2"></i>History
          </button>
        </div>

        <!-- Loading -->
        <div v-if="loadingAlerts" class="alerts-loading">
          <span class="spinner-border spinner-border-sm me-2"></span>
          Loading alert settings...
        </div>

        <!-- Channels Sub-tab -->
        <div v-else-if="alertsSubTab === 'channels'" class="alerts-content">
          <div class="alerts-header">
            <div>
              <h5>Notification Channels</h5>
              <p>Configure where alerts are sent</p>
            </div>
            <button class="btn btn-primary btn-sm" @click="openChannelModal()">
              <i class="bi bi-plus-lg me-1"></i>Add Channel
            </button>
          </div>

          <div v-if="alertChannels.length === 0" class="alerts-empty">
            <i class="bi bi-broadcast"></i>
            <p>No notification channels configured</p>
            <span>Add a channel to start receiving alerts via Discord, Slack, Email, and more.</span>
          </div>

          <div v-else class="channels-list">
            <div v-for="channel in alertChannels" :key="channel.id" class="channel-item">
              <div class="channel-icon">
                {{ getChannelTypeInfo(channel.type).icon }}
              </div>
              <div class="channel-info">
                <div class="channel-name">{{ channel.name }}</div>
                <div class="channel-type">{{ getChannelTypeInfo(channel.type).name }}</div>
              </div>
              <div class="channel-events">
                <span v-if="channel.events?.length" class="events-badge">
                  {{ channel.events.length }} event{{ channel.events.length !== 1 ? 's' : '' }}
                </span>
              </div>
              <div class="channel-actions">
                <button class="btn btn-sm btn-outline-secondary" @click="openChannelModal(channel)">
                  <i class="bi bi-pencil"></i>
                </button>
                <button class="btn btn-sm btn-outline-danger" @click="confirmDeleteChannel(channel)">
                  <i class="bi bi-trash"></i>
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- Rules Sub-tab -->
        <div v-else-if="alertsSubTab === 'rules'" class="alerts-content">
          <div class="alerts-header">
            <div>
              <h5>Alert Rules</h5>
              <p>Global rules apply to all agents and bookmarks by default</p>
            </div>
            <button class="btn btn-primary btn-sm" @click="openRuleModal()">
              <i class="bi bi-plus-lg me-1"></i>Add Rule
            </button>
          </div>

          <div v-if="alertRules.length === 0" class="alerts-empty">
            <i class="bi bi-exclamation-triangle"></i>
            <p>No alert rules configured</p>
            <span>Create rules to get notified about CPU spikes, disk space, offline agents, and more.</span>
          </div>

          <div v-else class="rules-list">
            <div v-for="rule in alertRules" :key="rule.id" class="rule-item" :class="{ disabled: !rule.enabled }">
              <div class="rule-toggle">
                <label class="toggle-switch-sm">
                  <input type="checkbox" :checked="rule.enabled" @change="toggleRuleEnabled(rule)">
                  <span class="toggle-slider"></span>
                </label>
              </div>
              <div class="rule-info">
                <div class="rule-name">{{ rule.name }}</div>
                <div class="rule-condition">{{ formatRuleCondition(rule) }}</div>
              </div>
              <div class="rule-scope">
                <span class="scope-badge" :class="rule.scope">
                  {{ rule.scope === 'global' ? 'All' : (rule.scope === 'agent' ? 'Agent' : 'Bookmark') }}
                </span>
              </div>
              <div class="rule-channels">
                <span v-if="rule.channels?.length" class="channels-count">
                  {{ rule.channels.length }} channel{{ rule.channels.length !== 1 ? 's' : '' }}
                </span>
                <span v-else class="text-muted">No channels</span>
              </div>
              <div class="rule-actions">
                <button class="btn btn-sm btn-outline-secondary" @click="openRuleModal(rule)">
                  <i class="bi bi-pencil"></i>
                </button>
                <button class="btn btn-sm btn-outline-danger" @click="confirmDeleteRule(rule)">
                  <i class="bi bi-trash"></i>
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- History Sub-tab -->
        <div v-else-if="alertsSubTab === 'history'" class="alerts-content">
          <div class="alerts-header">
            <div>
              <h5>Alert History</h5>
              <p>Recent notifications sent</p>
            </div>
            <button class="btn btn-outline-secondary btn-sm" @click="loadAlertHistory">
              <i class="bi bi-arrow-clockwise me-1"></i>Refresh
            </button>
          </div>

          <div v-if="alertHistory.length === 0" class="alerts-empty">
            <i class="bi bi-clock-history"></i>
            <p>No alerts sent yet</p>
            <span>Alert history will appear here once notifications are triggered.</span>
          </div>

          <div v-else class="history-list">
            <div v-for="alert in alertHistory" :key="alert.id" class="history-item">
              <div class="history-status" :class="alert.success ? 'success' : 'failed'">
                <i :class="alert.success ? 'bi bi-check-circle-fill' : 'bi bi-x-circle-fill'"></i>
              </div>
              <div class="history-info">
                <div class="history-title">{{ alert.rule_name || 'Alert' }}</div>
                <div class="history-detail">
                  <span class="history-channel">{{ alert.channel_name }}</span>
                  <span class="history-target" v-if="alert.target_name">to {{ alert.target_name }}</span>
                </div>
              </div>
              <div class="history-time">
                {{ formatAlertTime(alert.created_at) }}
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Appearance Tab -->
      <div v-if="activeTab === 'appearance'" class="settings-panel">
        <div class="settings-section">
          <div class="section-header">
            <i class="bi bi-palette"></i>
            <div>
              <h5>Theme</h5>
              <p>Customize the look and feel</p>
            </div>
          </div>
          <div class="section-content">
            <div class="form-group">
              <label>Color Theme</label>
              <select class="form-select" v-model="theme" disabled>
                <option value="dark">Dark Mode</option>
                <option value="light">Light Mode</option>
              </select>
              <span class="form-hint">Theme customization coming soon.</span>
            </div>
          </div>
        </div>
      </div>

    </div>
  </div>

  <!-- Delete Model Confirmation Modal -->
  <Teleport to="body">
    <div v-if="showDeleteModelModal" class="modal-overlay" @click.self="cancelDeleteModel">
      <div class="modal-container delete-modal">
        <div class="modal-header">
          <h3><i class="bi bi-exclamation-triangle text-warning me-2"></i>Delete Model</h3>
          <button class="close-btn" @click="cancelDeleteModel">
            <i class="bi bi-x-lg"></i>
          </button>
        </div>
        <div class="modal-body">
          <div class="delete-model-info" v-if="modelToDelete">
            <span class="model-icon-lg">{{ modelToDelete.icon }}</span>
            <div>
              <strong>{{ modelToDelete.name }}</strong>
              <p>{{ modelToDelete.size }}</p>
            </div>
          </div>
          <p class="delete-warning">
            This will permanently delete the model file. You'll need to download it again if you want to use it.
          </p>
        </div>
        <div class="modal-footer">
          <button class="btn btn-secondary" @click="cancelDeleteModel">Cancel</button>
          <button class="btn btn-danger" @click="deleteModel">
            <i class="bi bi-trash me-1"></i>Delete Model
          </button>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- Delete Tag Confirmation Modal -->
  <Teleport to="body">
    <div v-if="showDeleteTagModal" class="modal-overlay" @click.self="cancelDeleteTag">
      <div class="modal-container delete-modal">
        <div class="modal-header">
          <h3><i class="bi bi-exclamation-triangle text-warning me-2"></i>Delete Tag</h3>
          <button class="close-btn" @click="cancelDeleteTag">
            <i class="bi bi-x-lg"></i>
          </button>
        </div>
        <div class="modal-body">
          <div class="delete-tag-info" v-if="tagToDelete">
            <i class="bi bi-tag-fill tag-icon-lg"></i>
            <strong>{{ tagToDelete }}</strong>
          </div>
          <p class="delete-warning">
            This will remove the tag from all agents and bookmarks that use it. This action cannot be undone.
          </p>
          <div class="delete-profile-warning">
            <i class="bi bi-exclamation-circle text-warning me-2"></i>
            <span><strong>Warning:</strong> If this tag is used in any Report Profiles, those profiles will no longer include devices with this tag.</span>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-secondary" @click="cancelDeleteTag">Cancel</button>
          <button class="btn btn-danger" @click="executeDeleteTag" :disabled="deletingTag">
            <span v-if="deletingTag" class="spinner-border spinner-border-sm me-1"></span>
            <i v-else class="bi bi-trash me-1"></i>Delete Tag
          </button>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- Change Password Modal -->
  <Teleport to="body">
    <div v-if="showChangePasswordModal" class="modal-overlay" @click.self="closeChangePasswordModal">
      <div class="modal-container">
        <div class="modal-header">
          <h3><i class="bi bi-key me-2"></i>Change Password</h3>
          <button class="close-btn" @click="closeChangePasswordModal">
            <i class="bi bi-x-lg"></i>
          </button>
        </div>
        <form @submit.prevent="handleChangePassword">
          <div class="modal-body">
            <div class="form-group">
              <label>Current Password</label>
              <input type="password" class="form-control" v-model="passwordForm.current" required>
            </div>
            <div class="form-group">
              <label>New Password</label>
              <input type="password" class="form-control" v-model="passwordForm.new" required @input="validateNewPassword">
              <div class="password-requirements">
                <div :class="{ valid: passwordRequirements.length }">
                  <span>{{ passwordRequirements.length ? '✓' : '○' }}</span> At least 8 characters
                </div>
                <div :class="{ valid: passwordRequirements.number }">
                  <span>{{ passwordRequirements.number ? '✓' : '○' }}</span> Contains a number
                </div>
                <div :class="{ valid: passwordRequirements.special }">
                  <span>{{ passwordRequirements.special ? '✓' : '○' }}</span> Contains a special character
                </div>
              </div>
            </div>
            <div class="form-group">
              <label>Confirm New Password</label>
              <input type="password" class="form-control" v-model="passwordForm.confirm" required>
              <span v-if="passwordForm.confirm && passwordForm.new !== passwordForm.confirm" class="text-danger small">
                Passwords do not match
              </span>
            </div>
            <div v-if="passwordError" class="alert alert-danger mt-3">{{ passwordError }}</div>
            <div v-if="passwordSuccess" class="alert alert-success mt-3">{{ passwordSuccess }}</div>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn btn-secondary" @click="closeChangePasswordModal">Cancel</button>
            <button 
              type="submit" 
              class="btn btn-primary" 
              :disabled="!canChangePassword || changingPassword"
            >
              <span v-if="changingPassword" class="spinner-border spinner-border-sm me-1"></span>
              Change Password
            </button>
          </div>
        </form>
      </div>
    </div>
  </Teleport>

  <!-- Add User Modal -->
  <Teleport to="body">
    <div v-if="showAddUserModal" class="modal-overlay" @click.self="closeAddUserModal">
      <div class="modal-container">
        <div class="modal-header">
          <h3><i class="bi bi-person-plus me-2"></i>Add User</h3>
          <button class="close-btn" @click="closeAddUserModal">
            <i class="bi bi-x-lg"></i>
          </button>
        </div>
        <form @submit.prevent="handleAddUser">
          <div class="modal-body">
            <div class="form-group">
              <label>Username</label>
              <input type="text" class="form-control" v-model="newUserForm.username" required placeholder="Username or email">
            </div>
            <div class="form-group">
              <label>Password</label>
              <input type="password" class="form-control" v-model="newUserForm.password" required @input="validateNewUserPassword">
              <div class="password-requirements">
                <div :class="{ valid: newUserPasswordReqs.length }">
                  <span>{{ newUserPasswordReqs.length ? '✓' : '○' }}</span> At least 8 characters
                </div>
                <div :class="{ valid: newUserPasswordReqs.number }">
                  <span>{{ newUserPasswordReqs.number ? '✓' : '○' }}</span> Contains a number
                </div>
                <div :class="{ valid: newUserPasswordReqs.special }">
                  <span>{{ newUserPasswordReqs.special ? '✓' : '○' }}</span> Contains a special character
                </div>
              </div>
            </div>
            <div class="form-group">
              <label>Role</label>
              <select class="form-select" v-model="newUserForm.role">
                <option value="user">User</option>
                <option value="admin">Administrator</option>
              </select>
              <span class="form-hint">Administrators can manage all users and settings</span>
            </div>
            <div class="form-group" v-if="newUserForm.role === 'user'">
              <label>Assigned Profile</label>
              <select class="form-select" v-model="newUserForm.assignedProfileId">
                <option value="">None (No access)</option>
                <option v-for="profile in profiles" :key="profile.id" :value="profile.id">
                  {{ profile.name }}
                </option>
              </select>
              <span class="form-hint">Users can only see agents and logs matching their assigned profile's scope</span>
            </div>
            <div v-if="addUserError" class="alert alert-danger mt-3">{{ addUserError }}</div>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn btn-secondary" @click="closeAddUserModal">Cancel</button>
            <button 
              type="submit" 
              class="btn btn-primary" 
              :disabled="!canAddUser || addingUser"
            >
              <span v-if="addingUser" class="spinner-border spinner-border-sm me-1"></span>
              Add User
            </button>
          </div>
        </form>
      </div>
    </div>
  </Teleport>

  <!-- Edit User Modal -->
  <Teleport to="body">
    <div v-if="showEditUserModal" class="modal-overlay" @click.self="closeEditUserModal">
      <div class="modal-container">
        <div class="modal-header">
          <h3><i class="bi bi-pencil me-2"></i>Edit User</h3>
          <button class="close-btn" @click="closeEditUserModal">
            <i class="bi bi-x-lg"></i>
          </button>
        </div>
        <form @submit.prevent="handleEditUser">
          <div class="modal-body">
            <div class="form-group">
              <label>Username</label>
              <input type="text" class="form-control" :value="userToEdit?.username" disabled>
            </div>
            <div class="form-group">
              <label>Role</label>
              <select class="form-select" v-model="editUserForm.role">
                <option value="user">User</option>
                <option value="admin">Administrator</option>
              </select>
              <span class="form-hint">Administrators can manage all users and settings</span>
            </div>
            <div class="form-group" v-if="editUserForm.role === 'user'">
              <label>Assigned Profile</label>
              <select class="form-select" v-model="editUserForm.assignedProfileId">
                <option value="">None (No access)</option>
                <option v-for="profile in profiles" :key="profile.id" :value="profile.id">
                  {{ profile.name }}
                </option>
              </select>
              <span class="form-hint">Users can only see agents and logs matching their assigned profile's scope</span>
            </div>
            <div v-if="editUserError" class="alert alert-danger mt-3">{{ editUserError }}</div>
          </div>
          <div class="modal-footer">
            <button type="button" class="btn btn-secondary" @click="closeEditUserModal">Cancel</button>
            <button 
              type="submit" 
              class="btn btn-primary" 
              :disabled="editingUser"
            >
              <span v-if="editingUser" class="spinner-border spinner-border-sm me-1"></span>
              Save Changes
            </button>
          </div>
        </form>
      </div>
    </div>
  </Teleport>

  <!-- Delete User Confirmation Modal -->
  <Teleport to="body">
    <div v-if="showDeleteUserModal" class="modal-overlay" @click.self="closeDeleteUserModal">
      <div class="modal-container delete-modal">
        <div class="modal-header">
          <h3>⚠️ Delete User</h3>
          <button class="close-btn" @click="closeDeleteUserModal">
            ✕
          </button>
        </div>
        <div class="modal-body">
          <p>Are you sure you want to delete user <strong>{{ userToDelete?.username }}</strong>?</p>
          <p class="delete-warning">This action cannot be undone.</p>
          <div class="delete-confirm-input mt-3">
            <label>Type <strong>delete</strong> to confirm:</label>
            <input 
              v-model="deleteUserConfirmText" 
              type="text" 
              placeholder="delete"
              class="form-control mt-2"
              @keyup.enter="deleteUserConfirmText.toLowerCase() === 'delete' && handleDeleteUser()"
            />
          </div>
          <div v-if="deleteUserError" class="alert alert-danger mt-3">{{ deleteUserError }}</div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-secondary" @click="closeDeleteUserModal">Cancel</button>
          <button 
            class="btn btn-danger" 
            @click="handleDeleteUser" 
            :disabled="deletingUser || deleteUserConfirmText.toLowerCase() !== 'delete'"
          >
            <span v-if="deletingUser" class="spinner-border spinner-border-sm me-1"></span>
            🗑️ Delete User
          </button>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- Alert Channel Modal -->
  <AlertChannelModal 
    :show="showChannelModal"
    :channel="editingChannel"
    @close="showChannelModal = false"
    @saved="onChannelSaved"
  />

  <!-- Alert Rule Modal -->
  <AlertRuleModal 
    :show="showRuleModal"
    :rule="editingRule"
    :channels="alertChannels"
    @close="showRuleModal = false"
    @saved="onRuleSaved"
  />

  <!-- Delete Channel Confirmation Modal -->
  <Teleport to="body">
    <div v-if="showDeleteChannelModal" class="modal-overlay" @click.self="cancelDeleteChannel">
      <div class="modal-container delete-modal">
        <div class="modal-header">
          <h3><i class="bi bi-exclamation-triangle text-warning me-2"></i>Delete Channel</h3>
          <button class="close-btn" @click="cancelDeleteChannel">
            <i class="bi bi-x-lg"></i>
          </button>
        </div>
        <div class="modal-body">
          <p>Are you sure you want to delete <strong>{{ channelToDelete?.name }}</strong>?</p>
          <p class="delete-warning">
            Any alert rules using this channel will no longer send notifications to it.
          </p>
        </div>
        <div class="modal-footer">
          <button class="btn btn-secondary" @click="cancelDeleteChannel">Cancel</button>
          <button class="btn btn-danger" @click="executeDeleteChannel" :disabled="deletingChannel">
            <span v-if="deletingChannel" class="spinner-border spinner-border-sm me-1"></span>
            <i v-else class="bi bi-trash me-1"></i>Delete
          </button>
        </div>
      </div>
    </div>
  </Teleport>

  <!-- Delete Rule Confirmation Modal -->
  <Teleport to="body">
    <div v-if="showDeleteRuleModal" class="modal-overlay" @click.self="cancelDeleteRule">
      <div class="modal-container delete-modal">
        <div class="modal-header">
          <h3><i class="bi bi-exclamation-triangle text-warning me-2"></i>Delete Alert Rule</h3>
          <button class="close-btn" @click="cancelDeleteRule">
            <i class="bi bi-x-lg"></i>
          </button>
        </div>
        <div class="modal-body">
          <p>Are you sure you want to delete the rule <strong>{{ ruleToDelete?.name }}</strong>?</p>
          <p class="delete-warning">
            This will stop all alerts based on this rule.
          </p>
        </div>
        <div class="modal-footer">
          <button class="btn btn-secondary" @click="cancelDeleteRule">Cancel</button>
          <button class="btn btn-danger" @click="executeDeleteRule" :disabled="deletingRule">
            <span v-if="deletingRule" class="spinner-border spinner-border-sm me-1"></span>
            <i v-else class="bi bi-trash me-1"></i>Delete
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, computed, onMounted, onActivated, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import axios from 'axios'
import { 
  user as authUser, 
  getUsers, 
  addUser as apiAddUser, 
  deleteUser as apiDeleteUser,
  updateUser as apiUpdateUser,
  changePassword as apiChangePassword,
  logout,
  getAuthHeader 
} from '../auth.js'
import AlertChannelModal from './AlertChannelModal.vue'
import AlertRuleModal from './AlertRuleModal.vue'

const route = useRoute()
const router = useRouter()

// Current user from auth
const currentUser = computed(() => authUser.value)

// Tab management
const tabs = [
  { id: 'general', label: 'General', icon: 'bi bi-house' },
  { id: 'users', label: 'Users', icon: 'bi bi-people' },
  { id: 'connection', label: 'Connection', icon: 'bi bi-link-45deg' },
  { id: 'storage', label: 'Storage', icon: 'bi bi-hdd' },
  { id: 'alerts', label: 'Alerts', icon: 'bi bi-bell' },
  { id: 'appearance', label: 'Appearance', icon: 'bi bi-palette' },
]
// Check for tab query parameter
const initialTab = route.query.tab && tabs.some(t => t.id === route.query.tab) ? route.query.tab : 'general'
const activeTab = ref(initialTab)

// General settings
const settings = ref({ public_app_url: '' })
const savingGeneral = ref(false)
const generalMessage = ref('')
const generalMessageClass = ref('')

// Instance API Key
const instanceApiKey = ref('')
const maskedApiKey = computed(() => {
  if (!instanceApiKey.value) return ''
  const key = instanceApiKey.value
  if (key.length <= 12) return key
  return `${key.slice(0, 8)}${'•'.repeat(key.length - 12)}${key.slice(-4)}`
})
const showInstanceApiKey = ref(false)
const apiKeyCopied = ref(false)

// User management state
const users = ref([])
const profiles = ref([])
const loadingUsers = ref(false)
const showChangePasswordModal = ref(false)
const showAddUserModal = ref(false)
const showDeleteUserModal = ref(false)
const showEditUserModal = ref(false)
const userToDelete = ref(null)
const userToEdit = ref(null)

// Change password form
const passwordForm = ref({ current: '', new: '', confirm: '' })
const passwordRequirements = ref({ length: false, number: false, special: false })
const passwordError = ref('')
const passwordSuccess = ref('')
const changingPassword = ref(false)

const validateNewPassword = () => {
  passwordRequirements.value = {
    length: passwordForm.value.new.length >= 8,
    number: /\d/.test(passwordForm.value.new),
    special: /[!@#$%^&*(),.?":{}|<>`~\-_=+\[\]\\;'\/]/.test(passwordForm.value.new)
  }
}

const canChangePassword = computed(() => {
  return passwordForm.value.current &&
         passwordRequirements.value.length &&
         passwordRequirements.value.number &&
         passwordRequirements.value.special &&
         passwordForm.value.new === passwordForm.value.confirm
})

async function handleChangePassword() {
  passwordError.value = ''
  passwordSuccess.value = ''
  changingPassword.value = true
  
  try {
    await apiChangePassword(passwordForm.value.current, passwordForm.value.new)
    passwordSuccess.value = 'Password changed successfully!'
    passwordForm.value = { current: '', new: '', confirm: '' }
    passwordRequirements.value = { length: false, number: false, special: false }
    setTimeout(() => {
      closeChangePasswordModal()
    }, 1500)
  } catch (err) {
    passwordError.value = err.message || 'Failed to change password'
  } finally {
    changingPassword.value = false
  }
}

function closeChangePasswordModal() {
  showChangePasswordModal.value = false
  passwordForm.value = { current: '', new: '', confirm: '' }
  passwordRequirements.value = { length: false, number: false, special: false }
  passwordError.value = ''
  passwordSuccess.value = ''
}

// Add user form
const newUserForm = ref({ username: '', password: '', role: 'user', assignedProfileId: '' })
const newUserPasswordReqs = ref({ length: false, number: false, special: false })
const addUserError = ref('')
const addingUser = ref(false)

// Edit user form
const editUserForm = ref({ role: 'user', assignedProfileId: '' })
const editUserError = ref('')
const editingUser = ref(false)

const validateNewUserPassword = () => {
  newUserPasswordReqs.value = {
    length: newUserForm.value.password.length >= 8,
    number: /\d/.test(newUserForm.value.password),
    special: /[!@#$%^&*(),.?":{}|<>`~\-_=+\[\]\\;'\/]/.test(newUserForm.value.password)
  }
}

const canAddUser = computed(() => {
  return newUserForm.value.username.trim() &&
         newUserPasswordReqs.value.length &&
         newUserPasswordReqs.value.number &&
         newUserPasswordReqs.value.special
})

async function handleAddUser() {
  addUserError.value = ''
  addingUser.value = true
  
  try {
    await apiAddUser(
      newUserForm.value.username, 
      newUserForm.value.password, 
      newUserForm.value.role,
      newUserForm.value.assignedProfileId || null
    )
    closeAddUserModal()
    await loadUsers()
  } catch (err) {
    addUserError.value = err.message || 'Failed to add user'
  } finally {
    addingUser.value = false
  }
}

function closeAddUserModal() {
  showAddUserModal.value = false
  newUserForm.value = { username: '', password: '', role: 'user', assignedProfileId: '' }
  newUserPasswordReqs.value = { length: false, number: false, special: false }
  addUserError.value = ''
}

// Edit user functions
function openEditUserModal(user) {
  userToEdit.value = user
  editUserForm.value = {
    role: user.role || 'user',
    assignedProfileId: user.assigned_profile_id || ''
  }
  editUserError.value = ''
  showEditUserModal.value = true
}

function closeEditUserModal() {
  showEditUserModal.value = false
  userToEdit.value = null
  editUserForm.value = { role: 'user', assignedProfileId: '' }
  editUserError.value = ''
}

async function handleEditUser() {
  editUserError.value = ''
  editingUser.value = true
  
  try {
    await apiUpdateUser(userToEdit.value.id, {
      role: editUserForm.value.role,
      assigned_profile_id: editUserForm.value.assignedProfileId || null
    })
    closeEditUserModal()
    await loadUsers()
  } catch (err) {
    editUserError.value = err.message || 'Failed to update user'
  } finally {
    editingUser.value = false
  }
}

// Helper to get profile name by ID
function getProfileName(profileId) {
  if (!profileId) return 'None'
  const profile = profiles.value.find(p => p.id === profileId)
  return profile ? profile.name : 'Unknown'
}

// Delete user
const deleteUserError = ref('')
const deletingUser = ref(false)
const deleteUserConfirmText = ref('')

function confirmDeleteUser(user) {
  userToDelete.value = user
  deleteUserError.value = ''
  deleteUserConfirmText.value = ''
  showDeleteUserModal.value = true
}

async function handleDeleteUser() {
  deleteUserError.value = ''
  deletingUser.value = true
  
  try {
    await apiDeleteUser(userToDelete.value.id)
    closeDeleteUserModal()
    await loadUsers()
  } catch (err) {
    deleteUserError.value = err.message || 'Failed to delete user'
  } finally {
    deletingUser.value = false
  }
}

function closeDeleteUserModal() {
  showDeleteUserModal.value = false
  userToDelete.value = null
  deleteUserError.value = ''
  deleteUserConfirmText.value = ''
}

// Load users and profiles
async function loadUsers() {
  if (currentUser.value?.role !== 'admin') return
  
  loadingUsers.value = true
  try {
    const [usersData, profilesResponse] = await Promise.all([
      getUsers(),
      axios.get('/api/report-profiles')
    ])
    users.value = usersData.users || []
    profiles.value = profilesResponse.data.data || profilesResponse.data || []
  } catch (err) {
    console.error('Failed to load users/profiles:', err)
  } finally {
    loadingUsers.value = false
  }
}

// Logout
async function handleLogout() {
  await logout()
  router.push('/login')
}

// Timezone settings
const selectedTimezone = ref(localStorage.getItem('loglibrarian_timezone') || 'local')
const browserTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone
const currentTimeDisplay = ref('')
const timezoneSearch = ref('')
const timezoneDropdownOpen = ref(false)
const timezoneSelectorRef = ref(null)
const timezoneDropdownStyle = ref({})

function openTimezoneDropdown() {
  timezoneDropdownOpen.value = true
  // Position dropdown below the input
  if (timezoneSelectorRef.value) {
    const rect = timezoneSelectorRef.value.getBoundingClientRect()
    timezoneDropdownStyle.value = {
      position: 'fixed',
      top: `${rect.bottom + 4}px`,
      left: `${rect.left}px`,
      width: `${rect.width}px`,
      zIndex: 9999
    }
  }
}

const allTimezones = [
  // North America
  { value: 'America/New_York', label: 'Eastern Time (US)', region: 'North America' },
  { value: 'America/Chicago', label: 'Central Time (US)', region: 'North America' },
  { value: 'America/Denver', label: 'Mountain Time (US)', region: 'North America' },
  { value: 'America/Los_Angeles', label: 'Pacific Time (US)', region: 'North America' },
  { value: 'America/Phoenix', label: 'Arizona (No DST)', region: 'North America' },
  { value: 'America/Anchorage', label: 'Alaska', region: 'North America' },
  { value: 'Pacific/Honolulu', label: 'Hawaii', region: 'North America' },
  { value: 'America/Toronto', label: 'Toronto (Canada)', region: 'North America' },
  { value: 'America/Vancouver', label: 'Vancouver (Canada)', region: 'North America' },
  { value: 'America/Mexico_City', label: 'Mexico City', region: 'North America' },
  
  // South America
  { value: 'America/Sao_Paulo', label: 'São Paulo (Brazil)', region: 'South America' },
  { value: 'America/Buenos_Aires', label: 'Buenos Aires (Argentina)', region: 'South America' },
  { value: 'America/Santiago', label: 'Santiago (Chile)', region: 'South America' },
  { value: 'America/Lima', label: 'Lima (Peru)', region: 'South America' },
  { value: 'America/Bogota', label: 'Bogotá (Colombia)', region: 'South America' },
  
  // Europe
  { value: 'Europe/London', label: 'London (UK)', region: 'Europe' },
  { value: 'Europe/Dublin', label: 'Dublin (Ireland)', region: 'Europe' },
  { value: 'Europe/Paris', label: 'Paris (France)', region: 'Europe' },
  { value: 'Europe/Berlin', label: 'Berlin (Germany)', region: 'Europe' },
  { value: 'Europe/Amsterdam', label: 'Amsterdam (Netherlands)', region: 'Europe' },
  { value: 'Europe/Brussels', label: 'Brussels (Belgium)', region: 'Europe' },
  { value: 'Europe/Rome', label: 'Rome (Italy)', region: 'Europe' },
  { value: 'Europe/Madrid', label: 'Madrid (Spain)', region: 'Europe' },
  { value: 'Europe/Lisbon', label: 'Lisbon (Portugal)', region: 'Europe' },
  { value: 'Europe/Zurich', label: 'Zurich (Switzerland)', region: 'Europe' },
  { value: 'Europe/Vienna', label: 'Vienna (Austria)', region: 'Europe' },
  { value: 'Europe/Stockholm', label: 'Stockholm (Sweden)', region: 'Europe' },
  { value: 'Europe/Oslo', label: 'Oslo (Norway)', region: 'Europe' },
  { value: 'Europe/Copenhagen', label: 'Copenhagen (Denmark)', region: 'Europe' },
  { value: 'Europe/Helsinki', label: 'Helsinki (Finland)', region: 'Europe' },
  { value: 'Europe/Warsaw', label: 'Warsaw (Poland)', region: 'Europe' },
  { value: 'Europe/Prague', label: 'Prague (Czech Republic)', region: 'Europe' },
  { value: 'Europe/Athens', label: 'Athens (Greece)', region: 'Europe' },
  { value: 'Europe/Istanbul', label: 'Istanbul (Turkey)', region: 'Europe' },
  { value: 'Europe/Moscow', label: 'Moscow (Russia)', region: 'Europe' },
  { value: 'Europe/Kiev', label: 'Kyiv (Ukraine)', region: 'Europe' },
  
  // Asia
  { value: 'Asia/Tokyo', label: 'Tokyo (Japan)', region: 'Asia' },
  { value: 'Asia/Seoul', label: 'Seoul (South Korea)', region: 'Asia' },
  { value: 'Asia/Shanghai', label: 'Shanghai (China)', region: 'Asia' },
  { value: 'Asia/Hong_Kong', label: 'Hong Kong', region: 'Asia' },
  { value: 'Asia/Taipei', label: 'Taipei (Taiwan)', region: 'Asia' },
  { value: 'Asia/Singapore', label: 'Singapore', region: 'Asia' },
  { value: 'Asia/Kuala_Lumpur', label: 'Kuala Lumpur (Malaysia)', region: 'Asia' },
  { value: 'Asia/Bangkok', label: 'Bangkok (Thailand)', region: 'Asia' },
  { value: 'Asia/Ho_Chi_Minh', label: 'Ho Chi Minh (Vietnam)', region: 'Asia' },
  { value: 'Asia/Jakarta', label: 'Jakarta (Indonesia)', region: 'Asia' },
  { value: 'Asia/Manila', label: 'Manila (Philippines)', region: 'Asia' },
  { value: 'Asia/Kolkata', label: 'India (IST)', region: 'Asia' },
  { value: 'Asia/Mumbai', label: 'Mumbai (India)', region: 'Asia' },
  { value: 'Asia/Dhaka', label: 'Dhaka (Bangladesh)', region: 'Asia' },
  { value: 'Asia/Karachi', label: 'Karachi (Pakistan)', region: 'Asia' },
  { value: 'Asia/Dubai', label: 'Dubai (UAE)', region: 'Asia' },
  { value: 'Asia/Riyadh', label: 'Riyadh (Saudi Arabia)', region: 'Asia' },
  { value: 'Asia/Tel_Aviv', label: 'Tel Aviv (Israel)', region: 'Asia' },
  
  // Australia & Pacific
  { value: 'Australia/Sydney', label: 'Sydney (Australia)', region: 'Australia & Pacific' },
  { value: 'Australia/Melbourne', label: 'Melbourne (Australia)', region: 'Australia & Pacific' },
  { value: 'Australia/Brisbane', label: 'Brisbane (Australia)', region: 'Australia & Pacific' },
  { value: 'Australia/Perth', label: 'Perth (Australia)', region: 'Australia & Pacific' },
  { value: 'Australia/Adelaide', label: 'Adelaide (Australia)', region: 'Australia & Pacific' },
  { value: 'Australia/Darwin', label: 'Darwin (Australia)', region: 'Australia & Pacific' },
  { value: 'Australia/Hobart', label: 'Hobart (Australia)', region: 'Australia & Pacific' },
  { value: 'Pacific/Auckland', label: 'Auckland (New Zealand)', region: 'Australia & Pacific' },
  { value: 'Pacific/Wellington', label: 'Wellington (New Zealand)', region: 'Australia & Pacific' },
  { value: 'Pacific/Fiji', label: 'Fiji', region: 'Australia & Pacific' },
  { value: 'Pacific/Guam', label: 'Guam', region: 'Australia & Pacific' },
  
  // Africa
  { value: 'Africa/Cairo', label: 'Cairo (Egypt)', region: 'Africa' },
  { value: 'Africa/Johannesburg', label: 'Johannesburg (South Africa)', region: 'Africa' },
  { value: 'Africa/Lagos', label: 'Lagos (Nigeria)', region: 'Africa' },
  { value: 'Africa/Nairobi', label: 'Nairobi (Kenya)', region: 'Africa' },
  { value: 'Africa/Casablanca', label: 'Casablanca (Morocco)', region: 'Africa' },
]

const filteredTimezones = computed(() => {
  if (!timezoneSearch.value) return allTimezones
  const search = timezoneSearch.value.toLowerCase()
  return allTimezones.filter(tz => 
    tz.label.toLowerCase().includes(search) || 
    tz.value.toLowerCase().includes(search) ||
    tz.region.toLowerCase().includes(search)
  )
})

const selectedTimezoneLabel = computed(() => {
  if (selectedTimezone.value === 'local') return `Browser Local (${browserTimezone})`
  if (selectedTimezone.value === 'UTC') return 'UTC'
  const tz = allTimezones.find(t => t.value === selectedTimezone.value)
  return tz ? tz.label : selectedTimezone.value
})

function selectTimezone(value) {
  selectedTimezone.value = value
  timezoneDropdownOpen.value = false
  timezoneSearch.value = ''
  saveTimezone()
}

function saveTimezone() {
  localStorage.setItem('loglibrarian_timezone', selectedTimezone.value)
  updateCurrentTimeDisplay()
  // Dispatch event so other components can react
  window.dispatchEvent(new CustomEvent('timezone-changed', { detail: selectedTimezone.value }))
}

function updateCurrentTimeDisplay() {
  const now = new Date()
  const tz = selectedTimezone.value === 'local' ? browserTimezone : selectedTimezone.value
  currentTimeDisplay.value = now.toLocaleString('en-US', { 
    timeZone: tz,
    weekday: 'short',
    hour: '2-digit', 
    minute: '2-digit',
    second: '2-digit',
    timeZoneName: 'short'
  })
}

// Update clock every second when on general tab
let clockInterval = null

// Tag management
const allTags = ref([])
const loadingTags = ref(false)
const newTagName = ref('')
const creatingTag = ref(false)
const tagCreateError = ref('')
const showDeleteTagModal = ref(false)
const tagToDelete = ref(null)
const deletingTag = ref(false)

async function fetchAllTags() {
  loadingTags.value = true
  try {
    const response = await axios.get('/api/tags')
    if (response.data.success) {
      allTags.value = response.data.data || []
    }
  } catch (error) {
    console.error('Failed to fetch tags:', error)
  } finally {
    loadingTags.value = false
  }
}

async function createTag() {
  const tagName = newTagName.value.trim()
  if (!tagName) return
  
  tagCreateError.value = ''
  
  // Check if tag already exists
  if (allTags.value.includes(tagName)) {
    tagCreateError.value = `Tag "${tagName}" already exists`
    return
  }
  
  // Tags are created by being used - add it to the list locally
  // The tag will persist once it's actually used on an agent or bookmark
  allTags.value.push(tagName)
  allTags.value.sort()
  newTagName.value = ''
}

function confirmDeleteTag(tag) {
  tagToDelete.value = tag
  showDeleteTagModal.value = true
}

function cancelDeleteTag() {
  showDeleteTagModal.value = false
  tagToDelete.value = null
}

async function executeDeleteTag() {
  if (!tagToDelete.value) return
  
  deletingTag.value = true
  try {
    const response = await axios.delete(`/api/tags/${encodeURIComponent(tagToDelete.value)}`)
    if (response.data.success) {
      // Remove from local list
      allTags.value = allTags.value.filter(t => t !== tagToDelete.value)
      showDeleteTagModal.value = false
      tagToDelete.value = null
    }
  } catch (error) {
    console.error('Failed to delete tag:', error)
  } finally {
    deletingTag.value = false
  }
}

// Agent connection settings
const agentSettings = ref({ custom_url: '', fallback_order: 'lan_first', selected_lan_ip: '' })
const lanIps = ref([])
const selectedLanIpOption = ref('')
const customLanIp = ref('')
const savingAgent = ref(false)
const agentMessage = ref('')
const agentMessageClass = ref('')

// Janitor settings
const janitorStatus = ref({})
const janitorSettings = ref({
  max_storage_gb: 10,
  min_free_space_gb: 1,
  retention_raw_logs_days: 7,
  retention_metrics_days: 2,
  retention_process_snapshots_days: 7,
  // AI data retention
  retention_ai_briefings_days: 90,
  // Executive report storage
  max_exec_reports_per_profile: 12,
})
const loadingJanitor = ref(false)
const savingJanitor = ref(false)
const runningCleanup = ref(false)
const janitorMessage = ref('')
const janitorMessageClass = ref('')

// Storage calculator
const agentCount = ref(1)
const agentCountOverride = ref(null)
const profileCount = ref(1)

// Appearance
const theme = ref('dark')

// Alert Settings
const alertChannels = ref([])
const alertRules = ref([])
const alertHistory = ref([])
const loadingAlerts = ref(false)
const alertsSubTab = ref('channels')
const showChannelModal = ref(false)
const showRuleModal = ref(false)
const editingChannel = ref(null)
const editingRule = ref(null)
const deletingChannel = ref(false)
const deletingRule = ref(false)
const channelToDelete = ref(null)
const ruleToDelete = ref(null)
const showDeleteChannelModal = ref(false)
const showDeleteRuleModal = ref(false)

// Fetch notification channels
async function loadAlertChannels() {
  try {
    const response = await axios.get('/api/notifications/channels')
    alertChannels.value = response.data.channels || []
  } catch (err) {
    console.error('Failed to load channels:', err)
  }
}

// Fetch alert rules
async function loadAlertRules() {
  try {
    const response = await axios.get('/api/alerts/rules')
    alertRules.value = response.data.rules || []
  } catch (err) {
    console.error('Failed to load rules:', err)
  }
}

// Fetch alert history
async function loadAlertHistory() {
  try {
    const response = await axios.get('/api/notifications/history?limit=50')
    alertHistory.value = response.data.history || []
  } catch (err) {
    console.error('Failed to load history:', err)
  }
}

// Load all alerts data
async function loadAlertsData() {
  loadingAlerts.value = true
  try {
    await Promise.all([
      loadAlertChannels(),
      loadAlertRules(),
      loadAlertHistory()
    ])
  } finally {
    loadingAlerts.value = false
  }
}

// Open channel modal for add/edit
function openChannelModal(channel = null) {
  editingChannel.value = channel
  showChannelModal.value = true
}

// Open rule modal for add/edit
function openRuleModal(rule = null) {
  editingRule.value = rule
  showRuleModal.value = true
}

// Handle channel saved
function onChannelSaved() {
  loadAlertChannels()
}

// Handle rule saved
function onRuleSaved() {
  loadAlertRules()
}

// Delete channel
function confirmDeleteChannel(channel) {
  channelToDelete.value = channel
  showDeleteChannelModal.value = true
}

async function executeDeleteChannel() {
  if (!channelToDelete.value) return
  deletingChannel.value = true
  try {
    await axios.delete(`/api/notifications/channels/${channelToDelete.value.id}`)
    await loadAlertChannels()
    showDeleteChannelModal.value = false
    channelToDelete.value = null
  } catch (err) {
    console.error('Failed to delete channel:', err)
  } finally {
    deletingChannel.value = false
  }
}

function cancelDeleteChannel() {
  showDeleteChannelModal.value = false
  channelToDelete.value = null
}

// Delete rule
function confirmDeleteRule(rule) {
  ruleToDelete.value = rule
  showDeleteRuleModal.value = true
}

async function executeDeleteRule() {
  if (!ruleToDelete.value) return
  deletingRule.value = true
  try {
    await axios.delete(`/api/alerts/rules/${ruleToDelete.value.id}`)
    await loadAlertRules()
    showDeleteRuleModal.value = false
    ruleToDelete.value = null
  } catch (err) {
    console.error('Failed to delete rule:', err)
  } finally {
    deletingRule.value = false
  }
}

function cancelDeleteRule() {
  showDeleteRuleModal.value = false
  ruleToDelete.value = null
}

// Toggle rule enabled status
async function toggleRuleEnabled(rule) {
  try {
    await axios.put(`/api/alerts/rules/${rule.id}`, {
      ...rule,
      enabled: !rule.enabled
    })
    await loadAlertRules()
  } catch (err) {
    console.error('Failed to toggle rule:', err)
  }
}

// Get channel type icon/name
function getChannelTypeInfo(type) {
  const types = {
    discord: { icon: '💬', name: 'Discord' },
    slack: { icon: '💼', name: 'Slack' },
    email: { icon: '📧', name: 'Email' },
    telegram: { icon: '📱', name: 'Telegram' },
    pushover: { icon: '🔔', name: 'Pushover' },
    custom: { icon: '🌐', name: 'Custom' }
  }
  return types[type] || { icon: '🔔', name: type }
}

// Format rule condition for display
function formatRuleCondition(rule) {
  const metricNames = {
    cpu: 'CPU',
    ram: 'Memory',
    disk: 'Disk',
    disk_free: 'Free disk',
    cpu_temp: 'CPU temp',
    net_bandwidth: 'Network',
    status: rule.scope === 'bookmark' ? 'Failures' : 'Offline',
    response_time: 'Response time',
    ssl_expiry: 'SSL expiry'
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
    cpu_temp: '°C',
    response_time: 'ms',
    ssl_expiry: 'd'
  }
  
  const metric = metricNames[rule.metric] || rule.metric
  const op = opSymbols[rule.operator] || rule.operator
  const unit = units[rule.metric] || ''
  
  return `${metric} ${op} ${rule.threshold}${unit}`
}

// Format timestamp for history
function formatAlertTime(timestamp) {
  if (!timestamp) return ''
  const date = new Date(timestamp)
  return date.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}

// Computed
const diskClass = computed(() => {
  const used = janitorStatus.value.disk?.used_percent || 0
  if (used >= 95) return 'critical'
  if (used >= 85) return 'warning'
  return 'ok'
})

// Storage estimate calculator
const effectiveAgentCount = computed(() => agentCountOverride.value || agentCount.value || 1)

// Executive report storage estimate (profiles × max reports × 2MB)
const execReportStorageMB = computed(() => {
  const profiles = profileCount.value || 1
  const maxReports = janitorSettings.value.max_exec_reports_per_profile || 12
  return profiles * maxReports * 2  // 2MB per report
})

const execReportStorageEstimate = computed(() => {
  const mb = execReportStorageMB.value
  if (mb >= 1024) {
    return `${(mb / 1024).toFixed(1)} GB`
  }
  return `${mb} MB`
})

// Database storage estimate (without exec reports)
const estimatedDBStorageGB = computed(() => {
  const agents = effectiveAgentCount.value
  const logDays = janitorSettings.value.retention_raw_logs_days || 7
  const metricsDays = janitorSettings.value.retention_metrics_days || 2
  const processDays = janitorSettings.value.retention_process_snapshots_days || 7
  const briefingDays = janitorSettings.value.retention_ai_briefings_days || 90
  
  const logsGB = (agents * logDays * 0.5) / 1024
  const metricsGB = (agents * metricsDays * 4.5) / 1024
  const processGB = (agents * processDays * 0.2) / 1024
  const aiGB = (briefingDays * 0.05) / 1024
  
  return (logsGB + metricsGB + processGB + aiGB).toFixed(1)
})

const estimatedStorageGB = computed(() => {
  const agents = effectiveAgentCount.value
  const logDays = janitorSettings.value.retention_raw_logs_days || 7
  const metricsDays = janitorSettings.value.retention_metrics_days || 2
  const processDays = janitorSettings.value.retention_process_snapshots_days || 7
  
  // AI data retention
  const briefingDays = janitorSettings.value.retention_ai_briefings_days || 90
  
  // Estimates per agent per day:
  // - Logs: ~500KB/day (varies wildly, assume moderate logging)
  // - Metrics: ~4.5MB/day at 1-sec intervals (86400 records × ~50 bytes)
  // - Process snapshots: ~200KB/day (periodic snapshots)
  
  const logsGB = (agents * logDays * 0.5) / 1024  // 0.5 MB/day
  const metricsGB = (agents * metricsDays * 4.5) / 1024  // 4.5 MB/day
  const processGB = (agents * processDays * 0.2) / 1024  // 0.2 MB/day
  
  // AI data estimates (not per-agent, global):
  // - Briefings: ~50KB each, 1/day
  const aiGB = (briefingDays * 0.05) / 1024
  
  // Executive reports storage
  const execReportsGB = execReportStorageMB.value / 1024
  
  return (logsGB + metricsGB + processGB + aiGB + execReportsGB).toFixed(1)
})

const storageWarningLevel = computed(() => {
  const est = parseFloat(estimatedStorageGB.value)
  const max = janitorSettings.value.max_storage_gb
  if (est > max * 0.9) return 'danger'
  if (est > max * 0.7) return 'warning'
  return 'ok'
})

// Fetch all settings data
const fetchData = async () => {
  try {
    await Promise.all([
      loadGeneralSettings(),
      loadLanIps(),
      loadJanitorStatus(),
      loadJanitorSettings(),
      loadAgentCount(),
      fetchAllTags(),
      loadAlertsData(),
    ])
    await loadAgentConnectionSettings()
  } catch (e) {
    console.error('Failed to load settings:', e)
  }
}

// Mount
onMounted(() => {
  fetchData()
  loadUsers()
  updateCurrentTimeDisplay()
  clockInterval = setInterval(updateCurrentTimeDisplay, 1000)
})

// Handle keep-alive reactivation
onActivated(() => {
  fetchData()
  loadUsers()
})

// Cleanup
onUnmounted(() => {
  if (clockInterval) clearInterval(clockInterval)
  document.removeEventListener('click', handleClickOutside)
})

// Click outside handler for timezone dropdown
function handleClickOutside(e) {
  const selector = document.querySelector('.timezone-selector')
  if (selector && !selector.contains(e.target)) {
    timezoneDropdownOpen.value = false
  }
}

// Add click outside listener
document.addEventListener('click', handleClickOutside)

// General settings
async function loadGeneralSettings() {
  try {
    const res = await axios.get('/api/settings')
    settings.value.public_app_url = res.data.settings?.public_app_url || ''
  } catch (e) { console.error('Failed to load settings:', e) }
  
  // Load instance API key
  try {
    const res = await axios.get('/api/settings/api-key')
    instanceApiKey.value = res.data.api_key || ''
  } catch (e) { console.error('Failed to load API key:', e) }
}

// Copy API key to clipboard
async function copyApiKey() {
  if (!instanceApiKey.value) return
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(instanceApiKey.value)
    } else {
      // Fallback for non-HTTPS
      const textArea = document.createElement('textarea')
      textArea.value = instanceApiKey.value
      textArea.style.position = 'fixed'
      textArea.style.left = '-999999px'
      document.body.appendChild(textArea)
      textArea.select()
      document.execCommand('copy')
      document.body.removeChild(textArea)
    }
    apiKeyCopied.value = true
    setTimeout(() => apiKeyCopied.value = false, 2000)
  } catch (e) {
    console.error('Failed to copy:', e)
  }
}

async function saveGeneralSettings() {
  savingGeneral.value = true
  generalMessage.value = ''
  try {
    await axios.put('/api/settings', { public_app_url: settings.value.public_app_url })
    generalMessage.value = '✓ Saved'
    generalMessageClass.value = 'text-success'
    setTimeout(() => generalMessage.value = '', 3000)
  } catch (e) {
    generalMessage.value = e.response?.data?.detail || 'Failed'
    generalMessageClass.value = 'text-danger'
  } finally {
    savingGeneral.value = false
  }
}

// Agent settings
async function loadLanIps() {
  try {
    const res = await axios.get('/api/lan-ips')
    lanIps.value = res.data.ips || []
  } catch (e) { lanIps.value = [] }
}

async function loadAgentConnectionSettings() {
  try {
    const res = await axios.get('/api/agent-connection-settings')
    agentSettings.value.custom_url = res.data.custom_url || ''
    agentSettings.value.fallback_order = res.data.fallback_order || 'lan_first'
    agentSettings.value.selected_lan_ip = res.data.selected_lan_ip || ''
    
    const savedIp = res.data.selected_lan_ip || ''
    if (!savedIp) {
      selectedLanIpOption.value = ''
    } else if (lanIps.value.includes(savedIp)) {
      selectedLanIpOption.value = savedIp
    } else {
      selectedLanIpOption.value = 'custom'
      customLanIp.value = savedIp
    }
  } catch (e) { console.error('Failed to load agent settings:', e) }
}

function onLanIpOptionChange() {
  if (selectedLanIpOption.value === 'custom') {
    agentSettings.value.selected_lan_ip = customLanIp.value
  } else {
    agentSettings.value.selected_lan_ip = selectedLanIpOption.value
    customLanIp.value = ''
  }
}

function onCustomLanIpBlur() {
  agentSettings.value.selected_lan_ip = customLanIp.value
}

async function saveAgentSettings() {
  savingAgent.value = true
  agentMessage.value = ''
  try {
    await axios.put('/api/agent-connection-settings', {
      custom_url: agentSettings.value.custom_url,
      fallback_order: agentSettings.value.fallback_order,
      selected_lan_ip: agentSettings.value.selected_lan_ip,
    })
    agentMessage.value = '✓ Saved'
    agentMessageClass.value = 'text-success'
    setTimeout(() => agentMessage.value = '', 3000)
  } catch (e) {
    agentMessage.value = e.response?.data?.detail || 'Failed'
    agentMessageClass.value = 'text-danger'
  } finally {
    savingAgent.value = false
  }
}

// Janitor settings
async function loadJanitorStatus() {
  loadingJanitor.value = true
  try {
    const res = await axios.get('/api/janitor/status')
    janitorStatus.value = res.data
  } catch (e) { console.error('Failed to load janitor status:', e) }
  finally { loadingJanitor.value = false }
}

async function loadJanitorSettings() {
  try {
    const res = await axios.get('/api/janitor/settings')
    if (res.data.settings) {
      janitorSettings.value = { ...janitorSettings.value, ...res.data.settings }
    }
    
    // Also load profile count for the estimator
    try {
      const profilesRes = await axios.get('/api/report-profiles')
      profileCount.value = profilesRes.data.profiles?.length || 1
    } catch (e) {
      profileCount.value = 1
    }
  } catch (e) { console.error('Failed to load janitor settings:', e) }
}

async function saveJanitorSettings() {
  savingJanitor.value = true
  janitorMessage.value = ''
  try {
    await axios.put('/api/janitor/settings', janitorSettings.value)
    janitorMessage.value = '✓ Settings saved'
    janitorMessageClass.value = 'text-success'
    await loadJanitorStatus()
    setTimeout(() => janitorMessage.value = '', 3000)
  } catch (e) {
    janitorMessage.value = e.response?.data?.detail || 'Failed to save'
    janitorMessageClass.value = 'text-danger'
  } finally {
    savingJanitor.value = false
  }
}

async function runCleanup() {
  runningCleanup.value = true
  janitorMessage.value = ''
  try {
    const res = await axios.post('/api/janitor/run')
    const total = (res.data.time_based_cleanup?.total_rows_deleted || 0) + 
                  (res.data.size_based_cleanup?.rows_deleted || 0)
    janitorMessage.value = `✓ Cleaned ${total.toLocaleString()} rows`
    janitorMessageClass.value = 'text-success'
    await loadJanitorStatus()
    setTimeout(() => janitorMessage.value = '', 5000)
  } catch (e) {
    janitorMessage.value = e.response?.data?.detail || 'Cleanup failed'
    janitorMessageClass.value = 'text-danger'
  } finally {
    runningCleanup.value = false
  }
}

function formatSize(bytes) {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  while (bytes >= 1024 && i < units.length - 1) { bytes /= 1024; i++ }
  return `${bytes.toFixed(1)} ${units[i]}`
}

// Agent count for storage calculator
async function loadAgentCount() {
  try {
    const res = await axios.get('/api/agents')
    agentCount.value = res.data.agents?.length || 1
  } catch (e) { 
    agentCount.value = 1 
  }
}
</script>

<style scoped>
/* Coming Soon Styles */
.coming-soon-settings {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 4rem 2rem;
  text-align: center;
}

.coming-soon-settings .coming-soon-icon {
  font-size: 4rem;
  margin-bottom: 1rem;
}

.coming-soon-settings h3 {
  font-size: 1.5rem;
  color: var(--text-primary, #fff);
  margin-bottom: 0.5rem;
}

.coming-soon-settings p {
  color: var(--text-secondary, #888);
  margin-bottom: 1.5rem;
}

.coming-soon-features-inline {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  justify-content: center;
}

.coming-soon-features-inline .feature-badge {
  padding: 0.5rem 1rem;
  background: var(--bg-tertiary, #2a2a2a);
  border-radius: 20px;
  color: var(--text-secondary, #aaa);
  font-size: 0.9rem;
}

.settings-view {
  max-width: 900px;
  padding-bottom: 2rem;
}

/* Tabs */
.settings-tabs {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 1.5rem;
  border-bottom: 1px solid var(--border-color, #404040);
  padding-bottom: 0.5rem;
}

.tab-btn {
  padding: 0.75rem 1.25rem;
  border: none;
  background: transparent;
  color: var(--text-muted, #888);
  border-radius: 8px 8px 0 0;
  cursor: pointer;
  transition: all 0.2s;
  font-weight: 500;
}

.tab-btn:hover {
  color: var(--text-color, #fff);
  background: rgba(255,255,255,0.05);
}

.tab-btn.active {
  color: var(--primary-color, #5865f2);
  background: rgba(88, 101, 242, 0.15);
}

/* Sections */
.settings-section {
  background: var(--card-bg, #2c2c2c);
  border: 1px solid var(--border-color, #404040);
  border-radius: 12px;
  margin-bottom: 0.75rem;
  overflow: hidden;
}

.section-header {
  display: flex;
  align-items: flex-start;
  gap: 1rem;
  padding: 1rem;
  background: var(--card-header-bg, #252525);
  border-bottom: 1px solid var(--border-color, #404040);
}

.section-header > i {
  font-size: 1.25rem;
  color: var(--primary-color, #5865f2);
  margin-top: 0.15rem;
}

.section-header h5 {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 600;
}

.section-header p {
  margin: 0.15rem 0 0;
  font-size: 0.8rem;
  color: var(--text-muted, #888);
}

.section-content {
  padding: 1rem;
}

.section-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.5rem;
  padding: 0.75rem 1rem;
  background: rgba(0,0,0,0.1);
  border-top: 1px solid var(--border-color, #404040);
}

/* Forms */
.form-group {
  margin-bottom: 1.25rem;
}

.form-group:last-child {
  margin-bottom: 0;
}

.form-group label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 500;
  margin-bottom: 0.5rem;
}

.form-hint {
  display: block;
  font-size: 0.8rem;
  color: var(--text-muted, #888);
  margin-top: 0.5rem;
}

/* Timezone Selector */
.timezone-selector {
  position: relative;
}

.timezone-search {
  width: 100%;
}

.timezone-dropdown {
  max-height: 350px;
  overflow-y: auto;
  background: var(--card-bg, #1e1e1e);
  border: 1px solid var(--border-color, #404040);
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
}

.timezone-option {
  padding: 0.6rem 0.9rem;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  border-bottom: 1px solid var(--border-color, #333);
}

.timezone-option:last-child {
  border-bottom: none;
}

.timezone-option:hover {
  background: rgba(99, 102, 241, 0.15);
}

.timezone-option.selected {
  background: rgba(99, 102, 241, 0.25);
}

.timezone-option .tz-label {
  font-weight: 500;
  color: var(--text-color, #fff);
}

.timezone-option .tz-value {
  font-size: 0.75rem;
  color: var(--text-muted, #888);
}

.timezone-divider {
  height: 1px;
  background: var(--border-color, #404040);
  margin: 0.25rem 0;
}

.timezone-empty {
  padding: 1rem;
  text-align: center;
  color: var(--text-muted, #888);
  font-size: 0.9rem;
}

.selected-timezone {
  margin-top: 0.5rem;
  padding: 0.5rem 0.75rem;
  background: rgba(99, 102, 241, 0.1);
  border-radius: 6px;
  font-size: 0.85rem;
  color: var(--text-color, #fff);
}

.selected-timezone strong {
  color: var(--text-muted, #888);
  margin-right: 0.5rem;
}

.value-badge {
  background: var(--primary-color, #5865f2);
  color: white;
  padding: 0.2rem 0.6rem;
  border-radius: 4px;
  font-size: 0.8rem;
  font-weight: 600;
}

.form-control, .form-select {
  background: var(--input-bg, #1a1a1a);
  border: 1px solid var(--border-color, #404040);
  color: var(--text-color, #fff);
  border-radius: 8px;
  padding: 0.6rem 0.9rem;
  width: 100%;
}

.form-control:focus, .form-select:focus {
  background: var(--input-bg, #1a1a1a);
  border-color: var(--primary-color, #5865f2);
  box-shadow: 0 0 0 3px rgba(88, 101, 242, 0.2);
  outline: none;
}

.input-group {
  display: flex;
  gap: 0;
}

.input-group .form-select {
  border-radius: 8px 0 0 8px;
}

.input-group .form-control {
  border-radius: 0 8px 8px 0;
  border-left: none;
}

.form-range {
  width: 100%;
  height: 8px;
  background: var(--input-bg, #1a1a1a);
  border-radius: 4px;
  -webkit-appearance: none;
  appearance: none;
  cursor: pointer;
}

.form-range::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 20px;
  height: 20px;
  background: var(--primary-color, #5865f2);
  border-radius: 50%;
  cursor: pointer;
  transition: transform 0.1s;
}

.form-range::-webkit-slider-thumb:hover {
  transform: scale(1.1);
}

.form-range::-moz-range-thumb {
  width: 20px;
  height: 20px;
  background: var(--primary-color, #5865f2);
  border-radius: 50%;
  cursor: pointer;
  border: none;
}

.examples-box {
  background: rgba(0,0,0,0.2);
  padding: 0.75rem 1rem;
  border-radius: 8px;
  margin-top: 1rem;
  font-size: 0.85rem;
}

.examples-box ul {
  margin: 0.5rem 0 0;
  padding-left: 1.25rem;
}

.examples-box code {
  background: rgba(88, 101, 242, 0.2);
  padding: 0.15rem 0.4rem;
  border-radius: 4px;
  color: var(--primary-color, #5865f2);
}

/* Status Cards */
.status-card {
  background: var(--card-bg, #2c2c2c);
  border: 1px solid var(--border-color, #404040);
  border-radius: 12px;
  overflow: hidden;
}

.status-card-header {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 1rem 1.25rem;
  background: var(--card-header-bg, #252525);
  border-bottom: 1px solid var(--border-color, #404040);
  font-weight: 600;
}

.status-card-header i {
  color: var(--primary-color, #5865f2);
}

.status-card-header .btn-icon {
  margin-left: auto;
  background: transparent;
  border: none;
  color: var(--text-muted, #888);
  cursor: pointer;
  padding: 0.25rem;
}

.status-card-header .btn-icon:hover {
  color: var(--text-color, #fff);
}

/* Disk Visual */
.disk-visual {
  padding: 1.25rem;
}

.disk-bar {
  height: 24px;
  background: rgba(0,0,0,0.3);
  border-radius: 12px;
  overflow: hidden;
  margin-bottom: 1rem;
}

.disk-used {
  height: 100%;
  border-radius: 12px;
  transition: width 0.5s ease;
}

.disk-used.ok {
  background: linear-gradient(90deg, #22c55e, #16a34a);
}

.disk-used.warning {
  background: linear-gradient(90deg, #eab308, #ca8a04);
}

.disk-used.critical {
  background: linear-gradient(90deg, #ef4444, #dc2626);
}

.disk-stats {
  display: flex;
  justify-content: space-around;
  text-align: center;
}

.disk-stat .value {
  display: block;
  font-size: 1.25rem;
  font-weight: 600;
  color: var(--text-color, #fff);
}

.disk-stat .label {
  font-size: 0.75rem;
  color: var(--text-muted, #888);
  text-transform: uppercase;
}

/* Stats Grid */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 1rem;
  padding: 1.25rem;
}

.stat-item {
  text-align: center;
  padding: 0.75rem;
  background: rgba(0,0,0,0.2);
  border-radius: 8px;
}

.stat-value {
  display: block;
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--text-color, #fff);
}

.stat-value.highlight {
  color: #22c55e;
  text-transform: capitalize;
}

.stat-label {
  font-size: 0.7rem;
  color: var(--text-muted, #888);
  text-transform: uppercase;
  margin-top: 0.25rem;
  display: block;
}

/* Panic Alert */
.panic-alert {
  display: flex;
  align-items: flex-start;
  gap: 1rem;
  padding: 1rem 1.25rem;
  background: rgba(239, 68, 68, 0.15);
  border: 1px solid rgba(239, 68, 68, 0.4);
  border-radius: 12px;
  margin-bottom: 1.5rem;
  color: #fca5a5;
}

.panic-alert i {
  font-size: 1.5rem;
  color: #ef4444;
}

.panic-alert strong {
  color: #ef4444;
}

.panic-alert p {
  margin: 0.25rem 0 0;
  font-size: 0.875rem;
}

/* Buttons */
.btn {
  padding: 0.6rem 1.25rem;
  border-radius: 8px;
  font-weight: 500;
  transition: all 0.2s;
  border: none;
  cursor: pointer;
}

.btn-primary {
  background: var(--primary-color, #5865f2);
  color: white;
}

.btn-primary:hover:not(:disabled) {
  background: #4752c4;
}

.btn-warning {
  background: #ca8a04;
  color: white;
}

.btn-warning:hover:not(:disabled) {
  background: #a16207;
}

.btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.text-success {
  color: #22c55e;
}

.text-danger {
  color: #ef4444;
}

/* Animations */
.spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* Storage Estimate Calculator */
.storage-estimate {
  background: rgba(88, 101, 242, 0.1);
  border: 1px solid rgba(88, 101, 242, 0.3);
  border-radius: 8px;
  padding: 1rem;
  margin-top: 1.5rem;
}

.storage-estimate.warning {
  background: rgba(234, 179, 8, 0.1);
  border-color: rgba(234, 179, 8, 0.4);
}

.storage-estimate.danger {
  background: rgba(239, 68, 68, 0.1);
  border-color: rgba(239, 68, 68, 0.4);
}

.estimate-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-weight: 600;
  margin-bottom: 0.75rem;
  color: var(--primary-color, #5865f2);
}

.storage-estimate.warning .estimate-header {
  color: #eab308;
}

.storage-estimate.danger .estimate-header {
  color: #ef4444;
}

.estimate-body {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 1rem;
}

.estimate-main {
  display: flex;
  flex-direction: column;
}

.estimate-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: var(--text-color, #fff);
}

.estimate-label {
  font-size: 0.8rem;
  color: var(--text-muted, #888);
}

.estimate-agents {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.estimate-agents label {
  font-size: 0.85rem;
  margin: 0;
}

.agent-count-input {
  width: 70px !important;
  text-align: center;
  padding: 0.25rem 0.5rem !important;
}

.estimate-warning {
  margin-top: 0.75rem;
  padding: 0.5rem 0.75rem;
  background: rgba(234, 179, 8, 0.2);
  border-radius: 4px;
  font-size: 0.85rem;
  color: #eab308;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.estimate-warning.danger {
  background: rgba(239, 68, 68, 0.2);
  color: #ef4444;
}

/* ==================== COMPACT STORAGE TAB STYLES ==================== */

.storage-compact {
  padding: 1rem !important;
}

/* Combined Status Row */
.status-row-compact {
  display: grid;
  grid-template-columns: 1fr 1.5fr;
  gap: 1rem;
  margin-bottom: 1rem;
}

.status-card-compact {
  background: var(--surface-2, #1a1a1a);
  border: 1px solid var(--border-color, #333);
  border-radius: 10px;
  padding: 0.75rem 1rem;
}

.status-card-compact .status-card-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.85rem;
  font-weight: 600;
  margin-bottom: 0.5rem;
  padding: 0;
  background: none;
  border: none;
}

.status-card-compact .status-card-header i {
  color: var(--primary-color, #5865f2);
}

.btn-icon-sm {
  margin-left: auto;
  background: none;
  border: none;
  color: var(--text-muted, #888);
  cursor: pointer;
  padding: 0.25rem;
  font-size: 0.8rem;
}

.btn-icon-sm:hover {
  color: var(--text-color, #fff);
}

.disk-bar-compact {
  height: 6px;
  background: rgba(255,255,255,0.1);
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: 0.5rem;
}

.disk-stats-compact {
  display: flex;
  justify-content: space-between;
  font-size: 0.75rem;
  color: var(--text-muted, #888);
}

.stats-row-compact {
  display: flex;
  gap: 0.75rem;
}

.stat-compact {
  flex: 1;
  text-align: center;
  padding: 0.4rem;
  background: rgba(0,0,0,0.2);
  border-radius: 6px;
}

.stat-compact .val {
  display: block;
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--text-color, #fff);
}

.stat-compact .val.highlight {
  color: #22c55e;
  text-transform: capitalize;
}

.stat-compact .lbl {
  font-size: 0.65rem;
  color: var(--text-muted, #888);
  text-transform: uppercase;
}

/* Two Column Grid */
.settings-grid-2col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1.5rem;
  margin-bottom: 1rem;
}

.settings-column {
  background: var(--surface-2, #1a1a1a);
  border: 1px solid var(--border-color, #333);
  border-radius: 10px;
  padding: 1rem;
}

.section-header-compact {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}

.section-header-compact i {
  color: var(--primary-color, #5865f2);
  font-size: 1rem;
}

.section-header-compact h5 {
  margin: 0;
  font-size: 0.9rem;
  font-weight: 600;
}

.slider-group {
  margin-bottom: 0.6rem;
}

.slider-group label {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.8rem;
  margin-bottom: 0.2rem;
  color: var(--text-color, #e0e0e0);
}

.slider-group .form-range {
  height: 4px;
}

.value-badge-sm {
  background: rgba(88, 101, 242, 0.2);
  color: #818cf8;
  padding: 0.15rem 0.4rem;
  border-radius: 4px;
  font-size: 0.7rem;
  font-weight: 600;
}

.mt-3 {
  margin-top: 0.75rem !important;
}

/* Compact Storage Estimate */
.storage-estimate-compact {
  background: var(--surface-1, #121212);
  border: 1px solid var(--border-color, #333);
  border-radius: 8px;
  padding: 0.75rem;
  margin-top: 0.75rem;
}

.storage-estimate-compact.warning {
  border-color: rgba(234, 179, 8, 0.4);
  background: rgba(234, 179, 8, 0.1);
}

.storage-estimate-compact.danger {
  border-color: rgba(239, 68, 68, 0.4);
  background: rgba(239, 68, 68, 0.1);
}

.estimate-header-compact {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.75rem;
  color: var(--text-muted, #888);
  margin-bottom: 0.25rem;
}

.estimate-header-compact i {
  color: var(--primary-color, #5865f2);
}

.estimate-agents-compact {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 0.25rem;
  font-size: 0.7rem;
}

.agent-input-sm {
  width: 45px;
  padding: 0.15rem 0.3rem;
  font-size: 0.7rem;
  text-align: center;
  background: var(--surface-2, #1a1a1a);
  border: 1px solid var(--border-color, #444);
  border-radius: 4px;
  color: var(--text-color, #fff);
}

.estimate-value-compact {
  font-size: 1.25rem;
  font-weight: 700;
  color: var(--text-color, #fff);
}

.estimate-warning-compact {
  margin-top: 0.5rem;
  padding: 0.35rem 0.5rem;
  font-size: 0.7rem;
  border-radius: 4px;
  display: flex;
  align-items: center;
  gap: 0.35rem;
}

.storage-estimate-compact.warning .estimate-warning-compact {
  background: rgba(234, 179, 8, 0.2);
  color: #eab308;
}

.storage-estimate-compact.danger .estimate-warning-compact {
  background: rgba(239, 68, 68, 0.2);
  color: #ef4444;
}

/* Actions Row */
.actions-row-compact {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem 1rem;
  background: var(--surface-2, #1a1a1a);
  border: 1px solid var(--border-color, #333);
  border-radius: 10px;
}

.actions-row-compact .btn {
  padding: 0.5rem 1rem;
  font-size: 0.85rem;
}

/* AI Settings Styles */

/* Master Toggle */
.ai-master-toggle {
  background: linear-gradient(135deg, rgba(88, 101, 242, 0.15), rgba(139, 92, 246, 0.15));
  border-color: rgba(88, 101, 242, 0.3);
}

.ai-master-toggle .section-content {
  padding: 1.5rem;
}

.master-toggle-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1.5rem;
}

.master-toggle-info {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.master-icon {
  font-size: 2.5rem;
}

.master-toggle-info h4 {
  margin: 0;
  font-size: 1.25rem;
  font-weight: 600;
  color: var(--text-color, #fff);
}

.master-toggle-info p {
  margin: 0.25rem 0 0;
  font-size: 0.875rem;
  color: var(--text-muted, #888);
}

.toggle-switch.large {
  width: 60px;
  height: 32px;
}

.toggle-switch.large .toggle-slider:before {
  height: 26px;
  width: 26px;
}

.toggle-switch.large input:checked + .toggle-slider:before {
  transform: translateX(28px);
}

.ai-disabled-notice {
  margin-top: 1rem;
  padding: 0.75rem 1rem;
  background: rgba(234, 179, 8, 0.1);
  border: 1px solid rgba(234, 179, 8, 0.3);
  border-radius: 8px;
  font-size: 0.85rem;
  color: #eab308;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

/* AI Status Card */
.ai-status-card {
  background: var(--card-bg, #2c2c2c);
  border: 1px solid var(--border-color, #404040);
  border-radius: 12px;
  padding: 1rem 1.5rem;
  margin-bottom: 1.5rem;
}

.status-row {
  display: flex;
  gap: 2rem;
  flex-wrap: wrap;
}

.status-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.status-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.1rem;
}

.status-icon.running {
  background: rgba(34, 197, 94, 0.15);
  color: #22c55e;
}

.status-icon.ready {
  background: rgba(59, 130, 246, 0.15);
  color: #3b82f6;
}

.status-icon.warning {
  background: rgba(234, 179, 8, 0.15);
  color: #eab308;
}

.status-icon.disabled {
  background: rgba(148, 163, 184, 0.15);
  color: #94a3b8;
}

.status-icon.provider {
  background: rgba(139, 92, 246, 0.15);
  color: #8b5cf6;
}

.status-icon.model {
  background: rgba(236, 72, 153, 0.15);
  color: #ec4899;
}

.status-info {
  display: flex;
  flex-direction: column;
}

.status-label {
  font-size: 0.7rem;
  text-transform: uppercase;
  color: var(--text-muted, #888);
  letter-spacing: 0.5px;
}

.status-value {
  font-weight: 600;
  color: var(--text-color, #fff);
}

/* API Key Input */
.api-key-input .form-control {
  border-radius: 8px 0 0 8px;
}

.api-key-input .btn {
  border-radius: 0 8px 8px 0;
}

.api-key-status {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-top: 1rem;
  padding: 0.75rem 1rem;
  background: rgba(34, 197, 94, 0.1);
  border-radius: 8px;
  font-size: 0.875rem;
}

.api-test-result {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-top: 0.75rem;
  padding: 0.75rem 1rem;
  border-radius: 8px;
  font-size: 0.875rem;
}

.api-test-result.success {
  background: rgba(34, 197, 94, 0.1);
  color: #22c55e;
}

.api-test-result.error {
  background: rgba(239, 68, 68, 0.1);
  color: #ef4444;
}

/* Model Status Labels */
.model-status {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.75rem;
  font-weight: 500;
  padding: 0.25rem 0.5rem;
  border-radius: 4px;
  margin-right: 0.5rem;
}

.model-status.not-downloaded {
  background: rgba(148, 163, 184, 0.15);
  color: #94a3b8;
}

.model-status.ready {
  background: rgba(34, 197, 94, 0.15);
  color: #22c55e;
}

/* Runner Status */
.runner-status {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-top: 1.5rem;
  padding: 1rem 1.25rem;
  background: rgba(0, 0, 0, 0.2);
  border-radius: 10px;
  border: 1px solid transparent;
}

.runner-status.ready {
  border-color: rgba(34, 197, 94, 0.3);
}

.runner-status.not-installed {
  border-color: rgba(234, 179, 8, 0.3);
}

.runner-status.downloading {
  border-color: rgba(59, 130, 246, 0.3);
}

.runner-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.25rem;
}

.runner-status.ready .runner-icon {
  background: rgba(34, 197, 94, 0.15);
  color: #22c55e;
}

.runner-status.not-installed .runner-icon {
  background: rgba(234, 179, 8, 0.15);
  color: #eab308;
}

.runner-status.downloading .runner-icon {
  background: rgba(59, 130, 246, 0.15);
  color: #3b82f6;
}

.runner-info {
  flex: 1;
}

.runner-label {
  display: block;
  font-size: 0.75rem;
  text-transform: uppercase;
  color: var(--text-muted, #888);
  letter-spacing: 0.5px;
}

.runner-value {
  font-weight: 600;
  color: var(--text-color, #fff);
}

.runner-progress {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  min-width: 200px;
}

.runner-progress .progress {
  flex: 1;
  height: 8px;
  background: rgba(0,0,0,0.3);
  border-radius: 4px;
  overflow: hidden;
}

.runner-progress .progress-bar {
  height: 100%;
  background: linear-gradient(90deg, #3b82f6, #8b5cf6);
  border-radius: 4px;
  transition: width 0.3s ease;
}

.runner-progress .progress-text {
  font-size: 0.8rem;
  color: var(--text-muted, #aaa);
  white-space: nowrap;
  min-width: 100px;
}

.provider-toggle {
  display: flex;
  gap: 1rem;
}

.provider-btn {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 1.5rem 1rem;
  background: rgba(0,0,0,0.2);
  border: 2px solid transparent;
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.2s;
  text-align: center;
  color: var(--text-muted, #888);
}

.provider-btn:hover {
  background: rgba(0,0,0,0.3);
  border-color: rgba(255,255,255,0.1);
}

.provider-btn.active {
  background: rgba(34, 197, 94, 0.1);
  border-color: #22c55e;
  color: var(--text-color, #fff);
}

.provider-btn i {
  font-size: 2rem;
  margin-bottom: 0.75rem;
}

.provider-title {
  font-weight: 600;
  font-size: 1.1rem;
  color: inherit;
}

.provider-badge {
  font-size: 0.7rem;
  padding: 0.2rem 0.6rem;
  border-radius: 20px;
  margin-top: 0.5rem;
  font-weight: 600;
  text-transform: uppercase;
}

.provider-badge.free {
  background: rgba(34, 197, 94, 0.2);
  color: #22c55e;
}

.provider-badge.cloud {
  background: rgba(59, 130, 246, 0.2);
  color: #3b82f6;
}

.provider-desc {
  font-size: 0.8rem;
  margin-top: 0.5rem;
  color: var(--text-muted, #888);
}

/* Model Cards */
.model-cards {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.model-card {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1rem 1.25rem;
  background: rgba(0,0,0,0.2);
  border: 2px solid transparent;
  border-radius: 12px;
  transition: all 0.2s;
}

.model-card:hover {
  background: rgba(0,0,0,0.3);
}

.model-card.active {
  background: rgba(34, 197, 94, 0.1);
  border-color: #22c55e;
}

.model-card.downloading {
  background: rgba(59, 130, 246, 0.1);
  border-color: rgba(59, 130, 246, 0.5);
}

.model-icon {
  font-size: 2rem;
  width: 48px;
  text-align: center;
}

.model-info {
  flex: 1;
}

.model-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.25rem;
}

.model-name {
  font-weight: 600;
  color: var(--text-color, #fff);
}

.model-badge {
  font-size: 0.65rem;
  padding: 0.15rem 0.5rem;
  border-radius: 20px;
  font-weight: 600;
}

.model-badge.speed {
  background: rgba(234, 179, 8, 0.2);
  color: #eab308;
}

.model-badge.technical {
  background: rgba(139, 92, 246, 0.2);
  color: #8b5cf6;
}

.model-badge.brain {
  background: rgba(236, 72, 153, 0.2);
  color: #ec4899;
}

.model-desc {
  font-size: 0.8rem;
  color: var(--text-muted, #888);
  margin: 0 0 0.25rem;
}

.model-size {
  font-size: 0.7rem;
  color: var(--text-muted, #666);
}

.model-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.active-badge {
  color: #22c55e;
  font-weight: 600;
  font-size: 0.85rem;
}

.download-progress {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  min-width: 120px;
}

.download-progress .progress {
  flex: 1;
  height: 8px;
  background: rgba(0,0,0,0.3);
  border-radius: 4px;
  overflow: hidden;
}

.download-progress .progress-bar {
  background: linear-gradient(90deg, #3b82f6, #60a5fa);
}

.progress-text {
  font-size: 0.75rem;
  color: #3b82f6;
  font-weight: 600;
  min-width: 35px;
}

.model-note {
  margin-top: 1rem;
  padding: 0.75rem 1rem;
  background: rgba(59, 130, 246, 0.1);
  border-radius: 8px;
  font-size: 0.8rem;
  color: #93c5fd;
}

.model-note i {
  margin-right: 0.5rem;
}

/* Feature Toggles */
.feature-toggles {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.feature-toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem 1.25rem;
  background: rgba(0,0,0,0.2);
  border-radius: 10px;
  transition: background 0.2s;
}

.feature-toggle:hover {
  background: rgba(0,0,0,0.3);
}

.feature-info {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.feature-icon {
  font-size: 1.5rem;
  width: 40px;
  text-align: center;
}

.feature-name {
  display: block;
  font-weight: 600;
  color: var(--text-color, #fff);
}

.feature-desc {
  display: block;
  font-size: 0.8rem;
  color: var(--text-muted, #888);
}

/* Toggle Switch */
.toggle-switch {
  position: relative;
  width: 48px;
  height: 26px;
  cursor: pointer;
}

.toggle-switch input {
  opacity: 0;
  width: 0;
  height: 0;
}

.toggle-slider {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(255,255,255,0.1);
  border-radius: 26px;
  transition: all 0.3s;
}

.toggle-slider:before {
  position: absolute;
  content: "";
  height: 20px;
  width: 20px;
  left: 3px;
  bottom: 3px;
  background: #fff;
  border-radius: 50%;
  transition: all 0.3s;
}

.toggle-switch input:checked + .toggle-slider {
  background: #22c55e;
}

.toggle-switch input:checked + .toggle-slider:before {
  transform: translateX(22px);
}

/* ============================================
   AI Settings Compact Styles
   ============================================ */

.settings-panel.ai-compact {
  padding: 0.75rem;
}

/* Header Row: Toggle + Provider */
.ai-header-row {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-bottom: 1rem;
  flex-wrap: wrap;
}

.ai-toggle-card {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.6rem 1rem;
  background: linear-gradient(135deg, rgba(88, 101, 242, 0.15), rgba(139, 92, 246, 0.15));
  border: 1px solid rgba(88, 101, 242, 0.3);
  border-radius: 10px;
  flex: 1;
  min-width: 200px;
}

.ai-toggle-card .ai-icon {
  font-size: 1.5rem;
}

.ai-toggle-info h4 {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--text-color, #fff);
}

.ai-status-text {
  font-size: 0.7rem;
  font-weight: 500;
}

.ai-status-text.running { color: #22c55e; }
.ai-status-text.ready { color: #3b82f6; }
.ai-status-text.warning { color: #eab308; }

/* Compact Provider Toggle */
.ai-provider-toggle {
  display: flex;
  gap: 0.5rem;
}

.provider-btn-compact {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.4rem 0.75rem;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 6px;
  color: var(--text-muted, #888);
  font-size: 0.75rem;
  cursor: pointer;
  transition: all 0.2s;
}

.provider-btn-compact:hover {
  background: rgba(255, 255, 255, 0.1);
}

.provider-btn-compact.active {
  background: rgba(88, 101, 242, 0.2);
  border-color: rgba(88, 101, 242, 0.5);
  color: var(--text-color, #fff);
}

.provider-btn-compact i {
  font-size: 0.9rem;
}

.badge-sm {
  padding: 0.1rem 0.3rem;
  border-radius: 3px;
  font-size: 0.55rem;
  text-transform: uppercase;
  font-weight: 700;
}

.badge-sm.free {
  background: rgba(34, 197, 94, 0.2);
  color: #22c55e;
}

.badge-sm.cloud {
  background: rgba(59, 130, 246, 0.2);
  color: #3b82f6;
}

/* Two Column Grid */
.ai-grid-2col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.75rem;
  margin-bottom: 0.75rem;
}

.ai-column {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

/* Compact Section */
.ai-section-compact {
  background: var(--card-bg, #2c2c2c);
  border: 1px solid var(--border-color, #404040);
  border-radius: 8px;
  padding: 0.6rem;
}

.section-header-compact {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin-bottom: 0.5rem;
  padding-bottom: 0.35rem;
  border-bottom: 1px solid var(--border-color, #404040);
}

.section-header-compact i {
  font-size: 0.85rem;
  color: var(--accent-color, #5865f2);
}

.section-header-compact h5 {
  margin: 0;
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.3px;
  color: var(--text-muted, #888);
}

/* Compact Input Group */
.input-group-compact {
  display: flex;
  gap: 0.25rem;
}

.input-group-compact .form-control-sm {
  font-size: 0.8rem;
  padding: 0.35rem 0.5rem;
  border-radius: 4px;
  flex: 1;
}

.input-group-compact .btn-sm {
  padding: 0.25rem 0.5rem;
  font-size: 0.75rem;
}

.test-result-compact {
  margin-top: 0.35rem;
  padding: 0.3rem 0.5rem;
  border-radius: 4px;
  font-size: 0.7rem;
  display: flex;
  align-items: center;
  gap: 0.3rem;
}

.test-result-compact.success {
  background: rgba(34, 197, 94, 0.15);
  color: #22c55e;
}

.test-result-compact.error {
  background: rgba(239, 68, 68, 0.15);
  color: #ef4444;
}

/* Compact Model List */
.model-list-compact {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.model-row-compact {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem 1rem;
  background: rgba(0, 0, 0, 0.2);
  border-radius: 8px;
  border: 1px solid transparent;
  transition: all 0.2s;
}

.model-row-compact:hover {
  background: rgba(0, 0, 0, 0.3);
}

.model-row-compact.active {
  background: rgba(34, 197, 94, 0.1);
  border-color: rgba(34, 197, 94, 0.3);
}

.model-row-compact.downloading {
  border-color: rgba(59, 130, 246, 0.3);
}

.model-emoji {
  font-size: 1.5rem;
  width: 32px;
  text-align: center;
}

.model-info-compact {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
}

.model-name-compact {
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--text-color, #fff);
}

.model-desc-compact {
  font-size: 0.7rem;
  color: var(--text-muted, #888);
  font-style: italic;
}

.model-size-compact {
  font-size: 0.65rem;
  color: var(--accent-color, #5865f2);
  font-weight: 500;
}

.model-actions-compact {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  min-width: 140px;
  justify-content: flex-end;
}

/* Unified Model Action Buttons */
.model-action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.45rem 1rem;
  font-size: 0.8rem;
  font-weight: 600;
  border-radius: 6px;
  border: none;
  cursor: pointer;
  transition: all 0.2s;
  min-width: 95px;
  height: 32px;
}

.model-action-btn.download {
  background: linear-gradient(135deg, #3b82f6, #2563eb);
  color: #fff;
}

.model-action-btn.download:hover {
  background: linear-gradient(135deg, #2563eb, #1d4ed8);
  transform: translateY(-1px);
}

.model-action-btn.load {
  background: linear-gradient(135deg, #22c55e, #16a34a);
  color: #fff;
}

.model-action-btn.load:hover {
  background: linear-gradient(135deg, #16a34a, #15803d);
  transform: translateY(-1px);
}

.model-action-btn.load:disabled {
  opacity: 0.7;
  cursor: not-allowed;
  transform: none;
}

.model-action-btn.active-state {
  background: rgba(34, 197, 94, 0.15);
  color: #22c55e;
  cursor: default;
}

.model-action-btn.cancel {
  background: transparent;
  border: 1px solid rgba(239, 68, 68, 0.5);
  color: #ef4444;
  min-width: auto;
  padding: 0.35rem 0.5rem;
}

.model-action-btn.cancel:hover {
  background: rgba(239, 68, 68, 0.1);
}

/* Small icon-only action buttons */
.model-action-btn-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  font-size: 0.85rem;
  border-radius: 6px;
  border: 1px solid transparent;
  cursor: pointer;
  transition: all 0.2s;
  background: transparent;
  flex-shrink: 0;
}

.model-action-btn-icon.delete {
  background: rgba(239, 68, 68, 0.15);
  border-color: rgba(239, 68, 68, 0.4);
  color: #f87171;
}

.model-action-btn-icon.delete:hover {
  background: rgba(239, 68, 68, 0.25);
  border-color: rgba(239, 68, 68, 0.6);
  color: #ef4444;
}

.model-action-btn-icon.unload {
  background: rgba(148, 163, 184, 0.1);
  border-color: rgba(148, 163, 184, 0.3);
  color: #94a3b8;
}

.model-action-btn-icon.unload:hover {
  background: rgba(148, 163, 184, 0.2);
  border-color: rgba(148, 163, 184, 0.5);
}

/* Download progress bar in model row */
.download-progress-bar {
  width: 60px;
  height: 6px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 3px;
  overflow: hidden;
}

.download-progress-bar .progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #3b82f6, #60a5fa);
  transition: width 0.3s;
}

.progress-pct {
  font-size: 0.7rem;
  font-weight: 600;
  color: #3b82f6;
  min-width: 32px;
}

.active-badge-sm {
  display: inline-flex;
  align-items: center;
  padding: 0.25rem 0.5rem;
  background: rgba(34, 197, 94, 0.15);
  color: #22c55e;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 600;
}

/* Compact Runner Status */
.runner-compact {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-top: 0.75rem;
  padding: 0.5rem 0.75rem;
  background: rgba(0, 0, 0, 0.2);
  border-radius: 6px;
  font-size: 0.8rem;
  border: 1px solid transparent;
}

.runner-compact.ready {
  border-color: rgba(34, 197, 94, 0.3);
}

.runner-compact.not-installed {
  border-color: rgba(234, 179, 8, 0.3);
}

.runner-compact i {
  font-size: 0.9rem;
}

.runner-compact.ready i { color: #22c55e; }
.runner-compact.not-installed i { color: #eab308; }

.runner-progress-inline {
  width: 80px;
  height: 6px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 3px;
  overflow: hidden;
  margin-left: auto;
}

.runner-progress-inline .progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #3b82f6, #60a5fa);
  transition: width 0.3s;
  height: 4px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 2px;
  overflow: hidden;
}

.runner-progress-compact span {
  font-size: 0.6rem;
  color: #3b82f6;
}

/* Compact Feature Grid */
.feature-grid-compact {
  display: grid;
  grid-template-columns: 1fr;
  gap: 0.35rem;
}

.feature-item-compact {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.4rem 0.5rem;
  background: rgba(0, 0, 0, 0.2);
  border-radius: 6px;
}

.feature-item-compact:hover {
  background: rgba(0, 0, 0, 0.3);
}

.feature-emoji {
  font-size: 0.9rem;
  width: 20px;
  text-align: center;
}

.feature-label {
  flex: 1;
  font-size: 0.75rem;
  font-weight: 500;
  color: var(--text-color, #fff);
}

/* Briefing Settings */
.briefing-setting-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.5rem 0.5rem;
  background: rgba(0, 0, 0, 0.2);
  border-radius: 6px;
  margin-bottom: 0.4rem;
}

.briefing-setting-row:last-child {
  margin-bottom: 0;
}

.setting-label-group {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.time-picker {
  width: 100px;
  padding: 0.25rem 0.5rem;
  font-size: 0.8rem;
  background: var(--bg-secondary, #1e1e1e);
  border: 1px solid var(--border-color, #333);
  border-radius: 4px;
  color: var(--text-color, #fff);
}

.time-picker:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.style-select {
  width: 180px;
  padding: 0.25rem 0.5rem;
  font-size: 0.8rem;
  background: var(--bg-secondary, #1e1e1e);
  border: 1px solid var(--border-color, #333);
  border-radius: 4px;
  color: var(--text-color, #fff);
}

.style-select:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Small Toggle Switch */
.toggle-switch-sm {
  position: relative;
  width: 32px;
  height: 18px;
  cursor: pointer;
}

.toggle-switch-sm input {
  opacity: 0;
  width: 0;
  height: 0;
}

.toggle-switch-sm .toggle-slider {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(255,255,255,0.1);
  border-radius: 18px;
  transition: all 0.3s;
}

.toggle-switch-sm .toggle-slider:before {
  position: absolute;
  content: "";
  height: 14px;
  width: 14px;
  left: 2px;
  bottom: 2px;
  background: #fff;
  border-radius: 50%;
  transition: all 0.3s;
}

.toggle-switch-sm input:checked + .toggle-slider {
  background: #22c55e;
}

.toggle-switch-sm input:checked + .toggle-slider:before {
  transform: translateX(14px);
}

/* Actions Row */
.ai-actions-row {
  display: flex;
  align-items: center;
  padding: 0.5rem;
  background: var(--card-bg, #2c2c2c);
  border-radius: 8px;
  border: 1px solid var(--border-color, #404040);
}

.ai-actions-row .btn {
  padding: 0.4rem 1rem;
  font-size: 0.8rem;
}

/* Disabled State */
.ai-disabled-compact {
  padding: 1rem;
  text-align: center;
  background: rgba(0, 0, 0, 0.2);
  border-radius: 10px;
  margin-top: 0.5rem;
}

.disabled-features {
  display: flex;
  justify-content: center;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
}

.feature-preview {
  padding: 0.25rem 0.5rem;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 4px;
  font-size: 0.75rem;
  color: var(--text-muted, #888);
}

.ai-disabled-compact p {
  margin: 0;
  font-size: 0.8rem;
  color: var(--text-muted, #888);
}

/* Responsive for AI compact */
@media (max-width: 900px) {
  .ai-grid-2col {
    grid-template-columns: 1fr;
  }
  
  .ai-header-row {
    flex-direction: column;
    align-items: stretch;
  }
  
  .ai-provider-toggle {
    justify-content: center;
  }
}

/* Responsive */
@media (max-width: 768px) {
  .settings-tabs {
    flex-wrap: wrap;
  }
  
  .tab-btn {
    flex: 1;
    min-width: 80px;
    text-align: center;
    padding: 0.5rem;
    font-size: 0.85rem;
  }
  
  .tab-btn i {
    display: none;
  }
  
  .stats-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  
  .disk-stats {
    flex-wrap: wrap;
    gap: 1rem;
  }
  
  .section-actions {
    flex-direction: column;
    align-items: stretch;
  }
  
  .section-actions .btn {
    width: 100%;
  }
  
  .section-actions .ms-2,
  .section-actions .ms-3 {
    margin-left: 0 !important;
    margin-top: 0.5rem;
  }
  
  .provider-toggle {
    flex-direction: column;
  }
  
  .model-card {
    flex-wrap: wrap;
  }
  
  .model-actions {
    width: 100%;
    justify-content: flex-end;
    margin-top: 0.5rem;
  }
}

/* Delete Model Modal */
.delete-modal {
  max-width: 400px;
}

.delete-modal .modal-header h3 {
  display: flex;
  align-items: center;
}

.delete-model-info {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1rem;
  background: rgba(0, 0, 0, 0.2);
  border-radius: 8px;
  margin-bottom: 1rem;
}

.model-icon-lg {
  font-size: 2rem;
}

.delete-model-info strong {
  display: block;
  font-size: 1rem;
  color: var(--text-color, #fff);
}

.delete-model-info p {
  margin: 0;
  font-size: 0.8rem;
  color: var(--text-muted, #888);
}

.delete-warning {
  color: var(--text-muted, #888);
  font-size: 0.9rem;
  margin: 0;
}

.delete-modal .modal-footer {
  display: flex;
  gap: 0.75rem;
  justify-content: flex-end;
}

.delete-modal .btn-danger {
  background: linear-gradient(135deg, #ef4444, #dc2626);
  border: none;
}

.delete-modal .btn-danger:hover {
  background: linear-gradient(135deg, #dc2626, #b91c1c);
}

/* Executive Report Estimate */
.exec-report-estimate {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.5rem 0.75rem;
  background: rgba(88, 101, 242, 0.1);
  border-radius: 6px;
  font-size: 0.75rem;
  margin-top: 0.5rem;
}

.exec-report-estimate .estimate-formula {
  color: var(--text-muted, #888);
}

.exec-report-estimate .estimate-result {
  font-weight: 600;
  color: var(--primary-color, #5865f2);
}

/* Estimate Breakdown */
.estimate-breakdown {
  display: flex;
  gap: 1rem;
  margin-top: 0.35rem;
  font-size: 0.7rem;
  color: var(--text-muted, #888);
}

.estimate-breakdown .breakdown-item {
  display: flex;
  align-items: center;
  gap: 0.25rem;
}

/* Tag Management Section */
.tag-create-row {
  display: flex;
  gap: 0.5rem;
}

.tag-create-row .form-control {
  flex: 1;
}

.tag-create-row .btn {
  white-space: nowrap;
}

.tags-loading, .tags-empty {
  padding: 1rem;
  text-align: center;
  color: var(--text-muted, #888);
  background: var(--surface-color, #1e1e1e);
  border-radius: 8px;
  border: 1px solid var(--border-color, #333);
}

.tags-list {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  padding: 1rem;
  background: var(--surface-color, #1e1e1e);
  border-radius: 8px;
  border: 1px solid var(--border-color, #333);
  max-height: 300px;
  overflow-y: auto;
}

.tag-item {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.35rem 0.5rem 0.35rem 0.75rem;
  background: rgba(88, 101, 242, 0.15);
  border: 1px solid rgba(88, 101, 242, 0.3);
  border-radius: 20px;
  font-size: 0.85rem;
  color: var(--text-primary, #e0e0e0);
  position: relative;
}

.tag-item .tag-name {
  color: var(--primary-color, #5865f2);
  font-weight: 500;
}

.tag-delete-btn {
  display: inline-flex !important;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  min-width: 18px;
  padding: 0;
  border: none;
  background: rgba(255, 255, 255, 0.2);
  border-radius: 50%;
  cursor: pointer;
  color: #ccc;
  font-size: 14px;
  font-weight: bold;
  line-height: 1;
  transition: all 0.2s ease;
  pointer-events: auto !important;
  z-index: 100;
}

.tag-delete-btn:hover {
  background: rgba(239, 68, 68, 0.5);
  color: #fff;
}

/* Modal Overlay */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-container {
  background: var(--card-bg, #2c2c2c);
  border: 1px solid var(--border-color, #404040);
  border-radius: 12px;
  width: 100%;
  max-width: 450px;
  overflow: hidden;
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem 1.25rem;
  border-bottom: 1px solid var(--border-color, #404040);
  background: var(--card-header-bg, #252525);
}

.modal-header h3 {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 600;
  display: flex;
  align-items: center;
}

.modal-header .close-btn {
  background: transparent;
  border: none;
  color: var(--text-muted, #888);
  cursor: pointer;
  padding: 0.25rem;
  font-size: 1.1rem;
}

.modal-header .close-btn:hover {
  color: var(--text-primary, #fff);
}

.modal-body {
  padding: 1.25rem;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
  padding: 1rem 1.25rem;
  border-top: 1px solid var(--border-color, #404040);
  background: rgba(0, 0, 0, 0.1);
}

.delete-warning {
  color: var(--text-muted, #888);
  font-size: 0.9rem;
  margin: 0;
}

.delete-profile-warning {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  padding: 0.75rem 1rem;
  background: rgba(255, 193, 7, 0.1);
  border: 1px solid rgba(255, 193, 7, 0.3);
  border-radius: 6px;
  margin-top: 1rem;
  font-size: 0.85rem;
  color: var(--text-secondary, #aaa);
}

.delete-profile-warning i {
  flex-shrink: 0;
  margin-top: 2px;
}

/* Delete Tag Modal */
.delete-tag-info {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 1rem;
  background: rgba(88, 101, 242, 0.1);
  border-radius: 8px;
  margin-bottom: 1rem;
}

.tag-icon-lg {
  font-size: 1.5rem;
  color: var(--primary-color, #5865f2);
}

.delete-tag-info strong {
  font-size: 1.1rem;
  color: var(--primary-color, #5865f2);
}

/* User Management Styles */
.current-user-info {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1rem;
  background: var(--bg-secondary, #252525);
  border-radius: 8px;
}

.user-avatar {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: var(--primary-color, #5865f2);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-size: 1.5rem;
}

.user-avatar.small {
  width: 36px;
  height: 36px;
  font-size: 1rem;
}

.user-details {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.user-role {
  font-size: 0.8rem;
  color: var(--text-muted, #888);
  padding: 0.15rem 0.5rem;
  background: var(--bg-primary, #1a1a1a);
  border-radius: 4px;
  display: inline-block;
  width: fit-content;
}

.user-role.admin {
  color: #f59e0b;
  background: rgba(245, 158, 11, 0.15);
}

.users-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.user-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1rem;
  background: var(--bg-secondary, #252525);
  border-radius: 8px;
  border: 1px solid var(--border-color, #404040);
}

.user-info {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.user-info > div {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.user-info-details {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.user-name-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.user-profile {
  font-size: 0.8rem;
  color: var(--text-muted, #888);
  display: flex;
  align-items: center;
}

.user-profile i {
  font-size: 0.7rem;
}

.user-actions {
  display: flex;
  gap: 0.5rem;
}

.loading-users,
.no-users {
  padding: 2rem;
  text-align: center;
  color: var(--text-muted, #888);
}

/* Password Requirements */
.password-requirements {
  margin-top: 0.5rem;
  font-size: 0.8rem;
  color: var(--text-muted, #888);
}

.password-requirements > div {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.15rem;
  transition: color 0.2s;
}

.password-requirements > div.valid {
  color: #10b981;
}

.password-requirements span {
  font-size: 0.7rem;
}

/* Alerts Tab */
.alerts-panel {
  padding: 0;
}

.alerts-subtabs {
  display: flex;
  gap: 0.25rem;
  margin-bottom: 1rem;
  background: var(--card-bg, #2c2c2c);
  border: 1px solid var(--border-color, #404040);
  border-radius: 8px;
  padding: 0.25rem;
}

.subtab-btn {
  flex: 1;
  padding: 0.6rem 1rem;
  border: none;
  background: transparent;
  color: var(--text-muted, #888);
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.85rem;
  transition: all 0.2s;
}

.subtab-btn:hover {
  color: var(--text-color, #fff);
  background: rgba(255,255,255,0.05);
}

.subtab-btn.active {
  color: #fff;
  background: var(--primary-color, #5865f2);
}

.alerts-loading {
  padding: 3rem;
  text-align: center;
  color: var(--text-muted, #888);
}

.alerts-content {
  background: var(--card-bg, #2c2c2c);
  border: 1px solid var(--border-color, #404040);
  border-radius: 12px;
  overflow: hidden;
}

.alerts-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  padding: 1rem;
  background: var(--card-header-bg, #252525);
  border-bottom: 1px solid var(--border-color, #404040);
}

.alerts-header h5 {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 600;
}

.alerts-header p {
  margin: 0.25rem 0 0;
  font-size: 0.8rem;
  color: var(--text-muted, #888);
}

.alerts-empty {
  padding: 3rem;
  text-align: center;
  color: var(--text-muted, #888);
}

.alerts-empty i {
  font-size: 2.5rem;
  opacity: 0.5;
  display: block;
  margin-bottom: 1rem;
}

.alerts-empty p {
  margin: 0;
  font-weight: 500;
  color: var(--text-color, #fff);
}

.alerts-empty span {
  font-size: 0.85rem;
  display: block;
  margin-top: 0.5rem;
}

/* Channels List */
.channels-list {
  padding: 0.5rem;
}

.channel-item {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 0.75rem;
  border-radius: 8px;
  background: rgba(0,0,0,0.15);
  margin-bottom: 0.5rem;
}

.channel-item:last-child {
  margin-bottom: 0;
}

.channel-icon {
  font-size: 1.5rem;
  width: 40px;
  text-align: center;
}

.channel-info {
  flex: 1;
}

.channel-name {
  font-weight: 500;
}

.channel-type {
  font-size: 0.8rem;
  color: var(--text-muted, #888);
}

.channel-events .events-badge {
  font-size: 0.75rem;
  background: rgba(88, 101, 242, 0.2);
  color: var(--primary-color, #5865f2);
  padding: 0.25rem 0.5rem;
  border-radius: 4px;
}

.channel-actions {
  display: flex;
  gap: 0.25rem;
}

/* Rules List */
.rules-list {
  padding: 0.5rem;
}

.rule-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem;
  border-radius: 8px;
  background: rgba(0,0,0,0.15);
  margin-bottom: 0.5rem;
}

.rule-item:last-child {
  margin-bottom: 0;
}

.rule-item.disabled {
  opacity: 0.5;
}

.rule-toggle {
  flex-shrink: 0;
}

.rule-info {
  flex: 1;
  min-width: 0;
}

.rule-name {
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.rule-condition {
  font-size: 0.8rem;
  color: var(--text-muted, #888);
}

.rule-scope .scope-badge {
  font-size: 0.7rem;
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  text-transform: uppercase;
  font-weight: 600;
}

.scope-badge.global {
  background: rgba(88, 101, 242, 0.2);
  color: var(--primary-color, #5865f2);
}

.scope-badge.agent {
  background: rgba(16, 185, 129, 0.2);
  color: #10b981;
}

.scope-badge.bookmark {
  background: rgba(245, 158, 11, 0.2);
  color: #f59e0b;
}

.rule-channels {
  font-size: 0.8rem;
  color: var(--text-muted, #888);
  min-width: 80px;
  text-align: center;
}

.rule-actions {
  display: flex;
  gap: 0.25rem;
}

/* History List */
.history-list {
  padding: 0.5rem;
  max-height: 400px;
  overflow-y: auto;
}

.history-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.6rem 0.75rem;
  border-radius: 6px;
  background: rgba(0,0,0,0.15);
  margin-bottom: 0.35rem;
}

.history-item:last-child {
  margin-bottom: 0;
}

.history-status {
  font-size: 1rem;
}

.history-status.success {
  color: #10b981;
}

.history-status.failed {
  color: #ef4444;
}

.history-info {
  flex: 1;
  min-width: 0;
}

.history-title {
  font-weight: 500;
  font-size: 0.9rem;
}

.history-detail {
  font-size: 0.75rem;
  color: var(--text-muted, #888);
}

.history-channel {
  margin-right: 0.5rem;
}

.history-time {
  font-size: 0.75rem;
  color: var(--text-muted, #888);
  white-space: nowrap;
}

/* Toggle Switch Small */
.toggle-switch-sm {
  position: relative;
  display: inline-block;
  width: 36px;
  height: 20px;
}

.toggle-switch-sm input {
  opacity: 0;
  width: 0;
  height: 0;
}

.toggle-switch-sm .toggle-slider {
  position: absolute;
  cursor: pointer;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: #444;
  transition: 0.3s;
  border-radius: 20px;
}

.toggle-switch-sm .toggle-slider:before {
  position: absolute;
  content: "";
  height: 14px;
  width: 14px;
  left: 3px;
  bottom: 3px;
  background-color: white;
  transition: 0.3s;
  border-radius: 50%;
}

.toggle-switch-sm input:checked + .toggle-slider {
  background-color: var(--primary-color, #5865f2);
}

.toggle-switch-sm input:checked + .toggle-slider:before {
  transform: translateX(16px);
}

/* ============================================
   Librarian AI Styles
   ============================================ */

.librarian-status {
  background: var(--surface-1, #1a1a1a);
  border: 1px solid var(--border-color, #333);
  border-radius: 8px;
  padding: 1rem;
}

.status-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.4rem 0;
}

.status-row + .status-row {
  border-top: 1px solid var(--border-color-light, #2a2a2a);
}

.status-label {
  color: var(--text-muted, #888);
  font-size: 0.85rem;
  min-width: 120px;
}

.status-value {
  font-weight: 500;
  font-size: 0.9rem;
}

/* GPU Selection */
.gpu-options {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.gpu-option {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1rem;
  background: var(--surface-1, #1a1a1a);
  border: 2px solid var(--border-color, #333);
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.2s;
}

.gpu-option:hover {
  border-color: var(--primary-color-dim, #4a5bc7);
  background: rgba(88, 101, 242, 0.05);
}

.gpu-option.selected {
  border-color: var(--primary-color, #5865f2);
  background: rgba(88, 101, 242, 0.1);
}

.gpu-option-icon {
  font-size: 1.5rem;
}

.gpu-option-info {
  flex: 1;
}

.gpu-option-info strong {
  display: block;
  font-size: 0.95rem;
  color: var(--text-color, #fff);
  margin-bottom: 0.25rem;
}

.gpu-option-info span {
  font-size: 0.8rem;
  color: var(--text-muted, #888);
}

.recommended-badge {
  background: rgba(34, 197, 94, 0.2);
  color: #22c55e;
  padding: 0.25rem 0.75rem;
  border-radius: 20px;
  font-size: 0.75rem;
  font-weight: 600;
}

/* Install Progress */
.install-progress .progress {
  height: 8px;
  background: rgba(0,0,0,0.3);
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 0.5rem;
}

.install-progress .progress-bar {
  height: 100%;
  background: linear-gradient(90deg, #3b82f6, #8b5cf6);
  transition: width 0.3s ease;
}

/* Model List */
.models-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.model-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 1rem;
  background: var(--surface-1, #1a1a1a);
  border: 1px solid var(--border-color, #333);
  border-radius: 10px;
}

.model-info {
  flex: 1;
}

.model-name {
  font-weight: 600;
  font-size: 0.95rem;
  color: var(--text-color, #fff);
  margin-bottom: 0.25rem;
}

.model-description {
  font-size: 0.8rem;
  color: var(--text-muted, #888);
  margin-bottom: 0.5rem;
}

.model-meta {
  display: flex;
  gap: 1rem;
  font-size: 0.75rem;
  color: var(--text-muted, #666);
}

.model-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.download-progress {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.download-progress .progress {
  height: 6px;
  background: rgba(0,0,0,0.3);
  border-radius: 3px;
}

.download-progress .progress-bar {
  height: 100%;
  background: linear-gradient(90deg, #3b82f6, #8b5cf6);
}
</style>
