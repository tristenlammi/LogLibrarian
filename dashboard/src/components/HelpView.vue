<template>
  <div class="help-view">
    <!-- Header -->
    <div class="help-header">
      <div class="header-title">
        <span class="header-icon">📖</span>
        <h1>Help & Documentation</h1>
      </div>
      <div class="header-search">
        <i class="bi bi-search"></i>
        <input 
          type="text" 
          v-model="searchQuery" 
          placeholder="Search documentation..."
        >
      </div>
    </div>

    <!-- Tab Navigation -->
    <div class="help-tabs">
      <button 
        v-for="tab in tabs" 
        :key="tab.id"
        class="tab-btn"
        :class="{ active: activeTab === tab.id }"
        @click="activeTab = tab.id"
      >
        <span class="tab-icon">{{ tab.icon }}</span>
        {{ tab.label }}
      </button>
    </div>

    <!-- Guides Tab -->
    <div v-if="activeTab === 'guides'" class="tab-content">
      <div class="guides-grid">
        <div 
          v-for="guide in filteredGuides" 
          :key="guide.title"
          class="guide-card"
          :class="{ expanded: expandedGuide === guide.title }"
        >
          <button class="guide-header" @click="toggleGuide(guide.title)">
            <span class="guide-icon">{{ guide.icon }}</span>
            <span class="guide-title">{{ guide.title }}</span>
            <span class="guide-chevron">
              <i :class="expandedGuide === guide.title ? 'bi bi-chevron-up' : 'bi bi-chevron-down'"></i>
            </span>
          </button>
          <transition name="expand">
            <div v-if="expandedGuide === guide.title" class="guide-content">
              <div v-html="guide.content"></div>
            </div>
          </transition>
        </div>
      </div>
      <div v-if="filteredGuides.length === 0" class="empty-state">
        <span class="empty-icon">🔍</span>
        <p>No guides match "{{ searchQuery }}"</p>
      </div>
    </div>

    <!-- Features Tab -->
    <div v-if="activeTab === 'features'" class="tab-content">
      <div class="features-grid">
        <div 
          v-for="section in filteredFeatures" 
          :key="section.title"
          class="feature-section"
        >
          <h3 class="section-title">
            <span class="section-icon">{{ section.icon }}</span>
            {{ section.title }}
          </h3>
          <ul class="feature-list">
            <li v-for="feature in section.features" :key="feature.name">
              <strong>{{ feature.name }}</strong>
              <p>{{ feature.description }}</p>
            </li>
          </ul>
        </div>
      </div>
      <div v-if="filteredFeatures.length === 0" class="empty-state">
        <span class="empty-icon">🔍</span>
        <p>No features match "{{ searchQuery }}"</p>
      </div>
    </div>

    <!-- FAQ Tab -->
    <div v-if="activeTab === 'faq'" class="tab-content">
      <div class="faq-list">
        <div 
          v-for="(faq, index) in filteredFAQs" 
          :key="index"
          class="faq-item"
          :class="{ expanded: expandedFAQ === index }"
        >
          <button class="faq-question" @click="toggleFAQ(index)">
            <span>{{ faq.question }}</span>
            <i :class="expandedFAQ === index ? 'bi bi-dash' : 'bi bi-plus'"></i>
          </button>
          <transition name="expand">
            <div v-if="expandedFAQ === index" class="faq-answer">
              <div v-html="faq.answer"></div>
            </div>
          </transition>
        </div>
      </div>
      <div v-if="filteredFAQs.length === 0" class="empty-state">
        <span class="empty-icon">🔍</span>
        <p>No FAQs match "{{ searchQuery }}"</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const searchQuery = ref('')
const activeTab = ref('guides')
const expandedGuide = ref(null)
const expandedFAQ = ref(null)

const tabs = [
  { id: 'guides', label: 'How-To Guides', icon: '📋' },
  { id: 'features', label: 'Features', icon: '✨' },
  { id: 'faq', label: 'FAQ', icon: '❓' }
]

