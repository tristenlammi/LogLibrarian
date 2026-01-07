<template>
  <div class="help-widget" :class="{ expanded: isExpanded }">
    <!-- Toggle Button -->
    <button class="help-toggle" @click="isExpanded = !isExpanded" :title="isExpanded ? 'Close Help' : 'Help & Docs'">
      <span v-if="!isExpanded">❓</span>
      <span v-else>✕</span>
    </button>

    <!-- Expanded Panel -->
    <Transition name="slide">
      <div v-if="isExpanded" class="help-panel">
        <!-- Header -->
        <div class="help-header">
          <div class="help-title">
            <i class="bi bi-book"></i>
            <span>Help & Documentation</span>
          </div>
          <div class="help-search">
            <input 
              type="text" 
              v-model="searchQuery" 
              placeholder="Search docs..."
              class="search-input"
            >
          </div>
        </div>

        <!-- Tabs -->
        <div class="help-tabs">
          <button 
            v-for="tab in tabs" 
            :key="tab.id"
            class="help-tab"
            :class="{ active: activeTab === tab.id }"
            @click="activeTab = tab.id"
          >
            <span class="tab-icon">{{ tab.icon }}</span>
            <span class="tab-label">{{ tab.label }}</span>
          </button>
        </div>

        <!-- Content -->
        <div class="help-content">
          <!-- How-To Guides -->
          <div v-if="activeTab === 'guides'" class="tab-content">
            <div v-if="filteredGuides.length === 0" class="no-results">
              No guides match your search.
            </div>
            <div 
              v-for="guide in filteredGuides" 
              :key="guide.title"
              class="guide-item"
              :class="{ expanded: expandedGuide === guide.title }"
            >
              <button class="guide-header" @click="toggleGuide(guide.title)">
                <span class="guide-icon">{{ guide.icon }}</span>
                <span class="guide-title">{{ guide.title }}</span>
                <span class="guide-chevron">{{ expandedGuide === guide.title ? '▼' : '▶' }}</span>
              </button>
              <Transition name="expand">
                <div v-if="expandedGuide === guide.title" class="guide-content">
                  <div v-html="guide.content"></div>
                </div>
              </Transition>
            </div>
          </div>

          <!-- App Functionality -->
          <div v-if="activeTab === 'features'" class="tab-content">
            <div v-if="filteredFeatures.length === 0" class="no-results">
              No features match your search.
            </div>
            <div 
              v-for="section in filteredFeatures" 
              :key="section.title"
              class="feature-section"
            >
              <h4 class="section-title">
                <span class="section-icon">{{ section.icon }}</span>
                {{ section.title }}
              </h4>
              <ul class="feature-list">
                <li v-for="feature in section.features" :key="feature.name" class="feature-item">
                  <strong>{{ feature.name }}</strong>
                  <p>{{ feature.description }}</p>
                </li>
              </ul>
            </div>
          </div>

          <!-- System Internals -->
          <div v-if="activeTab === 'internals'" class="tab-content internals-tab">
            <div class="internals-section">
              <h4 class="internals-title">
                <span class="title-icon">🖥️</span>
                Windows vs. Linux Metrics Collection
              </h4>
              <p class="internals-intro">
                Understanding how LogLibrarian collects system metrics across different operating systems.
              </p>

              <div class="comparison-grid">
                <!-- Windows Section -->
                <div class="os-card windows">
                  <div class="os-header">
                    <span class="os-icon">🪟</span>
                    <h5>Windows</h5>
                    <span class="os-badge">WMI / PowerShell</span>
                  </div>
                  <div class="os-content">
                    <div class="metric-group">
                      <h6>CPU & Memory</h6>
                      <p>Uses <code>Win32_Processor</code> and <code>Win32_OperatingSystem</code> WMI classes via PowerShell.</p>
                    </div>
                    <div class="metric-group">
                      <h6>Temperature</h6>
                      <p>Queries <code>MSAcpi_ThermalZoneTemperature</code> from the root/WMI namespace. Requires admin privileges.</p>
                      <div class="note warning">
                        <strong>⚠️ Note:</strong> WMI temperature queries can be slow (2-3 seconds) on some systems.
                      </div>
                    </div>
                    <div class="metric-group">
                      <h6>GPU</h6>
                      <p>Uses <code>nvidia-smi</code> CLI for NVIDIA GPUs. Falls back to WMI for basic info on other GPUs.</p>
                    </div>
                    <div class="metric-group">
                      <h6>Disk & Network</h6>
                      <p>Native Go libraries (<code>gopsutil</code>) with Windows API calls.</p>
                    </div>
                  </div>
                </div>

                <!-- Linux Section -->
                <div class="os-card linux">
                  <div class="os-header">
                    <span class="os-icon">🐧</span>
                    <h5>Linux</h5>
                    <span class="os-badge">Kernel / Procfs</span>
                  </div>
                  <div class="os-content">
                    <div class="metric-group">
                      <h6>CPU & Memory</h6>
                      <p>Direct reads from <code>/proc/stat</code> and <code>/proc/meminfo</code>. Extremely fast and efficient.</p>
                    </div>
                    <div class="metric-group">
                      <h6>Temperature</h6>
                      <p>Reads from <code>/sys/class/thermal/</code> or <code>/sys/class/hwmon/</code> sysfs interfaces.</p>
                      <div class="note success">
                        <strong>✓ Advantage:</strong> Direct kernel interface - near-instant reads with no overhead.
                      </div>
                    </div>
                    <div class="metric-group">
                      <h6>GPU</h6>
                      <p>Uses <code>nvidia-smi</code> for NVIDIA. AMD GPUs use sysfs at <code>/sys/class/drm/</code>.</p>
                    </div>
                    <div class="metric-group">
                      <h6>Disk & Network</h6>
                      <p>Reads <code>/proc/diskstats</code> and <code>/proc/net/dev</code> directly from procfs.</p>
                    </div>
                  </div>
                </div>
              </div>

              <!-- Architecture Diagram -->
              <div class="architecture-section">
                <h4 class="internals-title">
                  <span class="title-icon">🏗️</span>
                  Collection Architecture
                </h4>
                <div class="architecture-diagram">
                  <div class="arch-layer">
                    <div class="arch-box agent">
                      <strong>Scribe Agent</strong>
                      <span>Go Binary</span>
                    </div>
                  </div>
                  <div class="arch-arrow">↓</div>
                  <div class="arch-layer split">
                    <div class="arch-box fast">
                      <strong>Fast Collector</strong>
                      <span>CPU, RAM, Network, Disk</span>
                      <em>~10ms latency</em>
                    </div>
                    <div class="arch-box slow">
                      <strong>Slow Collector</strong>
                      <span>Temperature, GPU, Ping</span>
                      <em>Background thread</em>
                    </div>
                  </div>
                  <div class="arch-arrow">↓</div>
                  <div class="arch-layer">
                    <div class="arch-box buffer">
                      <strong>Metrics Buffer</strong>
                      <span>Batched for efficiency</span>
                    </div>
                  </div>
                  <div class="arch-arrow">↓ WebSocket</div>
                  <div class="arch-layer">
                    <div class="arch-box server">
                      <strong>Librarian Server</strong>
                      <span>FastAPI + SQLite</span>
                    </div>
                  </div>
                </div>
              </div>

              <!-- Timing Details -->
              <div class="timing-section">
                <h4 class="internals-title">
                  <span class="title-icon">⏱️</span>
                  Collection Intervals
                </h4>
                <table class="timing-table">
                  <thead>
                    <tr>
                      <th>Mode</th>
                      <th>Fast Metrics</th>
                      <th>Slow Metrics</th>
                      <th>When Active</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td><span class="mode-badge active">Active</span></td>
                      <td>1 second</td>
                      <td>2 seconds</td>
                      <td>Dashboard viewing agent</td>
                    </tr>
                    <tr>
                      <td><span class="mode-badge idle">Idle</span></td>
                      <td>30 seconds</td>
                      <td>30 seconds</td>
                      <td>No active viewers</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>

        <!-- Footer -->
        <div class="help-footer">
          <span class="version">LogLibrarian v1.0</span>
          <a href="https://github.com" target="_blank" class="footer-link">
            <i class="bi bi-github"></i> GitHub
          </a>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const isExpanded = ref(false)
