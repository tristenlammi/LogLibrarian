<template>
  <div class="dashboard-container">
    <!-- Top Row: Stats Cards -->
    <div class="stats-row">
      <!-- Global Availability -->
      <div class="stat-card availability-card">
        <div class="stat-header">
          <span class="stat-icon">🌐</span>
          <span class="stat-title">Global Availability</span>
        </div>
        <div class="stat-value" :class="availabilityClass">
          {{ globalAvailability }}%
        </div>
        <div class="stat-subtitle">
          {{ onlineScribes }}/{{ totalScribes }} scribes · {{ upBookmarks }}/{{ totalBookmarks }} services
        </div>
      </div>

      <!-- Latest Briefing -->
      <div class="stat-card briefing-card">
        <div class="stat-header">
          <span class="stat-icon">📋</span>
          <span class="stat-title">Latest Briefing</span>
        </div>
        <div class="briefing-content" v-if="latestBriefing">
          <div class="briefing-date">{{ formatBriefingDate(latestBriefing.created_at) }}</div>
          <div class="briefing-summary">{{ truncateBriefing(latestBriefing.content) }}</div>
        </div>
        <div class="briefing-content" v-else>
          <div class="briefing-empty">No briefings yet</div>
        </div>
      </div>
    </div>

    <!-- Profile-Based Status Groups -->
    <div class="profile-groups">
      <!-- Render each profile as a status group -->
      <div 
        v-for="group in profileGroups" 
        :key="group.id" 
        class="status-section profile-section"
      >
        <div class="section-header">
          <h3>{{ group.name }}</h3>
          <span class="section-subtitle">
            {{ group.scribes.length }} Scribes · {{ group.bookmarks.length }} Services
          </span>
        </div>
        
        <!-- Scribes subsection -->
        <div v-if="group.scribes.length > 0" class="asset-subsection">
          <div class="subsection-label">
            <span class="subsection-icon">🖥️</span>
            <span>Scribes</span>
          </div>
          <div class="pill-grid">
            <router-link 
              v-for="scribe in group.scribes" 
              :key="scribe.agent_id"
              :to="`/agents?open=${scribe.agent_id}`"
              class="status-pill"
              :class="getScribeStatusClass(scribe)"
              :title="getScribeTooltip(scribe)"
            ></router-link>
          </div>
        </div>

        <!-- Bookmarks subsection -->
        <div v-if="group.bookmarks.length > 0" class="asset-subsection">
          <div class="subsection-label">
            <span class="subsection-icon">🔖</span>
            <span>Services</span>
          </div>
          <div class="pill-grid">
            <router-link 
              v-for="bookmark in group.bookmarks" 
              :key="bookmark.id"
              :to="`/bookmarks?open=${bookmark.id}`"
              class="status-pill"
              :class="getBookmarkStatusClass(bookmark)"
              :title="getBookmarkTooltip(bookmark)"
            ></router-link>
          </div>
        </div>

        <!-- Empty state for profile with no assets -->
        <div v-if="group.scribes.length === 0 && group.bookmarks.length === 0" class="empty-profile">
          <span>No assets in this profile</span>
        </div>
      </div>

      <!-- Ungrouped Assets Section (Safety Net) -->
      <div 
        v-if="ungroupedScribes.length > 0 || ungroupedBookmarks.length > 0" 
        class="status-section ungrouped-section"
      >
        <div class="section-header">
          <h3>Other Assets</h3>
          <span class="section-subtitle">
            {{ ungroupedScribes.length }} Scribes · {{ ungroupedBookmarks.length }} Services
          </span>
        </div>
        
        <!-- Ungrouped Scribes -->
        <div v-if="ungroupedScribes.length > 0" class="asset-subsection">
          <div class="subsection-label">
            <span class="subsection-icon">🖥️</span>
            <span>Scribes</span>
          </div>
          <div class="pill-grid">
            <router-link 
              v-for="scribe in ungroupedScribes" 
              :key="scribe.agent_id"
              :to="`/agents?open=${scribe.agent_id}`"
              class="status-pill"
              :class="getScribeStatusClass(scribe)"
              :title="getScribeTooltip(scribe)"
            ></router-link>
          </div>
        </div>

        <!-- Ungrouped Bookmarks -->
        <div v-if="ungroupedBookmarks.length > 0" class="asset-subsection">
          <div class="subsection-label">
            <span class="subsection-icon">🔖</span>
            <span>Services</span>
          </div>
          <div class="pill-grid">
            <router-link 
              v-for="bookmark in ungroupedBookmarks" 
              :key="bookmark.id"
              :to="`/bookmarks?open=${bookmark.id}`"
              class="status-pill"
              :class="getBookmarkStatusClass(bookmark)"
              :title="getBookmarkTooltip(bookmark)"
            ></router-link>
          </div>
        </div>
      </div>

      <!-- Fallback: Show all assets if no profiles exist -->
      <template v-if="profiles.length === 0">
        <div class="status-section">
          <div class="section-header">
            <h3>Infrastructure</h3>
            <span class="section-subtitle">{{ totalScribes }} Scribes</span>
          </div>
          <div class="pill-grid">
            <router-link 
              v-for="scribe in scribes" 
              :key="scribe.agent_id"
              :to="`/agents?open=${scribe.agent_id}`"
              class="status-pill"
              :class="getScribeStatusClass(scribe)"
              :title="getScribeTooltip(scribe)"
            ></router-link>
            <div v-if="scribes.length === 0" class="empty-grid">
              <span>No scribes connected</span>
            </div>
          </div>
        </div>

        <div class="status-section">
          <div class="section-header">
            <h3>Services</h3>
            <span class="section-subtitle">{{ totalBookmarks }} Bookmarks</span>
          </div>
          <div class="pill-grid">
            <router-link 
              v-for="bookmark in bookmarks" 
              :key="bookmark.id"
              :to="`/bookmarks?open=${bookmark.id}`"
              class="status-pill"
              :class="getBookmarkStatusClass(bookmark)"
              :title="getBookmarkTooltip(bookmark)"
            ></router-link>
            <div v-if="bookmarks.length === 0" class="empty-grid">
              <span>No monitors configured</span>
            </div>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { RouterLink } from 'vue-router'