const guides = [
  {
    icon: '🚀',
    title: 'Getting Started',
    content: `
      <h4>Quick Start Guide</h4>
      <ol>
        <li><strong>Install a Scribe Agent</strong> - Go to Settings > Install Agent and run the provided command on your server.</li>
        <li><strong>View Your Dashboard</strong> - Once connected, your server will appear on the Dashboard with live metrics.</li>
        <li><strong>Configure Alerts</strong> - Set up alert rules for CPU, RAM, or disk usage thresholds.</li>
        <li><strong>Enable the Librarian</strong> - Turn on AI features in Settings > AI to get daily briefings and smart tips.</li>
      </ol>
    `
  },
  {
    icon: '🖥️',
    title: 'Installing Scribe Agents',
    content: `
      <h4>Linux Installation</h4>
      <pre><code>curl -sSL http://your-server:8000/install-script | bash</code></pre>
      <p>The script will download, configure, and start the Scribe agent as a systemd service.</p>
      
      <h4>Windows Installation</h4>
      <pre><code>irm http://your-server:8000/install-script | iex</code></pre>
      <p>Run this in PowerShell as Administrator. The agent will be installed as a Windows service.</p>
    `
  },
  {
    icon: '🔔',
    title: 'Setting Up Alerts',
    content: `
      <h4>Alert Configuration</h4>
      <ol>
        <li>Click on a server in the Dashboard or Scribes view</li>
        <li>Navigate to the Alerts tab</li>
        <li>Configure thresholds for CPU, RAM, Disk, and Temperature</li>
        <li>Alerts will appear in the Librarian when thresholds are exceeded</li>
      </ol>
      <p><strong>Tip:</strong> Start with higher thresholds (80-90%) and adjust based on your needs.</p>
    `
  },
  {
    icon: '🤖',
    title: 'Using the AI Librarian',
    content: `
      <h4>AI Features</h4>
      <ul>
        <li><strong>Daily Briefings</strong> - Automatic summary of your infrastructure health</li>
        <li><strong>Smart Tips</strong> - Optimization suggestions based on metrics</li>
        <li><strong>Chat</strong> - Ask questions about your servers</li>
      </ul>
      <p>Enable AI in Settings > AI Configuration. You can use local models (no API key needed) or OpenAI.</p>
    `
  },
  {
    icon: '📝',
    title: 'Log Collection',
    content: `
      <h4>Configuring Log Sources</h4>
      <p>Each Scribe agent can collect logs from multiple sources:</p>
      <ul>
        <li><strong>System logs</strong> - journalctl (Linux) or Event Viewer (Windows)</li>
        <li><strong>Application logs</strong> - Configure custom log file paths</li>
        <li><strong>Docker logs</strong> - Automatic container log collection</li>
      </ul>
      <p>Configure log sources in the agent's config.json or through the web interface.</p>
    `
  }
]

const features = [
  {
    icon: '📊',
    title: 'Dashboard',
    features: [
      { name: 'Real-time Metrics', description: 'Live CPU, RAM, Disk, and Network stats updated every 5 seconds' },
      { name: 'Server Overview', description: 'At-a-glance view of all your servers and their health status' },
      { name: 'Quick Actions', description: 'One-click access to server details, alerts, and logs' }
    ]
  },
  {
    icon: '🖥️',
    title: 'Scribe Agents',
    features: [
      { name: 'Cross-Platform', description: 'Agents run on Linux (x64, ARM) and Windows' },
      { name: 'Low Overhead', description: 'Minimal resource usage with efficient data collection' },
      { name: 'Auto-Reconnect', description: 'Automatic reconnection with exponential backoff' }
    ]
  },
  {
    icon: '🤖',
    title: 'AI Librarian',
    features: [
      { name: 'Local AI', description: 'Run AI models locally without sending data to external services' },
      { name: 'Chat Interface', description: 'Ask questions about your infrastructure in natural language' },
      { name: 'Smart Insights', description: 'Automated tips and briefings based on your metrics' }
    ]
  }
]

