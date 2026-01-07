import { createApp } from 'vue'
import App from './App.vue'
import router from './router'

// Import Bootstrap CSS and JS
import 'bootstrap/dist/css/bootstrap.min.css'
import 'bootstrap/dist/js/bootstrap.bundle.min.js'

// Import global styles
import './assets/main.css'

// Create and configure app
const app = createApp(App)
app.use(router)
app.mount('#app')
