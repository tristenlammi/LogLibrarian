import asyncio
import json
import logging
import datetime
from typing import List, Dict, Optional, Any

# Try to import apprise, but don't fail if not installed (fallback gracefully)
try:
    import apprise
    APPRISE_AVAILABLE = True
except ImportError:
    APPRISE_AVAILABLE = False
    print("WARNING: 'apprise' package not found. Notifications will be disabled.")

# Import database factory for cross-database compatibility
from db_factory import get_database

logger = logging.getLogger("librarian.notifications")


class NotificationManager:
    """
    Manages sending notifications via Apprise to various channels (Discord, Slack, etc.)
    Uses db_factory for database abstraction (works with both SQLite and TimescaleDB).
    """
    
    def __init__(self, db_manager=None):
        self.db = db_manager or get_database()
        self.aprobj = None
        if APPRISE_AVAILABLE:
            self.aprobj = apprise.Apprise()
            
    def get_channels(self, tenant_id: str = "default") -> List[Dict]:
        """Get all notification channels for a tenant"""
        try:
            return self.db.get_notification_channels(tenant_id)
        except Exception as e:
            logger.error(f"Error fetching channels: {e}")
            return []

    def add_channel(self, name: str, url: str, events: List[str], tenant_id: str = "default") -> int:
        """Add a new notification channel"""
        try:
            # db_factory expects channel_type parameter - infer from URL
            channel_type = self._infer_channel_type(url)
            result = self.db.create_notification_channel(
                name=name,
                channel_type=channel_type,
                url=url,
                events=events,
                tenant_id=tenant_id
            )
            return result.get('id', 0) if result else 0
        except Exception as e:
            logger.error(f"Error adding channel: {e}")
            raise
    
    def _infer_channel_type(self, url: str) -> str:
        """Infer channel type from Apprise URL"""
        url_lower = url.lower()
        if 'discord' in url_lower:
            return 'discord'
        elif 'slack' in url_lower:
            return 'slack'
        elif 'telegram' in url_lower or 'tgram' in url_lower:
            return 'telegram'
        elif 'mailto' in url_lower or 'email' in url_lower:
            return 'email'
        elif 'webhook' in url_lower or 'http' in url_lower:
            return 'webhook'
        else:
            return 'other'

    def delete_channel(self, channel_id: int, tenant_id: str = "default") -> bool:
        """Delete a notification channel"""
        try:
            return self.db.delete_notification_channel(channel_id, tenant_id)
        except Exception as e:
            logger.error(f"Error deleting channel: {e}")
            return False
            
    async def send_notification(self, event_type: str, title: str, body: str, 
                              tenant_id: str = "default", tags: List[str] = None) -> Dict:
        """
        Send a notification to all subscribed channels.
        Returns stats on sent/failed.
        """
        if not APPRISE_AVAILABLE:
            return {"status": "skipped", "reason": "apprise_not_installed"}
            
        print(f"[NOTIFY] {event_type} - {title}")
        
        # 1. Get enabled channels subscribing to this event
        channels = self._get_subscribed_channels(event_type, tenant_id)
        if not channels:
            return {"status": "skipped", "reason": "no_subscribers"}
        
        sent_count = 0
        failed_count = 0
        
        # 2. Send to each channel
        # We instantiate a new Apprise object for each send to keep isolation simple
        # (Or we could group them by URL if optimizing)
        for channel in channels:
            ap = apprise.Apprise()
            ap.add(channel['url'])
            
            # Send
            success = await ap.async_notify(
                title=title,
                body=body,
            )
            
            # Record history
            self._record_history(
                channel_id=channel['id'],
                event_type=event_type,
                title=title,
                body=body,
                status="sent" if success else "failed",
                error=None if success else "Failed to send (check logs)"
            )
            
            if success:
                sent_count += 1
            else:
                failed_count += 1
                
        return {
            "status": "completed", 
            "sent": sent_count, 
            "failed": failed_count,
            "total": len(channels)
        }

    def _get_subscribed_channels(self, event_type: str, tenant_id: str) -> List[Dict]:
        """Helper to find matching channels that are subscribed to this event type"""
        try:
            all_channels = self.db.get_notification_channels(tenant_id)
            matching = []
            
            for channel in all_channels:
                # Skip disabled channels
                if not channel.get('enabled', True):
                    continue
                    
                events = channel.get('events', [])
                # Handle events as list or JSON string
                if isinstance(events, str):
                    try:
                        events = json.loads(events)
                    except:
                        events = []
                
                # Check if event_type is in allowed events OR if they subscribe to 'all'
                if event_type in events or 'all' in events:
                    matching.append({
                        "id": channel["id"],
                        "url": channel["url"]
                    })
                    
            return matching
        except Exception as e:
            logger.error(f"Error getting subscribed channels: {e}")
            return []
            
    def _record_history(self, channel_id: int, event_type: str, title: str, 
                       body: str, status: str, error: str = None):
        """Record notification attempt to DB (fire and forget)"""
        try:
            self.db.add_notification_history(
                channel_id=channel_id,
                event_type=event_type,
                title=title,
                body=body,
                status=status,
                error=error
            )
        except Exception as e:
            logger.error(f"Error recording notification history: {e}")

    async def test_channel(self, url: str) -> bool:
        """Test a specific Apprise URL"""
        if not APPRISE_AVAILABLE:
            return False
        
        try:
            ap = apprise.Apprise()
            if not ap.add(url):
                return False
            return await ap.async_notify(
                title="LogLibrarian Test",
                body="This is a test notification from LogLibrarian.",
            )
        except:
            return False
