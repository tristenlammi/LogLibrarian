<template>
  <Teleport to="body">
    <div v-if="show" class="delete-modal-overlay" @click.self="cancel">
      <div class="delete-modal-content">
        <div class="delete-modal-header">
          <h3>⚠️ Delete Agent</h3>
          <button class="delete-modal-close-btn" @click="cancel">×</button>
        </div>
        
        <div class="delete-modal-body">
          <p class="delete-warning-text">
            This will permanently delete agent <strong>{{ agentName }}</strong> and all its data:
          </p>
          <ul class="delete-list">
            <li>All metrics and performance data</li>
            <li>All log occurrences</li>
            <li>All process snapshots</li>
            <li>Agent registration</li>
          </ul>
          
          <p class="delete-danger-text">
            The agent will receive a shutdown signal and remove itself from the system.
          </p>
          
          <div class="delete-confirmation-input">
            <label>Type <code>delete</code> to confirm:</label>
            <input 
              v-model="confirmText" 
              type="text" 
              placeholder="delete"
              @keyup.enter="tryConfirm"
              ref="confirmInput"
            />
          </div>
        </div>
        
        <div class="delete-modal-footer">
          <button class="delete-btn-cancel" @click="cancel">Cancel</button>
          <button 
            class="delete-btn-confirm" 
            :disabled="!canDelete"
            @click="confirm"
          >
            Delete Agent
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, computed, watch } from 'vue';

const props = defineProps({
  show: Boolean,
  agentName: String
});

const emit = defineEmits(['confirm', 'cancel']);

const confirmText = ref('');
const confirmInput = ref(null);

const canDelete = computed(() => {
  return confirmText.value.toLowerCase() === 'delete';
});

// Focus input when modal opens
watch(() => props.show, (newVal) => {
  if (newVal) {
    confirmText.value = '';
    setTimeout(() => {
      confirmInput.value?.focus();
    }, 100);
  }
});

const confirm = () => {
  if (canDelete.value) {
    emit('confirm');
    confirmText.value = '';
  }
};

const tryConfirm = () => {
  if (canDelete.value) {
    confirm();
  }
};

const cancel = () => {
  emit('cancel');
  confirmText.value = '';
};
</script>

<style>
/* Delete Modal - Global styles for Teleport compatibility */
.delete-modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.9);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 999999;
  animation: deleteModalFadeIn 0.2s ease;
}

.delete-modal-content {
  background: #1e1e1e;
  border: 2px solid #ff6b6b;
  border-radius: 8px;
  width: 90%;
  max-width: 500px;
  box-shadow: 0 8px 32px rgba(255, 107, 107, 0.4);
  animation: deleteModalSlideIn 0.2s ease;
  position: relative;
  z-index: 1000000;
}

.delete-modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px;
  border-bottom: 1px solid #3a3a3a;
}

.delete-modal-header h3 {
  margin: 0;
  color: #ff6b6b;
  font-size: 1.3rem;
}

.delete-modal-close-btn {
  background: none;
  border: none;
  color: #888;
  font-size: 2rem;
  cursor: pointer;
  padding: 0;
  width: 30px;
  height: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: color 0.2s;
}

.delete-modal-close-btn:hover {
  color: #fff;
}

.delete-modal-body {
  padding: 20px;
}

.delete-warning-text {
  color: #e0e0e0;
  margin-bottom: 15px;
  line-height: 1.6;
}

.delete-warning-text strong {
  color: #4fc3f7;
}

.delete-list {
  margin: 15px 0;
  padding-left: 25px;
  color: #bbb;
}

.delete-list li {
  margin: 8px 0;
}

.delete-danger-text {
  background: rgba(255, 107, 107, 0.1);
  border-left: 3px solid #ff6b6b;
  padding: 12px;
  margin: 20px 0;
  color: #ffb3b3;
  font-size: 0.95rem;
}

.delete-confirmation-input {
  margin-top: 20px;
}

.delete-confirmation-input label {
  display: block;
  color: #e0e0e0;
  margin-bottom: 8px;
  font-size: 0.95rem;
}

.delete-confirmation-input code {
  background: rgba(255, 255, 255, 0.1);
  padding: 2px 6px;
  border-radius: 3px;
  color: #ff6b6b;
  font-weight: bold;
}

.delete-confirmation-input input {
  width: 100%;
  padding: 10px;
  background: #2a2a2a;
  border: 1px solid #3a3a3a;
  border-radius: 4px;
  color: #e0e0e0;
  font-size: 1rem;
  transition: border-color 0.2s;
}

.delete-confirmation-input input:focus {
  outline: none;
  border-color: #ff6b6b;
}

.delete-modal-footer {
  display: flex;
  gap: 10px;
  padding: 20px;
  border-top: 1px solid #3a3a3a;
  justify-content: flex-end;
}

.delete-btn-cancel,
.delete-btn-confirm {
  padding: 10px 20px;
  border: none;
  border-radius: 4px;
  font-size: 0.95rem;
  cursor: pointer;
  transition: all 0.2s;
}

.delete-btn-cancel {
  background: #3a3a3a;
  color: #e0e0e0;
}

.delete-btn-cancel:hover {
  background: #4a4a4a;
}

.delete-btn-confirm {
  background: #ff6b6b;
  color: white;
  font-weight: 500;
}

.delete-btn-confirm:hover:not(:disabled) {
  background: #ff5252;
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(255, 107, 107, 0.3);
}

.delete-btn-confirm:disabled {
  background: #555;
  color: #888;
  cursor: not-allowed;
  opacity: 0.5;
}

@keyframes deleteModalFadeIn {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}

@keyframes deleteModalSlideIn {
  from {
    transform: translateY(-20px);
    opacity: 0;
  }
  to {
    transform: translateY(0);
    opacity: 1;
  }
}
</style>
