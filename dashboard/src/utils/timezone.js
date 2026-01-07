/**
 * Timezone utility for formatting dates consistently across the app
 */

export function getTimezone() {
  const saved = localStorage.getItem('loglibrarian_timezone')
  if (!saved || saved === 'local') {
    return Intl.DateTimeFormat().resolvedOptions().timeZone
  }
  return saved
}

/**
 * Parse a date string, treating timestamps without timezone as UTC
 */
function parseDate(dateStr) {
  if (!dateStr) return null
  
  // If it already has timezone info (Z or +/-), parse directly
  if (dateStr.includes('Z') || /[+-]\d{2}:\d{2}$/.test(dateStr)) {
    return new Date(dateStr)
  }
  
  // Assume UTC for timestamps without timezone indicator
  // This handles ISO format timestamps stored without the Z suffix
  return new Date(dateStr + 'Z')
}

export function formatDateTime(dateStr, options = {}) {
  if (!dateStr) return ''
  const date = parseDate(dateStr)
  if (!date || isNaN(date)) return dateStr
  
  const tz = getTimezone()
  const defaultOptions = {
    timeZone: tz,
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    ...options
  }
  
  return date.toLocaleString('en-US', defaultOptions)
}

export function formatTime(dateStr, options = {}) {
  if (!dateStr) return ''
  const date = parseDate(dateStr)
  if (!date || isNaN(date)) return dateStr
  
  const tz = getTimezone()
  const defaultOptions = {
    timeZone: tz,
    hour: '2-digit',
    minute: '2-digit',
    ...options
  }
  
  return date.toLocaleTimeString('en-US', defaultOptions)
}

export function formatDate(dateStr, options = {}) {
  if (!dateStr) return ''
  const date = parseDate(dateStr)
  if (!date || isNaN(date)) return dateStr
  
  const tz = getTimezone()
  const defaultOptions = {
    timeZone: tz,
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    ...options
  }
  
  return date.toLocaleDateString('en-US', defaultOptions)
}

export function formatRelativeTime(dateStr) {
  if (!dateStr) return 'Never'
  const date = parseDate(dateStr)
  if (!date || isNaN(date)) return dateStr
  
  const now = new Date()
  const diffMs = now - date
  const diffSecs = Math.floor(diffMs / 1000)
  const diffMins = Math.floor(diffSecs / 60)
  const diffHours = Math.floor(diffMins / 60)
  const diffDays = Math.floor(diffHours / 24)
  
  if (diffSecs < 60) return 'Just now'
  if (diffMins < 60) return `${diffMins}m ago`
  if (diffHours < 24) return `${diffHours}h ago`
  if (diffDays < 7) return `${diffDays}d ago`
  
  return formatDate(dateStr)
}
