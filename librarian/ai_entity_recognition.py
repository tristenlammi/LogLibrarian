"""
AI Entity Recognition Module

Provides intelligent entity recognition for user queries:
- Scribe/Agent name matching (fuzzy matching, aliases)
- Bookmark name recognition
- Time expression parsing ("yesterday", "last week", "3pm")
- Ambiguity detection and resolution

This module preprocesses user queries to extract entities before
sending to the AI, improving accuracy and reducing hallucination.
"""

import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from difflib import SequenceMatcher
import logging

logger = logging.getLogger(__name__)


# ==================== DATA CLASSES ====================

@dataclass
class RecognizedEntity:
    """A recognized entity from user input"""
    entity_type: str  # 'scribe', 'bookmark', 'time', 'severity', 'metric'
    original_text: str  # The text that was matched
    resolved_value: Any  # The resolved ID, name, or datetime
    confidence: float  # 0.0 to 1.0
    alternatives: List[Any] = field(default_factory=list)  # Other possible matches
    
    def is_ambiguous(self) -> bool:
        """Returns True if multiple good alternatives exist"""
        return len(self.alternatives) > 0 and self.confidence < 0.9


@dataclass
class TimeRange:
    """Represents a resolved time range"""
    start: datetime
    end: datetime
    description: str  # Human-readable description
    
    def to_dict(self) -> dict:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "description": self.description
        }


@dataclass
class EntityExtractionResult:
    """Result of entity extraction from a query"""
    scribes: List[RecognizedEntity] = field(default_factory=list)
    bookmarks: List[RecognizedEntity] = field(default_factory=list)
    time_ranges: List[RecognizedEntity] = field(default_factory=list)
    severities: List[str] = field(default_factory=list)
    metrics: List[str] = field(default_factory=list)
    has_ambiguity: bool = False
    ambiguity_message: Optional[str] = None
    
    def get_scribe_ids(self) -> List[str]:
        """Get resolved scribe IDs"""
        return [e.resolved_value for e in self.scribes if e.confidence >= 0.7]
    
    def get_bookmark_ids(self) -> List[int]:
        """Get resolved bookmark IDs"""
        return [e.resolved_value for e in self.bookmarks if e.confidence >= 0.7]
    
    def get_time_range(self) -> Optional[TimeRange]:
        """Get the primary time range if any"""
        if self.time_ranges:
            return self.time_ranges[0].resolved_value
        return None
    
    def to_context_dict(self) -> dict:
        """Convert to context dictionary for AI prompt enhancement"""
        context = {}
        
        if self.scribes:
            context["detected_scribes"] = [
                {"name": e.original_text, "id": e.resolved_value, "confidence": e.confidence}
                for e in self.scribes
            ]
        
        if self.bookmarks:
            context["detected_bookmarks"] = [
                {"name": e.original_text, "id": e.resolved_value, "confidence": e.confidence}
                for e in self.bookmarks
            ]
        
        if self.time_ranges:
            tr = self.time_ranges[0].resolved_value
            context["detected_time_range"] = tr.to_dict()
        
        if self.severities:
            context["detected_severities"] = self.severities
        
        if self.metrics:
            context["detected_metrics"] = self.metrics
        
        return context


# ==================== TIME PARSER ====================

