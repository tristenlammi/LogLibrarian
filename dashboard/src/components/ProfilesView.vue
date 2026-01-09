<template>
  <div class="profiles-view">
    <!-- Modern Header -->
    <div class="profiles-header">
      <div class="header-left">
        <h2 class="page-title">Report Profiles</h2>
        <span class="count-badge">{{ profiles.length }}</span>
      </div>
      <div class="header-right">
        <!-- Search Bar -->
        <div class="search-wrapper">
          <svg class="search-icon" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="11" cy="11" r="8"></circle>
            <path d="m21 21-4.3-4.3"></path>
          </svg>
          <input 
            type="text" 
            class="search-input"
            v-model="searchQuery"
            placeholder="Search profiles..."
          >
        </div>
        <!-- Create Profile Button -->
        <button 
          v-if="isAdmin"
          class="btn btn-success d-flex align-items-center gap-2"
          @click="openCreateProfile"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 5v14M5 12h14"/>
          </svg>
          <span>Create Profile</span>
        </button>
      </div>
    </div>
    
    <!-- Content Area -->
    <div class="profiles-content">
      <!-- Loading State -->
      <div v-if="loading" class="text-center py-5">
        <div class="spinner-border text-primary mb-3" role="status"></div>
        <div class="text-secondary">Loading profiles...</div>
      </div>

      <!-- Empty State -->
      <div v-else-if="profiles.length === 0" class="empty-state">
        <div class="empty-icon">📊</div>
        <h5>No report profiles yet</h5>
        <p class="text-muted mb-4">Create a profile to generate executive summaries for your infrastructure</p>
        <button v-if="isAdmin" class="btn btn-success" @click="openCreateProfile">
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="me-2">
            <path d="M12 5v14M5 12h14"/>
          </svg>
          Create Your First Profile
        </button>
      </div>

      <!-- No Search Results -->
      <div v-else-if="filteredProfiles.length === 0" class="empty-state">
        <div class="empty-icon">🔍</div>
        <h6>No profiles match "{{ searchQuery }}"</h6>
        <button class="btn btn-sm btn-outline-secondary mt-2" @click="searchQuery = ''">
          Clear search
        </button>
      </div>

      <!-- Profiles Table -->
      <div v-else class="table-responsive">
        <table class="profiles-table">
          <thead>
            <tr>
              <th>Profile Name</th>
              <th class="text-center" style="width: 100px">Scribes</th>
              <th class="text-center" style="width: 100px">Bookmarks</th>
              <th class="text-center" style="width: 120px">Schedule</th>
              <th class="text-center" style="width: 140px">Next Run</th>
              <th class="text-center" style="width: 140px">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="profile in filteredProfiles" :key="profile.id">
              <td>
                <div class="profile-name-cell">
                  <span class="profile-name">{{ profile.name }}</span>
                  <span v-if="profile.description" class="profile-desc">{{ profile.description }}</span>
                </div>
              </td>
              <td class="text-center">
                <span class="pill-badge">{{ getScribeCount(profile) }}</span>
              </td>
              <td class="text-center">
                <span class="pill-badge">{{ getBookmarkCount(profile) }}</span>
              </td>
              <td class="text-center">
                <span class="schedule-badge" :class="getScheduleClass(profile.frequency)">
                  {{ getFrequencyLabel(profile.frequency) }}
                </span>
              </td>
              <td class="text-center text-muted">
                {{ getNextRun(profile) }}
              </td>
              <td class="text-center">
                <div class="action-buttons">
                  <button 
                    class="icon-btn icon-btn-primary"
                    @click="openReportsModal(profile)"
                    title="View Reports"
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/>
                      <circle cx="12" cy="12" r="3"/>
                    </svg>
                  </button>
                  <button 
                    v-if="isAdmin"
                    class="icon-btn icon-btn-secondary"
                    @click="openEditProfile(profile)"
                    title="Edit Profile"
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/>
                      <path d="m15 5 4 4"/>
                    </svg>
                  </button>
                  <button 
                    v-if="isAdmin"
                    class="icon-btn icon-btn-danger"
                    @click="confirmDelete(profile)"
                    title="Delete Profile"
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M3 6h18"/>
                      <path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/>
                      <path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>
                    </svg>
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Delete Confirmation Modal -->
    <Teleport to="body">
      <div v-if="deletingProfile" class="modal-overlay" @click.self="deletingProfile = null">
        <div class="modal-dialog-centered">
          <div class="modal-content bg-dark">
            <div class="modal-header border-secondary">
              <h5 class="modal-title">
                <span class="me-2">⚠️</span> Delete Profile
              </h5>
              <button type="button" class="btn-close btn-close-white" @click="deletingProfile = null"></button>
            </div>
            <div class="modal-body">
              <p>Are you sure you want to delete <strong>"{{ deletingProfile.name }}"</strong>?</p>
              <p class="text-muted mb-0">This will also delete all generated reports for this profile. This action cannot be undone.</p>
            </div>
            <div class="modal-footer border-secondary">
              <button type="button" class="btn btn-secondary" @click="deletingProfile = null">Cancel</button>
              <button type="button" class="btn btn-danger" @click="deleteProfile" :disabled="deleting">
                <span v-if="deleting" class="spinner-border spinner-border-sm me-1"></span>
                {{ deleting ? 'Deleting...' : 'Delete' }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Create/Edit Profile Modal -->
    <Teleport to="body">
      <div v-if="showProfileModal" class="modal-overlay" @click.self="closeProfileModal">
        <div class="modal-dialog-lg">
          <div class="modal-content bg-dark">
            <div class="modal-header border-secondary">
              <h5 class="modal-title">
                <span class="me-2">{{ editingProfile ? '✏️' : '➕' }}</span>
                {{ editingProfile ? 'Edit Profile' : 'Create Profile' }}
              </h5>
              <button type="button" class="btn-close btn-close-white" @click="closeProfileModal"></button>
            </div>
            <div class="modal-body">
              <form @submit.prevent="saveProfile">
                <!-- Basic Info -->
                <div class="form-section">
                  <h6 class="section-title">Basic Information</h6>
                  <div class="row g-3">
                    <div class="col-md-8">
                      <label class="form-label">Profile Name <span class="text-danger">*</span></label>
                      <input 
                        type="text" 
                        class="form-control" 
                        v-model="profileForm.name"
                        placeholder="e.g., Ocean View Motel Monthly"
                        required
                      >
                    </div>
                    <div class="col-md-4">
                      <label class="form-label">SLA Target (%)</label>
                      <input 
                        type="number" 
                        class="form-control" 
                        v-model.number="profileForm.sla_target"
                        min="0" max="100" step="0.1"
                        placeholder="99.9"
                      >
                    </div>
                    <div class="col-12">
                      <label class="form-label">Description</label>
                      <textarea 
                        class="form-control" 
                        v-model="profileForm.description"
                        rows="2"
                        placeholder="Optional description for this report profile"
                      ></textarea>
                    </div>
                  </div>
                </div>

                <!-- Schedule -->
                <div class="form-section">
                  <h6 class="section-title">Schedule</h6>
                  <div class="row g-3">
                    <div class="col-md-6">
                      <label class="form-label">Frequency</label>
                      <select class="form-select" v-model="profileForm.frequency">
                        <option value="MANUAL">Manual (on demand)</option>
                        <option value="DAILY">Daily</option>
                        <option value="WEEKLY">Weekly</option>
                        <option value="MONTHLY">Monthly</option>
                        <option value="QUARTERLY">Quarterly</option>
                        <option value="ANNUALLY">Annually</option>
                      </select>
                    </div>
                    <div class="col-md-6">
                      <label class="form-label">Run at Hour (0-23)</label>
                      <select class="form-select" v-model.number="profileForm.schedule_hour">
                        <option v-for="h in 24" :key="h-1" :value="h-1">
                          {{ formatHour(h-1) }}
                        </option>
                      </select>
                    </div>
                  </div>
                </div>

                <!-- Scribe Scope -->
                <div class="form-section">
                  <h6 class="section-title">Scribe Scope</h6>
                  <p class="text-muted small mb-2">Select which scribes to include in reports. Leave empty for all.</p>
                  
                  <div class="scope-selection">
                    <div class="scope-tabs">
                      <button type="button" :class="['scope-tab', { active: scribeScopeTab === 'all' }]" @click="scribeScopeTab = 'all'">
                        All Scribes
                      </button>
                      <button type="button" :class="['scope-tab', { active: scribeScopeTab === 'select' }]" @click="scribeScopeTab = 'select'">
                        Select Specific
                      </button>
                      <button type="button" :class="['scope-tab', { active: scribeScopeTab === 'tags' }]" @click="scribeScopeTab = 'tags'">
                        By Tags
                      </button>
                    </div>
                    
                    <div v-if="scribeScopeTab === 'select'" class="scope-list">
                      <div v-for="scribe in availableLogSources" :key="scribe.id" class="scope-item">
                        <input 
                          type="checkbox" 
                          :id="'scribe-' + scribe.id"
                          :value="scribe.id"
                          v-model="profileForm.scribe_scope_ids"
                        >
                        <label :for="'scribe-' + scribe.id">{{ scribe.name }}</label>
                      </div>
                      <div v-if="availableLogSources.length === 0" class="text-muted small">
                        No scribes available
                      </div>
                    </div>
                    
                    <div v-if="scribeScopeTab === 'tags'" class="scope-tags-input">
                      <input 
                        type="text" 
                        class="form-control" 
                        v-model="scribeTagsInput"
                        placeholder="Enter tags separated by commas"
                        @blur="parseScribeTags"
                      >
                      <div class="tags-display" v-if="profileForm.scribe_scope_tags?.length">
                        <span v-for="tag in profileForm.scribe_scope_tags" :key="tag" class="tag-badge">
                          {{ tag }}
                          <button type="button" @click="removeScribeTag(tag)">×</button>
                        </span>
                      </div>
                    </div>
                  </div>
                </div>

                <!-- Bookmark Scope -->
                <div class="form-section">
                  <h6 class="section-title">Bookmark Scope</h6>
                  <p class="text-muted small mb-2">Select which bookmarks to include in reports. Leave empty for all.</p>
                  
                  <div class="scope-selection">
                    <div class="scope-tabs">
                      <button type="button" :class="['scope-tab', { active: monitorScopeTab === 'all' }]" @click="monitorScopeTab = 'all'">
                        All Bookmarks
                      </button>
                      <button type="button" :class="['scope-tab', { active: monitorScopeTab === 'select' }]" @click="monitorScopeTab = 'select'">
                        Select Specific
                      </button>
                      <button type="button" :class="['scope-tab', { active: monitorScopeTab === 'tags' }]" @click="monitorScopeTab = 'tags'">
                        By Tags
                      </button>
                    </div>
                    
                    <div v-if="monitorScopeTab === 'select'" class="scope-list">
                      <div v-for="monitor in availableMonitors" :key="monitor.id" class="scope-item">
                        <input 
                          type="checkbox" 
                          :id="'monitor-' + monitor.id"
                          :value="monitor.id"
                          v-model="profileForm.monitor_scope_ids"
                        >
                        <label :for="'monitor-' + monitor.id">{{ monitor.name }}</label>
                      </div>
                      <div v-if="availableMonitors.length === 0" class="text-muted small">
                        No bookmarks available
                      </div>
                    </div>
                    
                    <div v-if="monitorScopeTab === 'tags'" class="scope-tags-input">
                      <input 
                        type="text" 
                        class="form-control" 
                        v-model="monitorTagsInput"
                        placeholder="Enter tags separated by commas"
                        @blur="parseMonitorTags"
                      >
                      <div class="tags-display" v-if="profileForm.monitor_scope_tags?.length">
                        <span v-for="tag in profileForm.monitor_scope_tags" :key="tag" class="tag-badge">
                          {{ tag }}
                          <button type="button" @click="removeMonitorTag(tag)">×</button>
                        </span>
                      </div>
                    </div>
                  </div>
                </div>

                <!-- Email Recipients (Future) -->
                <div class="form-section">
                  <h6 class="section-title">Email Recipients <span class="badge bg-secondary">Coming Soon</span></h6>
                  <input 
                    type="text" 
                    class="form-control" 
                    v-model="emailsInput"
                    placeholder="email1@example.com, email2@example.com"
                    disabled
                  >
                  <small class="text-muted">Email delivery will be available in a future update</small>
                </div>
              </form>
            </div>
            <div class="modal-footer border-secondary">
              <button type="button" class="btn btn-secondary" @click="closeProfileModal">Cancel</button>
              <button type="button" class="btn btn-primary" @click="saveProfile" :disabled="saving || !profileForm.name">
                <span v-if="saving" class="spinner-border spinner-border-sm me-1"></span>
                {{ saving ? 'Saving...' : (editingProfile ? 'Update Profile' : 'Create Profile') }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Reports Modal -->
    <Teleport to="body">
      <div v-if="showReportsModal" class="modal-overlay" @click.self="closeReportsModal">
        <div class="modal-dialog-lg">
          <div class="modal-content bg-dark">
            <div class="modal-header border-secondary">
              <h5 class="modal-title">
                <span class="me-2">📊</span>
                Stat Reports - {{ viewingProfile?.name }}
              </h5>
              <button type="button" class="btn-close btn-close-white" @click="closeReportsModal"></button>
            </div>
            <div class="modal-body">
              <!-- Loading -->
              <div v-if="loadingReports" class="text-center py-4">
                <div class="spinner-border text-primary mb-2"></div>
                <div class="text-muted">Loading reports...</div>
              </div>

              <!-- Empty State -->
              <div v-else-if="profileReports.length === 0 && !viewingReport && !showPeriodSelector" class="text-center py-5">
                <div class="mb-3" style="font-size: 3rem">📋</div>
                <h5 class="text-muted">No reports generated yet</h5>
                <p class="text-secondary mb-4">Generate a stat report to see uptime, response times, and incident data.</p>
                <button class="btn btn-primary" @click="showPeriodSelector = true" :disabled="generatingReport">
                  <span v-if="generatingReport" class="spinner-border spinner-border-sm me-1"></span>
                  {{ generatingReport ? 'Generating...' : '⚡ Generate Stat Report' }}
                </button>
              </div>

              <!-- Period Selector -->
              <div v-else-if="showPeriodSelector && !viewingReport" class="period-selector">
                <div class="text-center mb-4">
                  <h5>Select Report Period</h5>
                  <p class="text-muted">Choose the time range for this stat report</p>
                </div>
                <div class="period-options">
                  <button 
                    class="period-option" 
                    @click="generateReportWithPeriod(7)"
                    :disabled="generatingReport"
                  >
                    <div class="period-icon">📅</div>
                    <div class="period-label">Weekly</div>
                    <div class="period-desc">Last 7 days</div>
                  </button>
                  <button 
                    class="period-option" 
                    @click="generateReportWithPeriod(30)"
                    :disabled="generatingReport"
                  >
                    <div class="period-icon">📆</div>
                    <div class="period-label">Monthly</div>
                    <div class="period-desc">Last 30 days</div>
                  </button>
                  <button 
                    class="period-option" 
                    @click="generateReportWithPeriod(90)"
                    :disabled="generatingReport"
                  >
                    <div class="period-icon">📊</div>
                    <div class="period-label">Quarterly</div>
                    <div class="period-desc">Last 90 days</div>
                  </button>
                  <button 
                    class="period-option" 
                    @click="generateReportWithPeriod(365)"
                    :disabled="generatingReport"
                  >
                    <div class="period-icon">📈</div>
                    <div class="period-label">Yearly</div>
                    <div class="period-desc">Last 365 days</div>
                  </button>
                </div>
                <div class="text-center mt-4">
                  <button class="btn btn-sm btn-outline-secondary" @click="showPeriodSelector = false">
                    Cancel
                  </button>
                </div>
                <div v-if="generatingReport" class="text-center mt-3">
                  <div class="spinner-border text-primary" role="status"></div>
                  <div class="text-muted mt-2">Generating report...</div>
                </div>
              </div>

              <!-- Reports List (when not viewing a report) -->
              <div v-else-if="!viewingReport && !showPeriodSelector" class="reports-list">
                <div class="d-flex justify-content-between align-items-center mb-3">
                  <span class="text-muted">{{ profileReports.length }} report(s)</span>
                  <button class="btn btn-sm btn-primary" @click="showPeriodSelector = true" :disabled="generatingReport">
                    <span v-if="generatingReport" class="spinner-border spinner-border-sm me-1"></span>
                    {{ generatingReport ? 'Generating...' : 'Generate Now' }}
                  </button>
                </div>
                
                <!-- Reports Table -->
                <div class="reports-table">
                  <div class="reports-table-header">
                    <div class="col-title">REPORT TITLE</div>
                    <div class="col-date">DATE CREATED</div>
                    <div class="col-type">TYPE</div>
                    <div class="col-actions">ACTIONS</div>
                  </div>
                  <div class="reports-table-body">
                    <div class="reports-table-row" v-for="report in profileReports" :key="report.id">
                      <div class="col-title">{{ report.title || 'Stat Report' }}</div>
                      <div class="col-date">{{ formatReportDate(report.created_at) }}</div>
                      <div class="col-type">
                        <span class="badge bg-info">Stat Report</span>
                      </div>
                      <div class="col-actions">
                        <button 
                          class="btn btn-sm btn-outline-primary me-2"
                          @click="viewReport(report)"
                        >
                          View
                        </button>
                        <button 
                          class="btn btn-sm btn-outline-success me-2"
                          @click="downloadReportPDF(report)"
                          :disabled="downloadingPDF"
                        >
                          <span v-if="downloadingPDF && downloadingReportId === report.id" class="spinner-border spinner-border-sm"></span>
                          <span v-else>Download</span>
                        </button>
                        <button 
                          class="btn btn-sm btn-outline-danger"
                          @click="deleteReport(report)"
                        >
                          Delete
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <!-- Stat Report Viewer - A4 Dark Theme for Email -->
              <div v-if="viewingReport" class="stat-report-viewer">
                <div class="d-flex justify-content-between align-items-center mb-3">
                  <button class="btn btn-sm btn-outline-secondary" @click="viewingReport = null">
                    ← Back to List
                  </button>
                  <button 
                    class="btn btn-sm btn-success"
                    @click="downloadCurrentReportPDF"
                    :disabled="downloadingPDF"
                  >
                    <span v-if="downloadingPDF" class="spinner-border spinner-border-sm me-1"></span>
                    {{ downloadingPDF ? 'Generating PDF...' : 'Download PDF' }}
                  </button>
                </div>
                
                <!-- A4 Report Container -->
                <div class="a4-report" ref="reportContainer">
                  <!-- Report Header -->
                  <div class="report-header">
                    <div class="report-brand">
                      <span class="report-icon">📊</span>
                      <span class="report-title-text">STAT REPORT</span>
                    </div>
                    <div class="report-profile-name">{{ viewingProfile?.name || 'Profile' }}</div>
                    <div class="report-period" v-if="viewingReport.report_data?.period">
                      {{ formatReportDateShort(viewingReport.report_data.period.start) }} — 
                      {{ formatReportDateShort(viewingReport.report_data.period.end) }}
                    </div>
                  </div>
                  
                  <!-- Summary Cards Row -->
                  <div class="summary-strip" v-if="viewingReport.report_data?.summary">
                    <div class="summary-item">
                      <div class="summary-value" :class="getUptimeClass(viewingReport.report_data.summary.global_uptime_percent)">
                        {{ viewingReport.report_data.summary.global_uptime_percent != null ? 
                           viewingReport.report_data.summary.global_uptime_percent + '%' : 'N/A' }}
                      </div>
                      <div class="summary-label">Uptime</div>
                    </div>
                    <div class="summary-item">
                      <div class="summary-value">{{ viewingReport.report_data.summary.total_scribes }}</div>
                      <div class="summary-label">Scribes</div>
                    </div>
                    <div class="summary-item">
                      <div class="summary-value">{{ viewingReport.report_data.summary.total_monitors }}</div>
                      <div class="summary-label">Bookmarks</div>
                    </div>
                    <div class="summary-item">
                      <div class="summary-value warning">{{ viewingReport.report_data.summary.total_incidents }}</div>
                      <div class="summary-label">Incidents</div>
                    </div>
                    <div class="summary-item">
                      <div class="summary-value">{{ viewingReport.report_data?.logs?.total_logs?.toLocaleString() || 0 }}</div>
                      <div class="summary-label">Logs</div>
                    </div>
                  </div>
                  
                  <!-- Two Column Layout: Scribes Left | Bookmarks Right -->
                  <div class="report-columns">
                    <!-- Scribes Column (Left) -->
                    <div class="report-column">
                      <div class="column-header">
                        <span class="column-icon">🖥️</span>
                        <span class="column-title">SCRIBES</span>
                      </div>
                      <table class="report-table" v-if="viewingReport.report_data?.scribes?.length">
                        <thead>
                          <tr>
                            <th>Name</th>
                            <th>OS</th>
                            <th>Logs</th>
                            <th>Uptime</th>
                            <th>Status</th>
                          </tr>
                        </thead>
                        <tbody>
                          <tr v-for="scribe in viewingReport.report_data.scribes" :key="scribe.agent_id">
                            <td class="name-cell">{{ scribe.name }}</td>
                            <td>{{ formatOS(scribe.os) }}</td>
                            <td>{{ (scribe.log_count || 0).toLocaleString() }}</td>
                            <td :class="getUptimeClass(scribe.uptime_percent)">
                              {{ scribe.uptime_percent != null ? scribe.uptime_percent + '%' : '-' }}
                            </td>
                            <td>
                              <span :class="'status-badge ' + (scribe.health || 'unknown')">
                                {{ scribe.health || scribe.status }}
                              </span>
                            </td>
                          </tr>
                        </tbody>
                      </table>
                      <div v-else class="no-data">No scribes in this profile</div>
                    </div>
                    
                    <!-- Bookmarks Column (Right) -->
                    <div class="report-column">
                      <div class="column-header">
                        <span class="column-icon">📌</span>
                        <span class="column-title">BOOKMARKS</span>
                      </div>
                      <table class="report-table" v-if="viewingReport.report_data?.monitors?.length">
                        <thead>
                          <tr>
                            <th>Name</th>
                            <th>Uptime</th>
                            <th>Resp</th>
                            <th>Inc</th>
                            <th>Status</th>
                          </tr>
                        </thead>
                        <tbody>
                          <tr v-for="monitor in viewingReport.report_data.monitors" :key="monitor.name">
                            <td class="name-cell">{{ monitor.name }}</td>
                            <td :class="getUptimeClass(monitor.uptime_percent)">
                              {{ monitor.uptime_percent != null ? monitor.uptime_percent + '%' : '-' }}
                            </td>
                            <td>{{ monitor.avg_response_ms != null ? monitor.avg_response_ms + 'ms' : '-' }}</td>
                            <td>{{ monitor.incidents }}</td>
                            <td>
                              <span :class="'status-badge ' + (monitor.health || 'unknown')">
                                {{ monitor.health }}
                              </span>
                            </td>
                          </tr>
                        </tbody>
                      </table>
                      <div v-else class="no-data">No bookmarks in this profile</div>
                    </div>
                  </div>
                  
                  <!-- Log Summary Footer -->
                  <div class="log-summary-footer" v-if="viewingReport.report_data?.logs">
                    <div class="log-summary-title">📝 LOG SUMMARY</div>
                    <div class="log-severity-badges">
                      <div class="severity-badge critical">
                        <span class="severity-count">{{ viewingReport.report_data.logs.critical_events }}</span>
                        <span class="severity-label">Critical</span>
                      </div>
                      <div class="severity-badge error">
                        <span class="severity-count">{{ viewingReport.report_data.logs.error_events }}</span>
                        <span class="severity-label">Errors</span>
                      </div>
                      <div class="severity-badge warning">
                        <span class="severity-count">{{ viewingReport.report_data.logs.warning_events }}</span>
                        <span class="severity-label">Warnings</span>
                      </div>
                      <div class="severity-badge info">
                        <span class="severity-count">{{ viewingReport.report_data.logs.info_events || 0 }}</span>
                        <span class="severity-label">Info</span>
                      </div>
                    </div>
                  </div>
                  
                  <!-- Report Footer -->
                  <div class="report-footer-bar">
                    <span>Log Librarian</span>
                    <span v-if="viewingReport.report_data?.period">
                      {{ viewingReport.report_data.period.days }} day report
                    </span>
                    <span>Generated {{ formatReportDate(viewingReport.created_at) }}</span>
                  </div>
                </div>
              </div>
            </div>
            <div class="modal-footer border-secondary">
              <button type="button" class="btn btn-secondary" @click="closeReportsModal">Close</button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>
    
    <!-- Delete Confirmation Modal -->
    <Teleport to="body">
      <div v-if="showDeleteConfirm" class="modal d-block delete-confirm-modal" tabindex="-1">
        <div class="modal-dialog modal-dialog-centered modal-sm">
          <div class="modal-content bg-dark text-light border-danger">
            <div class="modal-header border-danger">
              <h5 class="modal-title">🗑️ Delete Report</h5>
              <button type="button" class="btn-close btn-close-white" @click="cancelDelete"></button>
            </div>
            <div class="modal-body text-center">
              <p class="mb-2">Are you sure you want to delete this report?</p>
              <p class="text-muted small mb-0">{{ reportToDelete?.title || 'Stat Report' }}</p>
              <p class="text-danger small mt-2 mb-0">This cannot be undone.</p>
            </div>
            <div class="modal-footer border-danger justify-content-center">
              <button type="button" class="btn btn-secondary" @click="cancelDelete">Cancel</button>
              <button type="button" class="btn btn-danger" @click="confirmReportDelete" :disabled="deletingReport">
                <span v-if="deletingReport" class="spinner-border spinner-border-sm me-1"></span>
                {{ deletingReport ? 'Deleting...' : 'Delete' }}
              </button>
            </div>
          </div>
        </div>
      </div>
      <div v-if="showDeleteConfirm" class="modal-backdrop show delete-confirm-backdrop"></div>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onActivated, nextTick } from 'vue'
import api from '../api.js'
import { isAdmin } from '../auth.js'

// State
const profiles = ref([])
const loading = ref(false)
const searchQuery = ref('')
const deletingProfile = ref(null)
const deleting = ref(false)

// Delete report confirmation modal state
const showDeleteConfirm = ref(false)
const reportToDelete = ref(null)
const deletingReport = ref(false)

// Data for counting
const availableMonitors = ref([])
const availableLogSources = ref([])

// Create/Edit Profile Modal State
const showProfileModal = ref(false)
const editingProfile = ref(null)
const saving = ref(false)
const profileForm = ref({
  name: '',
  description: '',
  frequency: 'MONTHLY',
  schedule_hour: 7,
  sla_target: 99.9,
  recipient_emails: [],
  monitor_scope_tags: [],
  monitor_scope_ids: [],
  scribe_scope_tags: [],
  scribe_scope_ids: []
})
const scribeScopeTab = ref('all')
const monitorScopeTab = ref('all')
const scribeTagsInput = ref('')
const monitorTagsInput = ref('')
const emailsInput = ref('')

// Reports Modal State
const showReportsModal = ref(false)
const viewingProfile = ref(null)
const profileReports = ref([])
const loadingReports = ref(false)
const generatingReport = ref(false)
const viewingReport = ref(null)
const showPeriodSelector = ref(false)
const downloadingPDF = ref(false)
const downloadingReportId = ref(null)
const reportContainer = ref(null)

// Computed
const filteredProfiles = computed(() => {
  if (!searchQuery.value) return profiles.value
  const query = searchQuery.value.toLowerCase()
  return profiles.value.filter(p => 
    p.name?.toLowerCase().includes(query) ||
    p.description?.toLowerCase().includes(query)
  )
})

// Lifecycle
onMounted(() => {
  loadProfiles()
  loadAvailableData()
})

onActivated(() => {
  loadProfiles()
  loadAvailableData()
})

// Methods
async function loadProfiles() {
  loading.value = true
  try {
    const res = await api.get('/api/report-profiles')
    profiles.value = res.data?.data || res.data || []
  } catch (e) {
    console.error('Failed to load profiles:', e)
  } finally {
    loading.value = false
  }
}

async function loadAvailableData() {
  try {
    // Load bookmarks for counting
    const bookmarksRes = await api.get('/api/bookmarks')
    const bookmarks = bookmarksRes.data?.data || bookmarksRes.data || []
    availableMonitors.value = bookmarks.map(b => {
      let tags = b.tags || []
      if (typeof tags === 'string') {
        tags = tags.split(',').map(t => t.trim()).filter(t => t)
      }
      return { id: b.id, name: b.name || b.target || b.id, tags }
    })
    
    // Load agents for counting
    const agentsRes = await api.get('/api/agents')
    const agents = agentsRes.data?.agents || agentsRes.data || []
    availableLogSources.value = agents.map(a => {
      let tags = a.tags || []
      if (typeof tags === 'string') {
        tags = tags.split(',').map(t => t.trim()).filter(t => t)
      }
      return { id: a.agent_id, name: a.display_name || a.hostname || a.agent_id, tags }
    })
  } catch (e) {
    console.error('Failed to load available data:', e)
  }
}

function getBookmarkCount(profile) {
  const scopeIds = profile.monitor_scope_ids || []
  const scopeTags = profile.monitor_scope_tags || []
  
  if (!scopeIds.length && !scopeTags.length) {
    return 'All'
  }
  
  const matchedIds = new Set(scopeIds)
  for (const monitor of availableMonitors.value) {
    if (monitor.tags && scopeTags.some(tag => monitor.tags.includes(tag))) {
      matchedIds.add(monitor.id)
    }
  }
  
  return matchedIds.size || 'All'
}

function getScribeCount(profile) {
  const scopeIds = profile.scribe_scope_ids || []
  const scopeTags = profile.scribe_scope_tags || []
  
  if (!scopeIds.length && !scopeTags.length) {
    return 'All'
  }
  
  const matchedIds = new Set(scopeIds)
  for (const scribe of availableLogSources.value) {
    if (scribe.tags && scopeTags.some(tag => scribe.tags.includes(tag))) {
      matchedIds.add(scribe.id)
    }
  }
  
  return matchedIds.size || 'All'
}

function getFrequencyLabel(frequency) {
  const labels = {
    'DAILY': 'Daily',
    'WEEKLY': 'Weekly',
    'MONTHLY': 'Monthly',
    'QUARTERLY': 'Quarterly',
    'ANNUALLY': 'Annually',
    'MANUAL': 'Manual'
  }
  return labels[frequency] || frequency || 'Manual'
}

function getScheduleClass(frequency) {
  const classes = {
    'DAILY': 'schedule-daily',
    'WEEKLY': 'schedule-weekly',
    'MONTHLY': 'schedule-monthly',
    'QUARTERLY': 'schedule-quarterly',
    'ANNUALLY': 'schedule-annually',
    'MANUAL': 'schedule-manual'
  }
  return classes[frequency] || 'schedule-manual'
}

function getNextRun(profile) {
  if (!profile.frequency || profile.frequency === 'MANUAL') {
    return '—'
  }
  
  const now = new Date()
  const hour = profile.schedule_hour || 7
  let nextRun = new Date()
  nextRun.setHours(hour, 0, 0, 0)
  
  switch (profile.frequency) {
    case 'DAILY':
      if (nextRun <= now) nextRun.setDate(nextRun.getDate() + 1)
      break
    case 'WEEKLY':
      // Next Monday
      const daysUntilMonday = (8 - now.getDay()) % 7 || 7
      nextRun.setDate(now.getDate() + daysUntilMonday)
      if (nextRun <= now) nextRun.setDate(nextRun.getDate() + 7)
      break
    case 'MONTHLY':
      // 1st of next month
      nextRun = new Date(now.getFullYear(), now.getMonth() + 1, 1, hour, 0, 0)
      if (now.getDate() === 1 && now.getHours() < hour) {
        nextRun = new Date(now.getFullYear(), now.getMonth(), 1, hour, 0, 0)
      }
      break
    case 'QUARTERLY':
      // Next quarter start (Jan, Apr, Jul, Oct)
      const quarterMonths = [0, 3, 6, 9]
      const currentMonth = now.getMonth()
      let nextQuarterMonth = quarterMonths.find(m => m > currentMonth)
      if (nextQuarterMonth === undefined) {
        nextQuarterMonth = 0
        nextRun = new Date(now.getFullYear() + 1, 0, 1, hour, 0, 0)
      } else {
        nextRun = new Date(now.getFullYear(), nextQuarterMonth, 1, hour, 0, 0)
      }
      break
    case 'ANNUALLY':
      // Jan 1st next year
      nextRun = new Date(now.getFullYear() + 1, 0, 1, hour, 0, 0)
      if (now.getMonth() === 0 && now.getDate() === 1 && now.getHours() < hour) {
        nextRun = new Date(now.getFullYear(), 0, 1, hour, 0, 0)
      }
      break
  }
  
  return nextRun.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

function openCreateProfile() {
  editingProfile.value = null
  profileForm.value = {
    name: '',
    description: '',
    frequency: 'MONTHLY',
    schedule_hour: 7,
    sla_target: 99.9,
    recipient_emails: [],
    monitor_scope_tags: [],
    monitor_scope_ids: [],
    scribe_scope_tags: [],
    scribe_scope_ids: []
  }
  scribeScopeTab.value = 'all'
  monitorScopeTab.value = 'all'
  scribeTagsInput.value = ''
  monitorTagsInput.value = ''
  emailsInput.value = ''
  showProfileModal.value = true
}

function openEditProfile(profile) {
  editingProfile.value = profile
  profileForm.value = {
    name: profile.name || '',
    description: profile.description || '',
    frequency: profile.frequency || 'MONTHLY',
    schedule_hour: profile.schedule_hour ?? 7,
    sla_target: profile.sla_target ?? 99.9,
    recipient_emails: profile.recipient_emails || [],
    monitor_scope_tags: profile.monitor_scope_tags || [],
    monitor_scope_ids: profile.monitor_scope_ids || [],
    scribe_scope_tags: profile.scribe_scope_tags || [],
    scribe_scope_ids: profile.scribe_scope_ids || []
  }
  
  // Set scope tabs based on existing data
  if (profileForm.value.scribe_scope_ids?.length) {
    scribeScopeTab.value = 'select'
  } else if (profileForm.value.scribe_scope_tags?.length) {
    scribeScopeTab.value = 'tags'
    scribeTagsInput.value = profileForm.value.scribe_scope_tags.join(', ')
  } else {
    scribeScopeTab.value = 'all'
  }
  
  if (profileForm.value.monitor_scope_ids?.length) {
    monitorScopeTab.value = 'select'
  } else if (profileForm.value.monitor_scope_tags?.length) {
    monitorScopeTab.value = 'tags'
    monitorTagsInput.value = profileForm.value.monitor_scope_tags.join(', ')
  } else {
    monitorScopeTab.value = 'all'
  }
  
  emailsInput.value = profileForm.value.recipient_emails?.join(', ') || ''
  showProfileModal.value = true
}

function closeProfileModal() {
  showProfileModal.value = false
  editingProfile.value = null
}

async function saveProfile() {
  if (!profileForm.value.name) return
  
  saving.value = true
  try {
    // Build payload based on scope tabs
    const payload = {
      name: profileForm.value.name,
      description: profileForm.value.description || null,
      frequency: profileForm.value.frequency,
      schedule_hour: profileForm.value.schedule_hour,
      sla_target: profileForm.value.sla_target,
      recipient_emails: [],
      monitor_scope_tags: monitorScopeTab.value === 'tags' ? profileForm.value.monitor_scope_tags : [],
      monitor_scope_ids: monitorScopeTab.value === 'select' ? profileForm.value.monitor_scope_ids : [],
      scribe_scope_tags: scribeScopeTab.value === 'tags' ? profileForm.value.scribe_scope_tags : [],
      scribe_scope_ids: scribeScopeTab.value === 'select' ? profileForm.value.scribe_scope_ids : []
    }
    
    if (editingProfile.value) {
      // Update existing
      await api.put(`/api/report-profiles/${editingProfile.value.id}`, payload)
    } else {
      // Create new
      await api.post('/api/report-profiles', payload)
    }
    
    await loadProfiles()
    closeProfileModal()
  } catch (e) {
    console.error('Failed to save profile:', e)
    alert('Failed to save profile: ' + (e.response?.data?.detail || e.message))
  } finally {
    saving.value = false
  }
}

function formatHour(h) {
  if (h === 0) return '12:00 AM'
  if (h === 12) return '12:00 PM'
  if (h < 12) return `${h}:00 AM`
  return `${h - 12}:00 PM`
}

function parseScribeTags() {
  if (scribeTagsInput.value) {
    profileForm.value.scribe_scope_tags = scribeTagsInput.value
      .split(',')
      .map(t => t.trim())
      .filter(t => t)
  }
}

function parseMonitorTags() {
  if (monitorTagsInput.value) {
    profileForm.value.monitor_scope_tags = monitorTagsInput.value
      .split(',')
      .map(t => t.trim())
      .filter(t => t)
  }
}

function removeScribeTag(tag) {
  profileForm.value.scribe_scope_tags = profileForm.value.scribe_scope_tags.filter(t => t !== tag)
  scribeTagsInput.value = profileForm.value.scribe_scope_tags.join(', ')
}

function removeMonitorTag(tag) {
  profileForm.value.monitor_scope_tags = profileForm.value.monitor_scope_tags.filter(t => t !== tag)
  monitorTagsInput.value = profileForm.value.monitor_scope_tags.join(', ')
}

// Reports Modal Methods
async function openReportsModal(profile) {
  viewingProfile.value = profile
  viewingReport.value = null
  profileReports.value = []
  showReportsModal.value = true
  await loadProfileReports(profile.id)
}

function closeReportsModal() {
  showReportsModal.value = false
  viewingProfile.value = null
  viewingReport.value = null
  profileReports.value = []
  showPeriodSelector.value = false
}

async function loadProfileReports(profileId) {
  loadingReports.value = true
  try {
    const res = await api.get(`/api/report-profiles/${profileId}/reports`)
    profileReports.value = res.data?.reports || []
  } catch (e) {
    console.error('Failed to load reports:', e)
  } finally {
    loadingReports.value = false
  }
}

async function generateReportNow() {
  // Legacy - redirect to period selector
  showPeriodSelector.value = true
}

async function generateReportWithPeriod(days) {
  if (!viewingProfile.value) return
  
  generatingReport.value = true
  try {
    // Generate stat report using the new endpoint with selected period
    const res = await api.post(`/api/report-profiles/${viewingProfile.value.id}/generate-stats?days=${days}`)
    
    // If successful, show the generated report immediately
    if (res.data?.success && res.data?.data) {
      viewingReport.value = {
        id: res.data.report_id,
        title: `Stat Report - ${viewingProfile.value.name}`,
        created_at: new Date().toISOString(),
        type: 'stat_report',
        report_data: res.data.data
      }
      showPeriodSelector.value = false
    }
    
    // Also reload the reports list
    await loadProfileReports(viewingProfile.value.id)
  } catch (e) {
    console.error('Failed to generate report:', e)
    alert('Failed to generate report: ' + (e.response?.data?.detail || e.message))
  } finally {
    generatingReport.value = false
  }
}

function viewReport(report) {
  viewingReport.value = report
}

// PDF Download Functions
async function downloadReportPDF(report) {
  downloadingPDF.value = true
  downloadingReportId.value = report.id
  
  try {
    // First view the report to render it
    viewingReport.value = report
    
    // Wait for Vue to render
    await nextTick()
    
    // Small delay to ensure all content is rendered
    await new Promise(resolve => setTimeout(resolve, 100))
    
    // Generate PDF
    await generatePDF(report)
  } catch (e) {
    console.error('Failed to generate PDF:', e)
    alert('Failed to generate PDF: ' + e.message)
  } finally {
    downloadingPDF.value = false
    downloadingReportId.value = null
  }
}

async function downloadCurrentReportPDF() {
  if (!viewingReport.value) return
  
  downloadingPDF.value = true
  
  try {
    await generatePDF(viewingReport.value)
  } catch (e) {
    console.error('Failed to generate PDF:', e)
    alert('Failed to generate PDF: ' + e.message)
  } finally {
    downloadingPDF.value = false
  }
}

async function generatePDF(report) {
  const element = reportContainer.value
  if (!element) {
    throw new Error('Report container not found')
  }
  
  // Dynamic import of html2pdf
  const html2pdf = (await import('html2pdf.js')).default
  
  // Generate filename from report title or date
  const filename = (report.title || `StatReport_${formatReportDate(report.created_at)}`)
    .replace(/[^a-zA-Z0-9_-]/g, '_') + '.pdf'
  
  const opt = {
    margin: 10,
    filename: filename,
    image: { type: 'jpeg', quality: 0.98 },
    html2canvas: { 
      scale: 2,
      useCORS: true,
      logging: false,
      backgroundColor: '#1a1a2e'
    },
    jsPDF: { 
      unit: 'mm', 
      format: 'a4', 
      orientation: 'portrait' 
    },
    pagebreak: { mode: 'avoid-all' }
  }
  
  await html2pdf().set(opt).from(element).save()
}

function deleteReport(report) {
  reportToDelete.value = report
  showDeleteConfirm.value = true
}

function cancelDelete() {
  showDeleteConfirm.value = false
  reportToDelete.value = null
}

async function confirmReportDelete() {
  if (!reportToDelete.value) return
  
  deletingReport.value = true
  try {
    await api.delete(`/api/ai/reports/${reportToDelete.value.id}`)
    showDeleteConfirm.value = false
    reportToDelete.value = null
    // Reload the reports list
    if (viewingProfile.value) {
      await loadProfileReports(viewingProfile.value.id)
    }
  } catch (e) {
    console.error('Failed to delete report:', e)
    alert('Failed to delete report: ' + (e.response?.data?.detail || e.message))
  } finally {
    deletingReport.value = false
  }
}

// Helper functions for stat report styling
function getUptimeClass(uptime) {
  if (uptime == null) return ''
  if (uptime >= 99.9) return 'text-success'
  if (uptime >= 99) return 'text-warning'
  return 'text-danger'
}

function getSlaStatusClass(status) {
  if (status === 'MEETING') return 'badge bg-success ms-2'
  if (status === 'AT_RISK') return 'badge bg-warning ms-2'
  if (status === 'BELOW') return 'badge bg-danger ms-2'
  return 'badge bg-secondary ms-2'
}

function getHealthBadge(health) {
  if (health === 'healthy') return 'badge bg-success'
  if (health === 'degraded') return 'badge bg-warning'
  if (health === 'down') return 'badge bg-danger'
  return 'badge bg-secondary'
}

async function downloadPdf(report) {
  if (!viewingProfile.value) return
  
  try {
    const res = await api.get(
      `/api/report-profiles/${viewingProfile.value.id}/reports/${report.id}/pdf`,
      { responseType: 'blob' }
    )
    
    const blob = new Blob([res.data], { type: 'application/pdf' })
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${viewingProfile.value.name}_${report.id}.pdf`
    link.click()
    window.URL.revokeObjectURL(url)
  } catch (e) {
    console.error('Failed to download PDF:', e)
    alert('PDF not available for this report')
  }
}

function formatReportDate(dateStr) {
  if (!dateStr) return 'Unknown date'
  const d = new Date(dateStr)
  return d.toLocaleDateString('en-US', { 
    year: 'numeric', 
    month: 'short', 
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  })
}

function formatReportDateShort(dateStr) {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  return d.toLocaleDateString('en-US', { 
    year: 'numeric', 
    month: 'short', 
    day: 'numeric'
  })
}

function formatOS(os) {
  if (!os) return '-'
  // Shorten OS names for table display
  if (os.toLowerCase().includes('windows')) return 'Win'
  if (os.toLowerCase().includes('linux')) return 'Linux'
  if (os.toLowerCase().includes('darwin') || os.toLowerCase().includes('mac')) return 'Mac'
  return os.substring(0, 8)
}

function formatReportContent(content) {
  if (!content) return '<p class="text-muted">No content available</p>'
  // Convert markdown-style content to HTML (basic)
  return content
    .replace(/\n\n/g, '</p><p>')
    .replace(/\n/g, '<br>')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
}

function confirmDelete(profile) {
  deletingProfile.value = profile
}

async function deleteProfile() {
  if (!deletingProfile.value) return
  
  deleting.value = true
  try {
    await api.delete(`/api/report-profiles/${deletingProfile.value.id}`)
    profiles.value = profiles.value.filter(p => p.id !== deletingProfile.value.id)
    deletingProfile.value = null
  } catch (e) {
    console.error('Failed to delete profile:', e)
    alert('Failed to delete profile')
  } finally {
    deleting.value = false
  }
}
</script>

<style scoped>
.profiles-view {
  width: 100%;
}

/* Modern Header */
.profiles-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1.5rem;
  flex-wrap: wrap;
  gap: 1rem;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.page-title {
  font-size: 1.75rem;
  font-weight: 600;
  color: var(--text-primary, #fff);
  margin: 0;
}

.count-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 28px;
  height: 28px;
  padding: 0 0.5rem;
  background: rgba(99, 102, 241, 0.2);
  color: #818cf8;
  border-radius: 999px;
  font-size: 0.875rem;
  font-weight: 600;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

/* Search Input */
.search-wrapper {
  position: relative;
}

.search-input {
  padding: 0.5rem 0.75rem 0.5rem 2.25rem;
  background: rgba(30, 30, 46, 0.8);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  color: var(--text-primary, #fff);
  min-width: 220px;
  font-size: 0.875rem;
  transition: all 0.2s ease;
}

.search-input:focus {
  outline: none;
  border-color: rgba(99, 102, 241, 0.5);
  background: rgba(30, 30, 46, 1);
}

.search-input::placeholder {
  color: rgba(255, 255, 255, 0.4);
}

.search-icon {
  position: absolute;
  left: 0.75rem;
  top: 50%;
  transform: translateY(-50%);
  color: rgba(255, 255, 255, 0.4);
  pointer-events: none;
}

/* Content Area */
.profiles-content {
  background: transparent;
}

/* Empty State */
.empty-state {
  text-align: center;
  padding: 4rem 2rem;
}

.empty-icon {
  font-size: 3rem;
  margin-bottom: 1rem;
}

/* Modern Table */
.profiles-table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  background: rgba(30, 30, 46, 0.4);
  border-radius: 12px;
  overflow: hidden;
}

.profiles-table th {
  background: transparent;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  font-weight: 500;
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: rgba(255, 255, 255, 0.5);
  padding: 1rem;
}

.profiles-table td {
  padding: 1rem;
  vertical-align: middle;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  color: var(--text-primary, #fff);
}

.profiles-table tbody tr {
  transition: background 0.15s ease;
}

.profiles-table tbody tr:hover {
  background: rgba(255, 255, 255, 0.03);
}

.profiles-table tbody tr:last-child td {
  border-bottom: none;
}

/* Profile Name Cell */
.profile-name-cell {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.profile-name {
  font-weight: 500;
  color: var(--text-primary, #fff);
}

.profile-desc {
  font-size: 0.8rem;
  color: rgba(255, 255, 255, 0.4);
  max-width: 300px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Pill Badge */
.pill-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 32px;
  padding: 0.25rem 0.625rem;
  background: rgba(255, 255, 255, 0.08);
  color: rgba(255, 255, 255, 0.7);
  border-radius: 999px;
  font-size: 0.8rem;
  font-weight: 500;
}

/* Schedule Badge */
.schedule-badge {
  display: inline-block;
  padding: 0.25rem 0.625rem;
  border-radius: 6px;
  font-size: 0.75rem;
  font-weight: 500;
}

.schedule-weekly {
  background: rgba(59, 130, 246, 0.15);
  color: #60a5fa;
}

.schedule-monthly {
  background: rgba(34, 197, 94, 0.15);
  color: #4ade80;
}

.schedule-quarterly {
  background: rgba(168, 85, 247, 0.15);
  color: #c084fc;
}

.schedule-annually {
  background: rgba(234, 179, 8, 0.15);
  color: #fbbf24;
}

.schedule-daily {
  background: rgba(236, 72, 153, 0.15);
  color: #f472b6;
}

.schedule-manual {
  background: rgba(107, 114, 128, 0.15);
  color: #9ca3af;
}

/* Icon Action Buttons */
.action-buttons {
  display: flex;
  gap: 0.375rem;
  justify-content: center;
}

.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  padding: 0;
  border: none;
  border-radius: 6px;
  background: transparent;
  cursor: pointer;
  transition: all 0.15s ease;
}

.icon-btn svg {
  width: 16px;
  height: 16px;
}

.icon-btn-primary {
  color: rgba(96, 165, 250, 0.8);
}

.icon-btn-primary:hover {
  background: rgba(96, 165, 250, 0.15);
  color: #60a5fa;
}

.icon-btn-secondary {
  color: rgba(255, 255, 255, 0.5);
}

.icon-btn-secondary:hover {
  background: rgba(255, 255, 255, 0.1);
  color: rgba(255, 255, 255, 0.8);
}

.icon-btn-danger {
  color: rgba(248, 113, 113, 0.7);
}

.icon-btn-danger:hover {
  background: rgba(248, 113, 113, 0.15);
  color: #f87171;
}

/* Modal Styles */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1050;
  backdrop-filter: blur(4px);
}

.modal-dialog-centered {
  width: 100%;
  max-width: 500px;
  margin: 1rem;
}

.modal-dialog-lg {
  width: 100%;
  max-width: 900px;
  margin: 1rem;
  max-height: 90vh;
  overflow-y: auto;
}

.modal-content {
  border-radius: 8px;
  border: 1px solid var(--border-color, #444);
}

.modal-header {
  padding: 1rem 1.5rem;
}

.modal-body {
  padding: 1.5rem;
  max-height: 70vh;
  overflow-y: auto;
}

.modal-footer {
  padding: 1rem 1.5rem;
}

/* Form Sections */
.form-section {
  margin-bottom: 1.5rem;
  padding-bottom: 1.5rem;
  border-bottom: 1px solid var(--border-color, #333);
}

.form-section:last-child {
  border-bottom: none;
  margin-bottom: 0;
  padding-bottom: 0;
}

.section-title {
  color: var(--text-primary, #fff);
  font-weight: 600;
  margin-bottom: 1rem;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

/* Scope Selection */
.scope-selection {
  background: var(--bg-secondary, #2a2a2a);
  border-radius: 8px;
  padding: 1rem;
}

.scope-tabs {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 1rem;
}

.scope-tab {
  padding: 0.5rem 1rem;
  border: 1px solid var(--border-color, #444);
  background: transparent;
  color: var(--text-secondary, #aaa);
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.85rem;
  transition: all 0.2s;
}

.scope-tab:hover {
  border-color: var(--text-primary, #fff);
  color: var(--text-primary, #fff);
}

.scope-tab.active {
  background: var(--accent-color, #4a6cf7);
  border-color: var(--accent-color, #4a6cf7);
  color: white;
}

.scope-list {
  max-height: 200px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.scope-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem;
  background: var(--bg-tertiary, #1e1e1e);
  border-radius: 4px;
}

.scope-item input[type="checkbox"] {
  width: 16px;
  height: 16px;
}

.scope-item label {
  margin: 0;
  cursor: pointer;
  flex: 1;
  font-size: 0.9rem;
}

.scope-tags-input {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.tags-display {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.tag-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.25rem 0.5rem;
  background: var(--accent-color, #4a6cf7);
  color: white;
  border-radius: 4px;
  font-size: 0.8rem;
}

.tag-badge button {
  background: none;
  border: none;
  color: white;
  cursor: pointer;
  padding: 0;
  font-size: 1rem;
  line-height: 1;
  opacity: 0.7;
}

.tag-badge button:hover {
  opacity: 1;
}

/* Period Selector */
.period-selector {
  padding: 1rem;
}

.period-options {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1rem;
}

.period-option {
  background: var(--bg-secondary, #2a2a2a);
  border: 2px solid var(--border-color, #444);
  border-radius: 12px;
  padding: 1.5rem 1rem;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s ease;
  color: var(--text-primary, #fff);
}

.period-option:hover:not(:disabled) {
  border-color: var(--accent-color, #4a6cf7);
  background: rgba(74, 108, 247, 0.1);
  transform: translateY(-2px);
}

.period-option:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.period-icon {
  font-size: 2rem;
  margin-bottom: 0.5rem;
}

.period-label {
  font-size: 1.1rem;
  font-weight: 600;
  margin-bottom: 0.25rem;
}

.period-desc {
  font-size: 0.85rem;
  color: var(--text-secondary, #888);
}

/* Reports List */
.reports-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

/* Reports Table Styling */
.reports-table {
  background: var(--bg-secondary, #1e1e1e);
  border-radius: 8px;
  overflow: hidden;
}

.reports-table-header {
  display: grid;
  grid-template-columns: 2fr 1.5fr 1fr 1.5fr;
  padding: 0.75rem 1rem;
  background: var(--bg-tertiary, #252525);
  border-bottom: 1px solid var(--border-color, #333);
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--text-secondary, #888);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.reports-table-body {
  display: flex;
  flex-direction: column;
}

.reports-table-row {
  display: grid;
  grid-template-columns: 2fr 1.5fr 1fr 1.5fr;
  padding: 0.875rem 1rem;
  align-items: center;
  border-bottom: 1px solid var(--border-color, #333);
  transition: background 0.15s ease;
}

.reports-table-row:last-child {
  border-bottom: none;
}

.reports-table-row:hover {
  background: var(--bg-tertiary, #252525);
}

.reports-table-row .col-title {
  font-weight: 500;
  color: var(--text-primary, #fff);
}

.reports-table-row .col-date {
  color: var(--text-secondary, #aaa);
  font-size: 0.9rem;
}

.reports-table-row .col-type {
  font-size: 0.85rem;
}

.reports-table-row .col-actions {
  display: flex;
  gap: 0.5rem;
  justify-content: flex-end;
}

/* Report Viewer */
.report-viewer {
  background: var(--bg-secondary, #2a2a2a);
  border-radius: 8px;
  border: 1px solid var(--border-color, #333);
  overflow: hidden;
}

.report-viewer-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem;
  border-bottom: 1px solid var(--border-color, #333);
  background: var(--bg-tertiary, #1e1e1e);
}

.report-viewer-header h6 {
  margin: 0;
  color: var(--text-primary, #fff);
}

.report-content {
  padding: 1.5rem;
  max-height: 400px;
  overflow-y: auto;
  color: var(--text-primary, #ddd);
  line-height: 1.6;
}

.report-content p {
  margin-bottom: 1rem;
}

/* Stat Report Viewer Styles - A4 Dark Theme */
.stat-report-viewer {
  color: var(--text-primary, #fff);
}

/* A4 Report Container - ~210mm width scaled for screen */
.a4-report {
  max-width: 794px;
  margin: 0 auto;
  background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
  border-radius: 12px;
  border: 1px solid #2a2d4e;
  overflow: hidden;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
}

/* Report Header */
.report-header {
  background: linear-gradient(135deg, #0f3460 0%, #16213e 100%);
  padding: 1.5rem 2rem;
  text-align: center;
  border-bottom: 1px solid #2a2d4e;
}

.report-brand {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
}

.report-icon {
  font-size: 1.5rem;
}

.report-title-text {
  font-size: 0.9rem;
  font-weight: 600;
  letter-spacing: 3px;
  color: #64b5f6;
  text-transform: uppercase;
}

.report-profile-name {
  font-size: 1.5rem;
  font-weight: 700;
  color: #fff;
  margin-bottom: 0.25rem;
}

.report-period {
  font-size: 0.85rem;
  color: #8892b0;
}

/* Summary Strip */
.summary-strip {
  display: flex;
  justify-content: space-around;
  padding: 1rem 1.5rem;
  background: rgba(0, 0, 0, 0.2);
  border-bottom: 1px solid #2a2d4e;
}

.summary-item {
  text-align: center;
  padding: 0.5rem 1rem;
}

.summary-value {
  font-size: 1.75rem;
  font-weight: 700;
  color: #fff;
  line-height: 1.2;
}

.summary-value.warning {
  color: #ffc107;
}

.summary-value.text-success {
  color: #4caf50;
}

.summary-value.text-warning {
  color: #ff9800;
}

.summary-value.text-danger {
  color: #f44336;
}

.summary-label {
  font-size: 0.7rem;
  color: #8892b0;
  text-transform: uppercase;
  letter-spacing: 1px;
  margin-top: 0.25rem;
}

/* Two Column Layout */
.report-columns {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1px;
  background: #2a2d4e;
}

.report-column {
  background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
  padding: 1rem;
}

.column-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0;
  border-bottom: 1px solid #2a2d4e;
  margin-bottom: 0.75rem;
}

.column-icon {
  font-size: 1rem;
}

.column-title {
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 2px;
  color: #64b5f6;
  text-transform: uppercase;
}

/* Report Tables */
.report-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.8rem;
}

.report-table th {
  text-align: left;
  padding: 0.5rem 0.4rem;
  color: #8892b0;
  font-weight: 500;
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  border-bottom: 1px solid #2a2d4e;
}

.report-table td {
  padding: 0.5rem 0.4rem;
  color: #e0e0e0;
  border-bottom: 1px solid rgba(42, 45, 78, 0.5);
}

.report-table tr:last-child td {
  border-bottom: none;
}

.report-table .name-cell {
  font-weight: 500;
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Status Badges */
.status-badge {
  display: inline-block;
  padding: 0.15rem 0.4rem;
  border-radius: 4px;
  font-size: 0.65rem;
  font-weight: 600;
  text-transform: uppercase;
}

.status-badge.healthy {
  background: rgba(76, 175, 80, 0.2);
  color: #81c784;
}

.status-badge.unhealthy {
  background: rgba(255, 152, 0, 0.2);
  color: #ffb74d;
}

.status-badge.offline,
.status-badge.down {
  background: rgba(244, 67, 54, 0.2);
  color: #e57373;
}

.status-badge.degraded {
  background: rgba(255, 152, 0, 0.2);
  color: #ffb74d;
}

.status-badge.unknown {
  background: rgba(158, 158, 158, 0.2);
  color: #bdbdbd;
}

.status-badge.online {
  background: rgba(76, 175, 80, 0.2);
  color: #81c784;
}

.no-data {
  color: #8892b0;
  font-size: 0.85rem;
  text-align: center;
  padding: 1.5rem;
}

/* Log Summary Footer */
.log-summary-footer {
  padding: 1rem 1.5rem;
  background: rgba(0, 0, 0, 0.2);
  border-top: 1px solid #2a2d4e;
}

.log-summary-title {
  font-size: 0.7rem;
  font-weight: 600;
  letter-spacing: 2px;
  color: #64b5f6;
  text-transform: uppercase;
  margin-bottom: 0.75rem;
  text-align: center;
}

.log-severity-badges {
  display: flex;
  justify-content: center;
  gap: 1.5rem;
}

.severity-badge {
  text-align: center;
}

.severity-count {
  display: block;
  font-size: 1.25rem;
  font-weight: 700;
  line-height: 1.2;
}

.severity-label {
  display: block;
  font-size: 0.65rem;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-top: 0.2rem;
}

.severity-badge.critical .severity-count,
.severity-badge.critical .severity-label {
  color: #e57373;
}

.severity-badge.error .severity-count,
.severity-badge.error .severity-label {
  color: #ffb74d;
}

.severity-badge.warning .severity-count,
.severity-badge.warning .severity-label {
  color: #fff176;
}

.severity-badge.info .severity-count,
.severity-badge.info .severity-label {
  color: #64b5f6;
}

/* Report Footer Bar */
.report-footer-bar {
  display: flex;
  justify-content: space-between;
  padding: 0.75rem 1.5rem;
  background: #0f0f1a;
  font-size: 0.7rem;
  color: #5c6370;
}

/* Responsive adjustments */
@media (max-width: 700px) {
  .report-columns {
    grid-template-columns: 1fr;
  }
  
  .summary-strip {
    flex-wrap: wrap;
    gap: 0.5rem;
  }
  
  .summary-item {
    flex: 0 0 calc(33% - 0.5rem);
  }
}

/* Delete Confirmation Modal - Higher z-index to appear above stat report modal */
.delete-confirm-modal {
  z-index: 1060 !important;
}

.delete-confirm-backdrop {
  z-index: 1055 !important;
}
</style>