const activeTab = ref('guides')
const searchQuery = ref('')
const expandedGuide = ref(null)

const tabs = [
  { id: 'guides', label: 'How-To', icon: '📖' },
  { id: 'features', label: 'Features', icon: '⚡' },
  { id: 'internals', label: 'Internals', icon: '🔧' },
]

const guides = [
  {
    icon: '🚀',
    title: 'Getting Started',
    content: `
      <ol>
        <li><strong>Deploy the Server</strong> - Run <code>docker compose up -d</code> in the LogLibrarian directory.</li>
        <li><strong>Access Dashboard</strong> - Open <code>http://your-server:3000</code> in your browser.</li>
        <li><strong>Install Scribe Agent</strong> - Go to Scribes → Install Scribe, copy the command for your OS.</li>
        <li><strong>Run Agent</strong> - Execute the command on the target machine. It will auto-connect.</li>
        <li><strong>View Metrics</strong> - Click on any agent card to see real-time data.</li>
      </ol>
    `
  },
  {
    icon: '📊',
    title: 'Understanding Metrics',
    content: `
      <p><strong>CPU Usage:</strong> Percentage of processor time in use. Per-core breakdown available.</p>
      <p><strong>Memory:</strong> RAM utilization. High sustained usage may indicate memory leaks.</p>
      <p><strong>Network I/O:</strong> Bytes per second sent/received. Useful for bandwidth monitoring.</p>
      <p><strong>Disk Usage:</strong> Storage utilization per mount point. Alerts when low.</p>
      <p><strong>Temperature:</strong> CPU/GPU thermal data (when available). Watch for thermal throttling.</p>
    `
  },
  {
    icon: '🔔',
    title: 'Setting Up Alerts',
    content: `
      <ol>
        <li>Click on an agent card to open details.</li>
        <li>Navigate to the <strong>Alerts</strong> tab.</li>
        <li>Toggle on the metrics you want to monitor (CPU, RAM, Disk).</li>
        <li>Adjust the threshold slider to your desired trigger point.</li>
        <li>Alerts will appear as badges on the agent card when triggered.</li>
      </ol>
      <p class="tip">💡 <strong>Tip:</strong> Set disk alerts to 10-15% free to catch issues early.</p>
    `
  },
  {
    icon: '🛠️',
    title: 'Agent Configuration',
    content: `
      <p>Each agent can be configured remotely from the <strong>Config</strong> tab:</p>
      <ul>
        <li><strong>Logging Enabled:</strong> Toggle log collection on/off.</li>
        <li><strong>Log Level:</strong> Filter by severity (ERROR, WARN, INFO).</li>
        <li><strong>Log Sources:</strong> Choose System, Security, or Docker logs.</li>
        <li><strong>Retention Override:</strong> Keep this agent's logs longer than the default.</li>
        <li><strong>Troubleshooting Mode:</strong> Temporarily capture all logs regardless of level.</li>
      </ul>
      <p>Changes are pushed to the agent in real-time via WebSocket.</p>
    `
  },
  {
    icon: '🗄️',
    title: 'Managing Storage',
    content: `
      <p>LogLibrarian automatically manages storage via the <strong>Janitor</strong> service:</p>
      <ul>
        <li><strong>Max Database Size:</strong> Oldest data deleted when exceeded.</li>
        <li><strong>Retention Periods:</strong> Data older than threshold is automatically purged.</li>
        <li><strong>Panic Switch:</strong> Blocks new data if disk space critically low.</li>
      </ul>
      <p>Configure in <strong>Settings → Storage</strong>. Use the calculator to estimate usage.</p>
    `
  },
  {
    icon: '🤖',
    title: 'Using the AI Librarian',
    content: `
      <p>The Librarian uses AI to answer questions about your infrastructure:</p>
      <ul>
        <li>"What errors occurred in the last hour?"</li>
        <li>"Show me high CPU events on server-01"</li>
        <li>"Are there any security warnings?"</li>
      </ul>
      <p>It searches your logs semantically, not just by keywords. This means it understands context and synonyms.</p>
      <p class="tip">💡 <strong>Tip:</strong> Be specific with time ranges for better results.</p>
    `
  },
]