class TimeExpressionParser:
    """
    Parses natural language time expressions into datetime ranges.
    
    Supports:
    - Relative times: "now", "today", "yesterday", "last week"
    - Relative durations: "past hour", "last 30 minutes", "past 7 days"
    - Specific times: "3pm", "14:30", "3:15pm"
    - Specific dates: "January 5", "Jan 5th", "1/5"
    - Combined: "yesterday at 3pm", "last Tuesday morning"
    """
    
    # Relative time patterns
    RELATIVE_PATTERNS = {
        r'\bnow\b': lambda: (datetime.now() - timedelta(minutes=5), datetime.now(), "now"),
        r'\btoday\b': lambda: (datetime.now().replace(hour=0, minute=0, second=0), 
                               datetime.now(), "today"),
        r'\byesterday\b': lambda: ((datetime.now() - timedelta(days=1)).replace(hour=0, minute=0, second=0),
                                   (datetime.now() - timedelta(days=1)).replace(hour=23, minute=59, second=59),
                                   "yesterday"),
        r'\blast\s+night\b': lambda: ((datetime.now() - timedelta(days=1)).replace(hour=20, minute=0, second=0),
                                      datetime.now().replace(hour=6, minute=0, second=0),
                                      "last night"),
        r'\bthis\s+morning\b': lambda: (datetime.now().replace(hour=6, minute=0, second=0),
                                        datetime.now().replace(hour=12, minute=0, second=0) if datetime.now().hour >= 12 
                                        else datetime.now(),
                                        "this morning"),
        r'\bthis\s+week\b': lambda: (datetime.now() - timedelta(days=datetime.now().weekday()),
                                     datetime.now(), "this week"),
        r'\blast\s+week\b': lambda: (datetime.now() - timedelta(days=datetime.now().weekday() + 7),
                                     datetime.now() - timedelta(days=datetime.now().weekday()),
                                     "last week"),
        r'\bthis\s+month\b': lambda: (datetime.now().replace(day=1, hour=0, minute=0, second=0),
                                      datetime.now(), "this month"),
    }
    
    # Duration patterns: "past X hours/minutes/days"
    DURATION_PATTERN = re.compile(
        r'(?:past|last|previous)\s+(\d+)\s*(minute|min|hour|hr|day|week|month)s?',
        re.IGNORECASE
    )
    
    # Time of day patterns: "3pm", "14:30", "3:15 pm"
    TIME_PATTERN = re.compile(
        r'\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b',
        re.IGNORECASE
    )
    
    # Day of week patterns
    DAYS_OF_WEEK = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    
    def parse(self, text: str, reference_time: datetime = None) -> Optional[TimeRange]:
        """
        Parse a time expression from text.
        
        Args:
            text: The text containing time expressions
            reference_time: Reference time for relative expressions (default: now)
            
        Returns:
            TimeRange if a time expression was found, None otherwise
        """
        text_lower = text.lower()
        ref = reference_time or datetime.now()
        
        # Check duration patterns first (most specific)
        duration_match = self.DURATION_PATTERN.search(text_lower)
        if duration_match:
            amount = int(duration_match.group(1))
            unit = duration_match.group(2).lower()
            
            if unit in ('minute', 'min'):
                delta = timedelta(minutes=amount)
            elif unit in ('hour', 'hr'):
                delta = timedelta(hours=amount)
            elif unit == 'day':
                delta = timedelta(days=amount)
            elif unit == 'week':
                delta = timedelta(weeks=amount)
            elif unit == 'month':
                delta = timedelta(days=amount * 30)  # Approximate
            else:
                delta = timedelta(hours=1)
            
            return TimeRange(
                start=ref - delta,
                end=ref,
                description=f"past {amount} {unit}{'s' if amount > 1 else ''}"
            )
        
        # Check relative patterns
        for pattern, resolver in self.RELATIVE_PATTERNS.items():
            if re.search(pattern, text_lower):
                start, end, desc = resolver()
                return TimeRange(start=start, end=end, description=desc)
        
        # Check for day of week: "last Tuesday", "on Monday"
        for i, day in enumerate(self.DAYS_OF_WEEK):
            if re.search(rf'\b(?:last\s+)?{day}\b', text_lower):
                # Calculate the date of that day
                current_dow = ref.weekday()
                target_dow = i
                days_ago = (current_dow - target_dow) % 7
                if days_ago == 0 and 'last' in text_lower:
                    days_ago = 7
                
                target_date = ref - timedelta(days=days_ago)
                return TimeRange(
                    start=target_date.replace(hour=0, minute=0, second=0),
                    end=target_date.replace(hour=23, minute=59, second=59),
                    description=f"last {day.capitalize()}" if days_ago > 0 else day.capitalize()
                )
        
        # Check for specific time patterns and combine with date context
        time_match = self.TIME_PATTERN.search(text_lower)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2)) if time_match.group(2) else 0
            ampm = time_match.group(3)
            
            if ampm:
                if ampm.lower() == 'pm' and hour < 12:
                    hour += 12
                elif ampm.lower() == 'am' and hour == 12:
                    hour = 0
            
            # Determine the date context
            if 'yesterday' in text_lower:
                base_date = ref - timedelta(days=1)
            else:
                base_date = ref
            
            target_time = base_date.replace(hour=hour, minute=minute, second=0)
            
            # Create a window around that time (±30 minutes)
            return TimeRange(
                start=target_time - timedelta(minutes=30),
                end=target_time + timedelta(minutes=30),
                description=f"around {target_time.strftime('%I:%M %p')}"
            )
        
        return None


