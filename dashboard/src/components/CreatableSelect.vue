<template>
  <div class="creatable-select" ref="containerRef">
    <!-- Input Field -->
    <div 
      class="select-input-wrapper" 
      :class="{ focused: isOpen, hasValue: hasValue }"
      @click="openDropdown"
    >
      <input
        ref="inputRef"
        type="text"
        class="select-input"
        :placeholder="hasValue ? '' : placeholder"
        v-model="searchQuery"
        @focus="openDropdown"
        @keydown="handleKeydown"
        autocomplete="off"
      />
      <div v-if="hasValue && !isOpen" class="selected-value">
        {{ displayValue }}
      </div>
      <div class="select-actions">
        <button 
          v-if="hasValue" 
          type="button" 
          class="clear-btn" 
          @click.stop="clearSelection"
          title="Clear"
        >
          ✕
        </button>
        <span class="chevron" :class="{ open: isOpen }">▼</span>
      </div>
    </div>

    <!-- Dropdown -->
    <Teleport to="body">
      <div 
        v-if="isOpen" 
        class="select-dropdown"
        :style="dropdownStyle"
        ref="dropdownRef"
      >
        <!-- Options List -->
        <div class="options-list" v-if="filteredOptions.length > 0 || canCreate">
          <!-- Existing Options -->
          <div
            v-for="(option, index) in filteredOptions"
            :key="option.value"
            class="option-item"
            :class="{ 
              highlighted: highlightedIndex === index,
              selected: isSelected(option)
            }"
            @click="selectOption(option)"
            @mouseenter="highlightedIndex = index"
          >
            <span class="option-icon">📁</span>
            <span class="option-label">{{ option.label }}</span>
          </div>

          <!-- Create New Option -->
          <div
            v-if="canCreate"
            class="option-item create-option"
            :class="{ highlighted: highlightedIndex === filteredOptions.length }"
            @click="createNewOption"
            @mouseenter="highlightedIndex = filteredOptions.length"
          >
            <span class="option-icon">➕</span>
            <span class="option-label">Create "{{ searchQuery }}"</span>
          </div>
        </div>

        <!-- No Results -->
        <div v-else class="no-options">
          <span>No groups found</span>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'

const props = defineProps({
  modelValue: {
    type: [String, Number, Object],
    default: null
  },
  options: {
    type: Array,
    default: () => []
  },
  placeholder: {
    type: String,
    default: 'Select or create...'
  },
  labelKey: {
    type: String,
    default: 'label'
  },
  valueKey: {
    type: String,
    default: 'value'
  }
})

const emit = defineEmits(['update:modelValue', 'create'])

// Refs
const containerRef = ref(null)
const inputRef = ref(null)
const dropdownRef = ref(null)

// State
const isOpen = ref(false)
const searchQuery = ref('')
const highlightedIndex = ref(0)
const dropdownStyle = ref({})

// Local created options (temporary, not yet saved to backend)
const localCreatedOptions = ref([])

// Computed
const allOptions = computed(() => {
  // Merge props.options with locally created options
  const propsOptions = props.options.map(opt => ({
    value: opt[props.valueKey] ?? opt.id ?? opt,
    label: opt[props.labelKey] ?? opt.name ?? opt,
    isNew: false
  }))
  
  return [...propsOptions, ...localCreatedOptions.value]
})

const filteredOptions = computed(() => {
  if (!searchQuery.value) return allOptions.value
  
  const query = searchQuery.value.toLowerCase()
  return allOptions.value.filter(opt => 
    opt.label.toLowerCase().includes(query)
  )
})

const canCreate = computed(() => {
  if (!searchQuery.value.trim()) return false
  
  // Check if exact match exists
  const query = searchQuery.value.toLowerCase().trim()
  return !allOptions.value.some(opt => 
    opt.label.toLowerCase() === query
  )
})

const hasValue = computed(() => {
  return props.modelValue !== null && props.modelValue !== undefined && props.modelValue !== ''
})

const displayValue = computed(() => {
  if (!hasValue.value) return ''
  
  // Check if it's an object (new group)
  if (typeof props.modelValue === 'object' && props.modelValue !== null) {
    return props.modelValue.label || props.modelValue.name || ''
  }
  
  // Find in options
  const option = allOptions.value.find(opt => opt.value === props.modelValue)
  return option?.label || ''
})

// Methods
const openDropdown = () => {
  isOpen.value = true
  highlightedIndex.value = 0
  nextTick(() => {
    inputRef.value?.focus()
    updateDropdownPosition()
  })
}

const closeDropdown = () => {
  isOpen.value = false
  searchQuery.value = ''
}

const updateDropdownPosition = () => {
  if (!containerRef.value) return
  
  const rect = containerRef.value.getBoundingClientRect()
  const viewportHeight = window.innerHeight
  const spaceBelow = viewportHeight - rect.bottom
  const dropdownHeight = 250 // max-height of dropdown
  
  // Position below or above depending on space
  if (spaceBelow < dropdownHeight && rect.top > dropdownHeight) {
    // Position above
    dropdownStyle.value = {
      position: 'fixed',
      left: `${rect.left}px`,
      bottom: `${viewportHeight - rect.top + 4}px`,
      width: `${rect.width}px`,
      zIndex: 9999
    }
  } else {
    // Position below
    dropdownStyle.value = {
      position: 'fixed',
      left: `${rect.left}px`,
      top: `${rect.bottom + 4}px`,
      width: `${rect.width}px`,
      zIndex: 9999
    }
  }
}

