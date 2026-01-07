<template>
  <div class="tag-input-container" @click="focusInput">
    <!-- Tag Pills -->
    <div class="tag-pills">
      <span 
        v-for="(tag, index) in tags" 
        :key="index" 
        class="tag-pill"
      >
        {{ tag }}
        <button type="button" class="tag-remove" @click.stop="removeTag(index)">&times;</button>
      </span>
      
      <!-- Input Field -->
      <div class="input-wrapper">
        <input
          ref="inputRef"
          type="text"
          class="tag-input"
          :placeholder="tags.length === 0 ? placeholder : ''"
          v-model="inputValue"
          @keydown.enter.prevent="addTag"
          @keydown.tab="handleTab"
          @keydown.down.prevent="navigateSuggestions(1)"
          @keydown.up.prevent="navigateSuggestions(-1)"
          @keydown.escape="closeSuggestions"
          @input="onInput"
          @focus="onFocus"
          @blur="onBlur"
        />
        
        <!-- Suggestions Dropdown -->
        <div v-if="showSuggestions && filteredSuggestions.length > 0" class="suggestions-dropdown">
          <div 
            v-for="(suggestion, index) in filteredSuggestions" 
            :key="suggestion"
            class="suggestion-item"
            :class="{ active: index === selectedSuggestionIndex }"
            @mousedown.prevent="selectSuggestion(suggestion)"
          >
            <span class="suggestion-tag-icon">🏷️</span>
            {{ suggestion }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'

const props = defineProps({
  modelValue: {
    type: String,
    default: ''
  },
  placeholder: {
    type: String,
    default: 'Type and press Enter...'
  },
  suggestions: {
    type: Array,
    default: () => []
  }
})

const emit = defineEmits(['update:modelValue'])

const inputRef = ref(null)
const inputValue = ref('')
const showSuggestions = ref(false)
const selectedSuggestionIndex = ref(-1)
const allTags = ref([])
const isLoadingTags = ref(false)

// Fetch all existing tags from the API
const fetchExistingTags = async () => {
  if (isLoadingTags.value) return
  isLoadingTags.value = true
  try {
    const response = await fetch('/api/tags')
    if (!response.ok) {
      console.error('Tags API returned error:', response.status)
      return
    }
    const data = await response.json()
    console.log('Tags API response:', data)
    if (data.success && data.data) {
      allTags.value = data.data
      console.log('Loaded tags:', allTags.value)
    }
  } catch (e) {
    console.error('Failed to fetch tags:', e)
  } finally {
    isLoadingTags.value = false
  }
}

onMounted(() => {
  fetchExistingTags()
})

// Parse comma-separated string into array
const tags = computed(() => {
  if (!props.modelValue) return []
  return props.modelValue.split(',').map(t => t.trim()).filter(t => t)
})

// Filter suggestions based on input and exclude already added tags
const filteredSuggestions = computed(() => {
  const query = inputValue.value.toLowerCase().trim()
  if (!query) return []
  
  // Use provided suggestions or fetched tags
  const availableTags = props.suggestions.length > 0 ? props.suggestions : allTags.value
  
  return availableTags
    .filter(tag => 
      tag.toLowerCase().includes(query) && 
      !tags.value.map(t => t.toLowerCase()).includes(tag.toLowerCase())
    )
    .slice(0, 8) // Limit to 8 suggestions
})

const focusInput = () => {
  inputRef.value?.focus()
}

const onFocus = () => {
  // Refresh tags when focusing
  fetchExistingTags()
}

const onBlur = () => {
  // Delay hiding to allow click on suggestion
  setTimeout(() => {
    showSuggestions.value = false
    selectedSuggestionIndex.value = -1
  }, 150)
  addTag()
}

const onInput = () => {
  showSuggestions.value = inputValue.value.trim().length > 0
  selectedSuggestionIndex.value = -1
}

const closeSuggestions = () => {
  showSuggestions.value = false
  selectedSuggestionIndex.value = -1
}

const navigateSuggestions = (direction) => {
  if (!showSuggestions.value || filteredSuggestions.value.length === 0) return
  
  selectedSuggestionIndex.value += direction
  
  if (selectedSuggestionIndex.value < 0) {
    selectedSuggestionIndex.value = filteredSuggestions.value.length - 1
  } else if (selectedSuggestionIndex.value >= filteredSuggestions.value.length) {
    selectedSuggestionIndex.value = 0
  }
}

const selectSuggestion = (suggestion) => {
  inputValue.value = suggestion
  addTag()
  showSuggestions.value = false
  selectedSuggestionIndex.value = -1
  inputRef.value?.focus()
}

const handleTab = (e) => {
  // If a suggestion is selected, use it
  if (showSuggestions.value && selectedSuggestionIndex.value >= 0) {
    e.preventDefault()
    selectSuggestion(filteredSuggestions.value[selectedSuggestionIndex.value])
  } else if (inputValue.value.trim()) {
    e.preventDefault()
    addTag()
  }
}

const addTag = () => {
  // If suggestion is selected, use it
  if (showSuggestions.value && selectedSuggestionIndex.value >= 0) {
    selectSuggestion(filteredSuggestions.value[selectedSuggestionIndex.value])
    return
  }
  
  const newTag = inputValue.value.trim()
  if (!newTag) return
  
  // Don't add duplicates
  if (tags.value.map(t => t.toLowerCase()).includes(newTag.toLowerCase())) {
    inputValue.value = ''
    showSuggestions.value = false
    return
  }
  
  // Add to existing tags
  const newTags = [...tags.value, newTag]
  emit('update:modelValue', newTags.join(', '))
  inputValue.value = ''
  showSuggestions.value = false
  selectedSuggestionIndex.value = -1
}

const removeTag = (index) => {
  const newTags = tags.value.filter((_, i) => i !== index)
  emit('update:modelValue', newTags.join(', '))
}
</script>

<style scoped>
.tag-input-container {
  display: flex;
  align-items: center;
  background: var(--input-bg, #1a1a2e);
  border: 1px solid var(--border-color, #2d2d44);
  border-radius: 6px;
  padding: 4px 8px;
  min-height: 34px;
  cursor: text;
  transition: border-color 0.2s;
}

.tag-input-container:focus-within {
  border-color: var(--primary-color, #6366f1);
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.1);
}

.tag-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
  flex: 1;
}

.tag-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.2), rgba(139, 92, 246, 0.2));
  border: 1px solid rgba(99, 102, 241, 0.3);
  color: #a5b4fc;
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 0.8rem;
  font-weight: 500;
  animation: tagAppear 0.15s ease-out;
}