# ==================== ENTITY MATCHER ====================

class EntityMatcher:
    """
    Fuzzy matches entity names from user queries.
    
    Uses:
    - Exact matching
    - Case-insensitive matching
    - Substring matching
    - Fuzzy string matching (Levenshtein-like)
    - Alias/nickname matching
    """
    
    # Common aliases for severity levels
    SEVERITY_ALIASES = {
        'error': ['error', 'errors', 'err', 'failed', 'failure', 'failures', 'crash', 'crashes'],
        'warning': ['warning', 'warnings', 'warn', 'warns', 'caution'],
        'info': ['info', 'information', 'informational'],
        'debug': ['debug', 'debugging', 'trace'],
        'critical': ['critical', 'crit', 'fatal', 'emergency', 'severe']
    }
    
    # Common metric aliases
    METRIC_ALIASES = {
        'cpu': ['cpu', 'processor', 'processing'],
        'memory': ['memory', 'ram', 'mem'],
        'disk': ['disk', 'storage', 'hdd', 'ssd', 'drive'],
        'network': ['network', 'net', 'bandwidth', 'traffic'],
        'disk_read': ['disk read', 'read', 'reading'],
        'disk_write': ['disk write', 'write', 'writing']
    }
    
    def __init__(self):
        self._scribe_cache: Dict[str, List[Dict]] = {}  # tenant_id -> scribes
        self._bookmark_cache: Dict[str, List[Dict]] = {}  # tenant_id -> bookmarks
        self._cache_time: datetime = None
        self._cache_ttl = timedelta(minutes=5)
    
    def _similarity(self, s1: str, s2: str) -> float:
        """Calculate string similarity (0.0 to 1.0)"""
        return SequenceMatcher(None, s1.lower(), s2.lower()).ratio()
    
    def _is_cache_valid(self) -> bool:
        """Check if cache is still valid"""
        if self._cache_time is None:
            return False
        return datetime.now() - self._cache_time < self._cache_ttl
    
    async def refresh_cache(self, db_manager, tenant_id: str = None):
        """Refresh the entity cache from database"""
        try:
            # Get all scribes
            scribes = await asyncio.get_event_loop().run_in_executor(
                None, lambda: db_manager.get_agents(tenant_id=tenant_id)
            )
            cache_key = tenant_id or "default"
            self._scribe_cache[cache_key] = scribes
            
            # Get all bookmarks
            bookmarks = await asyncio.get_event_loop().run_in_executor(
                None, lambda: db_manager.get_bookmarks(tenant_id=tenant_id)
            )
            self._bookmark_cache[cache_key] = bookmarks
            
            self._cache_time = datetime.now()
            logger.debug(f"Entity cache refreshed: {len(scribes)} scribes, {len(bookmarks)} bookmarks")
            
        except Exception as e:
            logger.error(f"Failed to refresh entity cache: {e}")
    
    def match_scribe(self, query: str, tenant_id: str = None) -> List[RecognizedEntity]:
        """
        Match scribe names in a query.
        
        Args:
            query: The user's query text
            tenant_id: Optional tenant filter
            
        Returns:
            List of recognized scribe entities
        """
        cache_key = tenant_id or "default"
        scribes = self._scribe_cache.get(cache_key, [])
        
        if not scribes:
            return []
        
        results = []
        query_lower = query.lower()
        query_words = set(re.findall(r'\b\w+\b', query_lower))
        
        for scribe in scribes:
            hostname = scribe.get('hostname', '')
            agent_id = scribe.get('agent_id', '')
            
            if not hostname:
                continue
            
            hostname_lower = hostname.lower()
            
            # Exact match
            if hostname_lower in query_lower:
                results.append(RecognizedEntity(
                    entity_type='scribe',
                    original_text=hostname,
                    resolved_value=agent_id,
                    confidence=1.0
                ))
                continue
            
            # Word match (hostname appears as a word)
            if hostname_lower in query_words:
                results.append(RecognizedEntity(
                    entity_type='scribe',
                    original_text=hostname,
                    resolved_value=agent_id,
                    confidence=0.95
                ))
                continue
            
            # Fuzzy match on each word
            for word in query_words:
                if len(word) >= 3:  # Skip very short words
                    sim = self._similarity(word, hostname_lower)
                    if sim >= 0.8:
                        results.append(RecognizedEntity(
                            entity_type='scribe',
                            original_text=word,
                            resolved_value=agent_id,
                            confidence=sim
                        ))
        
        # Sort by confidence and deduplicate
        results.sort(key=lambda x: x.confidence, reverse=True)
        seen_ids = set()
        unique_results = []
        for r in results:
            if r.resolved_value not in seen_ids:
                seen_ids.add(r.resolved_value)
                unique_results.append(r)
        
        return unique_results
    
    def match_bookmark(self, query: str, tenant_id: str = None) -> List[RecognizedEntity]:
        """
        Match bookmark names in a query.
        
        Args:
            query: The user's query text
            tenant_id: Optional tenant filter
            
        Returns:
            List of recognized bookmark entities
        """
        cache_key = tenant_id or "default"
        bookmarks = self._bookmark_cache.get(cache_key, [])
        
        if not bookmarks:
            return []
        
        results = []
        query_lower = query.lower()
        
        for bookmark in bookmarks:
            name = bookmark.get('name', '')
            bookmark_id = bookmark.get('id')
            
            if not name:
                continue
            
            name_lower = name.lower()
            
            # Exact match
            if name_lower in query_lower:
                results.append(RecognizedEntity(
                    entity_type='bookmark',
                    original_text=name,
                    resolved_value=bookmark_id,
                    confidence=1.0
                ))
                continue
            
            # Partial match (multi-word bookmark names)
            name_words = set(name_lower.split())
            if len(name_words) > 1:
                matches = sum(1 for w in name_words if w in query_lower)
                if matches >= len(name_words) * 0.5:
                    results.append(RecognizedEntity(
                        entity_type='bookmark',
                        original_text=name,
                        resolved_value=bookmark_id,
                        confidence=matches / len(name_words)
                    ))
                    continue
            
            # Fuzzy match
            sim = self._similarity(query_lower, name_lower)
            if sim >= 0.6:
                results.append(RecognizedEntity(
                    entity_type='bookmark',
                    original_text=name,
                    resolved_value=bookmark_id,
                    confidence=sim
                ))
        
        # Sort by confidence
        results.sort(key=lambda x: x.confidence, reverse=True)
        return results[:5]  # Return top 5 matches
    
    def match_severity(self, query: str) -> List[str]:
        """Extract severity levels from query"""
        query_lower = query.lower()
        found = []
        
        for severity, aliases in self.SEVERITY_ALIASES.items():
            for alias in aliases:
                if re.search(rf'\b{re.escape(alias)}\b', query_lower):
                    if severity not in found:
                        found.append(severity)
                    break
        
        return found
    
    def match_metric(self, query: str) -> List[str]:
        """Extract metric types from query"""
        query_lower = query.lower()
        found = []
        
        for metric, aliases in self.METRIC_ALIASES.items():
            for alias in aliases:
                if re.search(rf'\b{re.escape(alias)}\b', query_lower):
                    if metric not in found:
                        found.append(metric)
                    break
        
        return found