const selectOption = (option) => {
  if (option.isNew) {
    // Pass the new group object
    emit('update:modelValue', { __isNew: true, label: option.label })
  } else {
    emit('update:modelValue', option.value)
  }
  closeDropdown()
}

const createNewOption = () => {
  const newName = searchQuery.value.trim()
  if (!newName) return
  
  // Add to local created options
  const newOption = {
    value: `__new__${Date.now()}`,
    label: newName,
    isNew: true
  }
  localCreatedOptions.value.push(newOption)
  
  // Emit the new group object
  emit('update:modelValue', { __isNew: true, label: newName })
  emit('create', newName)
  closeDropdown()
}

const clearSelection = () => {
  emit('update:modelValue', null)
  searchQuery.value = ''
}

const isSelected = (option) => {
  if (!hasValue.value) return false
  
  if (typeof props.modelValue === 'object' && props.modelValue !== null) {
    return option.label === props.modelValue.label
  }
  
  return option.value === props.modelValue
}

const handleKeydown = (e) => {
  const totalOptions = filteredOptions.value.length + (canCreate.value ? 1 : 0)
  
  switch (e.key) {
    case 'ArrowDown':
      e.preventDefault()
      highlightedIndex.value = (highlightedIndex.value + 1) % totalOptions
      break
    case 'ArrowUp':
      e.preventDefault()
      highlightedIndex.value = (highlightedIndex.value - 1 + totalOptions) % totalOptions
      break
    case 'Enter':
      e.preventDefault()
      if (highlightedIndex.value < filteredOptions.value.length) {
        selectOption(filteredOptions.value[highlightedIndex.value])
      } else if (canCreate.value) {
        createNewOption()
      }
      break
    case 'Escape':
      closeDropdown()
      break
  }
}

// Click outside handler
const handleClickOutside = (e) => {
  if (containerRef.value && !containerRef.value.contains(e.target) &&
      dropdownRef.value && !dropdownRef.value.contains(e.target)) {
    closeDropdown()
  }
}

// Watch for scroll/resize to update position
const handleScrollResize = () => {
  if (isOpen.value) {
    updateDropdownPosition()
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
  window.addEventListener('scroll', handleScrollResize, true)
  window.addEventListener('resize', handleScrollResize)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
  window.removeEventListener('scroll', handleScrollResize, true)
  window.removeEventListener('resize', handleScrollResize)
})

// Reset highlighted index when search changes
watch(searchQuery, () => {
  highlightedIndex.value = 0
})
</script>

<style scoped>
.creatable-select {
  position: relative;
  width: 100%;
}

.select-input-wrapper {
  display: flex;
  align-items: center;
  padding: 0.75rem 1rem;
  background: var(--bg-color);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  cursor: text;
  transition: border-color 0.2s;
  position: relative;
}

.select-input-wrapper:hover {
  border-color: var(--text-secondary);
}

.select-input-wrapper.focused {
  border-color: var(--primary);
}

.select-input {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  color: var(--text-primary);
  font-size: 1rem;
  padding: 0;
  min-width: 50px;
}

.select-input::placeholder {
  color: var(--text-secondary);
  opacity: 0.6;
}

.selected-value {
  position: absolute;
  left: 1rem;
  right: 3rem;
  color: var(--text-primary);
  pointer-events: none;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.select-input-wrapper.hasValue:not(.focused) .select-input {
  color: transparent;
}

.select-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-left: 0.5rem;
}

.clear-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  background: var(--border-color);
  border: none;
  border-radius: 50%;
  color: var(--text-secondary);
  font-size: 0.7rem;
  cursor: pointer;
  transition: all 0.2s;
}

.clear-btn:hover {
  background: var(--danger);
  color: #fff;
}

.chevron {
  color: var(--text-secondary);
  font-size: 0.7rem;
  transition: transform 0.2s;
}

.chevron.open {
  transform: rotate(180deg);
}

/* Dropdown */
.select-dropdown {
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
  max-height: 250px;
  overflow-y: auto;
}

.options-list {
  padding: 0.5rem 0;
}

.option-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem 1rem;
  cursor: pointer;
  transition: background 0.15s;
}

.option-item:hover,
.option-item.highlighted {
  background: rgba(56, 139, 219, 0.1);
}

.option-item.selected {
  background: rgba(56, 139, 219, 0.2);
}

.option-item.create-option {
  border-top: 1px solid var(--border-color);
  color: var(--primary);
  font-weight: 500;
}

.option-item.create-option .option-icon {
  color: var(--primary);
}

.option-icon {
  font-size: 1rem;
  opacity: 0.8;
}

.option-label {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.no-options {
  padding: 1rem;
  text-align: center;
  color: var(--text-secondary);
  font-size: 0.875rem;
}
</style>