const features = [
  {
    icon: '📡',
    title: 'Real-Time Monitoring',
    features: [
      { name: 'Live Metrics', description: 'CPU, RAM, Disk, Network updated every second when viewing.' },
      { name: 'WebSocket Streaming', description: 'Instant data push - no polling delays.' },
      { name: 'Process Monitoring', description: 'See running processes sorted by resource usage.' },
      { name: 'Multi-Agent View', description: 'Monitor all your machines from one dashboard.' },
    ]
  },
  {
    icon: '📋',
    title: 'Log Management',
    features: [
      { name: 'Centralized Collection', description: 'System, security, and application logs in one place.' },
      { name: 'Smart Filtering', description: 'Filter by severity, source, time range, or free text.' },
      { name: 'Docker Support', description: 'Automatically collect logs from Docker containers.' },
      { name: 'Retention Policies', description: 'Auto-cleanup with configurable retention periods.' },
    ]
  },
  {
    icon: '🔔',
    title: 'Alerting',
    features: [
      { name: 'Threshold Alerts', description: 'Get notified when CPU, RAM, or Disk crosses limits.' },
      { name: 'Per-Agent Rules', description: 'Different thresholds for different machines.' },
      { name: 'Alert History', description: 'Review past alerts with timestamps and values.' },
      { name: 'Visual Indicators', description: 'Badge counts on agent cards show active alerts.' },
    ]
  },
  {
    icon: '🤖',
    title: 'AI-Powered Search',
    features: [
      { name: 'Natural Language Queries', description: 'Ask questions in plain English.' },
      { name: 'Semantic Search', description: 'Find logs by meaning, not just keywords.' },
      { name: 'Vector Embeddings', description: 'Powered by sentence-transformers and Qdrant.' },
      { name: 'Context-Aware', description: 'Understands infrastructure terminology.' },
    ]
  },
  {
    icon: '⚙️',
    title: 'Administration',
    features: [
      { name: 'Remote Configuration', description: 'Push settings to agents without SSH access.' },
      { name: 'Agent Management', description: 'Enable, disable, rename, or delete agents.' },
      { name: 'Storage Calculator', description: 'Estimate database size based on retention settings.' },
      { name: 'Manual Cleanup', description: 'Trigger Janitor cleanup on demand.' },
    ]
  },
]