import api from '../api.js'
import { user, isAdmin } from '../auth.js'

// State
const scribes = ref([])
const bookmarks = ref([])
const profiles = ref([])
const latestBriefing = ref(null)
const loading = ref(true)

let refreshInterval = null

// Computed: Basic counts
const totalScribes = computed(() => scribes.value.length)
const onlineScribes = computed(() => scribes.value.filter(s => s.status === 'online').length)

const totalBookmarks = computed(() => bookmarks.value.length)
const upBookmarks = computed(() => bookmarks.value.filter(b => {
  const status = b.latest_check?.status ?? b.last_status
  return status === 1
}).length)

const globalAvailability = computed(() => {
  const total = totalScribes.value + totalBookmarks.value
  if (total === 0) return 100
  const online = onlineScribes.value + upBookmarks.value
  return Math.round((online / total) * 100)
})

const availabilityClass = computed(() => {
  const pct = globalAvailability.value
  if (pct >= 95) return 'availability-good'
  if (pct >= 80) return 'availability-warn'
  return 'availability-bad'
})

// Helper: Get scribe tags as array
const getScribeTags = (scribe) => {
  if (!scribe.tags) return []
  if (Array.isArray(scribe.tags)) return scribe.tags
  if (typeof scribe.tags === 'string') {
    return scribe.tags.split(',').map(t => t.trim()).filter(Boolean)
  }
  return []
}

// Helper: Get bookmark tags as array
const getBookmarkTags = (bookmark) => {
  if (!bookmark.tags) return []
  if (Array.isArray(bookmark.tags)) return bookmark.tags
  if (typeof bookmark.tags === 'string') {
    return bookmark.tags.split(',').map(t => t.trim()).filter(Boolean)
  }
  return []
}

// Helper: Check if scribe matches profile scope
const scribeMatchesProfile = (scribe, profile) => {
  // Check if scribe ID is in scope_ids
  if (profile.scribe_scope_ids?.length > 0) {
    if (profile.scribe_scope_ids.includes(scribe.agent_id)) {
      return true
    }
  }
  
  // Check if any scribe tag matches scope_tags
  if (profile.scribe_scope_tags?.length > 0) {
    const scribeTags = getScribeTags(scribe)
    for (const tag of scribeTags) {
      if (profile.scribe_scope_tags.includes(tag)) {
        return true
      }
    }
  }
  
  // If profile has no scribe scope defined, it includes all scribes
  if ((!profile.scribe_scope_ids || profile.scribe_scope_ids.length === 0) &&
      (!profile.scribe_scope_tags || profile.scribe_scope_tags.length === 0)) {
    return true
  }
  
  return false
}