const faqs = [
  {
    question: 'How do I install an agent on a remote server?',
    answer: `<p>Go to <strong>Settings > Install Agent</strong> and copy the installation command. SSH into your server and run the command. The agent will automatically connect to LogLibrarian.</p>`
  },
  {
    question: 'What ports does LogLibrarian use?',
    answer: `<p>By default:</p>
      <ul>
        <li><strong>8000</strong> - Backend API and WebSocket connections</li>
        <li><strong>5173</strong> - Dashboard (dev mode)</li>
        <li><strong>6333</strong> - Qdrant vector database</li>
      </ul>`
  },
  {
    question: 'Can I use LogLibrarian without AI?',
    answer: `<p>Yes! AI features are optional. You can use LogLibrarian purely for metrics collection, log viewing, and alerting without enabling any AI features.</p>`
  },
  {
    question: 'How do I update the Scribe agent?',
    answer: `<p>Re-run the install command on your server. It will download the latest version and restart the service automatically.</p>`
  },
  {
    question: 'Why is my agent showing as offline?',
    answer: `<p>Check that:</p>
      <ul>
        <li>The agent service is running (<code>systemctl status scribe</code> on Linux)</li>
        <li>The server can reach the LogLibrarian backend on port 8000</li>
        <li>No firewall is blocking the WebSocket connection</li>
      </ul>`
  },
  {
    question: 'How do I change the data retention period?',
    answer: `<p>Go to <strong>Settings > System</strong> and configure the retention period for metrics and logs. Default is 90 days.</p>`
  }
]

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
  return features.filter(f => 
    f.title.toLowerCase().includes(q) ||
    f.features.some(feat => 
      feat.name.toLowerCase().includes(q) || 
      feat.description.toLowerCase().includes(q)
    )
  )
})

const filteredFAQs = computed(() => {
  if (!searchQuery.value) return faqs
  const q = searchQuery.value.toLowerCase()
  return faqs.filter(f => 
    f.question.toLowerCase().includes(q) || 
    f.answer.toLowerCase().includes(q)
  )
})

function toggleGuide(title) {
  expandedGuide.value = expandedGuide.value === title ? null : title
}

function toggleFAQ(index) {
  expandedFAQ.value = expandedFAQ.value === index ? null : index
}
</script>

<style scoped>
.help-view {
  max-width: 1000px;
}

.help-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1.5rem;
  flex-wrap: wrap;
  gap: 1rem;
}