const toggleGuide = (title) => {
  expandedGuide.value = expandedGuide.value === title ? null : title
}

const filteredGuides = computed(() => {
  if (!searchQuery.value) return guides
  const q = searchQuery.value.toLowerCase()
  return guides.filter(g => 
    g.title.toLowerCase().includes(q) || 
    g.content.toLowerCase().includes(q)
  )
})

const filteredFeatures = computed(() => {
  if (!searchQuery.value) return features
  const q = searchQuery.value.toLowerCase()
  return features.filter(section => 
    section.title.toLowerCase().includes(q) ||
    section.features.some(f => 
      f.name.toLowerCase().includes(q) || 
      f.description.toLowerCase().includes(q)
    )
  )
})
</script>

<style scoped>
.help-widget {
  position: fixed;
  bottom: 80px;
  right: 20px;
  z-index: 1000;
}

.help-toggle {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: linear-gradient(135deg, #5865f2, #4752c4);
  border: none;
  color: white;
  font-size: 1.25rem;
  cursor: pointer;
  box-shadow: 0 4px 12px rgba(88, 101, 242, 0.4);
  transition: all 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
}

.help-toggle:hover {
  transform: scale(1.1);
  box-shadow: 0 6px 20px rgba(88, 101, 242, 0.5);
}

.help-widget.expanded .help-toggle {
  position: absolute;
  top: -16px;
  right: -16px;
  width: 36px;
  height: 36px;
  font-size: 1rem;
  background: #404040;
  box-shadow: 0 2px 8px rgba(0,0,0,0.3);
}

.help-panel {
  width: 480px;
  max-height: 600px;
  background: #1a1a1a;
  border: 1px solid #404040;
  border-radius: 12px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.4);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* Header */
.help-header {
  padding: 1rem 1.25rem;
  background: #252525;
  border-bottom: 1px solid #404040;
}

.help-title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 1.1rem;
  font-weight: 600;
  color: #fff;
  margin-bottom: 0.75rem;
}

.help-title i {
  color: #5865f2;
}

.search-input {
  width: 100%;
  padding: 0.5rem 0.75rem;
  background: #1a1a1a;
  border: 1px solid #404040;
  border-radius: 6px;
  color: #fff;
  font-size: 0.875rem;
}

.search-input:focus {
  outline: none;
  border-color: #5865f2;
}

.search-input::placeholder {
  color: #666;
}

/* Tabs */
.help-tabs {
  display: flex;
  background: #252525;
  border-bottom: 1px solid #404040;
  padding: 0 0.5rem;
}

.help-tab {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 0.75rem 0.5rem;
  background: none;
  border: none;
  color: #888;
  font-size: 0.85rem;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  transition: all 0.2s;
}

.help-tab:hover {
  color: #fff;
  background: rgba(255,255,255,0.05);
}

