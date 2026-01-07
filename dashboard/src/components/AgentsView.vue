<template>
  <div>
    <!-- Agents List -->
    <div class="row g-3 mb-4">
      <div class="col-12">
        <div class="card">
          <div class="card-header d-flex justify-content-between align-items-center">
            <div class="d-flex align-items-center gap-3">
              <h5 class="mb-0">Connected Scribes</h5>
              <span class="badge bg-primary">{{ agents.length }} scribes</span>
            </div>
            <div class="d-flex align-items-center gap-2">
              <!-- Search Bar -->
              <div class="search-wrapper">
                <input 
                  type="text" 
                  class="form-control form-control-sm search-input"
                  v-model="searchQuery"
                  placeholder="Search scribes..."
                >
                <span class="search-icon">🔍</span>
              </div>
              <!-- Install Button (Admin Only) -->
              <button 
                v-if="isAdmin"
                class="btn btn-sm btn-success d-flex align-items-center gap-1"
                @click="showInstallModal = true"
              >
                <span style="font-size: 1.1rem">+</span>
                <span>Install a Scribe</span>
              </button>
              <!-- View Toggle -->
              <div class="btn-group" role="group">
                <button 
                  type="button" 
                  class="btn btn-sm"
                  :class="viewMode === 'grid' ? 'btn-primary' : 'btn-outline-secondary'"
                  @click="viewMode = 'grid'"
                  title="Grid View"
                >
                  <span style="font-size: 1.1rem">▦</span>
                </button>
                <button 
                  type="button" 
                  class="btn btn-sm"
                  :class="viewMode === 'list' ? 'btn-primary' : 'btn-outline-secondary'"
                  @click="viewMode = 'list'"
                  title="List View"
                >
                  <span style="font-size: 1.1rem">☰</span>
                </button>
              </div>
            </div>
          </div>
          <div class="card-body">
            <div v-if="loading" class="text-center py-5">
              <div class="spinner-border text-primary mb-3" role="status"></div>
              <div class="text-secondary">Loading scribes...</div>
            </div>

            <div v-else-if="agents.length === 0" class="text-center py-5">
              <div class="text-secondary">
                <div class="mb-3" style="font-size: 3rem">🖥️</div>
                <h5>No scribes connected yet</h5>
                <p class="text-muted mb-4" v-if="isAdmin">Deploy your first Scribe agent to start monitoring</p>
                <p class="text-muted mb-4" v-else>Contact an administrator to deploy Scribe agents</p>
                <button v-if="isAdmin" class="btn btn-success" @click="showInstallModal = true">
                  <span class="me-1">+</span> Install Your First Scribe
                </button>
              </div>
            </div>

            <!-- No Results -->
            <div v-else-if="filteredAgents.length === 0" class="text-center py-5">
              <div class="text-secondary">
                <div class="mb-3" style="font-size: 2rem">🔍</div>
                <h6>No scribes match "{{ searchQuery }}"</h6>
                <button class="btn btn-sm btn-outline-secondary mt-2" @click="searchQuery = ''">
                  Clear search
                </button>
              </div>
            </div>

            <!-- Grid View -->
            <div v-else-if="viewMode === 'grid'" class="agents-grid">
              <AgentCard 
                v-for="agent in filteredAgents" 
                :key="agent.agent_id"
                :agent="agent"
                @select="openAgentDetail"
              />
            </div>

            <!-- List View -->
            <div v-else class="table-responsive">
              <table class="table table-dark table-hover mb-0">
                <thead>
                  <tr>
                    <th style="width: 40px"></th>
                    <th>Hostname</th>
                    <th>Public IP</th>
                    <th style="width: 100px">CPU</th>
                    <th style="width: 100px">RAM</th>
                    <th style="width: 80px">Disk</th>
                    <th style="width: 100px">Avail.</th>
                    <th style="width: 120px">Last Seen</th>
                  </tr>
                </thead>
                <tbody>
                  <AgentListRow 
                    v-for="agent in filteredAgents" 
                    :key="agent.agent_id"
                    :agent="agent"
                    @select="openAgentDetail"
                  />
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Install Scribe Modal -->
    <InstallScribeModal 
      :show="showInstallModal"
      @close="showInstallModal = false"
    />

    <!-- Agent Detail Modal -->
    <AgentDetailModal 
      :show="showDetailModal"
      :agent="selectedAgent"
      @close="closeAgentDetail"
      @deleted="onAgentDeleted"
      @status-changed="onAgentStatusChanged"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, onActivated, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from '../api.js'
import AgentCard from './AgentCard.vue'
import AgentListRow from './AgentListRow.vue'
import InstallScribeModal from './InstallScribeModal.vue'
import AgentDetailModal from './AgentDetailModal.vue'
import { isAdmin } from '../auth.js'

