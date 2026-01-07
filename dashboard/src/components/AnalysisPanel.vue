<template>
  <div class="analysis-panel" :class="{ expanded: isExpanded }">
    <!-- Header -->
    <div class="analysis-header" @click="toggleExpand">
      <div class="header-left">
        <span class="analysis-icon">🤖</span>
        <span class="analysis-title">AI Analysis</span>
        <span v-if="isStreaming" class="streaming-badge">
          <span class="streaming-dot"></span>
          Analyzing...
        </span>
      </div>
      <div class="header-right">
        <button 
          v-if="!isStreaming && selectedLogs.length > 0"
          class="btn btn-sm btn-primary analyze-btn"
          @click.stop="runAnalysis"
        >
          <i class="bi bi-lightning-charge"></i>
          Analyze {{ selectedLogs.length }} logs
        </button>
        <button 
          v-if="isStreaming"
          class="btn btn-sm btn-outline-danger"
          @click.stop="cancelStream"
        >
          <i class="bi bi-stop-fill"></i>
          Stop
        </button>
        <button class="btn btn-sm btn-link expand-btn">
          <i :class="isExpanded ? 'bi-chevron-down' : 'bi-chevron-up'"></i>
        </button>
      </div>
    </div>

    <!-- Analysis Type Selector -->
    <div v-if="isExpanded && !isStreaming && !streamingText" class="analysis-types">
      <button 
        v-for="(label, type) in analysisTypes" 
        :key="type"
        class="type-btn"
        :class="{ active: selectedType === type }"
        @click="selectedType = type"
      >
        {{ label }}
      </button>
    </div>

    <!-- Streaming Content -->
    <div v-if="isExpanded" class="analysis-content">
      <!-- Empty State -->
      <div v-if="!streamingText && !isStreaming && !error" class="empty-state">
        <span class="empty-icon">💡</span>
        <p>Select some logs and click "Analyze" to get AI-powered insights</p>
      </div>

      <!-- Error State -->
      <div v-if="error" class="error-state">
        <span class="error-icon">⚠️</span>
        <p>{{ error }}</p>
        <button class="btn btn-sm btn-outline-primary" @click="reset">
          Try Again
        </button>
      </div>

      <!-- Streaming Output with Typing Effect -->
      <div v-if="streamingText || isStreaming" class="streaming-output">
        <div class="output-text" v-html="renderedContent"></div>
        <span v-if="isStreaming" class="cursor-blink">|</span>
        
        <!-- Token Counter -->
        <div v-if="tokenCount > 0" class="token-counter">
          {{ tokenCount }} tokens
        </div>
      </div>

      <!-- Actions -->
      <div v-if="isComplete && streamingText" class="analysis-actions">
        <button class="btn btn-sm btn-outline-secondary" @click="copyToClipboard">
          <i class="bi bi-clipboard"></i> Copy
        </button>
        <button class="btn btn-sm btn-outline-secondary" @click="reset">
          <i class="bi bi-arrow-clockwise"></i> New Analysis
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useAIAnalysis } from '../composables/useAIStream'

const props = defineProps({
  selectedLogs: {
    type: Array,
    default: () => []
  },
  agentBaseUrl: {
    type: String,
    default: 'http://localhost:12380'
  }
})

const emit = defineEmits(['analysis-complete', 'analysis-error'])

// UI State
const isExpanded = ref(false)
const selectedType = ref('general')

// Analysis types
const analysisTypes = {
  general: '📊 General',
  errors: '🔴 Errors',
  performance: '⚡ Performance',
  security: '🔒 Security',
  timeline: '📅 Timeline'
}

// Use the AI analysis composable
const {
  streamingText,
  isStreaming,
  isComplete,
  error,
  tokenCount,
  analyze,
  cancelStream,
  reset: resetAnalysis
} = useAIAnalysis({
  baseUrl: props.agentBaseUrl,
  onComplete: (text) => {
    emit('analysis-complete', text)
  },
  onError: (err) => {
    emit('analysis-error', err)
  }
})

// Computed - render markdown-like content
const renderedContent = computed(() => {
  if (!streamingText.value) return ''
  
  // Simple markdown-like rendering
  let content = streamingText.value
    // Escape HTML
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    // Bold
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    // Italic
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    // Code
    .replace(/`(.+?)`/g, '<code>$1</code>')
    // Line breaks
    .replace(/\n/g, '<br>')
    // Bullet points
    .replace(/^- /gm, '• ')
  
  return content
})

// Toggle panel expansion
function toggleExpand() {
  isExpanded.value = !isExpanded.value
}