.help-tab.active {
  color: #5865f2;
  border-bottom-color: #5865f2;
}

.tab-icon {
  font-size: 1rem;
}

/* Content */
.help-content {
  flex: 1;
  overflow-y: auto;
  padding: 1rem;
}

.tab-content {
  animation: fadeIn 0.2s ease;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

/* Guides */
.guide-item {
  background: #252525;
  border: 1px solid #333;
  border-radius: 8px;
  margin-bottom: 0.5rem;
  overflow: hidden;
}

.guide-header {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.875rem 1rem;
  background: none;
  border: none;
  color: #fff;
  font-size: 0.9rem;
  cursor: pointer;
  text-align: left;
  transition: background 0.2s;
}

.guide-header:hover {
  background: rgba(255,255,255,0.05);
}

.guide-icon {
  font-size: 1.1rem;
}

.guide-title {
  flex: 1;
  font-weight: 500;
}

.guide-chevron {
  color: #666;
  font-size: 0.75rem;
}

.guide-content {
  padding: 0 1rem 1rem;
  color: #ccc;
  font-size: 0.85rem;
  line-height: 1.6;
  border-top: 1px solid #333;
}

.guide-content :deep(ol),
.guide-content :deep(ul) {
  margin: 0.5rem 0;
  padding-left: 1.5rem;
}

.guide-content :deep(li) {
  margin: 0.5rem 0;
}

.guide-content :deep(code) {
  background: #333;
  padding: 0.15rem 0.4rem;
  border-radius: 4px;
  font-size: 0.8rem;
  color: #58a6ff;
}

.guide-content :deep(.tip) {
  background: rgba(88, 101, 242, 0.1);
  border-left: 3px solid #5865f2;
  padding: 0.5rem 0.75rem;
  margin-top: 0.75rem;
  border-radius: 0 4px 4px 0;
}

/* Features */
.feature-section {
  margin-bottom: 1.5rem;
}

.section-title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 1rem;
  font-weight: 600;
  color: #fff;
  margin-bottom: 0.75rem;
  padding-bottom: 0.5rem;
  border-bottom: 1px solid #333;
}

.section-icon {
  font-size: 1.1rem;
}

.feature-list {
  list-style: none;
  padding: 0;
  margin: 0;
}

.feature-item {
  padding: 0.5rem 0;
  border-bottom: 1px solid #2a2a2a;
}

.feature-item:last-child {
  border-bottom: none;
}

.feature-item strong {
  color: #fff;
  font-size: 0.875rem;
}

.feature-item p {
  margin: 0.25rem 0 0;
  color: #999;
  font-size: 0.8rem;
}

/* Internals */
.internals-tab {
  padding: 0 !important;
}

.internals-section {
  padding: 1rem;
}

.internals-title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 1rem;
  font-weight: 600;
  color: #fff;
  margin: 0 0 0.5rem;
}

.title-icon {
  font-size: 1.1rem;
}

.internals-intro {
  color: #999;
  font-size: 0.85rem;
  margin-bottom: 1rem;
}

/* OS Comparison */
.comparison-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.75rem;
  margin-bottom: 1.5rem;
}

.os-card {
  background: #252525;
  border: 1px solid #333;
  border-radius: 8px;
  overflow: hidden;
}

.os-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem;
  background: #2a2a2a;
  border-bottom: 1px solid #333;
}

.os-card.windows .os-header {
  background: linear-gradient(135deg, rgba(0, 120, 215, 0.2), rgba(0, 120, 215, 0.05));
}

.os-card.linux .os-header {
  background: linear-gradient(135deg, rgba(255, 165, 0, 0.2), rgba(255, 165, 0, 0.05));
}

.os-icon {
  font-size: 1.25rem;
}

.os-header h5 {
  flex: 1;
  margin: 0;
  font-size: 0.9rem;
  color: #fff;
}

.os-badge {
  font-size: 0.65rem;
  padding: 0.2rem 0.5rem;
  background: #404040;
  border-radius: 4px;
  color: #ccc;
}

.os-content {
  padding: 0.75rem;
}

.metric-group {
  margin-bottom: 0.75rem;
}

.metric-group:last-child {
  margin-bottom: 0;
}

