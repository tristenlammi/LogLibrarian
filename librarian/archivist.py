"""
Archivist - Long-term Memory System for AI Chat

This module provides the AI with semantic search over historical logs and alerts
using Qdrant vector database. It indexes logs hourly and provides search capabilities.

Components:
1. EmbedText - Generate embeddings using all-MiniLM-L6-v2
2. Indexer - Scheduled job to index new logs into Qdrant  
3. SearchArchives - Query Qdrant for relevant historical data

NOTE: This module gracefully handles missing AI dependencies. When qdrant-client
or sentence-transformers are not installed, the Archivist will be disabled but
the application will continue to function.
"""

import os
import json
import hashlib
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import asyncio

# Try to import AI dependencies - they may be disabled
ARCHIVIST_AVAILABLE = False
QdrantClient = None
Distance = None
VectorParams = None
PointStruct = None
Filter = None
FieldCondition = None
MatchValue = None
Range = None
PayloadSchemaType = None
SentenceTransformer = None

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import (
        Distance, VectorParams, PointStruct, 
        Filter, FieldCondition, MatchValue, Range,
        PayloadSchemaType
    )
    from sentence_transformers import SentenceTransformer
    ARCHIVIST_AVAILABLE = True
except ImportError as e:
    print(f"ℹ️ Archivist dependencies not available: {e}")
    print("   Archivist (semantic search) will be disabled. This is expected if AI features are not installed.")


# Configuration
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
ARCHIVE_COLLECTION = "logs_archive"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
VECTOR_SIZE = 384  # all-MiniLM-L6-v2 produces 384-dimensional vectors


@dataclass
class ArchiveEntry:
    """Represents a searchable archive entry"""
    id: str
    text: str
    server_name: str
    timestamp: float
    log_level: str
    source: str
    score: float = 0.0