# ==================== MAIN ENTITY EXTRACTOR ====================

class EntityExtractor:
    """
    Main entity extraction service.
    
    Combines time parsing, entity matching, and ambiguity detection
    to preprocess user queries before AI processing.
    """
    
    def __init__(self):
        self.time_parser = TimeExpressionParser()
        self.entity_matcher = EntityMatcher()
    
    async def refresh_cache(self, db_manager, tenant_id: str = None):
        """Refresh entity caches from database"""
        await self.entity_matcher.refresh_cache(db_manager, tenant_id)
    
    async def extract(self, query: str, db_manager=None, tenant_id: str = None) -> EntityExtractionResult:
        """
        Extract all entities from a user query.
        
        Args:
            query: The user's query text
            db_manager: Database manager for entity lookup
            tenant_id: Optional tenant filter
            
        Returns:
            EntityExtractionResult with all recognized entities
        """
        result = EntityExtractionResult()
        
        # Refresh cache if needed
        if db_manager and not self.entity_matcher._is_cache_valid():
            await self.refresh_cache(db_manager, tenant_id)
        
        # Extract time ranges
        time_range = self.time_parser.parse(query)
        if time_range:
            result.time_ranges.append(RecognizedEntity(
                entity_type='time',
                original_text=time_range.description,
                resolved_value=time_range,
                confidence=1.0
            ))
        
        # Match scribes
        scribes = self.entity_matcher.match_scribe(query, tenant_id)
        result.scribes = scribes
        
        # Match bookmarks
        bookmarks = self.entity_matcher.match_bookmark(query, tenant_id)
        result.bookmarks = bookmarks
        
        # Match severities
        result.severities = self.entity_matcher.match_severity(query)
        
        # Match metrics
        result.metrics = self.entity_matcher.match_metric(query)
        
        # Check for ambiguity
        if scribes and scribes[0].confidence < 0.9:
            # Multiple similar matches or low confidence
            if len(scribes) > 1 and scribes[1].confidence > 0.7:
                result.has_ambiguity = True
                names = [s.original_text for s in scribes[:3]]
                result.ambiguity_message = f"Did you mean one of these scribes: {', '.join(names)}?"
        
        if bookmarks and bookmarks[0].confidence < 0.9:
            if len(bookmarks) > 1 and bookmarks[1].confidence > 0.7:
                result.has_ambiguity = True
                names = [b.original_text for b in bookmarks[:3]]
                if result.ambiguity_message:
                    result.ambiguity_message += f" Or one of these bookmarks: {', '.join(names)}?"
                else:
                    result.ambiguity_message = f"Did you mean one of these bookmarks: {', '.join(names)}?"
        
        return result
    
    def enhance_query_context(self, query: str, extraction: EntityExtractionResult) -> str:
        """
        Enhance a query with extracted entity context.
        
        This adds structured information to help the AI understand
        exactly which entities the user is referring to.
        """
        enhancements = []
        
        if extraction.scribes:
            scribe_info = [f"{s.original_text} (ID: {s.resolved_value})" 
                          for s in extraction.scribes if s.confidence >= 0.8]
            if scribe_info:
                enhancements.append(f"[Detected Scribes: {', '.join(scribe_info)}]")
        
        if extraction.bookmarks:
            bookmark_info = [f"{b.original_text} (ID: {b.resolved_value})" 
                           for b in extraction.bookmarks if b.confidence >= 0.8]
            if bookmark_info:
                enhancements.append(f"[Detected Bookmarks: {', '.join(bookmark_info)}]")
        
        if extraction.time_ranges:
            tr = extraction.time_ranges[0].resolved_value
            enhancements.append(f"[Time Range: {tr.description} ({tr.start.isoformat()} to {tr.end.isoformat()})]")
        
        if extraction.severities:
            enhancements.append(f"[Severity Filter: {', '.join(extraction.severities)}]")
        
        if extraction.metrics:
            enhancements.append(f"[Metrics: {', '.join(extraction.metrics)}]")
        
        if enhancements:
            return f"{query}\n\n{''.join(enhancements)}"
        
        return query


# ==================== MODULE SINGLETON ====================

_extractor: EntityExtractor = None


def get_entity_extractor() -> EntityExtractor:
    """Get the global entity extractor instance"""
    global _extractor
    if _extractor is None:
        _extractor = EntityExtractor()
    return _extractor


# Need to import for run_in_executor
import asyncio
