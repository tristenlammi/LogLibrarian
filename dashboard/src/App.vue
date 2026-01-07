<template>
  <!-- Backend Loading Screen -->
  <div v-if="!backendReady" class="startup-overlay">
    <div class="startup-content">
      <div class="startup-logo">
        <span class="logo-line">Log</span>
        <span class="logo-line">Librarian</span>
      </div>
      <div class="startup-spinner"></div>
      <div class="startup-status">{{ startupMessage }}</div>
      <div v-if="startupError" class="startup-error">
        <span>{{ startupError }}</span>
        <button @click="retryConnection" class="retry-btn">Retry</button>
      </div>
    </div>
  </div>

  <!-- Main App (only shown when backend is ready) -->
  <template v-else>
    <!-- Offline Indicator -->
    <div v-if="isOffline" class="offline-banner">
      <span>⚠️ Unable to connect to server. Retrying...</span>
    </div>

    <!-- Global Error Toast -->
    <transition name="toast">
      <div v-if="showError" class="error-toast" @click="dismissError">
        <span class="error-icon">{{ errorIcon }}</span>
        <span class="error-message">{{ lastError?.message }}</span>
        <button class="error-dismiss">×</button>
      </div>
    </transition>

    <!-- Login and Setup pages are fullscreen, no layout -->
    <router-view v-if="isFullscreenPage" />
    
    <!-- Normal app layout -->
    <div v-else class="main-container">
    <!-- Sidebar -->
    <aside class="sidebar">
      <div class="sidebar-content">
        <!-- Logo/Title -->
        <div class="logo-section">
          <div class="logo-text">
            <span class="logo-line">Log</span>
            <span class="logo-line">Librarian</span>
          </div>
        </div>

        <!-- Navigation -->
        <nav class="nav flex-column mt-4">
          <router-link 
            v-for="route in filteredRoutes" 
            :key="route.path"
            :to="route.path"
            class="nav-link"
            :class="{ active: isActiveRoute(route.path) }"
          >
            <span class="nav-text">{{ route.name }}</span>
          </router-link>
        </nav>

        <!-- System Status -->
        <div class="system-status">
          <div class="status-card">
            <small class="text-secondary d-block mb-2">System Status</small>
            <div class="d-flex align-items-center">
              <span class="status-indicator online"></span>
              <span>Operational</span>
            </div>
            <div class="status-details mt-2">
              <small class="text-secondary">
                <div>Backend: <span class="text-success">●</span> Online</div>
                <div>Qdrant: <span class="text-success">●</span> Online</div>
              </small>
            </div>
          </div>
        </div>

        <!-- User Info and Logout -->
        <div class="logout-section">
          <div class="user-info-display">
            <span class="user-name">{{ currentUsername }}</span>
            <span class="user-role-badge" :class="{ admin: userIsAdmin }">{{ userIsAdmin ? 'admin' : 'user' }}</span>
          </div>
          <button class="logout-btn" @click="handleLogout">
            <span>Logout</span>
          </button>
        </div>
      </div>
    </aside>

    <!-- Main Content -->
    <main class="main-content">
      <!-- Header -->
      <header class="content-header mb-4">
        <div>
          <h1>{{ currentPageTitle }}</h1>
          <p class="text-secondary mb-0">{{ currentPageDescription }}</p>
        </div>
      </header>

      <!-- Router View -->
      <div class="content-body">
        <router-view v-slot="{ Component }">
          <keep-alive>
            <component :is="Component" :key="getComponentKey(route)" />
          </keep-alive>
        </router-view>
      </div>
    </main>
  </div>
  </template>
</template>