class Archivist:
    """
    The Archivist provides long-term memory for the AI by:
    1. Indexing logs and alerts into Qdrant with semantic embeddings
    2. Enabling semantic search over historical data
    """
    
    def __init__(self, db_manager=None):
        """Initialize the Archivist with Qdrant connection and embedding model"""
        self.db_manager = db_manager
        self._qdrant_client = None
        self._embedding_model = None
        self._last_indexed_time = None
        self._initialized = False
        
    def _ensure_initialized(self):
        """Lazy initialization of Qdrant and embedding model"""
        if self._initialized:
            return True
        
        # Check if dependencies are available
        if not ARCHIVIST_AVAILABLE:
            return False
            
        try:
            # Initialize Qdrant client
            self._qdrant_client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
            
            # Initialize embedding model
            self._embedding_model = SentenceTransformer(EMBEDDING_MODEL)
            
            # Initialize the archive collection
            self._init_archive_collection()
            
            # Load last indexed time from Qdrant collection info or state
            self._load_indexer_state()
            
            self._initialized = True
            print(f"Archivist initialized successfully with collection '{ARCHIVE_COLLECTION}'")
            return True
            
        except Exception as e:
            print(f"Archivist initialization failed: {e}")
            return False
    
    def _init_archive_collection(self):
        """Initialize the logs_archive Qdrant collection"""
        try:
            collections = self._qdrant_client.get_collections().collections
            collection_names = [c.name for c in collections]
            
            if ARCHIVE_COLLECTION not in collection_names:
                self._qdrant_client.create_collection(
                    collection_name=ARCHIVE_COLLECTION,
                    vectors_config=VectorParams(
                        size=VECTOR_SIZE,
                        distance=Distance.COSINE
                    )
                )
                
                # Create payload indexes for efficient filtering
                self._qdrant_client.create_payload_index(
                    collection_name=ARCHIVE_COLLECTION,
                    field_name="server_name",
                    field_schema=PayloadSchemaType.KEYWORD
                )
                self._qdrant_client.create_payload_index(
                    collection_name=ARCHIVE_COLLECTION,
                    field_name="log_level",
                    field_schema=PayloadSchemaType.KEYWORD
                )
                self._qdrant_client.create_payload_index(
                    collection_name=ARCHIVE_COLLECTION,
                    field_name="timestamp",
                    field_schema=PayloadSchemaType.FLOAT
                )
                
                print(f"Created Qdrant collection: {ARCHIVE_COLLECTION}")
            else:
                print(f"Qdrant collection '{ARCHIVE_COLLECTION}' already exists")
                
        except Exception as e:
            print(f"Error initializing archive collection: {e}")
            raise
    
    def _load_indexer_state(self):
        """Load the last indexed timestamp from persistent storage"""
        try:
            # Try to get collection info to determine last indexed time
            collection_info = self._qdrant_client.get_collection(ARCHIVE_COLLECTION)
            
            if collection_info.points_count == 0:
                # No points yet, start from 24 hours ago
                self._last_indexed_time = datetime.now() - timedelta(hours=24)
            else:
                # Get the most recent point's timestamp
                # Default to 1 hour ago if we can't determine
                self._last_indexed_time = datetime.now() - timedelta(hours=1)
                
        except Exception as e:
            print(f"Could not load indexer state: {e}")
            self._last_indexed_time = datetime.now() - timedelta(hours=24)
    
    # ==================== Embedding Service ====================
    
    def embed_text(self, text: str) -> List[float]:
        """
        Generate embeddings for text using all-MiniLM-L6-v2.
        
        Args:
            text: The text to embed
            
        Returns:
            A list of 384 floats representing the embedding vector
        """
        if not self._ensure_initialized():
            raise RuntimeError("Archivist not initialized")
            
        # Truncate very long texts to avoid memory issues
        max_length = 512
        if len(text) > max_length:
            text = text[:max_length]
            
        embedding = self._embedding_model.encode(text, convert_to_numpy=True)
        return embedding.tolist()
    
    def embed_texts_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for multiple texts efficiently.
        
        Args:
            texts: List of texts to embed
            
        Returns:
            List of embedding vectors
        """
        if not self._ensure_initialized():
            raise RuntimeError("Archivist not initialized")
        
        # Truncate long texts
        max_length = 512
        truncated = [t[:max_length] if len(t) > max_length else t for t in texts]
        
        embeddings = self._embedding_model.encode(truncated, convert_to_numpy=True, batch_size=32)
        return embeddings.tolist()
    
    # ==================== Indexer Job ====================
    
    def _generate_point_id(self, log_entry: Dict) -> str:
        """Generate a deterministic ID for a log entry to avoid duplicates"""
        # Create a hash from agent_id + timestamp + message
        unique_str = f"{log_entry.get('agent_id', '')}-{log_entry.get('timestamp', '')}-{log_entry.get('message', '')}"
        return hashlib.md5(unique_str.encode()).hexdigest()
    
    def _parse_timestamp(self, timestamp_str: str) -> float:
        """Parse various timestamp formats to Unix timestamp"""
        if not timestamp_str:
            return datetime.now().timestamp()
            
        try:
            # Handle ISO format
            if 'T' in str(timestamp_str):
                dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                return dt.timestamp()
            # Handle Unix timestamp
            elif isinstance(timestamp_str, (int, float)):
                return float(timestamp_str)
            # Handle date strings
            else:
                dt = datetime.strptime(str(timestamp_str)[:19], '%Y-%m-%d %H:%M:%S')
                return dt.timestamp()
        except:
            return datetime.now().timestamp()
    
    def run_indexer(self, hours_back: int = 1) -> Dict[str, Any]:
        """
        Run the indexer job to archive new logs.
        
        This should be called hourly by a scheduler.
        
        Args:
            hours_back: How many hours of logs to index (default: 1)
            
        Returns:
            Statistics about the indexing run
        """
        if not self._ensure_initialized():
            return {"error": "Archivist not initialized", "indexed": 0}
        
        if not self.db_manager:
            return {"error": "No database manager configured", "indexed": 0}
        
        stats = {
            "started_at": datetime.now().isoformat(),
            "logs_processed": 0,
            "logs_indexed": 0,
            "errors": 0,
            "skipped_duplicates": 0
        }
        
        try:
            # Fetch logs from the last N hours
            since_time = datetime.now() - timedelta(hours=hours_back)
            
            # Get logs using the db_manager
            logs = self.db_manager.get_logs(limit=1000)  # Get recent logs
            
            if not logs:
                stats["message"] = "No new logs to index"
                return stats
            
            # Filter logs by time (if timestamp is available)
            new_logs = []
            for log in logs:
                try:
                    log_time = self._parse_timestamp(log.get('timestamp', ''))
                    if log_time >= since_time.timestamp():
                        new_logs.append(log)
                except:
                    new_logs.append(log)  # Include if we can't parse time
            
            stats["logs_processed"] = len(new_logs)
            
            if not new_logs:
                stats["message"] = "No new logs in time window"
                return stats
            
            # Prepare points for upsert
            points = []
            texts_to_embed = []
            log_entries = []
            
            for log in new_logs:
                # Create searchable text from log content
                message = log.get('message', '')
                source = log.get('source', '')
                level = log.get('level', log.get('severity', 'INFO'))
                
                # Combine relevant fields for embedding
                search_text = f"{level}: {source} - {message}"
                texts_to_embed.append(search_text)
                log_entries.append(log)
            
            # Generate embeddings in batch (more efficient)
            embeddings = self.embed_texts_batch(texts_to_embed)
            
            # Create Qdrant points
            for i, (log, embedding) in enumerate(zip(log_entries, embeddings)):
                point_id = self._generate_point_id(log)
                
                # Extract agent/server name from agent_id
                agent_id = log.get('agent_id', 'unknown')
                server_name = agent_id.split('-')[0] if '-' in agent_id else agent_id
                
                point = PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload={
                        "server_name": server_name,
                        "agent_id": agent_id,
                        "timestamp": self._parse_timestamp(log.get('timestamp', '')),
                        "log_level": log.get('level', log.get('severity', 'INFO')).upper(),
                        "source": log.get('source', ''),
                        "message": log.get('message', '')[:1000],  # Limit message size
                        "indexed_at": datetime.now().isoformat()
                    }
                )
                points.append(point)
            
            # Upsert to Qdrant (upsert handles duplicates automatically)
            if points:
                self._qdrant_client.upsert(
                    collection_name=ARCHIVE_COLLECTION,
                    points=points,
                    wait=True
                )
                stats["logs_indexed"] = len(points)
            
            # Update last indexed time
            self._last_indexed_time = datetime.now()
            
            stats["completed_at"] = datetime.now().isoformat()
            stats["message"] = f"Successfully indexed {len(points)} logs"
            
        except Exception as e:
            stats["error"] = str(e)
            stats["errors"] += 1
            print(f"Indexer error: {e}")
        
        return stats
    
    # ==================== Search Tool ====================
    
    def search_archives(
        self,
        query: str,
        limit: int = 10,
        server_name: Optional[str] = None,
        log_level: Optional[str] = None,
        time_range_hours: Optional[int] = None
    ) -> List[ArchiveEntry]:
        """
        Search the log archives using semantic similarity.
        
        Args:
            query: The search query (natural language)
            limit: Maximum number of results (default: 10)
            server_name: Filter by server/agent name (optional)
            log_level: Filter by log level - ERROR, WARN, INFO, DEBUG (optional)
            time_range_hours: Only search logs from last N hours (optional)
            
        Returns:
            List of ArchiveEntry objects sorted by relevance
        """
        if not self._ensure_initialized():
            return []
        
        try:
            # Generate embedding for the query
            query_embedding = self.embed_text(query)
            
            # Build filters
            filter_conditions = []
            
            if server_name:
                filter_conditions.append(
                    FieldCondition(
                        key="server_name",
                        match=MatchValue(value=server_name)
                    )
                )
            
            if log_level:
                filter_conditions.append(
                    FieldCondition(
                        key="log_level",
                        match=MatchValue(value=log_level.upper())
                    )
                )
            
            if time_range_hours:
                min_timestamp = (datetime.now() - timedelta(hours=time_range_hours)).timestamp()
                filter_conditions.append(
                    FieldCondition(
                        key="timestamp",
                        range=Range(gte=min_timestamp)
                    )
                )
            
            # Build filter object
            search_filter = None
            if filter_conditions:
                search_filter = Filter(must=filter_conditions)
            
            # Search Qdrant (use query_points for newer qdrant-client versions)
            results = self._qdrant_client.query_points(
                collection_name=ARCHIVE_COLLECTION,
                query=query_embedding,
                query_filter=search_filter,
                limit=limit,
                with_payload=True
            ).points
            
            # Convert to ArchiveEntry objects
            entries = []
            for result in results:
                payload = result.payload
                entry = ArchiveEntry(
                    id=str(result.id),
                    text=payload.get('message', ''),
                    server_name=payload.get('server_name', 'unknown'),
                    timestamp=payload.get('timestamp', 0),
                    log_level=payload.get('log_level', 'INFO'),
                    source=payload.get('source', ''),
                    score=result.score
                )
                entries.append(entry)
            
            return entries
            
        except Exception as e:
            print(f"Search error: {e}")
            return []
    
    def search_archives_formatted(
        self,
        query: str,
        limit: int = 10,
        server_name: Optional[str] = None,
        log_level: Optional[str] = None,
        time_range_hours: Optional[int] = None
    ) -> str:
        """
        Search archives and return formatted results for AI context.
        
        Returns a human-readable string suitable for injection into AI prompts.
        """
        entries = self.search_archives(
            query=query,
            limit=limit,
            server_name=server_name,
            log_level=log_level,
            time_range_hours=time_range_hours
        )
        
        if not entries:
            return f"No archived logs found matching: '{query}'"
        
        result = f"## Archive Search Results for: '{query}'\n"
        result += f"Found {len(entries)} relevant entries:\n\n"
        
        for i, entry in enumerate(entries, 1):
            # Format timestamp
            try:
                dt = datetime.fromtimestamp(entry.timestamp)
                time_str = dt.strftime('%Y-%m-%d %H:%M:%S')
            except:
                time_str = "Unknown time"
            
            # Level emoji
            level_emoji = {
                'ERROR': '🔴',
                'WARN': '🟡',
                'WARNING': '🟡',
                'INFO': '🔵',
                'DEBUG': '⚪'
            }.get(entry.log_level.upper(), '⚪')
            
            result += f"{i}. {level_emoji} **[{time_str}]** [{entry.server_name}]\n"
            result += f"   Source: {entry.source}\n"
            result += f"   {entry.text[:300]}{'...' if len(entry.text) > 300 else ''}\n"
            result += f"   _(Relevance: {entry.score:.2f})_\n\n"
        
        return result
    
    def get_archive_stats(self) -> Dict[str, Any]:
        """Get statistics about the archive collection"""
        if not self._ensure_initialized():
            return {"error": "Archivist not initialized"}
        
        try:
            collection_info = self._qdrant_client.get_collection(ARCHIVE_COLLECTION)
            
            return {
                "collection": ARCHIVE_COLLECTION,
                "total_points": collection_info.points_count,
                "status": str(collection_info.status),
                "last_indexed": self._last_indexed_time.isoformat() if self._last_indexed_time else None
            }
        except Exception as e:
            return {"error": str(e)}


# Singleton instance
_archivist_instance = None


def get_archivist(db_manager=None) -> Archivist:
    """Get or create the singleton Archivist instance"""
    global _archivist_instance
    
    if _archivist_instance is None:
        _archivist_instance = Archivist(db_manager)
    elif db_manager and _archivist_instance.db_manager is None:
        _archivist_instance.db_manager = db_manager
        
    return _archivist_instance