.metric-group h6 {
  font-size: 0.75rem;
  font-weight: 600;
  color: #5865f2;
  margin: 0 0 0.25rem;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.metric-group p {
  font-size: 0.75rem;
  color: #aaa;
  margin: 0;
  line-height: 1.4;
}

.metric-group code {
  background: #333;
  padding: 0.1rem 0.3rem;
  border-radius: 3px;
  font-size: 0.7rem;
  color: #58a6ff;
}

.note {
  margin-top: 0.5rem;
  padding: 0.4rem 0.6rem;
  border-radius: 4px;
  font-size: 0.7rem;
}

.note.warning {
  background: rgba(234, 179, 8, 0.15);
  border-left: 2px solid #eab308;
  color: #eab308;
}

.note.success {
  background: rgba(34, 197, 94, 0.15);
  border-left: 2px solid #22c55e;
  color: #22c55e;
}

/* Architecture Diagram */
.architecture-section {
  background: #252525;
  border: 1px solid #333;
  border-radius: 8px;
  padding: 1rem;
  margin-bottom: 1rem;
}

.architecture-diagram {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  margin-top: 1rem;
}

.arch-layer {
  width: 100%;
  display: flex;
  justify-content: center;
  gap: 0.75rem;
}

.arch-layer.split {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.75rem;
}

.arch-box {
  padding: 0.6rem 1rem;
  background: #333;
  border: 1px solid #444;
  border-radius: 6px;
  text-align: center;
}

.arch-box strong {
  display: block;
  font-size: 0.8rem;
  color: #fff;
}

.arch-box span {
  display: block;
  font-size: 0.7rem;
  color: #888;
}

.arch-box em {
  display: block;
  font-size: 0.65rem;
  color: #5865f2;
  margin-top: 0.25rem;
}

.arch-box.agent {
  background: linear-gradient(135deg, #5865f2, #4752c4);
  border-color: #5865f2;
}

.arch-box.fast {
  border-color: #22c55e;
}

.arch-box.slow {
  border-color: #eab308;
}

.arch-box.buffer {
  border-color: #06b6d4;
}

.arch-box.server {
  background: linear-gradient(135deg, #5865f2, #4752c4);
  border-color: #5865f2;
}

.arch-arrow {
  color: #666;
  font-size: 0.8rem;
}

/* Timing Table */
.timing-section {
  background: #252525;
  border: 1px solid #333;
  border-radius: 8px;
  padding: 1rem;
}

.timing-table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 0.75rem;
  font-size: 0.8rem;
}

.timing-table th,
.timing-table td {
  padding: 0.5rem;
  text-align: left;
  border-bottom: 1px solid #333;
}

.timing-table th {
  color: #888;
  font-weight: 500;
  font-size: 0.75rem;
  text-transform: uppercase;
}

.timing-table td {
  color: #ccc;
}

.mode-badge {
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  font-size: 0.7rem;
  font-weight: 600;
}

.mode-badge.active {
  background: rgba(34, 197, 94, 0.2);
  color: #22c55e;
}

.mode-badge.idle {
  background: rgba(156, 163, 175, 0.2);
  color: #9ca3af;
}

/* Footer */
.help-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1rem;
  background: #252525;
  border-top: 1px solid #404040;
  font-size: 0.75rem;
}

.version {
  color: #666;
}

.footer-link {
  color: #888;
  text-decoration: none;
  display: flex;
  align-items: center;
  gap: 0.25rem;
}

.footer-link:hover {
  color: #5865f2;
}

.no-results {
  text-align: center;
  color: #666;
  padding: 2rem;
}

/* Transitions */
.slide-enter-active,
.slide-leave-active {
  transition: all 0.25s ease;
}

.slide-enter-from,
.slide-leave-to {
  opacity: 0;
  transform: translateY(20px) scale(0.95);
}

.expand-enter-active,
.expand-leave-active {
  transition: all 0.2s ease;
}

.expand-enter-from,
.expand-leave-to {
  opacity: 0;
  max-height: 0;
}

/* Scrollbar */
.help-content::-webkit-scrollbar {
  width: 6px;
}

.help-content::-webkit-scrollbar-track {
  background: transparent;
}

.help-content::-webkit-scrollbar-thumb {
  background: #404040;
  border-radius: 3px;
}

.help-content::-webkit-scrollbar-thumb:hover {
  background: #555;
}

/* Responsive */
@media (max-width: 540px) {
  .help-panel {
    width: calc(100vw - 40px);
    max-height: calc(100vh - 160px);
  }
  
  .comparison-grid {
    grid-template-columns: 1fr;
  }
}
</style>
