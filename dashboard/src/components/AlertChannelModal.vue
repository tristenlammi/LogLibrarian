<template>
  <div v-if="show" class="modal-backdrop" @click.self="close">
    <div class="modal-dialog">
      <div class="modal-content">
        <div class="modal-header">
          <h5 class="modal-title">{{ isEdit ? 'Edit' : 'Add' }} Notification Channel</h5>
          <button type="button" class="btn-close" @click="close"></button>
        </div>
        
        <div class="modal-body">
          <!-- Channel Name -->
          <div class="mb-3">
            <label class="form-label">Channel Name</label>
            <input 
              type="text" 
              class="form-control" 
              v-model="form.name"
              placeholder="e.g., Discord Alerts, Admin Email"
            >
          </div>
          
          <!-- Channel Type -->
          <div class="mb-3">
            <label class="form-label">Channel Type</label>
            <div class="channel-type-grid">
              <div 
                v-for="type in channelTypes" 
                :key="type.id"
                class="channel-type-card"
                :class="{ selected: form.channel_type === type.id }"
                @click="selectChannelType(type.id)"
              >
                <span class="channel-icon">{{ type.icon }}</span>
                <span class="channel-name">{{ type.name }}</span>
              </div>
            </div>
          </div>
          
          <!-- Type-specific URL input -->
          <div class="mb-3">
            <label class="form-label">{{ urlLabel }}</label>
            <input 
              type="text" 
              class="form-control" 
              v-model="form.url"
              :placeholder="urlPlaceholder"
            >
            <div class="form-text text-secondary">{{ urlHint }}</div>
          </div>
          
          <!-- Events to subscribe -->
          <div class="mb-3">
            <label class="form-label">Subscribe to Events</label>
            <div class="events-grid">
              <div class="form-check" v-for="event in eventTypes" :key="event.id">
                <input 
                  class="form-check-input" 
                  type="checkbox" 
                  :id="'event-' + event.id"
                  :checked="form.events.includes(event.id)"
                  @change="toggleEvent(event.id)"
                >
                <label class="form-check-label" :for="'event-' + event.id">
                  {{ event.name }}
                </label>
              </div>
            </div>
          </div>
          
          <!-- Enable/Disable -->
          <div class="form-check form-switch mb-3" v-if="isEdit">
            <input class="form-check-input" type="checkbox" v-model="form.enabled" id="channelEnabled">
            <label class="form-check-label" for="channelEnabled">Channel Enabled</label>
          </div>
          
          <!-- Error message -->
          <div v-if="error" class="alert alert-danger">{{ error }}</div>
        </div>
        
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" @click="close">Cancel</button>
          <button 
            v-if="isEdit" 
            type="button" 
            class="btn btn-outline-primary"
            @click="testChannel"
            :disabled="testing"
          >
            <span v-if="testing" class="spinner-border spinner-border-sm me-1"></span>
            Test
          </button>
          <button 
            type="button" 
            class="btn btn-primary"
            @click="save"
            :disabled="saving || !isValid"
          >
            <span v-if="saving" class="spinner-border spinner-border-sm me-1"></span>
            {{ isEdit ? 'Save Changes' : 'Add Channel' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import axios from 'axios'

const props = defineProps({
  show: Boolean,
  channel: Object // null for new, existing channel for edit
})

const emit = defineEmits(['close', 'saved'])

const channelTypes = [
  { id: 'discord', name: 'Discord', icon: '🎮' },
  { id: 'slack', name: 'Slack', icon: '💬' },
  { id: 'email', name: 'Email', icon: '📧' },
  { id: 'telegram', name: 'Telegram', icon: '📱' },
  { id: 'pushover', name: 'Pushover', icon: '🔔' },
  { id: 'custom', name: 'Custom URL', icon: '🔗' }
]

const eventTypes = [
  { id: 'all', name: 'All Events' },
  { id: 'agent_offline', name: 'Agent Offline' },
  { id: 'cpu_high', name: 'High CPU' },
  { id: 'ram_high', name: 'High Memory' },
  { id: 'disk_low', name: 'Low Disk Space' },
  { id: 'bookmark_down', name: 'Bookmark Down' },
  { id: 'ssl_expiry', name: 'SSL Expiring' }
]

const form = ref({
  name: '',
  channel_type: 'discord',
  url: '',
  events: ['all'],
  enabled: true
})

const error = ref('')
const saving = ref(false)
const testing = ref(false)

const isEdit = computed(() => !!props.channel)

const isValid = computed(() => {
  return form.value.name.trim() && form.value.url.trim() && form.value.events.length > 0
})

const urlLabel = computed(() => {
  const labels = {
    discord: 'Discord Webhook URL',
    slack: 'Slack Webhook URL',
    email: 'Email Address(es)',
    telegram: 'Telegram Bot Token / Chat ID',
    pushover: 'Pushover User Key',
    custom: 'Apprise URL'
  }
  return labels[form.value.channel_type] || 'URL'
})

const urlPlaceholder = computed(() => {
  const placeholders = {
    discord: 'https://discord.com/api/webhooks/...',
    slack: 'https://hooks.slack.com/services/...',
    email: 'admin@example.com',
    telegram: 'tgram://bottoken/ChatID',
    pushover: 'pover://user@token',
    custom: 'apprise://...'
  }
  return placeholders[form.value.channel_type] || 'Enter URL'
})

const urlHint = computed(() => {
  const hints = {
    discord: 'Create a webhook in Discord Server Settings > Integrations',
    slack: 'Create an Incoming Webhook in your Slack workspace',
    email: 'Requires SMTP configuration in backend. Separate multiple emails with commas.',
    telegram: 'Format: tgram://bottoken/ChatID - Get bot token from @BotFather',
    pushover: 'Format: pover://user@token - Get credentials from Pushover app',
    custom: 'Any valid Apprise URL. See apprise.readthedocs.io for supported services.'
  }
  return hints[form.value.channel_type] || ''
})

// Watch for channel prop changes (edit mode)
watch(() => props.channel, (newChannel) => {
  if (newChannel) {
    form.value = {
      name: newChannel.name || '',
      channel_type: newChannel.channel_type || 'discord',
      url: newChannel.url || '',
      events: newChannel.events || ['all'],
      enabled: newChannel.enabled !== false
    }
  } else {
    // Reset form for new channel
    form.value = {
      name: '',
      channel_type: 'discord',
      url: '',
      events: ['all'],
      enabled: true
    }
  }
}, { immediate: true })

// Watch show to reset error
watch(() => props.show, (newShow) => {
  if (newShow) {
    error.value = ''
  }
})

function selectChannelType(typeId) {
  form.value.channel_type = typeId
  // Clear URL when switching types
  if (!isEdit.value) {
    form.value.url = ''
  }
}

function toggleEvent(eventId) {
  const idx = form.value.events.indexOf(eventId)
  if (idx >= 0) {
    form.value.events.splice(idx, 1)
  } else {
    // If selecting 'all', clear others
    if (eventId === 'all') {
      form.value.events = ['all']
    } else {
      // Remove 'all' if selecting specific events
      const allIdx = form.value.events.indexOf('all')
      if (allIdx >= 0) {
        form.value.events.splice(allIdx, 1)
      }
      form.value.events.push(eventId)
    }
  }
}

function buildAppriseUrl() {
  // Convert user-friendly inputs to Apprise URLs where needed
  const type = form.value.channel_type
  let url = form.value.url.trim()
  
  if (type === 'discord' && url.includes('discord.com/api/webhooks')) {
    // Already a Discord URL, convert to Apprise format if needed
    if (!url.startsWith('discord://')) {
      // Extract webhook ID and token from URL
      const match = url.match(/webhooks\/(\d+)\/([^/\s]+)/)
      if (match) {
        url = `discord://${match[1]}/${match[2]}`
      }
    }
  } else if (type === 'slack' && url.includes('hooks.slack.com')) {
    // Already a Slack URL, convert to Apprise format if needed
    if (!url.startsWith('slack://')) {
      const match = url.match(/services\/([^/]+)\/([^/]+)\/([^/\s]+)/)
      if (match) {
        url = `slack://${match[1]}/${match[2]}/${match[3]}`
      }
    }
  } else if (type === 'email' && !url.includes('://')) {
    // Simple email address - wrap in mailto
    url = `mailto://${url}`
  }
  
  return url
}

async function save() {
  error.value = ''
  saving.value = true
  
  try {
    const payload = {
      name: form.value.name.trim(),
      channel_type: form.value.channel_type,
      url: buildAppriseUrl(),
      events: form.value.events
    }
    
    if (isEdit.value) {
      payload.enabled = form.value.enabled
      await axios.put(`/api/notifications/channels/${props.channel.id}`, payload)
    } else {
      await axios.post('/api/notifications/channels', payload)
    }
    
    emit('saved')
    close()
  } catch (e) {
    error.value = e.response?.data?.detail || 'Failed to save channel'
  } finally {
    saving.value = false
  }
}

async function testChannel() {
  if (!props.channel?.id) return
  
  error.value = ''
  testing.value = true
  
  try {
    await axios.post(`/api/notifications/channels/${props.channel.id}/test`)
    alert('Test notification sent successfully!')
  } catch (e) {
    error.value = e.response?.data?.detail || 'Failed to send test notification'
  } finally {
    testing.value = false
  }
}

function close() {
  emit('close')
}
</script>

<style scoped>
.modal-backdrop {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1050;
}

.modal-dialog {
  width: 100%;
  max-width: 550px;
  margin: 1rem;
}

.modal-content {
  background: #1e1e1e;
  border: 1px solid #333;
  border-radius: 8px;
}

.modal-header {
  border-bottom: 1px solid #333;
  padding: 1rem 1.25rem;
}

.modal-title {
  color: #fff;
  margin: 0;
  font-size: 1.1rem;
}

.btn-close {
  filter: invert(1);
}

.modal-body {
  padding: 1.25rem;
}

.modal-footer {
  border-top: 1px solid #333;
  padding: 1rem 1.25rem;
  display: flex;
  gap: 0.5rem;
  justify-content: flex-end;
}

.form-label {
  color: #ccc;
  font-size: 0.875rem;
  margin-bottom: 0.5rem;
}

.form-control {
  background: #2d2d2d;
  border: 1px solid #444;
  color: #fff;
}

.form-control:focus {
  background: #2d2d2d;
  border-color: #0d6efd;
  color: #fff;
  box-shadow: 0 0 0 0.2rem rgba(13, 110, 253, 0.25);
}

.form-control::placeholder {
  color: #666;
}

.form-text {
  font-size: 0.75rem;
  margin-top: 0.25rem;
}

.channel-type-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.5rem;
}

.channel-type-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 0.75rem 0.5rem;
  background: #2d2d2d;
  border: 2px solid transparent;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
}

.channel-type-card:hover {
  background: #363636;
}

.channel-type-card.selected {
  border-color: #0d6efd;
  background: rgba(13, 110, 253, 0.1);
}

.channel-icon {
  font-size: 1.5rem;
  margin-bottom: 0.25rem;
}

.channel-name {
  font-size: 0.75rem;
  color: #ccc;
}

.events-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 0.5rem;
  padding: 0.75rem;
  background: #2d2d2d;
  border-radius: 6px;
}

.form-check-label {
  color: #ccc;
  font-size: 0.875rem;
}

.form-check-input {
  background-color: #2d2d2d;
  border-color: #555;
}

.form-check-input:checked {
  background-color: #0d6efd;
  border-color: #0d6efd;
}

.alert {
  margin-bottom: 0;
}
</style>