<script setup>
import { computed, ref, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { logout, user, isAdmin } from './auth'
import { isOffline, lastError, clearError } from './api'
import axios from 'axios'

const route = useRoute()
const router = useRouter()

// Backend startup check
const backendReady = ref(false)
const startupMessage = ref('Connecting to server...')
const startupError = ref(null)
let startupCheckInterval = null

const checkBackendHealth = async () => {
  try {
    startupError.value = null
    startupMessage.value = 'Connecting to server...'
    
    const response = await axios.get('/api/health', { timeout: 5000 })
    
    if (response.status === 200) {
      startupMessage.value = 'Connected!'
      // Small delay so user sees the "Connected!" message
      setTimeout(() => {
        backendReady.value = true
      }, 300)
      
      // Stop polling
      if (startupCheckInterval) {
        clearInterval(startupCheckInterval)
        startupCheckInterval = null
      }
    }
  } catch (error) {
    if (error.code === 'ECONNABORTED' || error.message.includes('timeout')) {
      startupMessage.value = 'Server is starting up...'
    } else if (error.response?.status >= 500) {
      startupMessage.value = 'Server is initializing...'
    } else if (!error.response) {
      startupMessage.value = 'Waiting for server...'
    } else {
      // Other errors (4xx) - backend is up, just might need auth
      startupMessage.value = 'Connected!'
      setTimeout(() => {
        backendReady.value = true
      }, 300)
      
      if (startupCheckInterval) {
        clearInterval(startupCheckInterval)
        startupCheckInterval = null
      }
    }
  }
}

const retryConnection = () => {
  startupError.value = null
  checkBackendHealth()
}

// Start checking on mount
onMounted(() => {
  checkBackendHealth()
  // Poll every 2 seconds until ready
  startupCheckInterval = setInterval(() => {
    if (!backendReady.value) {
      checkBackendHealth()
    }
  }, 2000)
})

onUnmounted(() => {
  if (startupCheckInterval) {
    clearInterval(startupCheckInterval)
  }
})

// Error toast visibility
const showError = ref(false)
let errorTimeout = null

// Watch for new errors
watch(lastError, (newError) => {
  if (newError && newError.type !== 'auth') { // Don't show toast for auth errors (handled by redirect)
    showError.value = true
    // Auto-dismiss after 5 seconds
    if (errorTimeout) clearTimeout(errorTimeout)
    errorTimeout = setTimeout(() => {
      showError.value = false
      clearError()
    }, 5000)
  }
})

const errorIcon = computed(() => {
  if (!lastError.value) return '⚠️'
  switch (lastError.value.type) {
    case 'network': return '🔌'
    case 'server': return '🔥'
    case 'forbidden': return '🚫'
    default: return '⚠️'
  }
})

const dismissError = () => {
  showError.value = false
  clearError()
  if (errorTimeout) clearTimeout(errorTimeout)
}

// User info
const currentUsername = computed(() => user.value?.username || 'Unknown')
const userIsAdmin = computed(() => isAdmin.value)

// Logout handler
const handleLogout = async () => {
  await logout()
  router.push('/login')
}

// Check if on login or setup page (hide sidebar, show fullscreen)
const isFullscreenPage = computed(() => route.path === '/login' || route.path === '/setup')

onMounted(() => {
})

onUnmounted(() => {
})

// Get a stable key for keep-alive - group related routes together
const getComponentKey = (route) => {
  // Bookmarks settings is a different component, needs its own key
  if (route.path === '/bookmarks/settings') {
    return 'bookmarks-settings'
  }
  // Bookmarks routes all use the same component, use same key to prevent remount
  if (route.path.startsWith('/bookmarks')) {
    return 'bookmarks'
  }
  // Other routes use their path as key
  return route.path
}

const routes = computed(() => router.getRoutes().filter(r => r.meta?.title && !r.meta?.hideFromNav))

// Filter routes - hide admin-only pages from non-admin users
const filteredRoutes = computed(() => {
  return routes.value.filter(r => {
    // Hide any route marked adminOnly for non-admin users
    if (r.meta?.adminOnly && !userIsAdmin.value) {
      return false
    }
    return true
  })
})

const isActiveRoute = (path) => {
  // Handle bookmarks detail route
  if (path === '/bookmarks' && route.path.startsWith('/bookmarks')) {
    return true
  }
  return route.path === path
}

const currentPageTitle = computed(() => route.meta?.title || route.name || '')

const currentPageDescription = computed(() => {
  const descriptions = {
    Dashboard: 'Overview of your log infrastructure',
    Logs: 'Search and explore your logs',
    Scribes: 'Manage your log collection scribes',
    Settings: 'Configure LogLibrarian',
    Bookmarks: 'Monitor uptime for your services',
    BookmarkDetail: 'Monitor uptime for your services'
  }
  return descriptions[route.name] || ''
})
</script>

<style scoped>
.main-container {
  display: flex;
  min-height: 100vh;
}

.sidebar {
  width: var(--sidebar-width);
  background-color: var(--card-bg);
  border-right: 1px solid var(--border-color);
  position: fixed;
  height: 100vh;
  overflow-y: auto;
  z-index: 100;
}

.sidebar-content {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 1.5rem;
}

/* Logo Section */
.logo-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-bottom: 1.5rem;
  border-bottom: 1px solid var(--border-color);
}

.logo-text {
  display: flex;
  flex-direction: column;
  align-items: center;
  color: white;
  font-weight: 700;
  line-height: 1.1;
}

.logo-line {
  font-size: 1.75rem;
  letter-spacing: 0.02em;
}

/* Navigation */
.nav {
  flex: 1;
}

.nav-link {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  color: var(--text-secondary);
  padding: 0.875rem 1rem;
  border-radius: var(--radius);
  transition: all 0.2s ease;
  margin-bottom: 0.25rem;
  text-decoration: none;
  font-weight: 500;
}