// Helper: Check if bookmark matches profile scope
const bookmarkMatchesProfile = (bookmark, profile) => {
  // Check if bookmark ID is in scope_ids
  if (profile.monitor_scope_ids?.length > 0) {
    if (profile.monitor_scope_ids.includes(bookmark.id)) {
      return true
    }
  }
  
  // Check if any bookmark tag matches scope_tags
  if (profile.monitor_scope_tags?.length > 0) {
    const bookmarkTags = getBookmarkTags(bookmark)
    for (const tag of bookmarkTags) {
      if (profile.monitor_scope_tags.includes(tag)) {
        return true
      }
    }
  }
  
  // If profile has no monitor scope defined, it includes all bookmarks
  if ((!profile.monitor_scope_ids || profile.monitor_scope_ids.length === 0) &&
      (!profile.monitor_scope_tags || profile.monitor_scope_tags.length === 0)) {
    return true
  }
  
  return false
}

// Computed: Build profile groups with their assets
const profileGroups = computed(() => {
  // For non-admin users with an assigned profile, only show that profile
  let filteredProfiles = profiles.value
  if (!isAdmin.value && user.value?.assigned_profile_id) {
    filteredProfiles = profiles.value.filter(p => p.id === user.value.assigned_profile_id)
  }
  
  return filteredProfiles.map(profile => {
    const matchingScribes = scribes.value.filter(s => scribeMatchesProfile(s, profile))
    const matchingBookmarks = bookmarks.value.filter(b => bookmarkMatchesProfile(b, profile))
    
    return {
      id: profile.id,
      name: profile.name,
      description: profile.description,
      scribes: matchingScribes,
      bookmarks: matchingBookmarks
    }
  })
})

// Computed: Track which assets are grouped
const groupedScribeIds = computed(() => {
  const ids = new Set()
  for (const group of profileGroups.value) {
    for (const scribe of group.scribes) {
      ids.add(scribe.agent_id)
    }
  }
  return ids
})

const groupedBookmarkIds = computed(() => {
  const ids = new Set()
  for (const group of profileGroups.value) {
    for (const bookmark of group.bookmarks) {
      ids.add(bookmark.id)
    }
  }
  return ids
})

// Computed: Ungrouped assets (safety net)
const ungroupedScribes = computed(() => {
  if (profiles.value.length === 0) return []
  return scribes.value.filter(s => !groupedScribeIds.value.has(s.agent_id))
})

const ungroupedBookmarks = computed(() => {
  if (profiles.value.length === 0) return []
  return bookmarks.value.filter(b => !groupedBookmarkIds.value.has(b.id))
})

// Methods
const fetchScribes = async () => {
  try {
    const response = await api.get('/api/agents')
    scribes.value = response.data.agents || []
  } catch (error) {
    console.error('Error fetching scribes:', error)
  }
}

const fetchBookmarks = async () => {
  try {
    const response = await api.get('/api/bookmarks')
    bookmarks.value = response.data.data || response.data || []
  } catch (error) {
    console.error('Error fetching bookmarks:', error)
  }
}

const fetchProfiles = async () => {
  try {
    const response = await api.get('/api/report-profiles')
    profiles.value = response.data.data || response.data || []
  } catch (error) {
    console.error('Error fetching profiles:', error)
    profiles.value = []
  }
}

const fetchLatestBriefing = async () => {
  // Stat reports are accessed via Report Profiles, not a separate reports endpoint
  // This function is no longer needed but kept for future use
  latestBriefing.value = null
}

const getScribeStatusClass = (scribe) => {
  const isOnline = scribe.status === 'online'
  return isOnline ? 'pill-online' : 'pill-offline'
}

const getBookmarkStatusClass = (bookmark) => {
  const status = bookmark.latest_check?.status ?? bookmark.last_status
  return status === 1 ? 'pill-online' : 'pill-offline'
}

const getScribeTooltip = (scribe) => {
  const name = scribe.display_name || scribe.hostname || scribe.agent_id
  const status = scribe.status === 'online' ? '✓ Online' : '✗ Offline'
  return `${name} - ${status}`
}

const getBookmarkTooltip = (bookmark) => {
  const name = bookmark.name || bookmark.url
  const status = (bookmark.latest_check?.status ?? bookmark.last_status) === 1 ? '✓ Up' : '✗ Down'
  const latency = bookmark.last_latency ? ` (${bookmark.last_latency}ms)` : ''
  return `${name} - ${status}${latency}`
}

