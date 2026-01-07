<template>
  <div class="bookmark-settings-view">
    <!-- Header -->
    <div class="settings-header">
      <button class="back-btn" @click="goBack" title="Go back">←</button>
      <h1>Bookmark Settings</h1>
    </div>

    <!-- Tabs -->
    <div class="settings-tabs">
      <button 
        :class="['tab-btn', { active: activeTab === 'groups' }]"
        @click="activeTab = 'groups'"
      >
        Groups
      </button>
      <button 
        :class="['tab-btn', { active: activeTab === 'display' }]"
        @click="activeTab = 'display'"
      >
        Display
      </button>
      <button 
        :class="['tab-btn', { active: activeTab === 'alerts' }]"
        @click="activeTab = 'alerts'"
      >
        Alerts
      </button>
    </div>

    <!-- Groups Tab -->
    <div v-if="activeTab === 'groups'" class="tab-content">
      <div class="section-header">
        <h2>Manage Groups</h2>
        <p class="section-desc">Delete or reorganize your monitor groups</p>
      </div>

      <div v-if="loading" class="loading">Loading groups...</div>
      
      <div v-else-if="groups.length === 0" class="empty-state">
        <p>No groups created yet.</p>
        <p class="hint">Groups are created when you add a monitor with a new group name.</p>
      </div>

      <div v-else class="groups-list">
        <div v-for="group in groups" :key="group.id" class="group-item">
          <div class="group-info">
            <span class="group-name">{{ group.name }}</span>
            <span class="group-count">{{ group.monitor_count || 0 }} monitor{{ group.monitor_count !== 1 ? 's' : '' }}</span>
          </div>
          <div class="group-actions">
            <button 
              class="btn-danger-sm" 
              @click="confirmDelete(group)"
              :disabled="deleting === group.id"
            >
              {{ deleting === group.id ? 'Deleting...' : 'Delete' }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Display Tab -->
    <div v-if="activeTab === 'display'" class="tab-content">
      <div class="section-header">
        <h2>Display Preferences</h2>
        <p class="section-desc">Customize how bookmarks are displayed</p>
      </div>

      <div class="settings-card">
        <div class="setting-row">
          <div class="setting-info">
            <span class="setting-label">Default Group State</span>
            <span class="setting-desc">Choose whether groups start expanded or collapsed when viewing bookmarks</span>
          </div>
          <div class="setting-control">
            <select v-model="displaySettings.groupsExpanded" @change="saveDisplaySettings" class="form-select">
              <option :value="false">Collapsed</option>
              <option :value="true">Expanded</option>
            </select>
          </div>
        </div>
      </div>

      <div v-if="displaySettingsSaved" class="save-feedback">
        ✓ Settings saved
      </div>
    </div>

    <!-- Alerts Tab -->
    <div v-if="activeTab === 'alerts'" class="tab-content">
      <div class="section-header">
        <h2>Alert Settings</h2>
        <p class="section-desc">Configure notifications when monitors go down or respond slowly</p>
      </div>

      <!-- Notification Channels Quick Link -->
      <div class="alert-info-card">
        <i class="info-icon">ℹ️</i>
        <div class="info-content">
          <p>Alert rules for bookmarks are configured globally and can notify you via Discord, Slack, Email, and more.</p>
          <router-link to="/settings?tab=alerts" class="settings-link">
            Configure Notification Channels & Rules →
          </router-link>
        </div>
      </div>

      <!-- Effective Rules for All Bookmarks -->
      <div class="rules-section">
        <h3>Active Alert Rules</h3>
        <p class="section-desc">Global rules that apply to all bookmarks</p>
        
        <div v-if="loadingRules" class="loading">Loading rules...</div>
        
        <div v-else-if="bookmarkRules.length === 0" class="empty-state">
          <p>No bookmark alert rules configured.</p>
          <router-link to="/settings?tab=alerts" class="btn-primary-sm">
            Create Alert Rule
          </router-link>
        </div>
        
        <div v-else class="rules-list">
          <div v-for="rule in bookmarkRules" :key="rule.id" class="rule-item" :class="{ disabled: !rule.enabled }">
            <div class="rule-indicator">
              <span v-if="rule.enabled" class="status-dot active"></span>
              <span v-else class="status-dot inactive"></span>
            </div>
            <div class="rule-info">
              <span class="rule-name">{{ rule.name }}</span>
              <span class="rule-condition">{{ formatCondition(rule) }}</span>
            </div>
            <div class="rule-channels" v-if="rule.channels?.length">
              <span class="channel-count">🔔 {{ rule.channels.length }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Alert Metrics -->
      <div class="metrics-section">
        <h3>Available Metrics</h3>
        <p class="section-desc">What can be monitored for bookmarks</p>
        
        <div class="metrics-grid">
          <div class="metric-card">
            <span class="metric-icon">🔴</span>
            <div class="metric-info">
              <span class="metric-name">Status</span>
              <span class="metric-desc">Alert after consecutive failures</span>
            </div>
          </div>
          <div class="metric-card">
            <span class="metric-icon">⏱️</span>
            <div class="metric-info">
              <span class="metric-name">Response Time</span>
              <span class="metric-desc">Alert if response exceeds threshold</span>
            </div>
          </div>
          <div class="metric-card">
            <span class="metric-icon">🔒</span>
            <div class="metric-info">
              <span class="metric-name">SSL Expiry</span>
              <span class="metric-desc">Alert before certificate expires</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Delete Confirmation Modal -->
    <div v-if="showDeleteModal" class="modal-overlay" @click.self="showDeleteModal = false">
      <div class="modal-content">
        <h3>Delete Group</h3>
        <p>Are you sure you want to delete <strong>"{{ groupToDelete?.name }}"</strong>?</p>
        
        <div v-if="groupToDelete?.monitor_count > 0" class="monitor-choice">
          <p class="choice-label">This group has <strong>{{ groupToDelete.monitor_count }} monitor{{ groupToDelete.monitor_count !== 1 ? 's' : '' }}</strong>. What would you like to do with them?</p>
          
          <div class="choice-options">
            <label class="choice-option" :class="{ selected: deleteChoice === 'ungroup' }">
              <input type="radio" v-model="deleteChoice" value="ungroup" />
              <div class="choice-content">
                <span class="choice-title">📂 Move to Ungrouped</span>
                <span class="choice-desc">Keep the monitors but remove them from this group</span>
              </div>
            </label>
            
            <label class="choice-option" :class="{ selected: deleteChoice === 'delete' }">
              <input type="radio" v-model="deleteChoice" value="delete" />
              <div class="choice-content">
                <span class="choice-title">🗑️ Delete Everything</span>
                <span class="choice-desc">Permanently delete all monitors and their history</span>
              </div>
            </label>
          </div>
        </div>
        
        <div v-else class="no-monitors-note">
          <p>This group has no monitors and can be safely deleted.</p>
        </div>

        <div class="modal-actions">
          <button class="btn-secondary" @click="showDeleteModal = false">Cancel</button>
          <button class="btn-danger" @click="deleteGroup">Delete Group</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'

const API_BASE = import.meta.env.VITE_API_URL || ''

const router = useRouter()

const activeTab = ref('groups')
const loading = ref(true)
const groups = ref([])
const deleting = ref(null)
const showDeleteModal = ref(false)
const groupToDelete = ref(null)
const deleteChoice = ref('ungroup')

// Alert rules state
const bookmarkRules = ref([])
const loadingRules = ref(false)

// Display settings
const displaySettings = ref({
  groupsExpanded: JSON.parse(localStorage.getItem('bookmarkGroupsExpanded') || 'false')
})
const displaySettingsSaved = ref(false)

const saveDisplaySettings = () => {
  localStorage.setItem('bookmarkGroupsExpanded', JSON.stringify(displaySettings.value.groupsExpanded))
  displaySettingsSaved.value = true
  setTimeout(() => {
    displaySettingsSaved.value = false
  }, 2000)
}

const fetchGroups = async () => {
  loading.value = true
  try {
    const response = await fetch(`${API_BASE}/api/bookmarks/groups`)
    const data = await response.json()
    if (data.success) {
      groups.value = data.data || []
    }
  } catch (error) {
    console.error('Error fetching groups:', error)
  } finally {
    loading.value = false
  }
}

const fetchBookmarkRules = async () => {
  loadingRules.value = true
  try {
    const response = await fetch(`${API_BASE}/api/alerts/rules`)
    const data = await response.json()
    // Filter to only bookmark-related rules (global or bookmark scope)
    bookmarkRules.value = (data.rules || []).filter(r => 
      r.scope === 'global' || r.scope === 'bookmark'
    ).filter(r => 
      ['status', 'response_time', 'ssl_expiry'].includes(r.metric)
    )
  } catch (error) {
    console.error('Error fetching bookmark rules:', error)
  } finally {
    loadingRules.value = false
  }
}

const formatCondition = (rule) => {
  const metricNames = {
    status: 'Failures',
    response_time: 'Response time',
    ssl_expiry: 'SSL expires in'
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
    response_time: 'ms',
    ssl_expiry: ' days'
  }
  
  const metric = metricNames[rule.metric] || rule.metric
  const op = opSymbols[rule.operator] || rule.operator
  const unit = units[rule.metric] || ''
  
  return `${metric} ${op} ${rule.threshold}${unit}`
}

// Watch for tab changes to load alerts data
watch(activeTab, (newTab) => {
  if (newTab === 'alerts' && bookmarkRules.value.length === 0) {
    fetchBookmarkRules()
  }
})

const confirmDelete = (group) => {
  groupToDelete.value = group
  deleteChoice.value = 'ungroup' // Default to safer option
  showDeleteModal.value = true
}

const deleteGroup = async () => {
  if (!groupToDelete.value) return
  
  deleting.value = groupToDelete.value.id
  showDeleteModal.value = false
  
  try {
    const deleteMonitors = deleteChoice.value === 'delete'
    const response = await fetch(
      `${API_BASE}/api/bookmarks/groups/${groupToDelete.value.id}?delete_monitors=${deleteMonitors}`, 
      { method: 'DELETE' }
    )
    const data = await response.json()
    if (data.success) {
      groups.value = groups.value.filter(g => g.id !== groupToDelete.value.id)
    }
  } catch (error) {
    console.error('Error deleting group:', error)
  } finally {
    deleting.value = null
    groupToDelete.value = null
  }
}

const goBack = () => {
  router.push('/bookmarks')
}

onMounted(() => {
  fetchGroups()
})
</script>

<style scoped>
.bookmark-settings-view {
  padding: 20px;
  max-width: 800px;
  margin: 0 auto;
}

.settings-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 24px;
}

.settings-header h1 {
  margin: 0;
  font-size: 1.5rem;
  color: var(--text-primary, #e0e0e0);
}

.back-btn {
  background: var(--bg-tertiary, #2a2a3e);
  border: 1px solid var(--border-color, #3a3a4e);
  color: var(--text-primary, #e0e0e0);
  width: 36px;
  height: 36px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 1.2rem;
  display: flex;
  align-items: center;
  justify-content: center;
}

.back-btn:hover {
  background: var(--bg-hover, #3a3a4e);
}

/* Tabs */
.settings-tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 24px;
  border-bottom: 1px solid var(--border-color, #3a3a4e);
  padding-bottom: 12px;
}

.tab-btn {
  background: transparent;
  border: none;
  color: var(--text-secondary, #888);
  padding: 8px 16px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.9rem;
  transition: all 0.2s ease;
}

.tab-btn:hover {
  background: var(--bg-tertiary, #2a2a3e);
  color: var(--text-primary, #e0e0e0);
}

.tab-btn.active {
  background: var(--accent-color, #4a6cf7);
  color: white;
}

/* Tab Content */
.tab-content {
  background: var(--bg-secondary, #1e1e2e);
  border-radius: 12px;
  padding: 20px;
  border: 1px solid var(--border-color, #3a3a4e);
}

.section-header {
  margin-bottom: 20px;
}

.section-header h2 {
  margin: 0 0 4px 0;
  font-size: 1.1rem;
  color: var(--text-primary, #e0e0e0);
}

.section-desc {
  margin: 0;
  color: var(--text-secondary, #888);
  font-size: 0.85rem;
}

/* Groups List */
.groups-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 16px;
}

.group-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  background: var(--bg-tertiary, #2a2a3e);
  border-radius: 8px;
  border: 1px solid var(--border-color, #3a3a4e);
}

.group-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.group-name {
  color: var(--text-primary, #e0e0e0);
  font-weight: 500;
}

.group-count {
  color: var(--text-secondary, #888);
  font-size: 0.8rem;
}

.btn-danger-sm {
  background: #dc3545;
  color: white;
  border: none;
  padding: 6px 12px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.85rem;
  transition: background 0.2s ease;
}

.btn-danger-sm:hover:not(:disabled) {
  background: #c82333;
}

.btn-danger-sm:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.warning-note {
  background: rgba(255, 193, 7, 0.1);
  border: 1px solid rgba(255, 193, 7, 0.3);
  border-radius: 8px;
  padding: 12px;
  font-size: 0.85rem;
  color: #ffc107;
}

/* Empty & Loading States */
.loading, .empty-state {
  text-align: center;
  padding: 40px 20px;
  color: var(--text-secondary, #888);
}

.empty-state .hint {
  font-size: 0.85rem;
  margin-top: 8px;
}

/* Alerts Placeholder */
.placeholder-content {
  text-align: center;
  padding: 40px 20px;
}

.placeholder-icon {
  font-size: 3rem;
  margin-bottom: 16px;
}

.placeholder-content h3 {
  margin: 0 0 8px 0;
  color: var(--text-primary, #e0e0e0);
}

.placeholder-content p {
  color: var(--text-secondary, #888);
  margin: 0 0 8px 0;
}

.placeholder-content .hint {
  margin-top: 20px;
  font-size: 0.9rem;
}

.planned-features {
  list-style: none;
  padding: 0;
  margin: 12px 0 0 0;
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
}

.planned-features li {
  background: var(--bg-tertiary, #2a2a3e);
  padding: 6px 12px;
  border-radius: 16px;
  font-size: 0.8rem;
  color: var(--text-secondary, #888);
}

/* Modal */
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

.modal-content {
  background: var(--bg-secondary, #1e1e2e);
  border-radius: 12px;
  padding: 24px;
  max-width: 480px;
  width: 90%;
  border: 1px solid var(--border-color, #3a3a4e);
}

.modal-content h3 {
  margin: 0 0 12px 0;
  color: var(--text-primary, #e0e0e0);
}

.modal-content p {
  color: var(--text-secondary, #888);
  margin: 0 0 8px 0;
}

/* Monitor Choice */
.monitor-choice {
  margin: 16px 0;
}

.choice-label {
  margin-bottom: 12px !important;
  color: var(--text-primary, #e0e0e0) !important;
}

.choice-options {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.choice-option {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 12px;
  background: var(--bg-tertiary, #2a2a3e);
  border: 2px solid var(--border-color, #3a3a4e);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.choice-option:hover {
  border-color: var(--primary, #5DADE2);
}

.choice-option.selected {
  border-color: var(--primary, #5DADE2);
  background: rgba(93, 173, 226, 0.1);
}

.choice-option input[type="radio"] {
  margin-top: 2px;
  accent-color: var(--primary, #5DADE2);
}

.choice-content {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.choice-title {
  color: var(--text-primary, #e0e0e0);
  font-weight: 500;
}

.choice-desc {
  color: var(--text-secondary, #888);
  font-size: 0.85rem;
}

.no-monitors-note {
  margin: 16px 0;
  padding: 12px;
  background: var(--bg-tertiary, #2a2a3e);
  border-radius: 8px;
}

.no-monitors-note p {
  margin: 0;
}

.warning-text {
  color: #dc3545 !important;
  font-size: 0.9rem;
}

.modal-actions {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
  margin-top: 20px;
}

.btn-secondary {
  background: var(--bg-tertiary, #2a2a3e);
  color: var(--text-primary, #e0e0e0);
  border: 1px solid var(--border-color, #3a3a4e);
  padding: 8px 16px;
  border-radius: 6px;
  cursor: pointer;
}

.btn-secondary:hover {
  background: var(--bg-hover, #3a3a4e);
}

.btn-danger {
  background: #dc3545;
  color: white;
  border: none;
  padding: 8px 16px;
  border-radius: 6px;
  cursor: pointer;
}

.btn-danger:hover {
  background: #c82333;
}

/* Alert Info Card */
.alert-info-card {
  display: flex;
  gap: 12px;
  padding: 16px;
  background: rgba(93, 173, 226, 0.1);
  border: 1px solid rgba(93, 173, 226, 0.3);
  border-radius: 8px;
  margin-bottom: 24px;
}

.info-icon {
  font-size: 1.2rem;
  flex-shrink: 0;
}

.info-content p {
  margin: 0 0 8px 0;
  color: var(--text-primary, #e0e0e0);
  font-size: 0.9rem;
}

.settings-link {
  color: var(--accent-color, #4a6cf7);
  text-decoration: none;
  font-size: 0.9rem;
}

.settings-link:hover {
  text-decoration: underline;
}

/* Rules Section */
.rules-section {
  margin-bottom: 24px;
}

.rules-section h3 {
  margin: 0 0 4px 0;
  font-size: 1rem;
  color: var(--text-primary, #e0e0e0);
}

.rules-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 12px;
}

.rule-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: var(--bg-tertiary, #2a2a3e);
  border-radius: 8px;
  border: 1px solid var(--border-color, #3a3a4e);
}

.rule-item.disabled {
  opacity: 0.5;
}

.rule-indicator {
  flex-shrink: 0;
}

.status-dot {
  display: block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.status-dot.active {
  background: #10b981;
}

.status-dot.inactive {
  background: #6b7280;
}

.rule-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.rule-name {
  color: var(--text-primary, #e0e0e0);
  font-weight: 500;
}

.rule-condition {
  font-size: 0.8rem;
  color: var(--text-secondary, #888);
}

.rule-channels {
  flex-shrink: 0;
}

.channel-count {
  font-size: 0.8rem;
  color: var(--text-secondary, #888);
}

.btn-primary-sm {
  display: inline-block;
  background: var(--accent-color, #4a6cf7);
  color: white;
  border: none;
  padding: 8px 16px;
  border-radius: 6px;
  text-decoration: none;
  font-size: 0.85rem;
  margin-top: 12px;
}

.btn-primary-sm:hover {
  opacity: 0.9;
}

/* Metrics Section */
.metrics-section h3 {
  margin: 0 0 4px 0;
  font-size: 1rem;
  color: var(--text-primary, #e0e0e0);
}

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 12px;
  margin-top: 12px;
}

.metric-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  background: var(--bg-tertiary, #2a2a3e);
  border-radius: 8px;
  border: 1px solid var(--border-color, #3a3a4e);
}

.metric-icon {
  font-size: 1.5rem;
  flex-shrink: 0;
}

.metric-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.metric-name {
  color: var(--text-primary, #e0e0e0);
  font-weight: 500;
  font-size: 0.9rem;
}

.metric-desc {
  color: var(--text-secondary, #888);
  font-size: 0.8rem;
}

/* Display Settings */
.settings-card {
  background: var(--bg-tertiary, #2a2a3e);
  border-radius: 8px;
  padding: 16px;
  border: 1px solid var(--border-color, #3a3a4e);
}

.setting-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
}

.setting-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.setting-label {
  color: var(--text-primary, #e0e0e0);
  font-weight: 500;
  font-size: 0.95rem;
}

.setting-desc {
  color: var(--text-secondary, #888);
  font-size: 0.8rem;
}

.setting-control .form-select {
  background: var(--bg-secondary, #1e1e2e);
  border: 1px solid var(--border-color, #3a3a4e);
  color: var(--text-primary, #e0e0e0);
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 0.9rem;
  min-width: 140px;
}

.setting-control .form-select:focus {
  outline: none;
  border-color: var(--accent-color, #4a6cf7);
}

.save-feedback {
  margin-top: 12px;
  padding: 8px 12px;
  background: rgba(40, 167, 69, 0.15);
  border: 1px solid rgba(40, 167, 69, 0.3);
  border-radius: 6px;
  color: #28a745;
  font-size: 0.85rem;
  text-align: center;
}
</style>
