"""
AI Proactive Insights Module

Provides proactive intelligence features:
- Anomaly detection in metrics and logs
- Trend analysis over time
- Correlation detection between events
- "Did you know?" suggestions
- Predictive warnings
"""

import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


# ==================== DATA CLASSES ====================

@dataclass
class Anomaly:
    """A detected anomaly"""
    entity: str  # Scribe or bookmark name
    metric: str  # e.g., 'cpu', 'memory', 'response_time'
    severity: str  # 'low', 'medium', 'high', 'critical'
    current_value: float
    expected_range: Tuple[float, float]
    detected_at: datetime
    description: str
    
    def to_markdown(self) -> str:
        severity_icons = {
            'low': '🔵',
            'medium': '🟡',
            'high': '🟠',
            'critical': '🔴'
        }
        icon = severity_icons.get(self.severity, '⚪')
        return f"{icon} **{self.entity}**: {self.description} (current: {self.current_value:.1f}, expected: {self.expected_range[0]:.1f}-{self.expected_range[1]:.1f})"


@dataclass
class Trend:
    """A detected trend"""
    entity: str
    metric: str
    direction: str  # 'increasing', 'decreasing', 'stable'
    rate: float  # Change per hour
    period: str  # Time period analyzed
    significance: str  # 'minor', 'notable', 'significant', 'critical'
    prediction: Optional[str] = None
    
    def to_markdown(self) -> str:
        arrows = {
            'increasing': '📈',
            'decreasing': '📉',
            'stable': '➡️'
        }
        arrow = arrows.get(self.direction, '•')
        msg = f"{arrow} **{self.entity}** {self.metric} is {self.direction}"
        if self.rate:
            msg += f" ({abs(self.rate):.1f}/hour)"
        if self.prediction:
            msg += f". {self.prediction}"
        return msg


@dataclass
class Correlation:
    """A detected correlation between events"""
    event_a: str
    event_b: str
    correlation_type: str  # 'temporal', 'causal', 'coincident'
    confidence: float  # 0.0 to 1.0
    description: str
    
    def to_markdown(self) -> str:
        return f"🔗 **Correlation detected**: {self.description} (confidence: {self.confidence:.0%})"


@dataclass
class InsightSuggestion:
    """A 'Did you know?' style suggestion"""
    category: str  # 'optimization', 'health', 'usage', 'tip'
    title: str
    message: str
    action: Optional[str] = None
    
    def to_markdown(self) -> str:
        icons = {
            'optimization': '💡',
            'health': '❤️',
            'usage': '📊',
            'tip': '✨'
        }
        icon = icons.get(self.category, '💡')
        result = f"{icon} **{self.title}**: {self.message}"
        if self.action:
            result += f"\n   → *Suggestion*: {self.action}"
        return result


# ==================== ANOMALY DETECTOR ====================

