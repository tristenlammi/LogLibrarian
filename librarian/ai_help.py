"""
AI Help & Documentation Module

Provides in-app help and documentation for the AI Librarian:
- Example queries and templates
- Feature documentation
- Tips and best practices
- Interactive help system
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field


# ==================== EXAMPLE QUERIES ====================

@dataclass
class ExampleQuery:
    """An example query with description"""
    query: str
    description: str
    category: str
    tags: List[str] = field(default_factory=list)
    difficulty: str = "beginner"  # beginner, intermediate, advanced


EXAMPLE_QUERIES: List[ExampleQuery] = [
    # ===== Scribe Status =====
    ExampleQuery(
        query="What scribes are currently offline?",
        description="Check which log collection agents are disconnected",
        category="scribe_status",
        tags=["scribes", "status", "offline"],
        difficulty="beginner"
    ),
    ExampleQuery(
        query="Show me the status of all scribes",
        description="Get an overview of all agents with their connection status",
        category="scribe_status",
        tags=["scribes", "status", "overview"],
        difficulty="beginner"
    ),
    ExampleQuery(
        query="Which servers haven't checked in for more than an hour?",
        description="Find agents that may be having connectivity issues",
        category="scribe_status",
        tags=["scribes", "connectivity", "timeout"],
        difficulty="intermediate"
    ),
    ExampleQuery(
        query="How long has prod-web-01 been online?",
        description="Check the uptime for a specific server",
        category="scribe_status",
        tags=["scribes", "uptime", "specific"],
        difficulty="beginner"
    ),
    
    # ===== Logs & Errors =====
    ExampleQuery(
        query="Show recent errors",
        description="View the most recent error-level log entries",
        category="logs",
        tags=["logs", "errors", "recent"],
        difficulty="beginner"
    ),
    ExampleQuery(
        query="What errors occurred in the last hour?",
        description="Time-bounded error search",
        category="logs",
        tags=["logs", "errors", "time"],
        difficulty="beginner"
    ),
    ExampleQuery(
        query="Search for 'connection refused' in logs",
        description="Search for a specific error message",
        category="logs",
        tags=["logs", "search", "specific"],
        difficulty="beginner"
    ),
    ExampleQuery(
        query="Show warning and error logs from yesterday",
        description="View multiple log levels for a past time period",
        category="logs",
        tags=["logs", "multi-level", "time"],
        difficulty="intermediate"
    ),
    ExampleQuery(
        query="What were the most common errors last week?",
        description="Analyze error patterns over time",
        category="logs",
        tags=["logs", "analysis", "patterns"],
        difficulty="advanced"
    ),
    
    # ===== Metrics & Performance =====
    ExampleQuery(
        query="How is CPU usage on the web servers?",
        description="Check CPU metrics for a group of servers",
        category="metrics",
        tags=["metrics", "cpu", "performance"],
        difficulty="beginner"
    ),
    ExampleQuery(
        query="What's the memory usage trend?",
        description="View memory utilization patterns",
        category="metrics",
        tags=["metrics", "memory", "trends"],
        difficulty="intermediate"
    ),
    ExampleQuery(
        query="Show disk space usage for prod servers",
        description="Check storage metrics for production systems",
        category="metrics",
        tags=["metrics", "disk", "storage"],
        difficulty="beginner"
    ),
    ExampleQuery(
        query="Are any servers running low on memory?",
        description="Find systems with high memory utilization",
        category="metrics",
        tags=["metrics", "memory", "alerts"],
        difficulty="intermediate"
    ),
    ExampleQuery(
        query="Compare CPU usage between this week and last week",
        description="Historical metric comparison",
        category="metrics",
        tags=["metrics", "comparison", "historical"],
        difficulty="advanced"
    ),
    
    # ===== Alerts =====
    ExampleQuery(
        query="Are there any active alerts?",
        description="Check for currently firing alerts",
        category="alerts",
        tags=["alerts", "active", "status"],
        difficulty="beginner"
    ),
    ExampleQuery(
        query="What alerts triggered in the last 24 hours?",
        description="Review recent alert history",
        category="alerts",
        tags=["alerts", "history", "time"],
        difficulty="beginner"
    ),
    ExampleQuery(
        query="Show me critical alerts",
        description="Filter alerts by severity",
        category="alerts",
        tags=["alerts", "critical", "severity"],
        difficulty="beginner"
    ),
    ExampleQuery(
        query="Which servers have the most alerts?",
        description="Identify problematic systems by alert count",
        category="alerts",
        tags=["alerts", "analysis", "ranking"],
        difficulty="intermediate"
    ),
    
    # ===== Bookmarks & Servers =====
    ExampleQuery(
        query="List all monitored servers",
        description="View all bookmarked servers and their groups",
        category="bookmarks",
        tags=["bookmarks", "servers", "list"],
        difficulty="beginner"
    ),
    ExampleQuery(
        query="What servers are in the production group?",
        description="Filter servers by bookmark group",
        category="bookmarks",
        tags=["bookmarks", "groups", "filter"],
        difficulty="beginner"
    ),
    ExampleQuery(
        query="Show me all database servers",
        description="Find servers by type or role",
        category="bookmarks",
        tags=["bookmarks", "search", "role"],
        difficulty="intermediate"
    ),
    
    # ===== Complex Queries =====
    ExampleQuery(
        query="What happened on the web servers yesterday around 3pm?",
        description="Investigate a specific time period for a server group",
        category="investigation",
        tags=["investigation", "time", "specific"],
        difficulty="intermediate"
    ),
    ExampleQuery(
        query="Why did prod-app-02 go offline last night?",
        description="Investigate a specific incident",
        category="investigation",
        tags=["investigation", "incident", "root-cause"],
        difficulty="advanced"
    ),
    ExampleQuery(
        query="Give me a health summary for all production servers",
        description="Comprehensive status report for a server group",
        category="summary",
        tags=["summary", "health", "comprehensive"],
        difficulty="intermediate"
    ),
    ExampleQuery(
        query="What's the overall system health right now?",
        description="Quick overview of entire infrastructure",
        category="summary",
        tags=["summary", "overview", "status"],
        difficulty="beginner"
    ),
]


# ==================== FEATURE DOCUMENTATION ====================

@dataclass
class FeatureDoc:
    """Documentation for a feature"""
    title: str
    description: str
    capabilities: List[str]
    limitations: List[str] = field(default_factory=list)
    tips: List[str] = field(default_factory=list)


FEATURE_DOCS: Dict[str, FeatureDoc] = {
    "natural_language": FeatureDoc(
        title="Natural Language Queries",
        description="Ask questions in plain English - no special syntax required.",
        capabilities=[
            "Understands relative time expressions ('last hour', 'yesterday', '2 days ago')",
            "Recognizes server names even with partial matches",
            "Interprets common synonyms ('machines' = 'servers' = 'scribes')",
            "Handles multi-part questions"
        ],
        limitations=[
            "Very ambiguous questions may need clarification",
            "Cannot understand context from previous conversations (yet)"
        ],
        tips=[
            "Be specific about time ranges for better results",
            "Use server names or groups when asking about specific systems",
            "Start with simple questions before complex investigations"
        ]
    ),
    
    "log_analysis": FeatureDoc(
        title="Log Analysis",
        description="Search and analyze log entries across all monitored servers.",
        capabilities=[
            "Full-text search across all logs",
            "Filter by log level (error, warning, info, debug)",
            "Time-based filtering with natural language",
            "Pattern detection for common errors"
        ],
        limitations=[
            "Very large time ranges may take longer to process",
            "Some log formats may not be fully parsed"
        ],
        tips=[
            "Search for specific error messages in quotes",
            "Use log levels to narrow down results",
            "Combine time filters with log levels for focused searches"
        ]
    ),
    
    "metrics_monitoring": FeatureDoc(
        title="Metrics Monitoring",
        description="Query CPU, memory, disk, and network metrics from your servers.",
        capabilities=[
            "Real-time metric queries",
            "Historical trend analysis",
            "Multi-server comparisons",
            "Anomaly detection for unusual values"
        ],
        limitations=[
            "Metric history depends on retention settings",
            "Very fine-grained queries (per-second) may have gaps"
        ],
        tips=[
            "Ask about trends to see patterns over time",
            "Specify server names for targeted queries",
            "Ask 'is anything unusual?' for anomaly detection"
        ]
    ),
    
    "alerts": FeatureDoc(
        title="Alert Management",
        description="Query and analyze alerts from your monitoring system.",
        capabilities=[
            "View active alerts",
            "Review alert history",
            "Filter by severity (critical, warning, info)",
            "Identify alert patterns"
        ],
        limitations=[
            "Cannot modify alert rules (view only)",
            "Alert acknowledgment requires dashboard"
        ],
        tips=[
            "Check active alerts regularly",
            "Use severity filters to prioritize",
            "Ask about alert patterns to identify recurring issues"
        ]
    ),
    
    "scribes": FeatureDoc(
        title="Scribe (Agent) Status",
        description="Monitor the health and status of log collection agents.",
        capabilities=[
            "Check online/offline status",
            "View agent uptime",
            "Monitor agent versions",
            "Detect connectivity issues"
        ],
        limitations=[
            "Cannot restart agents remotely",
            "Agent configuration changes require console access"
        ],
        tips=[
            "Check for offline scribes daily",
            "Monitor uptime to detect restart issues",
            "Ask about scribes that haven't checked in recently"
        ]
    ),
    
    "proactive_insights": FeatureDoc(
        title="Proactive Insights",
        description="AI-generated insights about your infrastructure without having to ask.",
        capabilities=[
            "Automatic anomaly detection",
            "Trend analysis and predictions",
            "Correlation detection between events",
            "Suggested actions based on current state"
        ],
        limitations=[
            "Insights are suggestions, not definitive answers",
            "May miss very subtle patterns"
        ],
        tips=[
            "Check insights regularly for early warning signs",
            "Follow up on anomalies with specific questions",
            "Use suggested actions as starting points"
        ]
    ),
}


# ==================== TIPS & BEST PRACTICES ====================

TIPS: List[Dict[str, str]] = [
    {
        "title": "Start Simple",
        "tip": "Begin with straightforward questions like 'What scribes are offline?' before asking complex multi-part questions.",
        "category": "getting_started"
    },
    {
        "title": "Use Time Expressions",
        "tip": "I understand natural time expressions like 'last hour', 'yesterday afternoon', '2 days ago', and 'this morning'.",
        "category": "time"
    },
    {
        "title": "Be Specific",
        "tip": "The more specific your question, the better my answer. 'Show errors from prod-web-01 in the last hour' is better than 'show errors'.",
        "category": "queries"
    },
    {
        "title": "Name Your Servers",
        "tip": "I can recognize server names even with partial matches. Just say the server name and I'll find it.",
        "category": "servers"
    },
    {
        "title": "Ask Follow-Up Questions",
        "tip": "If my first answer doesn't give you what you need, ask a follow-up question with more details.",
        "category": "workflow"
    },
    {
        "title": "Check Insights",
        "tip": "Review the proactive insights panel for automatically detected anomalies and trends.",
        "category": "insights"
    },
    {
        "title": "Use Log Levels",
        "tip": "Filter logs by level: 'show only errors', 'warnings and above', 'debug logs from server X'.",
        "category": "logs"
    },
    {
        "title": "Request Summaries",
        "tip": "For large result sets, ask me to 'summarize' or give you 'the highlights'.",
        "category": "summaries"
    },
    {
        "title": "Investigate Incidents",
        "tip": "Describe what happened and when: 'Why did the website slow down yesterday at 3pm?'",
        "category": "investigation"
    },
    {
        "title": "Compare Time Periods",
        "tip": "Ask me to compare metrics between time periods: 'Compare CPU usage this week vs last week'.",
        "category": "comparison"
    },
]


# ==================== HELP SERVICE ====================

class HelpService:
    """
    Service for providing help and documentation.
    """
    
    def __init__(self):
        self.examples = EXAMPLE_QUERIES
        self.features = FEATURE_DOCS
        self.tips = TIPS
    
    def get_examples(
        self,
        category: str = None,
        difficulty: str = None,
        tag: str = None,
        limit: int = 10
    ) -> List[ExampleQuery]:
        """Get example queries, optionally filtered"""
        examples = self.examples
        
        if category:
            examples = [e for e in examples if e.category == category]
        
        if difficulty:
            examples = [e for e in examples if e.difficulty == difficulty]
        
        if tag:
            examples = [e for e in examples if tag in e.tags]
        
        return examples[:limit]
    
    def get_categories(self) -> List[Dict[str, Any]]:
        """Get all example categories with counts"""
        categories = {}
        for example in self.examples:
            if example.category not in categories:
                categories[example.category] = {
                    "name": example.category,
                    "count": 0,
                    "examples": []
                }
            categories[example.category]["count"] += 1
            categories[example.category]["examples"].append(example.query)
        
        return list(categories.values())
    
    def get_feature_docs(self, feature: str = None) -> Dict[str, FeatureDoc]:
        """Get feature documentation"""
        if feature:
            return {feature: self.features.get(feature)} if feature in self.features else {}
        return self.features
    
    def get_tips(self, category: str = None, random: bool = False) -> List[Dict[str, str]]:
        """Get tips, optionally filtered by category"""
        tips = self.tips
        
        if category:
            tips = [t for t in tips if t["category"] == category]
        
        if random:
            import random as rand
            return [rand.choice(tips)] if tips else []
        
        return tips
    
    def get_quick_start_guide(self) -> Dict[str, Any]:
        """Get a quick start guide for new users"""
        return {
            "welcome": "Welcome to the AI Librarian! I can help you monitor your servers and analyze logs.",
            "getting_started": [
                "Ask 'What scribes are online?' to see your server status",
                "Ask 'Show recent errors' to check for problems",
                "Ask 'How is CPU usage?' to view metrics",
                "Ask 'Are there any alerts?' to check alerts"
            ],
            "example_queries": [e.query for e in self.get_examples(difficulty="beginner", limit=5)],
            "features": list(self.features.keys()),
            "tip": self.get_tips(random=True)[0] if self.tips else None
        }
    
    def search_help(self, query: str) -> Dict[str, Any]:
        """Search help content for relevant information"""
        query_lower = query.lower()
        results = {
            "examples": [],
            "features": [],
            "tips": []
        }
        
        # Search examples
        for example in self.examples:
            if (query_lower in example.query.lower() or 
                query_lower in example.description.lower() or
                any(query_lower in tag for tag in example.tags)):
                results["examples"].append(example)
        
        # Search features
        for key, feature in self.features.items():
            if (query_lower in feature.title.lower() or
                query_lower in feature.description.lower() or
                any(query_lower in cap.lower() for cap in feature.capabilities)):
                results["features"].append(feature)
        
        # Search tips
        for tip in self.tips:
            if (query_lower in tip["title"].lower() or
                query_lower in tip["tip"].lower()):
                results["tips"].append(tip)
        
        return results
    
    def get_contextual_help(self, context: str) -> Dict[str, Any]:
        """Get help relevant to the current context"""
        context_lower = context.lower()
        
        # Determine relevant category based on context
        category = None
        if any(word in context_lower for word in ['scribe', 'agent', 'online', 'offline', 'status']):
            category = 'scribe_status'
        elif any(word in context_lower for word in ['log', 'error', 'warning', 'message']):
            category = 'logs'
        elif any(word in context_lower for word in ['cpu', 'memory', 'disk', 'metric', 'performance']):
            category = 'metrics'
        elif any(word in context_lower for word in ['alert', 'notification', 'alarm']):
            category = 'alerts'
        elif any(word in context_lower for word in ['server', 'bookmark', 'group']):
            category = 'bookmarks'
        
        return {
            "suggested_examples": [e.query for e in self.get_examples(category=category, limit=3)],
            "relevant_tips": self.get_tips(category=category.split('_')[0] if category else None),
            "feature": self.features.get(category.replace('_status', 's') if category else None)
        }


# ==================== FORMAT HELP FOR DISPLAY ====================

class HelpFormatter:
    """Format help content for display"""
    
    @staticmethod
    def format_examples_markdown(examples: List[ExampleQuery]) -> str:
        """Format examples as markdown"""
        lines = ["## Example Queries\n"]
        
        current_category = None
        for example in examples:
            if example.category != current_category:
                current_category = example.category
                lines.append(f"\n### {current_category.replace('_', ' ').title()}\n")
            
            lines.append(f"- **\"{example.query}\"**")
            lines.append(f"  - {example.description}")
        
        return "\n".join(lines)
    
    @staticmethod
    def format_feature_markdown(feature: FeatureDoc) -> str:
        """Format a feature as markdown"""
        lines = [f"## {feature.title}\n"]
        lines.append(f"{feature.description}\n")
        
        lines.append("\n### What I Can Do\n")
        for cap in feature.capabilities:
            lines.append(f"- {cap}")
        
        if feature.limitations:
            lines.append("\n### Limitations\n")
            for lim in feature.limitations:
                lines.append(f"- {lim}")
        
        if feature.tips:
            lines.append("\n### Tips\n")
            for tip in feature.tips:
                lines.append(f"- 💡 {tip}")
        
        return "\n".join(lines)
    
    @staticmethod
    def format_quick_start_markdown(guide: Dict[str, Any]) -> str:
        """Format quick start guide as markdown"""
        lines = [
            "# 🤖 AI Librarian Quick Start\n",
            guide["welcome"],
            "\n## Getting Started\n"
        ]
        
        for step in guide["getting_started"]:
            lines.append(f"1. {step}")
        
        lines.append("\n## Try These Examples\n")
        for example in guide["example_queries"]:
            lines.append(f"- \"{example}\"")
        
        if guide.get("tip"):
            lines.append(f"\n💡 **Tip:** {guide['tip']['tip']}")
        
        return "\n".join(lines)


# ==================== MODULE SINGLETON ====================

_help_service: HelpService = None


def get_help_service() -> HelpService:
    """Get the global help service instance"""
    global _help_service
    if _help_service is None:
        _help_service = HelpService()
    return _help_service
