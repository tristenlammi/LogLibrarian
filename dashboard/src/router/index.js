import { createRouter, createWebHistory } from 'vue-router'
import DashboardView from '../components/DashboardView.vue'
import LogsView from '../components/LogsView.vue'
import AgentsView from '../components/AgentsView.vue'
import ProfilesView from '../components/ProfilesView.vue'
import SettingsView from '../components/SettingsView.vue'
import HelpView from '../components/HelpView.vue'
import BookmarksView from '../components/BookmarksView.vue'
import BookmarkSettingsView from '../components/BookmarkSettingsView.vue'
import LoginView from '../components/LoginView.vue'
import SetupWizard from '../components/SetupWizard.vue'
import { checkAuthStatus, isAuthenticated, isAdmin } from '../auth.js'

const routes = [
  {
    path: '/setup',
    name: 'Setup',
    component: SetupWizard,
    meta: { title: 'Setup', public: true, hideFromNav: true, isSetup: true }
  },
  {
    path: '/login',
    name: 'Login',
    component: LoginView,
    meta: { title: 'Login', public: true, hideFromNav: true }
  },
  {
    path: '/',
    name: 'Dashboard',
    component: DashboardView,
    meta: { title: 'Dashboard' }
  },
  {
    path: '/agents',
    name: 'Scribes',
    component: AgentsView,
    meta: { title: 'Scribes' }
  },
  {
    path: '/bookmarks',
    name: 'Bookmarks',
    component: BookmarksView,
    meta: { title: 'Bookmarks' }
  },
  {
    path: '/bookmarks/settings',
    name: 'BookmarkSettings',
    component: BookmarkSettingsView,
    meta: { title: 'Bookmark Settings', hideFromNav: true, adminOnly: true }
  },
  {
    path: '/bookmarks/new',
    name: 'BookmarkNew',
    component: BookmarksView,
    meta: { title: 'Add Bookmark', hideFromNav: true, adminOnly: true }
  },
  {
    path: '/bookmarks/:id',
    name: 'BookmarkDetail',
    component: BookmarksView,
    meta: { title: 'Bookmarks', hideFromNav: true }
  },
  {
    path: '/bookmarks/:id/edit',
    name: 'BookmarkEdit',
    component: BookmarksView,
    meta: { title: 'Edit Bookmark', hideFromNav: true, adminOnly: true }
  },
  {
    path: '/profiles',
    name: 'Profiles',
    component: ProfilesView,
    meta: { title: 'Profiles', adminOnly: true }
  },
  {
    path: '/logs',
    name: 'Logs',
    component: LogsView,
    meta: { title: 'Log Browser', adminOnly: true }
  },
  {
    path: '/settings',
    name: 'Settings',
    component: SettingsView,
    meta: { title: 'Settings', adminOnly: true }
  },
  {
    path: '/help',
    name: 'Help',
    component: HelpView,
    meta: { title: 'Help & FAQ', adminOnly: true }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

// Auth guard with setup check
router.beforeEach(async (to, from, next) => {
  // Setup route is always accessible
  if (to.meta.isSetup) {
    next()
    return
  }
  
  // Check if setup is required first
  try {
    const setupRes = await fetch('/api/setup/status')
    const setupStatus = await setupRes.json()
    
    if (setupStatus.setup_required && to.name !== 'Setup') {
      // Redirect to setup wizard
      next({ name: 'Setup' })
      return
    }
  } catch (e) {
    console.error('Failed to check setup status:', e)
  }
  
  // Public routes don't need auth
  if (to.meta.public) {
    next()
    return
  }
  
  // Check auth status
  const status = await checkAuthStatus()
  
  if (!status.authenticated) {
    // Redirect to login
    next({ name: 'Login' })
    return
  }
  
  // Check admin-only routes
  if (to.meta.adminOnly && !isAdmin.value) {
    // Non-admin trying to access admin page - redirect to dashboard
    next({ name: 'Dashboard' })
    return
  }
  
  next()
})

export default router