class AnomalyDetector:
    """
    Detects anomalies in metrics using statistical methods.
    
    Uses:
    - Z-score for single point anomalies
    - Rolling statistics for trend anomalies
    - Threshold-based alerts for critical values
    """
    
    # Critical thresholds (absolute values that are always concerning)
    CRITICAL_THRESHOLDS = {
        'cpu_percent': {'warning': 80, 'critical': 95},
        'memory_percent': {'warning': 85, 'critical': 95},
        'disk_percent': {'warning': 85, 'critical': 95},
        'response_time_ms': {'warning': 3000, 'critical': 10000}
    }
    
    def __init__(self, sensitivity: float = 2.0):
        """
        Args:
            sensitivity: Z-score threshold for anomaly detection (default 2.0 = ~95% confidence)
        """
        self.sensitivity = sensitivity
    
    def detect_metric_anomaly(
        self,
        current_value: float,
        historical_values: List[float],
        metric_name: str,
        entity_name: str
    ) -> Optional[Anomaly]:
        """
        Detect if a current metric value is anomalous.
        
        Args:
            current_value: The current metric value
            historical_values: Recent historical values for comparison
            metric_name: Name of the metric (e.g., 'cpu_percent')
            entity_name: Name of the entity (e.g., scribe hostname)
            
        Returns:
            Anomaly if detected, None otherwise
        """
        # Check critical thresholds first
        if metric_name in self.CRITICAL_THRESHOLDS:
            thresholds = self.CRITICAL_THRESHOLDS[metric_name]
            if current_value >= thresholds.get('critical', 999):
                return Anomaly(
                    entity=entity_name,
                    metric=metric_name,
                    severity='critical',
                    current_value=current_value,
                    expected_range=(0, thresholds['warning']),
                    detected_at=datetime.now(),
                    description=f"{metric_name} at critical level"
                )
            elif current_value >= thresholds.get('warning', 999):
                return Anomaly(
                    entity=entity_name,
                    metric=metric_name,
                    severity='high',
                    current_value=current_value,
                    expected_range=(0, thresholds['warning']),
                    detected_at=datetime.now(),
                    description=f"{metric_name} elevated"
                )
        
        # Statistical anomaly detection
        if len(historical_values) < 5:
            return None  # Not enough data
        
        mean = sum(historical_values) / len(historical_values)
        variance = sum((x - mean) ** 2 for x in historical_values) / len(historical_values)
        std_dev = math.sqrt(variance) if variance > 0 else 0.01
        
        z_score = abs(current_value - mean) / std_dev
        
        if z_score >= self.sensitivity * 2:
            severity = 'critical' if z_score >= self.sensitivity * 3 else 'high'
        elif z_score >= self.sensitivity:
            severity = 'medium'
        else:
            return None  # Not anomalous
        
        direction = "above" if current_value > mean else "below"
        
        return Anomaly(
            entity=entity_name,
            metric=metric_name,
            severity=severity,
            current_value=current_value,
            expected_range=(mean - std_dev, mean + std_dev),
            detected_at=datetime.now(),
            description=f"{metric_name} is {direction} normal (z-score: {z_score:.1f})"
        )
    
    def detect_scribe_anomalies(
        self,
        current: Dict[str, Any],
        history: List[Dict[str, Any]] = None
    ) -> List[Anomaly]:
        """
        Detect anomalies in a scribe's current state.
        
        Args:
            current: Current scribe state
            history: Optional historical metrics
            
        Returns:
            List of detected anomalies
        """
        anomalies = []
        hostname = current.get('hostname', 'Unknown')
        
        # Check each metric
        for metric in ['cpu_percent', 'memory_percent', 'disk_percent']:
            current_value = current.get(metric)
            if current_value is None:
                continue
            
            historical = []
            if history:
                historical = [h.get(metric) for h in history if h.get(metric) is not None]
            
            anomaly = self.detect_metric_anomaly(
                current_value, historical, metric, hostname
            )
            if anomaly:
                anomalies.append(anomaly)
        
        return anomalies


# ==================== TREND ANALYZER ====================

class TrendAnalyzer:
    """
    Analyzes trends in time-series data.
    
    Uses linear regression to detect:
    - Increasing/decreasing trends
    - Rate of change
    - Projected future values
    """
    
    def analyze_metric_trend(
        self,
        values: List[Tuple[datetime, float]],
        metric_name: str,
        entity_name: str
    ) -> Optional[Trend]:
        """
        Analyze trend in metric values over time.
        
        Args:
            values: List of (timestamp, value) tuples, sorted by time
            metric_name: Name of the metric
            entity_name: Name of the entity
            
        Returns:
            Trend if significant trend detected, None otherwise
        """
        if len(values) < 10:
            return None  # Need enough data points
        
        # Convert to hours from start for regression
        start_time = values[0][0]
        x = [(t - start_time).total_seconds() / 3600 for t, v in values]
        y = [v for t, v in values]
        
        # Simple linear regression
        n = len(x)
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(x[i] * y[i] for i in range(n))
        sum_xx = sum(x[i] ** 2 for i in range(n))
        
        denominator = n * sum_xx - sum_x ** 2
        if denominator == 0:
            return None
        
        slope = (n * sum_xy - sum_x * sum_y) / denominator
        
        # Calculate R-squared for significance
        mean_y = sum_y / n
        ss_tot = sum((yi - mean_y) ** 2 for yi in y)
        intercept = (sum_y - slope * sum_x) / n
        ss_res = sum((y[i] - (slope * x[i] + intercept)) ** 2 for i in range(n))
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
        
        # Determine trend direction and significance
        if abs(slope) < 0.1:
            direction = 'stable'
            significance = 'minor'
        else:
            direction = 'increasing' if slope > 0 else 'decreasing'
            if r_squared > 0.8:
                significance = 'significant'
            elif r_squared > 0.5:
                significance = 'notable'
            else:
                significance = 'minor'
        
        # Only report notable+ trends
        if significance == 'minor':
            return None
        
        # Calculate period
        hours = (values[-1][0] - values[0][0]).total_seconds() / 3600
        period = f"past {hours:.0f} hours" if hours < 24 else f"past {hours/24:.1f} days"
        
        # Make prediction if significant
        prediction = None
        if significance == 'significant' and abs(slope) > 1:
            current = values[-1][1]
            # Project 4 hours forward
            projected = current + slope * 4
            
            if metric_name == 'disk_percent' and projected > 95:
                prediction = f"At current rate, disk may reach 95% in ~{(95 - current) / slope:.1f} hours"
            elif metric_name == 'memory_percent' and projected > 90:
                prediction = f"Memory trending toward {projected:.0f}% in ~4 hours"
        
        return Trend(
            entity=entity_name,
            metric=metric_name,
            direction=direction,
            rate=slope,
            period=period,
            significance=significance,
            prediction=prediction
        )