.nav-icon {
  font-size: 1.25rem;
  width: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.nav-text {
  flex: 1;
}

.nav-link:hover {
  background-color: rgba(88, 166, 255, 0.15);
  color: var(--primary);
  transform: translateX(4px);
}

.nav-link.active {
  background-color: var(--primary);
  color: #000;
  font-weight: 600;
  box-shadow: 0 2px 8px rgba(88, 166, 255, 0.4);
}

.nav-link.active .nav-icon {
  transform: scale(1.1);
}

/* System Status */
.system-status {
  margin-top: auto;
  padding-top: 1.5rem;
  border-top: 1px solid var(--border-color);
}

.status-card {
  padding: 1rem;
  background-color: rgba(88, 166, 255, 0.05);
  border: 1px solid var(--border-color);
  border-radius: var(--radius);
}

.status-details {
  font-size: 0.8rem;
  line-height: 1.6;
}

/* Logout Section */
.logout-section {
  padding: 1rem;
  margin-top: auto;
  border-top: 1px solid var(--border-color);
}

.user-info-display {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  margin-bottom: 0.75rem;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 6px;
  font-size: 0.85rem;
}

.user-name {
  color: var(--text-primary);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.user-role-badge {
  font-size: 0.7rem;
  padding: 0.15rem 0.4rem;
  border-radius: 4px;
  background: rgba(156, 163, 175, 0.2);
  color: var(--text-secondary);
  text-transform: uppercase;
  font-weight: 600;
  letter-spacing: 0.5px;
}

.user-role-badge.admin {
  background: rgba(59, 130, 246, 0.2);
  color: #60a5fa;
}

.logout-btn {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  width: 100%;
  padding: 0.75rem 1rem;
  background: transparent;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  color: var(--text-secondary);
  font-size: 0.9rem;
  cursor: pointer;
  transition: all 0.2s ease;
}

.logout-btn:hover {
  background-color: rgba(255, 255, 255, 0.05);
  border-color: var(--text-secondary);
  color: var(--text-primary);
}

.logout-icon {
  font-size: 1rem;
}

/* Main Content */
.main-content {
  margin-left: var(--sidebar-width);
  flex: 1;
  min-height: 100vh;
  background-color: var(--bg-color);
}

.content-header {
  padding: 2rem 2rem 0;
  background-color: var(--bg-color);
  position: sticky;
  top: 0;
  z-index: 10;
}

.content-header h1 {
  font-size: 2rem;
  font-weight: 700;
  margin-bottom: 0.5rem;
  color: var(--text-primary);
}

.content-body {
  padding: 2rem;
}

/* Offline Banner */
.offline-banner {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  background: linear-gradient(90deg, #f59e0b, #d97706);
  color: #000;
  text-align: center;
  padding: 0.5rem 1rem;
  font-weight: 600;
  z-index: 9999;
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.8; }
}

/* Error Toast */
.error-toast {
  position: fixed;
  top: 1rem;
  right: 1rem;
  background: var(--card-bg);
  border: 1px solid var(--danger);
  border-left: 4px solid var(--danger);
  border-radius: var(--radius);
  padding: 1rem 1.5rem;
  display: flex;
  align-items: center;
  gap: 0.75rem;
  z-index: 9998;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
  cursor: pointer;
  max-width: 400px;
}

.error-icon {
  font-size: 1.25rem;
}

.error-message {
  flex: 1;
  color: var(--text-primary);
}

.error-dismiss {
  background: none;
  border: none;
  color: var(--text-secondary);
  font-size: 1.5rem;
  cursor: pointer;
  padding: 0;
  line-height: 1;
}

.error-dismiss:hover {
  color: var(--text-primary);
}

/* Toast Animation */
.toast-enter-active,
.toast-leave-active {
  transition: all 0.3s ease;
}

.toast-enter-from {
  opacity: 0;
  transform: translateX(100%);
}

.toast-leave-to {
  opacity: 0;
  transform: translateX(100%);
}

/* Page Transitions */
.page-enter-active,
.page-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.page-enter-from {
  opacity: 0;
  transform: translateY(10px);
}

.page-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}

/* Responsive */
@media (max-width: 768px) {
  .sidebar {
    width: 80px;
  }
  
  .main-content {
    margin-left: 80px;
  }
  
  .logo-text,
  .nav-text,
  .system-status {
    display: none;
  }
  
  .nav-link {
    justify-content: center;
  }
  
  .logout-btn span:not(.logout-icon) {
    display: none;
  }
  
  .logout-btn {
    justify-content: center;
  }
}

/* Startup Loading Screen */
.startup-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
}

.startup-content {
  text-align: center;
  color: #e0e0e0;
}

.startup-logo {
  margin-bottom: 2rem;
}

.startup-logo .logo-line {
  display: block;
  font-size: 2.5rem;
  font-weight: 700;
  line-height: 1.1;
  background: linear-gradient(135deg, #60a5fa, #a78bfa);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.startup-spinner {
  width: 48px;
  height: 48px;
  border: 3px solid rgba(96, 165, 250, 0.2);
  border-top-color: #60a5fa;
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin: 0 auto 1.5rem;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.startup-status {
  font-size: 1rem;
  color: #a0aec0;
  margin-bottom: 1rem;
}

.startup-error {
  margin-top: 1rem;
  padding: 1rem;
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.3);
  border-radius: 8px;
  color: #fca5a5;
}

.startup-error span {
  display: block;
  margin-bottom: 0.75rem;
}

.retry-btn {
  background: #60a5fa;
  color: white;
  border: none;
  padding: 0.5rem 1.5rem;
  border-radius: 6px;
  cursor: pointer;
  font-weight: 500;
  transition: background 0.2s;
}

.retry-btn:hover {
  background: #3b82f6;
}
</style>
