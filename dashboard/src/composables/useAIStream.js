/**
 * useAIStream - Vue 3 Composable for AI Streaming via Server-Sent Events
 * 
 * Provides real-time streaming of AI responses with typing effect for
 * the "Analyze This" feature in the logs view.
 * 
 * Usage:
 *   const { streamingText, isStreaming, error, startStream, cancelStream } = useAIStream()
 *   
 *   // Start streaming
 *   await startStream({
 *     prompt: 'Analyze these logs',
 *     logs: ['log line 1', 'log line 2'],
 *     sanitize: true
 *   })
 */

import { ref, onUnmounted } from 'vue'

// Default AI HTTP server port (matches Go ai_http.go)
const DEFAULT_AI_PORT = 12380

export function useAIStream(options = {}) {
  // Configuration
  const baseUrl = options.baseUrl || `http://localhost:${DEFAULT_AI_PORT}`
  
  // Reactive state
  const streamingText = ref('')
  const isStreaming = ref(false)
  const isComplete = ref(false)
  const error = ref(null)
  const tokenCount = ref(0)
  const abortController = ref(null)
  
  // Event handlers
  const onChunk = options.onChunk || null
  const onComplete = options.onComplete || null
  const onError = options.onError || null

  /**
   * Start streaming an AI analysis request
   * @param {Object} request - The analysis request
   * @param {string} request.prompt - The analysis prompt
   * @param {string[]} [request.logs] - Optional log lines to include
   * @param {number} [request.max_tokens] - Max tokens to generate
   * @param {number} [request.temperature] - Temperature (0-2)
   * @param {boolean} [request.sanitize] - Apply PII redaction
   */
  async function startStream(request) {
    // Reset state
    streamingText.value = ''
    isStreaming.value = true
    isComplete.value = false
    error.value = null
    tokenCount.value = 0
    
    // Create abort controller for cancellation
    abortController.value = new AbortController()
    
    try {
      const response = await fetch(`${baseUrl}/api/ai/stream-analysis`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'text/event-stream',
        },
        body: JSON.stringify(request),
        signal: abortController.value.signal,
      })
      
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`)
      }
      
      // Check if we got an SSE response
      const contentType = response.headers.get('content-type')
      if (!contentType || !contentType.includes('text/event-stream')) {
        // Fallback to non-streaming response
        const data = await response.json()
        if (data.error) {
          throw new Error(data.error)
        }
        streamingText.value = data.content || ''
        isComplete.value = true
        isStreaming.value = false
        if (onComplete) onComplete(streamingText.value)
        return streamingText.value
      }
      
      // Process SSE stream
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      
      while (true) {
        const { done, value } = await reader.read()
        
        if (done) {
          break
        }
        
        buffer += decoder.decode(value, { stream: true })
        
        // Process complete events from buffer
        const lines = buffer.split('\n')
        buffer = lines.pop() || '' // Keep incomplete line in buffer
        
        for (const line of lines) {
          if (line.startsWith('event: ')) {
            // Event type line - we'll use this for routing
            continue
          }
          
          if (line.startsWith('data: ')) {
            const data = line.slice(6)
            
            // Handle [DONE] marker
            if (data === '[DONE]') {
              isComplete.value = true
              isStreaming.value = false
              if (onComplete) onComplete(streamingText.value)
              continue
            }
            
            try {
              const parsed = JSON.parse(data)
              
              // Handle different event types
              if (parsed.error) {
                error.value = parsed.error
                if (onError) onError(parsed.error)
                continue
              }
              
              if (parsed.content !== undefined) {
                // Chunk event - append content
                streamingText.value += parsed.content
                tokenCount.value = parsed.tokens || tokenCount.value + 1
                
                if (onChunk) onChunk(parsed.content, streamingText.value)
              }
              
              if (parsed.status === 'complete') {
                // Complete event
                isComplete.value = true
                tokenCount.value = parsed.total_tokens || tokenCount.value
              }
            } catch (e) {
              // Skip unparseable data
              console.warn('Failed to parse SSE data:', data)
            }
          }
        }
      }
      
      isStreaming.value = false
      return streamingText.value
      
    } catch (err) {
      if (err.name === 'AbortError') {
        // User cancelled - not an error
        isStreaming.value = false
        return streamingText.value
      }
      
      error.value = err.message
      isStreaming.value = false
      if (onError) onError(err.message)
      throw err
    }
  }
  
  /**
   * Cancel the current stream
   */
  function cancelStream() {
    if (abortController.value) {
      abortController.value.abort()
      abortController.value = null
    }
    isStreaming.value = false
  }
  
  /**
   * Reset all state
   */
  function reset() {
    cancelStream()
    streamingText.value = ''
    isComplete.value = false
    error.value = null
    tokenCount.value = 0
  }
  
  // Cleanup on unmount
  onUnmounted(() => {
    cancelStream()
  })
  
  return {
    // State
    streamingText,
    isStreaming,
    isComplete,
    error,
    tokenCount,
    
    // Methods
    startStream,
    cancelStream,
    reset,
  }
}

/**
 * useAIAnalysis - Higher-level composable for log analysis with streaming
 * 
 * Combines SSE streaming with log selection and analysis prompts.
 */
export function useAIAnalysis(options = {}) {
  const {
    streamingText,
    isStreaming,
    isComplete,
    error,
    tokenCount,
    startStream,
    cancelStream,
    reset,
  } = useAIStream(options)
  
  // Analysis-specific state
  const analysisType = ref('general')
  const selectedLogs = ref([])
  
  // Pre-built analysis prompts
  const analysisPrompts = {
    general: 'Analyze these logs and provide a summary of what\'s happening, any issues detected, and recommendations.',
    errors: 'Focus on errors and warnings in these logs. Identify root causes and suggest fixes.',
    performance: 'Analyze these logs for performance issues. Look for slow operations, timeouts, and bottlenecks.',
    security: 'Review these logs for security concerns. Look for suspicious activity, failed authentication, or potential vulnerabilities.',
    timeline: 'Create a timeline of events from these logs. Identify the sequence of actions and any anomalies.',
  }
  
  /**
   * Analyze selected logs with a specific analysis type
   * @param {string} type - Analysis type (general, errors, performance, security, timeline)
   * @param {string[]} logs - Log lines to analyze
   * @param {Object} [options] - Additional options
   */
  async function analyze(type, logs, opts = {}) {
    analysisType.value = type
    selectedLogs.value = logs
    
    const prompt = opts.customPrompt || analysisPrompts[type] || analysisPrompts.general
    
    return startStream({
      prompt,
      logs,
      sanitize: opts.sanitize !== false, // Default to true for safety
      max_tokens: opts.maxTokens || 1024,
      temperature: opts.temperature || 0.7,
    })
  }
  
  /**
   * Quick analysis with custom prompt
   */
  async function quickAnalyze(prompt, logs, opts = {}) {
    return analyze('custom', logs, { ...opts, customPrompt: prompt })
  }
  
  return {
    // State from base composable
    streamingText,
    isStreaming,
    isComplete,
    error,
    tokenCount,
    
    // Analysis-specific state
    analysisType,
    selectedLogs,
    analysisPrompts,
    
    // Methods
    analyze,
    quickAnalyze,
    cancelStream,
    reset,
  }
}

export default useAIStream
