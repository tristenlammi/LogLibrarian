<template>
  <div v-if="show" class="modal-backdrop" @click.self="close">
    <div class="modal-dialog" :class="{ 'modal-lg': form.scope === 'profile' }">
      <div class="modal-content">
        <div class="modal-header">
          <h5 class="modal-title">{{ isEdit ? 'Edit' : 'Add' }} Alert Rule</h5>
          <button type="button" class="btn-close" @click="close"></button>
        </div>
        
        <div class="modal-body">
          <!-- Rule Name -->
          <div class="mb-3">
            <label class="form-label">Rule Name</label>
            <input 
              type="text" 
              class="form-control" 
              v-model="form.name"
              placeholder="e.g., High CPU Alert, Disk Space Warning"
            >
          </div>
          
          <!-- Description (optional) -->
          <div class="mb-3">
            <label class="form-label">Description <span class="text-secondary">(optional)</span></label>
            <input 
              type="text" 
              class="form-control" 
              v-model="form.description"
              placeholder="Brief description of this rule"
            >
          </div>
          
          <!-- Scope (only for new rules, not agent/bookmark specific) -->
          <div class="mb-3" v-if="!targetType">
            <label class="form-label">Scope</label>
            <select class="form-select" v-model="form.scope" @change="onScopeChange">
              <option value="global">Global (all agents & bookmarks)</option>
              <option value="profile">Report Profile</option>
              <option value="agent">Specific Agent</option>
              <option value="bookmark">Specific Bookmark</option>
            </select>
          </div>

          <!-- Profile Scope Section -->
          <div v-if="form.scope === 'profile' && !targetType" class="profile-scope-section">
            <!-- Profile Selector -->
            <div class="mb-3">
              <label class="form-label">Select Profile</label>
              <select class="form-select" v-model="form.profile_id" @change="onProfileChange">
                <option value="">-- Select a Profile --</option>
                <option v-for="profile in allProfiles" :key="profile.id" :value="profile.id">
                  {{ profile.name }}
                </option>
              </select>
              <div v-if="loadingProfiles" class="form-text text-secondary">
                <span class="spinner-border spinner-border-sm me-1"></span>Loading profiles...
              </div>
            </div>

            <!-- Profile Scribes Selection -->
            <div v-if="form.profile_id" class="mb-3">
              <label class="form-label">
                Select Scribes 
                <span class="text-secondary">({{ selectedProfileAgents.length }} selected)</span>
              </label>
              <div class="profile-targets-box">
                <div class="profile-targets-header">
                  <button type="button" class="btn btn-sm btn-link" @click="selectAllProfileAgents">
                    Select All
                  </button>
                  <button type="button" class="btn btn-sm btn-link" @click="deselectAllProfileAgents">
                    Clear
                  </button>
                </div>
                <div v-if="profileAgents.length === 0" class="profile-targets-empty">
                  No scribes in this profile
                </div>
                <div v-else class="profile-targets-list">
                  <div 
                    v-for="agent in profileAgents" 
                    :key="agent.agent_id"
                    class="profile-target-item"
                    :class="{ selected: selectedProfileAgents.includes(agent.agent_id) }"
                    @click="toggleProfileAgent(agent.agent_id)"
                  >
                    <input type="checkbox" :checked="selectedProfileAgents.includes(agent.agent_id)">
                    <i class="bi bi-hdd-network"></i>
                    <span>{{ agent.display_name || agent.hostname }}</span>
                  </div>
                </div>
              </div>
            </div>

            <!-- Profile Bookmarks Selection -->
            <div v-if="form.profile_id" class="mb-3">
              <label class="form-label">
                Select Bookmarks 
                <span class="text-secondary">({{ selectedProfileBookmarks.length }} selected)</span>
              </label>
              <div class="profile-targets-box">
                <div class="profile-targets-header">
                  <button type="button" class="btn btn-sm btn-link" @click="selectAllProfileBookmarks">
                    Select All
                  </button>
                  <button type="button" class="btn btn-sm btn-link" @click="deselectAllProfileBookmarks">
                    Clear
                  </button>
                </div>
                <div v-if="profileBookmarks.length === 0" class="profile-targets-empty">
                  No bookmarks in this profile
                </div>
                <div v-else class="profile-targets-list">
                  <div 
                    v-for="bookmark in profileBookmarks" 
                    :key="bookmark.id"
                    class="profile-target-item"
                    :class="{ selected: selectedProfileBookmarks.includes(bookmark.id) }"
                    @click="toggleProfileBookmark(bookmark.id)"
                  >
                    <input type="checkbox" :checked="selectedProfileBookmarks.includes(bookmark.id)">
                    <i class="bi bi-bookmark-fill"></i>
                    <span>{{ bookmark.name }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
          
          <!-- Agent Search Selector -->
          <div class="mb-3" v-if="form.scope === 'agent' && !targetType">
            <label class="form-label">
              Select Agents 
              <span class="text-secondary">({{ selectedAgents.length }} selected)</span>
            </label>
            <div class="target-selector-box">
              <!-- Search Input -->
              <div class="target-search-header">
                <input
                  type="text"
                  class="target-filter-input"
                  placeholder="Filter agents..."
                  v-model="agentFilter"
                >
                <button type="button" class="btn btn-sm btn-link" @click="selectAllAgents">
                  Select All
                </button>
                <button type="button" class="btn btn-sm btn-link" @click="deselectAllAgents">
                  Clear
                </button>
              </div>
              <div v-if="loadingTargets" class="profile-targets-empty">
                <span class="spinner-border spinner-border-sm me-1"></span>Loading agents...
              </div>
              <div v-else-if="filteredAgentsList.length === 0" class="profile-targets-empty">
                No agents found
              </div>
              <div v-else class="profile-targets-list">
                <div 
                  v-for="agent in filteredAgentsList" 
                  :key="agent.agent_id"
                  class="profile-target-item"
                  :class="{ selected: selectedAgents.includes(agent.agent_id) }"
                  @click="toggleAgent(agent.agent_id)"
                >
                  <input type="checkbox" :checked="selectedAgents.includes(agent.agent_id)">
                  <i class="bi bi-hdd-network"></i>
                  <span>{{ agent.display_name || agent.hostname }}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- Bookmark Search Selector -->
          <div class="mb-3" v-if="form.scope === 'bookmark' && !targetType">
            <label class="form-label">
              Select Bookmarks 
              <span class="text-secondary">({{ selectedBookmarks.length }} selected)</span>
            </label>
            <div class="target-selector-box">
              <!-- Search Input -->
              <div class="target-search-header">
                <input
                  type="text"
                  class="target-filter-input"
                  placeholder="Filter bookmarks..."
                  v-model="bookmarkFilter"
                >
                <button type="button" class="btn btn-sm btn-link" @click="selectAllBookmarks">
                  Select All
                </button>
                <button type="button" class="btn btn-sm btn-link" @click="deselectAllBookmarks">
                  Clear
                </button>
              </div>
              <div v-if="loadingTargets" class="profile-targets-empty">
                <span class="spinner-border spinner-border-sm me-1"></span>Loading bookmarks...
              </div>
              <div v-else-if="filteredBookmarksList.length === 0" class="profile-targets-empty">
                No bookmarks found
              </div>
              <div v-else class="profile-targets-list">
                <div 
                  v-for="bookmark in filteredBookmarksList" 
                  :key="bookmark.id"
                  class="profile-target-item"
                  :class="{ selected: selectedBookmarks.includes(bookmark.id) }"
                  @click="toggleBookmark(bookmark.id)"
                >
                  <input type="checkbox" :checked="selectedBookmarks.includes(bookmark.id)">
                  <i class="bi bi-bookmark-fill"></i>
                  <span>{{ bookmark.name }}</span>
                </div>
              </div>
            </div>
          </div>
          
          <!-- Metric -->
          <div class="mb-3">
            <label class="form-label">Metric</label>
            <select class="form-select" v-model="form.metric">
              <optgroup label="Agent Metrics" v-if="showAgentMetrics">
                <option value="cpu">CPU Usage (%)</option>
                <option value="ram">Memory Usage (%)</option>
                <option value="disk">Disk Usage (%)</option>
                <option value="disk_free">Disk Free (%)</option>
                <option value="cpu_temp">CPU Temperature (°C)</option>
                <option value="net_bandwidth">Network Bandwidth (Mbps)</option>
                <option value="status">Agent Status (offline seconds)</option>
              </optgroup>
              <optgroup label="Bookmark Metrics" v-if="showBookmarkMetrics">
                <option value="bookmark_status">Bookmark Status (consecutive failures)</option>
                <option value="response_time">Response Time (ms)</option>
                <option value="ssl_expiry">SSL Expiry (days remaining)</option>
              </optgroup>
            </select>
          </div>
          
          <!-- Condition -->
          <div class="row mb-3">
            <div class="col-5">
              <label class="form-label">Operator</label>
              <select class="form-select" v-model="form.operator">
                <option value="gt">Greater than (&gt;)</option>
                <option value="gte">Greater or equal (≥)</option>
                <option value="lt">Less than (&lt;)</option>
                <option value="lte">Less or equal (≤)</option>
                <option value="eq">Equal to (=)</option>
                <option value="ne">Not equal (≠)</option>
              </select>
            </div>
            <div class="col-7">
              <label class="form-label">Threshold</label>
              <div class="input-group">
                <input 
                  type="number" 
                  class="form-control" 
                  v-model.number="form.threshold"
                  :placeholder="thresholdPlaceholder"
                >
                <span class="input-group-text">{{ thresholdUnit }}</span>
              </div>
            </div>
          </div>
          
          <!-- Condition preview -->
          <div class="condition-preview mb-3">
            <span class="text-secondary">Trigger when:</span>
            <span class="condition-text">{{ conditionPreview }}</span>
          </div>
          
          <!-- Notification Channels -->
          <div class="mb-3">
            <label class="form-label">Notify via</label>
            <div v-if="channels.length === 0" class="text-secondary small">
              No notification channels configured. 
              <a href="#" @click.prevent="$emit('add-channel')">Add one first</a>
            </div>
            <div v-else class="channels-select">
              <div 
                v-for="channel in channels" 
                :key="channel.id"
                class="channel-option"
                :class="{ selected: form.channels.includes(channel.id) }"
                @click="toggleChannel(channel.id)"
              >
                <input type="checkbox" :checked="form.channels.includes(channel.id)">
                <span>{{ channel.name }}</span>
              </div>
            </div>
          </div>
          
          <!-- Cooldown -->
          <div class="mb-3">
            <label class="form-label">Cooldown Period</label>
            <select class="form-select" v-model.number="form.cooldown_minutes">
              <option :value="1">1 minute</option>
              <option :value="5">5 minutes</option>
              <option :value="15">15 minutes</option>
              <option :value="30">30 minutes</option>
              <option :value="60">1 hour</option>
              <option :value="240">4 hours</option>
            </select>
            <div class="form-text text-secondary">
              Minimum time between repeat alerts for the same target
            </div>
          </div>
          
          <!-- Enable/Disable -->
          <div class="form-check form-switch mb-3" v-if="isEdit">
            <input class="form-check-input" type="checkbox" v-model="form.enabled" id="ruleEnabled">
            <label class="form-check-label" for="ruleEnabled">Rule Enabled</label>
          </div>
          
          <!-- Error message -->
          <div v-if="error" class="alert alert-danger">{{ error }}</div>
        </div>
        
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" @click="close">Cancel</button>
          <button 
            type="button" 
            class="btn btn-primary"
            @click="save"
            :disabled="saving || !isValid"
          >
            <span v-if="saving" class="spinner-border spinner-border-sm me-1"></span>
            {{ isEdit ? 'Save Changes' : 'Create Rule' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import axios from 'axios'

const props = defineProps({
  show: Boolean,
  rule: Object,
  channels: Array,
  targetType: String,
  targetId: String
})

const emit = defineEmits(['close', 'saved', 'add-channel'])

const form = ref({
  name: '',
  description: '',
  scope: 'global',
  target_id: null,
  profile_id: '',
  metric: 'cpu',
  operator: 'gt',
  threshold: 90,
  channels: [],
  cooldown_minutes: 5,
  enabled: true
})

const error = ref('')
const saving = ref(false)

// Target search state
const allAgents = ref([])
const allBookmarks = ref([])
const allProfiles = ref([])
const loadingTargets = ref(false)
const loadingProfiles = ref(false)

// Multi-select for agent/bookmark scope
const selectedAgents = ref([])
const selectedBookmarks = ref([])
const agentFilter = ref('')
const bookmarkFilter = ref('')

// Profile scope state
const profileAgents = ref([])
const profileBookmarks = ref([])
const selectedProfileAgents = ref([])
const selectedProfileBookmarks = ref([])

const isEdit = computed(() => !!props.rule)

const showAgentMetrics = computed(() => {
  return ['global', 'agent', 'profile'].includes(form.value.scope)
})

const showBookmarkMetrics = computed(() => {
  return ['global', 'bookmark', 'profile'].includes(form.value.scope)
})

const filteredAgentsList = computed(() => {
  const query = agentFilter.value.toLowerCase().trim()
  if (!query) return allAgents.value
  return allAgents.value.filter(a => 
    (a.display_name || '').toLowerCase().includes(query) ||
    (a.hostname || '').toLowerCase().includes(query) ||
    (a.agent_id || '').toLowerCase().includes(query)
  )
})

const filteredBookmarksList = computed(() => {
  const query = bookmarkFilter.value.toLowerCase().trim()
  if (!query) return allBookmarks.value
  return allBookmarks.value.filter(b => 
    (b.name || '').toLowerCase().includes(query) ||
    (b.url || '').toLowerCase().includes(query)
  )
})

const isValid = computed(() => {
  if (!form.value.name.trim()) return false
  if (!form.value.metric) return false
  if (form.value.threshold === null || form.value.threshold === '') return false
  
  if (form.value.scope === 'agent' && !props.targetType && selectedAgents.value.length === 0) return false
  if (form.value.scope === 'bookmark' && !props.targetType && selectedBookmarks.value.length === 0) return false
  if (form.value.scope === 'profile') {
    if (!form.value.profile_id) return false
    if (selectedProfileAgents.value.length === 0 && selectedProfileBookmarks.value.length === 0) return false
  }
  
  return true
})

const thresholdUnit = computed(() => {
  const units = {
    cpu: '%',
    ram: '%',
    disk: '%',
    disk_free: '%',
    cpu_temp: '°C',
    net_bandwidth: 'Mbps',
    status: 'sec',
    bookmark_status: 'fails',
    response_time: 'ms',
    ssl_expiry: 'days'
  }
  return units[form.value.metric] || ''
})

const thresholdPlaceholder = computed(() => {
  const defaults = {
    cpu: '90',
    ram: '90',
    disk: '90',
    disk_free: '10',
    cpu_temp: '80',
    net_bandwidth: '100',
    status: '120',
    bookmark_status: '2',
    response_time: '5000',
    ssl_expiry: '14'
  }
  return defaults[form.value.metric] || '0'
})

const conditionPreview = computed(() => {
  const metricNames = {
    cpu: 'CPU usage',
    ram: 'Memory usage',
    disk: 'Disk usage',
    disk_free: 'Free disk space',
    cpu_temp: 'CPU temperature',
    net_bandwidth: 'Network bandwidth',
    status: 'Offline duration',
    bookmark_status: 'Consecutive failures',
    response_time: 'Response time',
    ssl_expiry: 'SSL days remaining'
  }
  
  const opNames = {
    gt: '>',
    gte: '≥',
    lt: '<',
    lte: '≤',
    eq: '=',
    ne: '≠'
  }
  
  const metric = metricNames[form.value.metric] || form.value.metric
  const op = opNames[form.value.operator] || form.value.operator
  const value = form.value.threshold ?? '?'
  const unit = thresholdUnit.value
  
  return `${metric} ${op} ${value}${unit}`
})

// API fetches
async function fetchAgents() {
  try {
    const response = await axios.get('/api/agents')
    allAgents.value = response.data.agents || response.data.data || response.data || []
    console.log('Fetched agents:', allAgents.value.length)
  } catch (e) {
    console.error('Failed to fetch agents:', e)
  }
}

async function fetchBookmarks() {
  try {
    const response = await axios.get('/api/bookmarks')
    // API returns { success: true, data: [...] }
    allBookmarks.value = response.data.data || response.data.bookmarks || response.data || []
    console.log('Fetched bookmarks:', allBookmarks.value.length, allBookmarks.value.map(b => b.name))
  } catch (e) {
    console.error('Failed to fetch bookmarks:', e)
  }
}

async function fetchProfiles() {
  loadingProfiles.value = true
  try {
    const response = await axios.get('/api/report-profiles')
    allProfiles.value = response.data.data || []
  } catch (e) {
    console.error('Failed to fetch profiles:', e)
  } finally {
    loadingProfiles.value = false
  }
}

async function loadTargets() {
  loadingTargets.value = true
  try {
    await Promise.all([fetchAgents(), fetchBookmarks()])
  } finally {
    loadingTargets.value = false
  }
}

// Profile scope methods
async function loadProfileTargets(profileId) {
  if (!profileId) {
    profileAgents.value = []
    profileBookmarks.value = []
    return
  }
  
  try {
    console.log('Loading profile targets for:', profileId)
    
    // Get all agents and bookmarks first
    await loadTargets()
    console.log('Loaded agents:', allAgents.value.length, 'bookmarks:', allBookmarks.value.length)
    
    // Get full profile details including scope info
    const profileRes = await axios.get(`/api/report-profiles/${profileId}`)
    console.log('Profile response:', profileRes.data)
    const profile = profileRes.data.data || profileRes.data
    
    if (!profile) {
      console.error('No profile data returned')
      profileAgents.value = allAgents.value
      profileBookmarks.value = allBookmarks.value
      return
    }
    
    // Filter based on profile scope
    const scribeIds = profile.scribe_scope_ids || []
    const scribeTags = profile.scribe_scope_tags || []
    const monitorIds = profile.monitor_scope_ids || []
    const monitorTags = profile.monitor_scope_tags || []
    
    console.log('Profile scope - scribes:', scribeIds, scribeTags, 'monitors:', monitorIds, monitorTags)
    
    // Filter agents by profile scope
    if (scribeIds.length === 0 && scribeTags.length === 0) {
      // No scope = all agents
      profileAgents.value = [...allAgents.value]
    } else {
      profileAgents.value = allAgents.value.filter(agent => {
        if (scribeIds.includes(agent.agent_id)) return true
        const agentTags = typeof agent.tags === 'string' 
          ? agent.tags.split(',').map(t => t.trim()).filter(t => t)
          : (Array.isArray(agent.tags) ? agent.tags : [])
        return agentTags.some(t => scribeTags.includes(t))
      })
    }
    
    // Filter bookmarks by profile scope
    if (monitorIds.length === 0 && monitorTags.length === 0) {
      // No scope = all bookmarks
      profileBookmarks.value = [...allBookmarks.value]
    } else {
      profileBookmarks.value = allBookmarks.value.filter(bookmark => {
        if (monitorIds.includes(bookmark.id)) return true
        const bookmarkTags = typeof bookmark.tags === 'string' 
          ? bookmark.tags.split(',').map(t => t.trim()).filter(t => t)
          : (Array.isArray(bookmark.tags) ? bookmark.tags : [])
        return bookmarkTags.some(t => monitorTags.includes(t))
      })
    }
    
    console.log('Filtered - agents:', profileAgents.value.length, 'bookmarks:', profileBookmarks.value.length)
  } catch (e) {
    console.error('Failed to load profile targets:', e)
    // On error, show all agents/bookmarks
    profileAgents.value = [...allAgents.value]
    profileBookmarks.value = [...allBookmarks.value]
  }
}

function onProfileChange() {
  selectedProfileAgents.value = []
  selectedProfileBookmarks.value = []
  loadProfileTargets(form.value.profile_id)
}

function toggleProfileAgent(agentId) {
  const idx = selectedProfileAgents.value.indexOf(agentId)
  if (idx >= 0) {
    selectedProfileAgents.value.splice(idx, 1)
  } else {
    selectedProfileAgents.value.push(agentId)
  }
}

function toggleProfileBookmark(bookmarkId) {
  const idx = selectedProfileBookmarks.value.indexOf(bookmarkId)
  if (idx >= 0) {
    selectedProfileBookmarks.value.splice(idx, 1)
  } else {
    selectedProfileBookmarks.value.push(bookmarkId)
  }
}

function selectAllProfileAgents() {
  selectedProfileAgents.value = profileAgents.value.map(a => a.agent_id)
}

function deselectAllProfileAgents() {
  selectedProfileAgents.value = []
}

function selectAllProfileBookmarks() {
  selectedProfileBookmarks.value = profileBookmarks.value.map(b => b.id)
}

function deselectAllProfileBookmarks() {
  selectedProfileBookmarks.value = []
}

// Agent/Bookmark multi-select handlers
function toggleAgent(agentId) {
  const idx = selectedAgents.value.indexOf(agentId)
  if (idx >= 0) {
    selectedAgents.value.splice(idx, 1)
  } else {
    selectedAgents.value.push(agentId)
  }
}

function toggleBookmark(bookmarkId) {
  const idx = selectedBookmarks.value.indexOf(bookmarkId)
  if (idx >= 0) {
    selectedBookmarks.value.splice(idx, 1)
  } else {
    selectedBookmarks.value.push(bookmarkId)
  }
}

function selectAllAgents() {
  selectedAgents.value = filteredAgentsList.value.map(a => a.agent_id)
}

function deselectAllAgents() {
  selectedAgents.value = []
}

function selectAllBookmarks() {
  selectedBookmarks.value = filteredBookmarksList.value.map(b => b.id)
}

function deselectAllBookmarks() {
  selectedBookmarks.value = []
}

function onScopeChange() {
  selectedAgents.value = []
  selectedBookmarks.value = []
  agentFilter.value = ''
  bookmarkFilter.value = ''
  form.value.profile_id = ''
  selectedProfileAgents.value = []
  selectedProfileBookmarks.value = []
  profileAgents.value = []
  profileBookmarks.value = []
  
  // Set appropriate default metric
  if (form.value.scope === 'bookmark') {
    form.value.metric = 'bookmark_status'
    form.value.operator = 'gte'
    form.value.threshold = 2
  } else if (form.value.scope === 'agent') {
    form.value.metric = 'cpu'
    form.value.operator = 'gt'
    form.value.threshold = 90
  } else if (form.value.scope === 'profile') {
    form.value.metric = 'cpu'
    form.value.operator = 'gt'
    form.value.threshold = 90
    fetchProfiles()
  }
}

// Watch for rule prop changes (edit mode)
watch(() => props.rule, async (newRule) => {
  if (newRule) {
    form.value = {
      name: newRule.name || '',
      description: newRule.description || '',
      scope: newRule.scope || 'global',
      target_id: newRule.target_id || null,
      profile_id: newRule.profile_id || '',
      metric: newRule.metric || 'cpu',
      operator: newRule.operator || 'gt',
      threshold: newRule.threshold ?? 90,
      channels: newRule.channels || [],
      cooldown_minutes: newRule.cooldown_minutes || 5,
      enabled: newRule.enabled !== false
    }
    // Load agents/bookmarks for edit mode
    await loadTargets()
    
    // Set selected agents/bookmarks for edit mode
    if (newRule.scope === 'agent') {
      // Support both old single target_id and new multi-select
      selectedAgents.value = newRule.profile_agents?.length > 0 
        ? newRule.profile_agents 
        : (newRule.target_id ? [newRule.target_id] : [])
    } else if (newRule.scope === 'bookmark') {
      selectedBookmarks.value = newRule.profile_bookmarks?.length > 0 
        ? newRule.profile_bookmarks 
        : (newRule.target_id ? [newRule.target_id] : [])
    }
    
    // Load profile targets for edit mode
    if (newRule.scope === 'profile' && newRule.profile_id) {
      await fetchProfiles()
      await loadProfileTargets(newRule.profile_id)
      selectedProfileAgents.value = newRule.profile_agents || []
      selectedProfileBookmarks.value = newRule.profile_bookmarks || []
    }
  } else {
    resetForm()
  }
}, { immediate: true })

// Watch for preset target type/id
watch([() => props.targetType, () => props.targetId], ([type, id]) => {
  if (type && !props.rule) {
    form.value.scope = type
    if (type === 'agent' && id) {
      selectedAgents.value = [id]
    } else if (type === 'bookmark' && id) {
      selectedBookmarks.value = [id]
    }
    if (type === 'bookmark') {
      form.value.metric = 'bookmark_status'
      form.value.operator = 'gte'
      form.value.threshold = 2
    }
  }
}, { immediate: true })

// Watch show to reset error and load data
watch(() => props.show, async (newShow) => {
  if (newShow) {
    error.value = ''
    if (!props.rule) {
      resetForm()
    }
    await loadTargets()
    await fetchProfiles()
  } else {
    agentFilter.value = ''
    bookmarkFilter.value = ''
  }
})

function resetForm() {
  form.value = {
    name: '',
    description: '',
    scope: props.targetType || 'global',
    target_id: props.targetId || null,
    profile_id: '',
    metric: props.targetType === 'bookmark' ? 'bookmark_status' : 'cpu',
    operator: props.targetType === 'bookmark' ? 'gte' : 'gt',
    threshold: props.targetType === 'bookmark' ? 2 : 90,
    channels: [],
    cooldown_minutes: 5,
    enabled: true
  }
  selectedAgents.value = []
  selectedBookmarks.value = []
  agentFilter.value = ''
  bookmarkFilter.value = ''
  selectedProfileAgents.value = []
  selectedProfileBookmarks.value = []
  profileAgents.value = []
  profileBookmarks.value = []
}

function toggleChannel(channelId) {
  const idx = form.value.channels.indexOf(channelId)
  if (idx >= 0) {
    form.value.channels.splice(idx, 1)
  } else {
    form.value.channels.push(channelId)
  }
}

async function save() {
  error.value = ''
  saving.value = true
  
  try {
    const payload = {
      name: form.value.name.trim(),
      description: form.value.description.trim() || null,
      scope: form.value.scope,
      metric: form.value.metric,
      operator: form.value.operator,
      threshold: String(form.value.threshold),
      channels: form.value.channels,
      cooldown_minutes: form.value.cooldown_minutes
    }
    
    // Add scope-specific data
    if (form.value.scope === 'agent') {
      payload.profile_agents = selectedAgents.value
      // For backwards compat, set target_id to first agent if only one selected
      payload.target_id = selectedAgents.value.length === 1 ? selectedAgents.value[0] : null
    } else if (form.value.scope === 'bookmark') {
      payload.profile_bookmarks = selectedBookmarks.value
      payload.target_id = selectedBookmarks.value.length === 1 ? selectedBookmarks.value[0] : null
    } else if (form.value.scope === 'profile') {
      payload.profile_id = form.value.profile_id
      payload.profile_agents = selectedProfileAgents.value
      payload.profile_bookmarks = selectedProfileBookmarks.value
    } else if (props.targetId) {
      payload.target_id = props.targetId
    }
    
    if (isEdit.value) {
      payload.enabled = form.value.enabled
      await axios.put(`/api/alerts/rules/${props.rule.id}`, payload)
    } else {
      await axios.post('/api/alerts/rules', payload)
    }
    
    emit('saved')
    close()
  } catch (e) {
    error.value = e.response?.data?.detail || 'Failed to save rule'
  } finally {
    saving.value = false
  }
}

function close() {
  emit('close')
}
</script>

<style scoped>
.modal-backdrop {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1050;
}

.modal-dialog {
  width: 100%;
  max-width: 550px;
  margin: 1rem;
  max-height: 90vh;
  overflow-y: auto;
}

.modal-dialog.modal-lg {
  max-width: 700px;
}

.modal-content {
  background: #1e1e1e;
  border: 1px solid #333;
  border-radius: 8px;
}

.modal-header {
  border-bottom: 1px solid #333;
  padding: 1rem 1.25rem;
}

.modal-title {
  color: #fff;
  margin: 0;
  font-size: 1.1rem;
}

.btn-close {
  filter: invert(1);
}

.modal-body {
  padding: 1.25rem;
}

.modal-footer {
  border-top: 1px solid #333;
  padding: 1rem 1.25rem;
  display: flex;
  gap: 0.5rem;
  justify-content: flex-end;
}

.form-label {
  color: #ccc;
  font-size: 0.875rem;
  margin-bottom: 0.5rem;
}

.form-control, .form-select {
  background: #2d2d2d;
  border: 1px solid #444;
  color: #fff;
}

.form-control:focus, .form-select:focus {
  background: #2d2d2d;
  border-color: #0d6efd;
  color: #fff;
  box-shadow: 0 0 0 0.2rem rgba(13, 110, 253, 0.25);
}

.form-control::placeholder {
  color: #666;
}

.form-select option {
  background: #2d2d2d;
}

.input-group-text {
  background: #363636;
  border: 1px solid #444;
  color: #999;
}

.condition-preview {
  padding: 0.75rem;
  background: #252525;
  border-radius: 6px;
  border-left: 3px solid #0d6efd;
}

.condition-text {
  color: #fff;
  font-weight: 500;
  margin-left: 0.5rem;
}

.channels-select {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.channel-option {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  background: #2d2d2d;
  border: 2px solid transparent;
  border-radius: 6px;
  cursor: pointer;
  color: #ccc;
}

.channel-option:hover {
  background: #363636;
}

.channel-option.selected {
  border-color: #0d6efd;
  background: rgba(13, 110, 253, 0.1);
}

.channel-option input[type="checkbox"] {
  pointer-events: none;
}

.form-text {
  font-size: 0.75rem;
  margin-top: 0.25rem;
}

.form-check-label {
  color: #ccc;
}

.form-check-input {
  background-color: #2d2d2d;
  border-color: #555;
}

.form-check-input:checked {
  background-color: #0d6efd;
  border-color: #0d6efd;
}

.alert {
  margin-bottom: 0;
}

/* Target Selector Styles */
.target-selector {
  position: relative;
}

.selected-target {
  padding: 0.5rem;
  background: #2d2d2d;
  border: 1px solid #444;
  border-radius: 6px;
  min-height: 42px;
  display: flex;
  align-items: center;
}

.target-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: linear-gradient(135deg, rgba(16, 185, 129, 0.2), rgba(6, 182, 212, 0.2));
  border: 1px solid rgba(16, 185, 129, 0.4);
  color: #6ee7b7;
  padding: 4px 10px;
  border-radius: 16px;
  font-size: 0.85rem;
  font-weight: 500;
}

.target-pill.bookmark {
  background: linear-gradient(135deg, rgba(251, 191, 36, 0.2), rgba(245, 158, 11, 0.2));
  border: 1px solid rgba(251, 191, 36, 0.4);
  color: #fcd34d;
}

.target-remove {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: none;
  border: none;
  color: inherit;
  cursor: pointer;
  padding: 0;
  width: 16px;
  height: 16px;
  font-size: 16px;
  line-height: 1;
  border-radius: 50%;
  opacity: 0.7;
  transition: all 0.15s;
  margin-left: 2px;
}

.target-remove:hover {
  opacity: 1;
  background: rgba(239, 68, 68, 0.3);
  color: #fca5a5;
}

.target-search-container {
  position: relative;
}

.target-search-input {
  width: 100%;
  padding: 0.5rem 0.75rem;
  background: #2d2d2d;
  border: 1px solid #444;
  border-radius: 6px;
  color: #fff;
  font-size: 0.875rem;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.target-search-input:focus {
  outline: none;
  border-color: #0d6efd;
  box-shadow: 0 0 0 0.2rem rgba(13, 110, 253, 0.25);
}

.target-search-input::placeholder {
  color: #666;
}

.target-dropdown {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  background: #1e1e1e;
  border: 1px solid #444;
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
  z-index: 1100;
  margin-top: 4px;
  max-height: 280px;
  overflow-y: auto;
  animation: dropdownAppear 0.15s ease-out;
}

@keyframes dropdownAppear {
  from {
    opacity: 0;
    transform: translateY(-8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.target-option {
  display: flex;
  align-items: center;
  padding: 10px 12px;
  cursor: pointer;
  color: #ccc;
  transition: background 0.15s;
  border-bottom: 1px solid #333;
}

.target-option:last-child {
  border-bottom: none;
}

.target-option:hover,
.target-option.highlighted {
  background: rgba(13, 110, 253, 0.15);
}

.target-option.highlighted {
  background: rgba(13, 110, 253, 0.25);
}

.target-option i {
  color: #888;
  flex-shrink: 0;
}

.target-name {
  font-weight: 500;
  color: #fff;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.target-hostname,
.target-url {
  font-size: 0.75rem;
  color: #666;
  margin-left: 8px;
  flex-shrink: 0;
  max-width: 150px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.target-empty {
  padding: 16px;
  text-align: center;
  color: #666;
  font-size: 0.875rem;
}

/* Target Selector Box Styles */
.target-selector-box {
  border: 1px solid #444;
  border-radius: 6px;
  background: #2d2d2d;
  max-height: 250px;
  overflow-y: auto;
}

.target-search-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem;
  border-bottom: 1px solid #444;
  background: #252525;
  position: sticky;
  top: 0;
  z-index: 1;
}

.target-filter-input {
  flex: 1;
  padding: 0.35rem 0.6rem;
  background: #1e1e1e;
  border: 1px solid #444;
  border-radius: 4px;
  color: #fff;
  font-size: 0.8rem;
}

.target-filter-input:focus {
  outline: none;
  border-color: #0d6efd;
}

.target-filter-input::placeholder {
  color: #666;
}

.target-search-header .btn-link {
  color: #6b7ffc;
  font-size: 0.75rem;
  padding: 0;
  text-decoration: none;
  white-space: nowrap;
}

.target-search-header .btn-link:hover {
  color: #818cf8;
}

/* Profile Scope Styles */
.profile-scope-section {
  border: 1px solid #333;
  border-radius: 8px;
  padding: 1rem;
  margin-bottom: 1rem;
  background: rgba(99, 102, 241, 0.05);
}

.profile-targets-box {
  border: 1px solid #444;
  border-radius: 6px;
  background: #2d2d2d;
  max-height: 200px;
  overflow-y: auto;
}

.profile-targets-header {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  padding: 0.5rem;
  border-bottom: 1px solid #444;
  background: #252525;
}

.profile-targets-header .btn-link {
  color: #6b7ffc;
  font-size: 0.75rem;
  padding: 0;
  text-decoration: none;
}

.profile-targets-header .btn-link:hover {
  color: #818cf8;
}

.profile-targets-empty {
  padding: 1rem;
  text-align: center;
  color: #666;
  font-size: 0.875rem;
}

.profile-targets-list {
  padding: 0.25rem;
}

.profile-target-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  cursor: pointer;
  border-radius: 4px;
  color: #ccc;
  font-size: 0.875rem;
  transition: background 0.15s;
}

.profile-target-item:hover {
  background: rgba(255, 255, 255, 0.05);
}

.profile-target-item.selected {
  background: rgba(13, 110, 253, 0.15);
  color: #fff;
}

.profile-target-item input[type="checkbox"] {
  pointer-events: none;
  accent-color: #0d6efd;
}

.profile-target-item i {
  color: #666;
  font-size: 0.8rem;
}

.profile-target-item.selected i {
  color: #0d6efd;
}
</style>