@keyframes tagAppear {
  from {
    transform: scale(0.8);
    opacity: 0;
  }
  to {
    transform: scale(1);
    opacity: 1;
  }
}

.tag-remove {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: none;
  border: none;
  color: #a5b4fc;
  cursor: pointer;
  padding: 0;
  width: 14px;
  height: 14px;
  font-size: 14px;
  line-height: 1;
  border-radius: 50%;
  opacity: 0.6;
  transition: all 0.15s;
}

.tag-remove:hover {
  opacity: 1;
  background: rgba(239, 68, 68, 0.3);
  color: #fca5a5;
}

.input-wrapper {
  position: relative;
  flex: 1;
  min-width: 80px;
}

.tag-input {
  width: 100%;
  background: transparent;
  border: none;
  outline: none;
  color: var(--text-color, #e2e8f0);
  font-size: 0.85rem;
  padding: 4px 0;
}

.tag-input::placeholder {
  color: var(--text-muted, #64748b);
}

/* Suggestions Dropdown */
.suggestions-dropdown {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  min-width: 180px;
  background: var(--card-bg, #1e1e2e);
  border: 1px solid var(--border-color, #2d2d44);
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
  z-index: 1000;
  margin-top: 4px;
  overflow: hidden;
  animation: dropdownAppear 0.15s ease-out;
}

@keyframes dropdownAppear {
  from {
    opacity: 0;
    transform: translateY(-8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.suggestion-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  cursor: pointer;
  font-size: 0.85rem;
  color: var(--text-color, #e2e8f0);
  transition: background 0.15s;
}

.suggestion-item:hover,
.suggestion-item.active {
  background: rgba(99, 102, 241, 0.15);
}

.suggestion-item.active {
  background: rgba(99, 102, 241, 0.25);
}

.suggestion-tag-icon {
  font-size: 0.75rem;
  opacity: 0.7;
}
</style>