const formatBriefingDate = (dateStr) => {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  return date.toLocaleDateString('en-US', { 
    weekday: 'short', 
    month: 'short', 
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}

const truncateBriefing = (content) => {
  if (!content) return ''
  // Get first 150 chars, strip markdown
  const stripped = content.replace(/[#*`_\[\]]/g, '').trim()
  return stripped.length > 150 ? stripped.substring(0, 150) + '...' : stripped
}

const fetchAll = async () => {
  await Promise.all([
    fetchScribes(),
    fetchBookmarks(),
    fetchProfiles(),
    fetchLatestBriefing()
  ])
  loading.value = false
}

// Lifecycle
onMounted(() => {
  fetchAll()
  refreshInterval = setInterval(fetchAll, 30000) // Refresh every 30s
})

onUnmounted(() => {
  if (refreshInterval) {
    clearInterval(refreshInterval)
  }
})
</script>

<style scoped>
.dashboard-container {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

/* Stats Row */
.stats-row {
  display: grid;
  grid-template-columns: 1fr 2fr;
  gap: 1rem;
}

.stat-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 1.25rem;
}

.stat-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}

.stat-icon {
  font-size: 1.25rem;
}

.stat-title {
  font-size: 0.9rem;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.stat-value {
  font-size: 2.5rem;
  font-weight: 700;
  line-height: 1;
  margin-bottom: 0.5rem;
}

.availability-good { color: #00ff00; }
.availability-warn { color: #ffaa00; }
.availability-bad { color: #ff0000; }

.stat-subtitle {
  font-size: 0.85rem;
  color: var(--text-secondary);
}

/* Briefing Card */
.briefing-content {
  margin-top: 0.5rem;
}

.briefing-date {
  font-size: 0.8rem;
  color: var(--accent-color);
  margin-bottom: 0.5rem;
}

.briefing-summary {
  font-size: 0.9rem;
  color: var(--text-secondary);
  line-height: 1.4;
}

.briefing-empty {
  color: var(--text-secondary);
  font-style: italic;
}

/* Profile Groups Container */
.profile-groups {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

/* Status Sections */
.status-section {
  background: var(--bg-secondary);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  padding: 1.25rem;
  position: relative;
  overflow: hidden;
}

.profile-section::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: var(--accent-color);
  border-radius: 8px 0 0 8px;
}

.ungrouped-section {
  opacity: 0.85;
}

.ungrouped-section::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: var(--text-secondary);
  border-radius: 8px 0 0 8px;
}

.section-header {
  display: flex;
  align-items: baseline;
  gap: 0.75rem;
  margin-bottom: 1rem;
}

.section-header h3 {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 600;
}

.section-subtitle {
  font-size: 0.8rem;
  color: var(--text-secondary);
}

/* Asset Subsections */
.asset-subsection {
  margin-bottom: 1rem;
}

.asset-subsection:last-child {
  margin-bottom: 0;
}

.subsection-label {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.8rem;
  color: var(--text-secondary);
  margin-bottom: 0.5rem;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.subsection-icon {
  font-size: 0.9rem;
}

/* Pill Grid */
.pill-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-height: 40px;
  align-items: flex-start;
  align-content: flex-start;
}

.status-pill {
  display: block;
  width: 24px;
  height: 12px;
  border-radius: 6px;
  cursor: pointer;
  transition: transform 0.15s ease, box-shadow 0.15s ease;
  text-decoration: none;
}

.status-pill:hover {
  transform: scale(1.3);
  z-index: 10;
}

/* Online/Up - Bright Green with glow */
.pill-online {
  background-color: #00ff00;
  box-shadow: 
    0 0 4px #00ff00,
    0 0 8px rgba(0, 255, 0, 0.5);
}

.pill-online:hover {
  box-shadow: 
    0 0 8px #00ff00,
    0 0 16px rgba(0, 255, 0, 0.7);
}

/* Offline/Down - Bright Red with glow */
.pill-offline {
  background-color: #ff0000;
  box-shadow: 
    0 0 4px #ff0000,
    0 0 8px rgba(255, 0, 0, 0.5);
}

.pill-offline:hover {
  box-shadow: 
    0 0 8px #ff0000,
    0 0 16px rgba(255, 0, 0, 0.7);
}

.empty-grid,
.empty-profile {
  width: 100%;
  text-align: center;
  color: var(--text-secondary);
  font-size: 0.9rem;
  padding: 1rem;
  font-style: italic;
}

/* Responsive adjustments */
@media (max-width: 992px) {
  .stats-row {
    grid-template-columns: 1fr;
  }
}
</style>
