<template>
  <div class="latency-chart-container">
    <Line 
      v-if="chartData.labels.length > 0"
      :data="chartData" 
      :options="chartOptions" 
    />
    <div v-else class="no-data">
      <span>📊</span>
      <p>No latency data available</p>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Line } from 'vue-chartjs'
import { formatTime } from '../utils/timezone.js'
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler
} from 'chart.js'

// Register Chart.js components
ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler
)

const props = defineProps({
  checks: {
    type: Array,
    default: () => []
  },
  hours: {
    type: Number,
    default: 24
  }
})

// Filter and prepare chart data
const chartData = computed(() => {
  const checks = props.checks || []
  
  // Filter only successful checks (status = 1) for latency chart
  const validChecks = checks
    .filter(c => c.status === 1 && c.latency_ms !== null)
    .slice(0, 200) // Limit data points
    .reverse() // Oldest first for chart
  
  const labels = validChecks.map(c => {
    return formatTime(c.created_at, {
      hour: '2-digit',
      minute: '2-digit'
    })
  })
  
  const data = validChecks.map(c => c.latency_ms)
  
  return {
    labels,
    datasets: [
      {
        label: 'Latency (ms)',
        data,
        fill: true,
        backgroundColor: (context) => {
          const chart = context.chart
          const { ctx, chartArea } = chart
          if (!chartArea) return 'rgba(74, 222, 128, 0.1)'
          
          const gradient = ctx.createLinearGradient(0, chartArea.bottom, 0, chartArea.top)
          gradient.addColorStop(0, 'rgba(74, 222, 128, 0)')
          gradient.addColorStop(0.5, 'rgba(74, 222, 128, 0.1)')
          gradient.addColorStop(1, 'rgba(74, 222, 128, 0.3)')
          return gradient
        },
        borderColor: '#4ade80',
        borderWidth: 2,
        tension: 0.4,
        pointRadius: 0,
        pointHoverRadius: 6,
        pointHoverBackgroundColor: '#4ade80',
        pointHoverBorderColor: '#fff',
        pointHoverBorderWidth: 2
      }
    ]
  }
})

// Chart options
const chartOptions = computed(() => ({
  responsive: true,
  maintainAspectRatio: false,
  interaction: {
    mode: 'index',
    intersect: false
  },
  plugins: {
    legend: {
      display: false
    },
    tooltip: {
      backgroundColor: '#1f2937',
      titleColor: '#9ca3af',
      bodyColor: '#fff',
      borderColor: '#374151',
      borderWidth: 1,
      padding: 12,
      displayColors: false,
      titleFont: {
        size: 11
      },
      bodyFont: {
        size: 14,
        weight: 'bold'
      },
      callbacks: {
        title: (items) => items[0]?.label || '',
        label: (item) => `${item.raw} ms`
      }
    }
  },
  scales: {
    x: {
      display: true,
      grid: {
        display: false,
        drawBorder: false
      },
      ticks: {
        color: '#6b7280',
        font: {
          size: 10
        },
        maxRotation: 0,
        autoSkip: true,
        maxTicksLimit: 8
      },
      border: {
        display: false
      }
    },
    y: {
      display: true,
      position: 'right',
      grid: {
        color: 'rgba(75, 85, 99, 0.2)',
        drawBorder: false
      },
      ticks: {
        color: '#6b7280',
        font: {
          size: 10
        },
        padding: 8,
        callback: (value) => `${value}ms`
      },
      border: {
        display: false
      },
      min: 0
    }
  }
}))
</script>

<style scoped>
.latency-chart-container {
  width: 100%;
  height: 200px;
  position: relative;
}

.no-data {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-secondary);
}

.no-data span {
  font-size: 2rem;
  margin-bottom: 0.5rem;
  opacity: 0.5;
}

.no-data p {
  margin: 0;
  font-size: 0.875rem;
}
</style>