# ==================== CORRELATION DETECTOR ====================

class CorrelationDetector:
    """
    Detects correlations between events.
    
    Looks for:
    - Temporal correlations (events happening around same time)
    - Resource correlations (CPU spikes when disk I/O spikes)
    - Alert-log correlations (alerts correlating with error logs)
    """
    
    def __init__(self, time_window: timedelta = timedelta(minutes=5)):
        self.time_window = time_window
    
    def detect_temporal_correlation(
        self,
        events_a: List[Dict],
        events_b: List[Dict],
        label_a: str = "Event A",
        label_b: str = "Event B"
    ) -> Optional[Correlation]:
        """
        Detect if events A and B occur together in time.
        """
        if not events_a or not events_b:
            return None
        
        # Extract timestamps
        def get_time(event):
            ts = event.get('timestamp') or event.get('created_at') or event.get('triggered_at')
            if isinstance(ts, str):
                return datetime.fromisoformat(ts.replace('Z', '+00:00'))
            return ts
        
        times_a = [get_time(e) for e in events_a if get_time(e)]
        times_b = [get_time(e) for e in events_b if get_time(e)]
        
        if not times_a or not times_b:
            return None
        
        # Count co-occurrences within time window
        co_occurrences = 0
        for ta in times_a:
            for tb in times_b:
                if ta and tb and abs((ta - tb).total_seconds()) <= self.time_window.total_seconds():
                    co_occurrences += 1
                    break
        
        # Calculate correlation strength
        if len(times_a) == 0:
            return None
        
        correlation_rate = co_occurrences / len(times_a)
        
        if correlation_rate < 0.3:
            return None
        
        confidence = min(correlation_rate, 0.95)
        
        return Correlation(
            event_a=label_a,
            event_b=label_b,
            correlation_type='temporal',
            confidence=confidence,
            description=f"{label_a} often occurs with {label_b} ({co_occurrences} times within {self.time_window.seconds//60} minutes)"
        )
    
    def detect_metric_correlation(
        self,
        metrics: List[Dict],
        metric_a: str,
        metric_b: str
    ) -> Optional[Correlation]:
        """
        Detect if two metrics correlate (e.g., CPU and disk I/O).
        """
        if len(metrics) < 10:
            return None
        
        values_a = [m.get(metric_a) for m in metrics if m.get(metric_a) is not None]
        values_b = [m.get(metric_b) for m in metrics if m.get(metric_b) is not None]
        
        if len(values_a) != len(values_b) or len(values_a) < 10:
            return None
        
        # Calculate Pearson correlation coefficient
        n = len(values_a)
        mean_a = sum(values_a) / n
        mean_b = sum(values_b) / n
        
        numerator = sum((values_a[i] - mean_a) * (values_b[i] - mean_b) for i in range(n))
        
        sum_sq_a = sum((v - mean_a) ** 2 for v in values_a)
        sum_sq_b = sum((v - mean_b) ** 2 for v in values_b)
        
        denominator = math.sqrt(sum_sq_a * sum_sq_b)
        if denominator == 0:
            return None
        
        r = numerator / denominator
        
        # Only report strong correlations
        if abs(r) < 0.7:
            return None
        
        direction = "positively" if r > 0 else "negatively"
        
        return Correlation(
            event_a=metric_a,
            event_b=metric_b,
            correlation_type='metric',
            confidence=abs(r),
            description=f"{metric_a} and {metric_b} are {direction} correlated"
        )


# ==================== SUGGESTION GENERATOR ====================

