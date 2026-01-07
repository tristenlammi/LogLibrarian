<template>
  <div class="coming-soon-container">
    <div class="coming-soon-content">
      <div class="coming-soon-icon">🤖</div>
      <h2>Librarian AI</h2>
      <h3>Coming Soon</h3>
      <p>An intelligent AI assistant that understands your infrastructure, analyzes logs, and helps you troubleshoot issues.</p>
      <div class="coming-soon-features">
        <div class="feature-badge">💬 Natural Language Queries</div>
        <div class="feature-badge">🔍 Log Analysis</div>
        <div class="feature-badge">📊 Anomaly Detection</div>
        <div class="feature-badge">🛠️ Troubleshooting Assistance</div>
        <div class="feature-badge">📈 Trend Insights</div>
        <div class="feature-badge">🔒 100% Local & Private</div>
      </div>
    </div>
  </div>
</template>

<script setup>
</script>

<style scoped>
.coming-soon-container {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: calc(100vh - 120px);
  padding: 2rem;
}

.coming-soon-content {
  text-align: center;
  max-width: 600px;
}

.coming-soon-icon {
  font-size: 5rem;
  margin-bottom: 1rem;
}

.coming-soon-content h2 {
  font-size: 2rem;
  color: var(--text-primary, #fff);
  margin-bottom: 0.5rem;
}

.coming-soon-content h3 {
  font-size: 1.5rem;
  color: var(--accent-color, #007bff);
  margin-bottom: 1rem;
}

.coming-soon-content p {
  color: var(--text-secondary, #888);
  font-size: 1.1rem;
  margin-bottom: 2rem;
  line-height: 1.6;
}

.coming-soon-features {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  justify-content: center;
}

.feature-badge {
  padding: 0.6rem 1.2rem;
  background: var(--bg-tertiary, #2a2a2a);
  border: 1px solid var(--border-color, #404040);
  border-radius: 25px;
  color: var(--text-secondary, #aaa);
  font-size: 0.9rem;
}
</style>