const route = useRoute()
const router = useRouter()

// State
const agents = ref([])
const loading = ref(true)
const viewMode = ref('grid')
const showInstallModal = ref(false)
const showDetailModal = ref(false)
const selectedAgentId = ref(null)
const searchQuery = ref('')

let agentsRefreshInterval = null

// Computed
const selectedAgent = computed(() => {
  return agents.value.find(a => a.agent_id === selectedAgentId.value)
})

const filteredAgents = computed(() => {
  if (!searchQuery.value.trim()) {
    return agents.value
  }
  const query = searchQuery.value.toLowerCase().trim()
  return agents.value.filter(agent => {
    return (
      agent.hostname?.toLowerCase().includes(query) ||
      agent.agent_id?.toLowerCase().includes(query) ||
      agent.public_ip?.toLowerCase().includes(query) ||
      agent.display_name?.toLowerCase().includes(query)
    )
  })
})

// Methods
const fetchAgents = async () => {
  if (agents.value.length === 0) {
    loading.value = true
  }
  
  try {
    const response = await api.get('/api/agents')
    agents.value = response.data.agents
    
    // Check for ?open= query parameter after agents are loaded
    checkOpenQuery()
  } catch (error) {
    console.error('Error fetching agents:', error)
  } finally {
    loading.value = false
  }
}

// Handle ?open=<agent_id> query parameter
const checkOpenQuery = () => {
  const openId = route.query.open
  if (openId && agents.value.length > 0) {
    // Find the agent
    const agent = agents.value.find(a => a.agent_id === openId)
    if (agent) {
      openAgentDetail(openId)
    }
    // Clear the query parameter to prevent re-opening on refresh
    router.replace({ path: route.path, query: {} })
  }
}

const openAgentDetail = (agentOrId) => {
  // Handle both agent object and agent_id string
  const agentId = typeof agentOrId === 'string' ? agentOrId : agentOrId.agent_id
  selectedAgentId.value = agentId
  showDetailModal.value = true
}

const closeAgentDetail = () => {
  showDetailModal.value = false
  selectedAgentId.value = null
}

const onAgentDeleted = (agentId) => {
  agents.value = agents.value.filter(a => a.agent_id !== agentId)
}

const onAgentStatusChanged = (agentId, enabled) => {
  const agent = agents.value.find(a => a.agent_id === agentId)
  if (agent) {
    agent.enabled = enabled
  }
  fetchAgents()
}

// Lifecycle - fetch data on mount and when route becomes active
const fetchData = async () => {
  try {
    await fetchAgents()
  } catch (e) {
    console.error('Failed to fetch agents:', e)
  }
}

onMounted(() => {
  fetchData()
  agentsRefreshInterval = setInterval(fetchAgents, 10000)
})

// Refetch when navigating back to this view (works with keep-alive)
onActivated(() => {
  fetchData()
})

// Watch for query parameter changes (in case user navigates from dashboard)
watch(() => route.query.open, (newVal) => {
  if (newVal && agents.value.length > 0) {
    checkOpenQuery()
  }
})

onUnmounted(() => {
  if (agentsRefreshInterval) {
    clearInterval(agentsRefreshInterval)
  }
})
</script>

<style scoped>
.agents-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 1rem;
}

/* Search Bar */
.search-wrapper {
  position: relative;
}

.search-input {
  background-color: var(--bg-secondary);
  border: 1px solid var(--border-color);
  color: var(--text-primary);
  padding-left: 2rem;
  width: 200px;
}

.search-input:focus {
  background-color: var(--bg-secondary);
  border-color: var(--accent-color);
  color: var(--text-primary);
  box-shadow: 0 0 0 2px rgba(88, 166, 255, 0.2);
}

.search-input::placeholder {
  color: var(--text-secondary);
}

.search-icon {
  position: absolute;
  left: 0.5rem;
  top: 50%;
  transform: translateY(-50%);
  font-size: 0.8rem;
  opacity: 0.6;
  pointer-events: none;
}

/* Table Styles */
.table-dark {
  color: var(--text-primary);
  background-color: transparent;
}

.table-dark thead th {
  background-color: rgba(88, 166, 255, 0.1);
  border-color: var(--border-color);
  font-weight: 600;
  text-transform: uppercase;
  font-size: 0.85rem;
  letter-spacing: 0.5px;
  padding: 0.75rem;
}

.table-dark tbody td {
  border-color: var(--border-color);
  padding: 0.75rem;
  vertical-align: middle;
}

.table-dark tbody tr:hover {
  background-color: rgba(88, 166, 255, 0.05);
  cursor: pointer;
}
</style>