.header-title {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.header-title .header-icon {
  font-size: 2rem;
}

.header-title h1 {
  margin: 0;
  font-size: 1.5rem;
}

.header-search {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.625rem 1rem;
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: var(--radius);
  width: 280px;
}

.header-search i {
  color: var(--text-secondary);
}

.header-search input {
  flex: 1;
  background: none;
  border: none;
  color: var(--text-primary);
  font-size: 0.9rem;
  outline: none;
}

.header-search input::placeholder {
  color: var(--text-secondary);
}

/* Tabs */
.help-tabs {
  display: flex;
  gap: 0.25rem;
  padding: 0.25rem;
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: var(--radius);
  margin-bottom: 1.5rem;
}

.tab-btn {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem 1.25rem;
  background: transparent;
  border: none;
  border-radius: calc(var(--radius) - 2px);
  color: var(--text-secondary);
  font-size: 0.9rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
}

.tab-btn:hover {
  color: var(--text-primary);
  background: rgba(255, 255, 255, 0.05);
}

.tab-btn.active {
  background: var(--primary);
  color: #000;
}

.tab-icon {
  font-size: 1.1rem;
}

/* Tab Content */
.tab-content {
  animation: fadeIn 0.2s ease;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

/* Guides */
.guides-grid {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.guide-card {
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: var(--radius);
  overflow: hidden;
}

.guide-header {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 1rem 1.25rem;
  width: 100%;
  background: none;
  border: none;
  color: var(--text-primary);
  font-size: 1rem;
  font-weight: 500;
  cursor: pointer;
  text-align: left;
  transition: background 0.15s ease;
}

.guide-header:hover {
  background: rgba(255, 255, 255, 0.03);
}

.guide-icon {
  font-size: 1.25rem;
}

.guide-title {
  flex: 1;
}

.guide-chevron {
  color: var(--text-secondary);
}

.guide-content {
  padding: 0 1.25rem 1.25rem;
  border-top: 1px solid var(--border-color);
  color: var(--text-secondary);
  line-height: 1.6;
}

.guide-content h4 {
  color: var(--text-primary);
  margin: 1rem 0 0.75rem;
}

.guide-content h4:first-child {
  margin-top: 1rem;
}

.guide-content ol,
.guide-content ul {
  margin: 0.5rem 0;
  padding-left: 1.25rem;
}

.guide-content li {
  margin: 0.5rem 0;
}

.guide-content pre {
  background: var(--bg-color);
  padding: 0.75rem 1rem;
  border-radius: var(--radius);
  overflow-x: auto;
  margin: 0.75rem 0;
}

.guide-content code {
  font-family: 'Courier New', monospace;
  font-size: 0.875rem;
}

/* Features */
.features-grid {
  display: grid;
  gap: 1.5rem;
}

.feature-section {
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: var(--radius);
  padding: 1.25rem;
}

.section-title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0 0 1rem;
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--text-primary);
}

.section-icon {
  font-size: 1.25rem;
}

.feature-list {
  list-style: none;
  padding: 0;
  margin: 0;
}

.feature-list li {
  padding: 0.75rem 0;
  border-bottom: 1px solid var(--border-color);
}

.feature-list li:last-child {
  border-bottom: none;
  padding-bottom: 0;
}

.feature-list strong {
  display: block;
  color: var(--text-primary);
  margin-bottom: 0.25rem;
}

.feature-list p {
  margin: 0;
  color: var(--text-secondary);
  font-size: 0.9rem;
}

/* FAQ */
.faq-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.faq-item {
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: var(--radius);
  overflow: hidden;
}

.faq-question {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 1rem 1.25rem;
  width: 100%;
  background: none;
  border: none;
  color: var(--text-primary);
  font-size: 0.95rem;
  font-weight: 500;
  cursor: pointer;
  text-align: left;
  transition: background 0.15s ease;
}

.faq-question:hover {
  background: rgba(255, 255, 255, 0.03);
}

.faq-question i {
  color: var(--primary);
  font-size: 1.1rem;
}

.faq-answer {
  padding: 0 1.25rem 1.25rem;
  border-top: 1px solid var(--border-color);
  color: var(--text-secondary);
  line-height: 1.6;
}

.faq-answer p {
  margin: 1rem 0 0;
}

.faq-answer ul {
  margin: 0.5rem 0;
  padding-left: 1.25rem;
}

.faq-answer li {
  margin: 0.5rem 0;
}

.faq-answer code {
  background: var(--bg-color);
  padding: 0.125rem 0.375rem;
  border-radius: 3px;
  font-family: 'Courier New', monospace;
  font-size: 0.875rem;
}

/* Empty State */
.empty-state {
  text-align: center;
  padding: 3rem 1rem;
  color: var(--text-secondary);
}

.empty-state .empty-icon {
  font-size: 2.5rem;
  display: block;
  margin-bottom: 0.75rem;
}

/* Transitions */
.expand-enter-active,
.expand-leave-active {
  transition: all 0.2s ease;
  overflow: hidden;
}

.expand-enter-from,
.expand-leave-to {
  opacity: 0;
  max-height: 0;
}

.expand-enter-to,
.expand-leave-from {
  opacity: 1;
  max-height: 1000px;
}
</style>