class SuggestionGenerator:
    """
    Generates "Did you know?" style proactive suggestions.
    """
    
    def generate_scribe_suggestions(
        self,
        scribes: List[Dict],
        alerts: List[Dict] = None,
        logs_summary: Dict = None
    ) -> List[InsightSuggestion]:
        """Generate suggestions based on scribe state"""
        suggestions = []
        
        if not scribes:
            return suggestions
        
        # Check for offline scribes
        offline = [s for s in scribes if not s.get('is_online')]
        if offline:
            suggestions.append(InsightSuggestion(
                category='health',
                title='Offline Agents',
                message=f"{len(offline)} agent(s) are currently offline: {', '.join(s.get('hostname', 'Unknown') for s in offline[:3])}",
                action='Check network connectivity and service status'
            ))
        
        # Check for resource patterns
        high_cpu = [s for s in scribes if s.get('cpu_percent', 0) > 70 and s.get('is_online')]
        if len(high_cpu) > 1:
            suggestions.append(InsightSuggestion(
                category='optimization',
                title='Multiple High-CPU Systems',
                message=f"{len(high_cpu)} systems have elevated CPU (>70%)",
                action='Consider load balancing or scheduling resource-intensive tasks at different times'
            ))
        
        # Check for disk space patterns
        low_disk = [s for s in scribes if s.get('disk_percent', 0) > 80 and s.get('is_online')]
        if low_disk:
            suggestions.append(InsightSuggestion(
                category='health',
                title='Disk Space Warning',
                message=f"{len(low_disk)} system(s) have less than 20% free disk space",
                action='Plan for cleanup or storage expansion'
            ))
        
        return suggestions
    
    def generate_usage_insights(
        self,
        query_stats: Dict,
        time_range: str = "today"
    ) -> List[InsightSuggestion]:
        """Generate insights about system usage"""
        suggestions = []
        
        # Could analyze common queries, peak times, etc.
        # This is a placeholder for usage analytics
        
        return suggestions
    
    def generate_tip(self) -> InsightSuggestion:
        """Generate a helpful tip about using the Librarian"""
        tips = [
            InsightSuggestion(
                category='tip',
                title='Quick Health Check',
                message='Ask "What\'s the system health?" for a quick overview of all scribes'
            ),
            InsightSuggestion(
                category='tip',
                title='Time-Based Queries',
                message='You can ask about specific times like "What happened yesterday at 3pm?"'
            ),
            InsightSuggestion(
                category='tip',
                title='Error Analysis',
                message='Ask "Show recent errors" to see error patterns across all systems'
            ),
            InsightSuggestion(
                category='tip',
                title='Scribe Comparison',
                message='Compare systems by asking "Which scribe has the highest CPU usage?"'
            )
        ]
        import random
        return random.choice(tips)


# ==================== PROACTIVE INSIGHTS SERVICE ====================

class ProactiveInsights:
    """
    Main service for proactive intelligence features.
    """
    
    def __init__(self):
        self.anomaly_detector = AnomalyDetector()
        self.trend_analyzer = TrendAnalyzer()
        self.correlation_detector = CorrelationDetector()
        self.suggestion_generator = SuggestionGenerator()
    
    async def analyze_current_state(
        self,
        db_manager,
        tenant_id: str = None
    ) -> Dict[str, Any]:
        """
        Analyze current system state and return proactive insights.
        
        Returns dict with:
        - anomalies: List of detected anomalies
        - trends: List of detected trends
        - correlations: List of detected correlations
        - suggestions: List of proactive suggestions
        """
        import asyncio
        
        insights = {
            'anomalies': [],
            'trends': [],
            'correlations': [],
            'suggestions': []
        }
        
        try:
            # Get current scribe states
            scribes = await asyncio.get_event_loop().run_in_executor(
                None, lambda: db_manager.get_agents(tenant_id=tenant_id)
            )
            
            # Detect anomalies in current state
            for scribe in scribes:
                if scribe.get('is_online'):
                    anomalies = self.anomaly_detector.detect_scribe_anomalies(scribe)
                    insights['anomalies'].extend(anomalies)
            
            # Generate suggestions
            suggestions = self.suggestion_generator.generate_scribe_suggestions(scribes)
            insights['suggestions'].extend(suggestions)
            
            # Add a random tip
            tip = self.suggestion_generator.generate_tip()
            insights['suggestions'].append(tip)
            
        except Exception as e:
            logger.error(f"Error analyzing current state: {e}")
        
        return insights
    
    def format_insights_summary(self, insights: Dict[str, Any]) -> str:
        """Format insights as markdown summary"""
        lines = []
        
        if insights.get('anomalies'):
            lines.append("## ⚠️ Anomalies Detected")
            for a in insights['anomalies'][:5]:
                lines.append(a.to_markdown())
            lines.append("")
        
        if insights.get('trends'):
            lines.append("## 📈 Trends")
            for t in insights['trends'][:3]:
                lines.append(t.to_markdown())
            lines.append("")
        
        if insights.get('correlations'):
            lines.append("## 🔗 Correlations")
            for c in insights['correlations'][:3]:
                lines.append(c.to_markdown())
            lines.append("")
        
        if insights.get('suggestions'):
            lines.append("## 💡 Insights")
            for s in insights['suggestions'][:3]:
                lines.append(s.to_markdown())
            lines.append("")
        
        return "\n".join(lines) if lines else "No significant insights at this time."


# ==================== MODULE SINGLETON ====================

_insights: ProactiveInsights = None


def get_proactive_insights() -> ProactiveInsights:
    """Get the global proactive insights instance"""
    global _insights
    if _insights is None:
        _insights = ProactiveInsights()
    return _insights