// Run analysis
async function runAnalysis() {
  if (props.selectedLogs.length === 0) return
  
  isExpanded.value = true
  
  try {
    await analyze(selectedType.value, props.selectedLogs, {
      sanitize: true
    })
  } catch (err) {
    console.error('Analysis failed:', err)
  }
}

// Reset state
function reset() {
  resetAnalysis()
}

// Copy to clipboard
async function copyToClipboard() {
  try {
    await navigator.clipboard.writeText(streamingText.value)
    // Could emit an event or show a toast here
  } catch (err) {
    console.error('Failed to copy:', err)
  }
}

// Watch for log selection changes
watch(() => props.selectedLogs, (newLogs) => {
  if (newLogs.length > 0 && !isExpanded.value) {
    // Optionally auto-expand when logs are selected
    // isExpanded.value = true
  }
})
</script>

<style scoped>
.analysis-panel {
  background: var(--card-bg, #1a1f2e);
  border: 1px solid var(--border-color, #2d3748);
  border-radius: 8px;
  margin-top: 1rem;
  overflow: hidden;
  transition: all 0.3s ease;
}

.analysis-panel.expanded {
  max-height: 600px;
}

.analysis-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.75rem 1rem;
  cursor: pointer;
  border-bottom: 1px solid var(--border-color, #2d3748);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.analysis-icon {
  font-size: 1.25rem;
}

.analysis-title {
  font-weight: 600;
  color: var(--text-primary, #e2e8f0);
}

.streaming-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  background: rgba(34, 197, 94, 0.15);
  color: #22c55e;
  padding: 0.2rem 0.6rem;
  border-radius: 12px;
  font-size: 0.75rem;
  font-weight: 500;
}

.streaming-dot {
  width: 6px;
  height: 6px;
  background: #22c55e;
  border-radius: 50%;
  animation: pulse 1s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(1.2); }
}

.header-right {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.analyze-btn {
  display: flex;
  align-items: center;
  gap: 0.35rem;
}

.expand-btn {
  color: var(--text-secondary, #94a3b8);
}

/* Analysis Types */
.analysis-types {
  display: flex;
  gap: 0.5rem;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--border-color, #2d3748);
  flex-wrap: wrap;
}

.type-btn {
  padding: 0.35rem 0.75rem;
  border: 1px solid var(--border-color, #2d3748);
  border-radius: 6px;
  background: transparent;
  color: var(--text-secondary, #94a3b8);
  font-size: 0.8rem;
  cursor: pointer;
  transition: all 0.2s;
}

.type-btn:hover {
  border-color: var(--primary, #58a6ff);
  color: var(--primary, #58a6ff);
}

.type-btn.active {
  background: var(--primary, #58a6ff);
  border-color: var(--primary, #58a6ff);
  color: white;
}

/* Content Area */
.analysis-content {
  padding: 1rem;
  max-height: 400px;
  overflow-y: auto;
}

.empty-state,
.error-state {
  text-align: center;
  padding: 2rem;
  color: var(--text-secondary, #94a3b8);
}

.empty-icon,
.error-icon {
  font-size: 2rem;
  display: block;
  margin-bottom: 0.5rem;
}

.error-state {
  color: #ef4444;
}

/* Streaming Output */
.streaming-output {
  position: relative;
  background: rgba(0, 0, 0, 0.2);
  border-radius: 6px;
  padding: 1rem;
  font-family: system-ui, -apple-system, sans-serif;
  font-size: 0.9rem;
  line-height: 1.6;
  color: var(--text-primary, #e2e8f0);
}

.output-text {
  white-space: pre-wrap;
  word-break: break-word;
}

.output-text code {
  background: rgba(88, 166, 255, 0.15);
  padding: 0.1rem 0.3rem;
  border-radius: 3px;
  font-family: monospace;
  font-size: 0.85em;
}

.cursor-blink {
  display: inline-block;
  color: var(--primary, #58a6ff);
  animation: blink 1s step-end infinite;
  font-weight: bold;
}

@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

.token-counter {
  position: absolute;
  bottom: 0.5rem;
  right: 0.5rem;
  font-size: 0.7rem;
  color: var(--text-secondary, #94a3b8);
  opacity: 0.7;
}

/* Actions */
.analysis-actions {
  display: flex;
  gap: 0.5rem;
  margin-top: 1rem;
  padding-top: 1rem;
  border-top: 1px solid var(--border-color, #2d3748);
}

/* Scrollbar */
.analysis-content::-webkit-scrollbar {
  width: 6px;
}

.analysis-content::-webkit-scrollbar-track {
  background: rgba(255, 255, 255, 0.05);
}

.analysis-content::-webkit-scrollbar-thumb {
  background: var(--primary, #58a6ff);
  border-radius: 3px;
}
</style>
