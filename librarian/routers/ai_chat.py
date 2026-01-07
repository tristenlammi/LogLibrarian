"""
AI Chat Router - WebSocket and REST endpoints for Librarian AI chat

Provides:
- WebSocket for streaming chat responses
- REST endpoints for conversation management
- Tool execution status updates
- Entity recognition for improved accuracy
- Query optimization with caching and parallel execution
- Error handling and resilience (Phase 6)
- Security hardening (Phase 6)
- In-app help and documentation (Phase 6)
"""

import asyncio
import json
import uuid
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Depends, Query, Request
from pydantic import BaseModel
import logging

# Import AI service components
from ai_service import get_ai_service, reload_ai_service, AIService
from ai_tools import ToolRegistry, ToolExecutor, ToolCallParser, get_tool_registry

# Import Phase 5 intelligence enhancements
from ai_entity_recognition import get_entity_extractor, EntityExtractor
from ai_query_optimizer import get_query_optimizer, QueryOptimizer
from ai_response_quality import get_response_enhancer, ResponseEnhancer
from ai_proactive_insights import get_proactive_insights, ProactiveInsights

# Import Phase 6 resilience, security, and help modules
from ai_resilience import (
    get_resilience_service, ResilienceService,
    AIError, AIServiceUnavailableError, AITimeoutError,
    with_retry, RetryConfig, with_circuit_breaker
)
from ai_security import get_security_service, SecurityService
from ai_help import get_help_service, HelpService, HelpFormatter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai", tags=["AI Chat"])


# ==================== PYDANTIC MODELS ====================

class ConversationCreate(BaseModel):
    title: Optional[str] = "New Chat"

class ConversationUpdate(BaseModel):
    title: str

class MessageCreate(BaseModel):
    content: str
    conversation_id: Optional[str] = None  # If None, creates new conversation

class ChatMessage(BaseModel):
    role: str  # 'user' or 'assistant'
    content: str

class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None


# ==================== DEPENDENCY ====================

def get_db_manager():
    """Get database manager from app state - will be injected in main.py"""
    from main import db_manager
    return db_manager


# ==================== CONVERSATION ENDPOINTS ====================

@router.get("/conversations")
async def list_conversations(
    limit: int = Query(50, ge=1, le=100),
    db_manager = Depends(get_db_manager)
):
    """List all conversations, newest first"""
    conversations = db_manager.get_conversations(limit=limit)
    return {"conversations": conversations}


@router.post("/conversations")
async def create_conversation(
    data: ConversationCreate,
    db_manager = Depends(get_db_manager)
):
    """Create a new conversation"""
    conversation = db_manager.create_conversation(title=data.title)
    if not conversation:
        raise HTTPException(status_code=500, detail="Failed to create conversation")
    return conversation


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    db_manager = Depends(get_db_manager)
):
    """Get a conversation with all its messages"""
    conversation = db_manager.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@router.patch("/conversations/{conversation_id}")
async def update_conversation(
    conversation_id: str,
    data: ConversationUpdate,
    db_manager = Depends(get_db_manager)
):
    """Update conversation title"""
    success = db_manager.update_conversation_title(conversation_id, data.title)
    if not success:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"success": True}


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    db_manager = Depends(get_db_manager)
):
    """Delete a conversation and all its messages"""
    success = db_manager.delete_conversation(conversation_id)
    if not success:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"success": True}


# ==================== CHAT ENDPOINT (REST) ====================

@router.post("/chat")
async def chat(
    data: ChatRequest,
    request: Request,
    db_manager = Depends(get_db_manager)
):
    """
    Send a chat message and get a response.
    
    This is the non-streaming version. For streaming, use the WebSocket endpoint.
    """
    # PHASE 6: Security validation
    security = get_security_service()
    resilience = get_resilience_service()
    
    # Extract client info for rate limiting
    client_ip = request.client.host if request.client else None
    user_id = "default"  # TODO: Get from auth
    tenant_id = "default"  # TODO: Get from tenant context
    
    # Validate request (rate limiting, input sanitization)
    allowed, sanitized_message, error_message = security.validate_request(
        query=data.message,
        user_id=user_id,
        tenant_id=tenant_id,
        ip_address=client_ip
    )
    
    if not allowed:
        raise HTTPException(status_code=429, detail=error_message)
    
    # Check circuit breaker
    if not resilience.is_ai_available():
        # Return graceful fallback
        fallback_response = resilience.get_fallback_response(data.message)
        return {
            "conversation_id": data.conversation_id,
            "response": fallback_response,
            "is_fallback": True
        }
    
    ai_service = get_ai_service(db_manager)
    
    if not ai_service or not ai_service.is_ready():
        raise HTTPException(
            status_code=503,
            detail="AI service not available. Please enable and configure AI in settings."
        )
    
    try:
        # Get or create conversation
        conversation_id = data.conversation_id
        if not conversation_id:
            conversation = db_manager.create_conversation()
            conversation_id = conversation["id"]
        
        # Save user message (use sanitized version)
        db_manager.add_message(conversation_id, "user", sanitized_message)
        
        # PHASE 5: Extract entities from user query
        entity_extractor = get_entity_extractor()
        entities = await entity_extractor.extract(sanitized_message, db_manager)
        
        # Enhance query with detected entities
        enhanced_message = sanitized_message
        if entities.get_scribe_ids() or entities.get_bookmark_ids() or entities.get_time_range():
            enhanced_message = entity_extractor.enhance_query_context(sanitized_message, entities)
        
        # Build context from conversation history (get more for summarization)
        recent_messages = db_manager.get_recent_messages(conversation_id, limit=20)
        context = _build_context(recent_messages, ai_service)
        
        # Get system prompt with Librarian persona
        system_prompt = _get_librarian_system_prompt()
        
        # Generate response with tools
        result = await ai_service.generate_with_tools(
            prompt=context + f"\n\nUser: {enhanced_message}",
            db_manager=db_manager,
            system_prompt=system_prompt,
            max_tokens=2048,
            temperature=0.3
        )
        
        # Record success with circuit breaker
        resilience.record_ai_success()
        
        if not result.success:
            raise HTTPException(status_code=500, detail=result.error)
        
        # PHASE 6: Filter response for sensitive content
        filtered_response = security.filter_response(result.content)
        
        # Save assistant response
        db_manager.add_message(conversation_id, "assistant", filtered_response)
        
        # Auto-generate title if this is a new conversation
        if len(recent_messages) <= 1:
            _auto_title_conversation(db_manager, conversation_id, sanitized_message)
        
        return {
            "conversation_id": conversation_id,
            "response": filtered_response,
            "tokens_used": result.tokens_used,
            "model": result.model,
            "entities_detected": entities.to_context_dict() if entities else None
        }
        
    except AIError as e:
        # Record failure with circuit breaker
        resilience.record_ai_failure(e)
        
        # Return user-friendly error
        raise HTTPException(status_code=500, detail=e.user_message)
        
    except Exception as e:
        # Record failure with circuit breaker
        resilience.record_ai_failure(e)
        logger.exception("Chat error")
        
        raise HTTPException(
            status_code=500, 
            detail="An unexpected error occurred. Please try again."
        )


# ==================== WEBSOCKET CHAT (STREAMING) ====================

class ChatWebSocketManager:
    """Manages WebSocket connections for chat"""
    
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}
    
    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket
    
    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
    
    async def send_message(self, client_id: str, message: dict):
        if client_id in self.active_connections:
            await self.active_connections[client_id].send_json(message)


ws_manager = ChatWebSocketManager()


@router.websocket("/chat/ws")
async def websocket_chat(websocket: WebSocket):
    """
    WebSocket endpoint for streaming chat.
    
    Protocol:
    1. Client connects
    2. Server sends: {"type": "connected", "client_id": "..."}
    3. Client sends: {"type": "message", "content": "...", "conversation_id": "..."}
    4. Server sends status updates:
       - {"type": "status", "status": "thinking"}
       - {"type": "tool_call", "tool": "query_logs", "status": "executing"}
       - {"type": "tool_result", "tool": "query_logs", "status": "complete"}
    5. Server streams response:
       - {"type": "token", "content": "The"}
       - {"type": "token", "content": " system"}
       - ...
    6. Server sends completion:
       - {"type": "complete", "conversation_id": "...", "message_id": "..."}
    """
    from main import db_manager
    
    client_id = str(uuid.uuid4())
    await ws_manager.connect(websocket, client_id)
    
    # Send connection confirmation
    await websocket.send_json({
        "type": "connected",
        "client_id": client_id
    })
    
    try:
        while True:
            # Receive message from client
            data = await websocket.receive_json()
            
            if data.get("type") == "message":
                await _handle_chat_message(
                    websocket=websocket,
                    client_id=client_id,
                    content=data.get("content", ""),
                    conversation_id=data.get("conversation_id"),
                    db_manager=db_manager
                )
            
            elif data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    
    except WebSocketDisconnect:
        ws_manager.disconnect(client_id)
    except Exception as e:
        print(f"WebSocket error: {e}")
        ws_manager.disconnect(client_id)


async def _handle_chat_message(
    websocket: WebSocket,
    client_id: str,
    content: str,
    conversation_id: Optional[str],
    db_manager
):
    """Handle an incoming chat message via WebSocket"""
    
    # PHASE 6: Security validation
    security = get_security_service()
    resilience = get_resilience_service()
    
    user_id = "default"  # TODO: Get from auth
    tenant_id = "default"  # TODO: Get from tenant context
    
    # Validate request (rate limiting, input sanitization)
    allowed, sanitized_content, error_message = security.validate_request(
        query=content,
        user_id=user_id,
        tenant_id=tenant_id,
        ip_address=None  # WebSocket doesn't have easy IP access
    )
    
    if not allowed:
        await websocket.send_json({
            "type": "error",
            "error": error_message,
            "retryable": True
        })
        return
    
    try:
        # Check circuit breaker
        if not resilience.is_ai_available():
            fallback_response = resilience.get_fallback_response(content)
            await websocket.send_json({
                "type": "response",
                "content": fallback_response,
                "is_fallback": True
            })
            await websocket.send_json({
                "type": "complete",
                "conversation_id": conversation_id,
                "is_fallback": True
            })
            return
        
        # Get AI service
        ai_service = get_ai_service(db_manager)
        
        if not ai_service or not ai_service.is_ready():
            await websocket.send_json({
                "type": "error",
                "error": "AI service not available",
                "retryable": True
            })
            return
        
        # Get or create conversation
        if not conversation_id:
            conversation = db_manager.create_conversation()
            conversation_id = conversation["id"]
            await websocket.send_json({
                "type": "conversation_created",
                "conversation_id": conversation_id
            })
        
        # Save user message (use sanitized version)
        user_msg = db_manager.add_message(conversation_id, "user", sanitized_content)
        
        # Send thinking status
        await websocket.send_json({
            "type": "status",
            "status": "thinking"
        })
        
        # PHASE 5: Extract entities from user query
        entity_extractor = get_entity_extractor()
        entities = await entity_extractor.extract(sanitized_content, db_manager)
        
        # Enhance query with detected entities
        enhanced_content = sanitized_content
        if entities.get_scribe_ids() or entities.get_bookmark_ids() or entities.get_time_range():
            enhanced_content = entity_extractor.enhance_query_context(sanitized_content, entities)
        
        # Check for ambiguity and ask for clarification if needed
        if entities.has_ambiguity and entities.ambiguity_message:
            # For now, proceed but note the ambiguity in context
            enhanced_content += f"\n[Note: {entities.ambiguity_message}]"
        
        # Build context (get more for summarization)
        recent_messages = db_manager.get_recent_messages(conversation_id, limit=20)
        context = _build_context(recent_messages, ai_service)
        system_prompt = _get_librarian_system_prompt()
        
        # Generate with tool tracking
        full_response = await _generate_with_tool_updates(
            ai_service=ai_service,
            websocket=websocket,
            prompt=context + f"\n\nUser: {enhanced_content}",
            db_manager=db_manager,
            system_prompt=system_prompt,
            entities=entities
        )
        
        # PHASE 6: Filter response for sensitive content
        filtered_response = security.filter_response(full_response)
        
        # Record success with circuit breaker
        resilience.record_ai_success()
        
        # Save assistant response (use filtered version)
        assistant_msg = db_manager.add_message(conversation_id, "assistant", filtered_response)
        
        # Auto-title if new conversation
        if len(recent_messages) <= 1:
            _auto_title_conversation(db_manager, conversation_id, sanitized_content)
        
        # Send completion
        await websocket.send_json({
            "type": "complete",
            "conversation_id": conversation_id,
            "message_id": assistant_msg["id"] if assistant_msg else None
        })
        
    except AIError as e:
        # Record failure with circuit breaker
        resilience.record_ai_failure(e)
        
        await websocket.send_json({
            "type": "error",
            "error": e.user_message,
            "retryable": e.retryable
        })
        
    except Exception as e:
        # Record failure with circuit breaker
        resilience.record_ai_failure(e)
        logger.exception("WebSocket chat error")
        
        await websocket.send_json({
            "type": "error",
            "error": "An unexpected error occurred. Please try again.",
            "retryable": True
        })


async def _generate_with_tool_updates(
    ai_service: AIService,
    websocket: WebSocket,
    prompt: str,
    db_manager,
    system_prompt: str,
    stream: bool = True,
    entities = None
) -> str:
    """
    Generate response with tool updates sent to WebSocket.
    
    Supports streaming token-by-token responses.
    Uses Phase 5 optimizations: caching, parallel execution, response enhancement.
    """
    # Get tool schemas for context
    registry = get_tool_registry()
    tool_schemas = registry.get_all_schemas()
    tool_prompt = _build_tool_system_prompt(system_prompt, tool_schemas)
    
    # Initialize executor with callback for tool updates
    executor = ToolExecutor(db_manager)
    
    # PHASE 5: Get query optimizer and response enhancer
    optimizer = get_query_optimizer()
    enhancer = get_response_enhancer()
    
    tool_results_text = ""
    total_tokens = 0
    max_turns = 3
    
    for turn in range(max_turns):
        # Build prompt with tool results
        full_prompt = prompt
        if tool_results_text:
            full_prompt = f"{prompt}\n\n[Tool Results]\n{tool_results_text}"
        
        # Generate (check for tool calls first without streaming)
        result = await ai_service.provider.generate(
            full_prompt,
            tool_prompt,
            max_tokens=2048,
            temperature=0.3
        )
        
        if not result.success:
            return f"Error: {result.error}"
        
        total_tokens += result.tokens_used
        
        # Check for tool calls
        tool_calls = ToolCallParser.parse(result.content)
        
        if not tool_calls:
            # No tool calls - this is the final response
            # If streaming enabled, re-generate with streaming
            if stream and hasattr(ai_service.provider, 'generate_stream'):
                full_response = ""
                async for chunk in ai_service.provider.generate_stream(
                    full_prompt,
                    tool_prompt,
                    max_tokens=2048,
                    temperature=0.3
                ):
                    if chunk.get("token"):
                        await websocket.send_json({
                            "type": "token",
                            "content": chunk["token"]
                        })
                        full_response += chunk["token"]
                    if chunk.get("done"):
                        break
                return full_response
            else:
                # Non-streaming - send full response
                await websocket.send_json({
                    "type": "response",
                    "content": result.content
                })
                return result.content
        
        # Execute tool calls with status updates
        # PHASE 5: Inject detected entity IDs into tool arguments
        for call in tool_calls:
            tool_name = call.get('tool') or call.get('name')
            args = call.get('arguments') or call.get('args', {})
            
            # Enhance tool arguments with entity context
            if entities:
                # Add detected scribe IDs if the tool supports it
                if 'agent_id' not in args and entities.get_scribe_ids():
                    if tool_name in ('get_scribe_info', 'get_scribe_metrics', 'get_scribe_processes'):
                        args['agent_id'] = entities.get_scribe_ids()[0]
                
                # Add detected bookmark ID if applicable
                if 'bookmark_id' not in args and entities.get_bookmark_ids():
                    if tool_name in ('get_bookmark_info', 'get_bookmark_status'):
                        args['bookmark_id'] = entities.get_bookmark_ids()[0]
                
                # Add detected time range if applicable
                time_range = entities.get_time_range()
                if time_range and 'start_time' not in args and 'period' not in args:
                    if tool_name in ('query_logs', 'get_scribe_metrics', 'get_bookmark_uptime'):
                        args['start_time'] = time_range.start.isoformat()
                        args['end_time'] = time_range.end.isoformat()
            
            # Send tool execution status
            await websocket.send_json({
                "type": "tool_call",
                "tool": tool_name,
                "status": "executing"
            })
            
            # Execute tool with optimizer (caching, timeout handling)
            tool_result = await executor.execute(tool_name, args)
            
            # Send tool result status
            await websocket.send_json({
                "type": "tool_result",
                "tool": tool_name,
                "status": "complete" if tool_result and tool_result.success else "error"
            })
            
            if tool_result:
                if tool_result.success:
                    # PHASE 5: Enhance tool result with summaries and recommendations
                    enhanced_result = enhancer.enhance_tool_result(tool_name, tool_result.to_dict())
                    
                    result_str = json.dumps(enhanced_result.get('data', {}), default=str, indent=2)
                    if len(result_str) > 2000:
                        result_str = result_str[:2000] + "\n...(truncated)"
                    
                    tool_results_text += f"\n[{tool_name}]:\n{result_str}"
                    
                    # Include summary if available
                    if enhanced_result.get('summary'):
                        tool_results_text += f"\n{enhanced_result['summary']}"
                    
                    # Include highlights if available
                    if enhanced_result.get('highlights'):
                        tool_results_text += f"\nHighlights: " + "; ".join(enhanced_result['highlights'])
                    
                    tool_results_text += "\n"
                else:
                    tool_results_text += f"\n[{tool_name}]: Error - {tool_result.error}\n"
        
        # Check token budget
        if executor._token_budget_used >= 4000:
            break
    
    # Final generation with all tool results
    await websocket.send_json({
        "type": "status",
        "status": "synthesizing"
    })
    
    final_prompt = f"{prompt}\n\n[Tool Results]\n{tool_results_text}\n\nPlease provide your response based on the data above."
    
    # Stream the final response
    if stream and hasattr(ai_service.provider, 'generate_stream'):
        full_response = ""
        async for chunk in ai_service.provider.generate_stream(
            final_prompt,
            system_prompt,
            max_tokens=2048,
            temperature=0.3
        ):
            if chunk.get("token"):
                await websocket.send_json({
                    "type": "token",
                    "content": chunk["token"]
                })
                full_response += chunk["token"]
            if chunk.get("done"):
                break
        return full_response
    else:
        final_result = await ai_service.provider.generate(
            final_prompt,
            system_prompt,
            max_tokens=2048,
            temperature=0.3
        )
        
        response = final_result.content if final_result.success else f"Error: {final_result.error}"
        
        await websocket.send_json({
            "type": "response",
            "content": response
        })
        
        return response


# ==================== HELPER FUNCTIONS ====================

# Context window constants
MAX_CONTEXT_MESSAGES = 10  # Recent messages to include in full
MAX_CONTEXT_TOKENS = 3000  # Rough token budget for context
SUMMARIZE_THRESHOLD = 6    # Summarize if more than this many messages


def _estimate_tokens(text: str) -> int:
    """Rough token estimate (4 chars per token)"""
    return len(text) // 4


def _build_context(messages: List[dict], ai_service=None) -> str:
    """
    Build conversation context from message history.
    
    For short conversations: include all messages
    For long conversations: summarize older messages
    """
    if not messages:
        return ""
    
    # Exclude the current (last) message
    history = messages[:-1] if len(messages) > 1 else []
    
    if not history:
        return ""
    
    # If conversation is short, include everything
    if len(history) <= MAX_CONTEXT_MESSAGES:
        context_parts = []
        for msg in history:
            role = "User" if msg["role"] == "user" else "Assistant"
            # Truncate very long messages
            content = msg['content'][:1000] if len(msg['content']) > 1000 else msg['content']
            context_parts.append(f"{role}: {content}")
        
        return "Previous conversation:\n" + "\n".join(context_parts)
    
    # Long conversation - summarize older messages, keep recent ones
    recent = history[-MAX_CONTEXT_MESSAGES:]
    older = history[:-MAX_CONTEXT_MESSAGES]
    
    # Build summary of older messages
    summary_parts = []
    for msg in older:
        role = "User" if msg["role"] == "user" else "Assistant"
        # Extract key points (first 100 chars)
        snippet = msg['content'][:100].replace('\n', ' ')
        if len(msg['content']) > 100:
            snippet += "..."
        summary_parts.append(f"- {role}: {snippet}")
    
    older_summary = f"[Earlier in conversation - {len(older)} messages summarized]:\n" + "\n".join(summary_parts[:5])
    if len(summary_parts) > 5:
        older_summary += f"\n... and {len(summary_parts) - 5} more exchanges"
    
    # Build recent context
    recent_parts = []
    for msg in recent:
        role = "User" if msg["role"] == "user" else "Assistant"
        content = msg['content'][:1000] if len(msg['content']) > 1000 else msg['content']
        recent_parts.append(f"{role}: {content}")
    
    recent_context = "\n".join(recent_parts)
    
    return f"{older_summary}\n\nRecent conversation:\n{recent_context}"


async def _build_context_with_summary(messages: List[dict], ai_service, db_manager) -> str:
    """
    Build context with AI-generated summary for very long conversations.
    
    This is more expensive but produces better context for complex conversations.
    """
    if not messages or len(messages) <= MAX_CONTEXT_MESSAGES:
        return _build_context(messages)
    
    # For very long conversations (>20 messages), generate AI summary
    if len(messages) > 20 and ai_service and ai_service.is_ready():
        older = messages[:-MAX_CONTEXT_MESSAGES]
        recent = messages[-MAX_CONTEXT_MESSAGES:]
        
        # Build text to summarize
        older_text = "\n".join([
            f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content'][:500]}"
            for m in older
        ])
        
        # Generate summary (non-streaming, quick)
        summary_prompt = f"""Summarize this conversation history in 2-3 sentences, focusing on:
1. The main topics discussed
2. Any problems identified
3. Any actions taken or recommendations made

Conversation:
{older_text[:3000]}

Summary:"""
        
        try:
            result = await ai_service.provider.generate(
                summary_prompt,
                system_prompt="You are a helpful assistant that summarizes conversations concisely.",
                max_tokens=200,
                temperature=0.3
            )
            
            if result.success:
                summary = result.content
            else:
                summary = f"[{len(older)} earlier messages about system monitoring]"
        except Exception:
            summary = f"[{len(older)} earlier messages]"
        
        # Build recent context
        recent_parts = []
        for msg in recent:
            role = "User" if msg["role"] == "user" else "Assistant"
            content = msg['content'][:1000] if len(msg['content']) > 1000 else msg['content']
            recent_parts.append(f"{role}: {content}")
        
        return f"[Conversation summary]: {summary}\n\nRecent messages:\n" + "\n".join(recent_parts)
    
    # Fall back to basic summarization
    return _build_context(messages)


def _get_librarian_system_prompt() -> str:
    """Get the Librarian persona system prompt"""
    return """You are the Librarian, a senior site reliability engineer assistant for LogLibrarian.

PERSONALITY:
- Concise and direct - no fluff or filler phrases
- Evidence-based - every claim cites specific data you retrieved
- Humble about uncertainty - "I don't see that in the data" not "that didn't happen"
- Proactive - mention related issues you notice while investigating

CRITICAL RULES:
1. NEVER guess or hallucinate. If the data doesn't show it, say "I don't have data for that"
2. ALWAYS cite your sources: "According to the metrics..." or "The logs show..."
3. When results are limited or summarized, say so
4. Use tables and lists for multiple items - they're easier to scan
5. Include timestamps in a readable format when relevant

RESPONSE FORMAT:
- Lead with the direct answer to the question
- Follow with supporting evidence and data
- End with recommendations or next steps if applicable
- Keep responses concise - users can ask follow-up questions"""


def _build_tool_system_prompt(base_prompt: str, tool_schemas: list) -> str:
    """Build system prompt with tool instructions"""
    tool_list = "\n".join([
        f"- {t['function']['name']}: {t['function']['description']}"
        for t in tool_schemas
    ])
    
    return f"""{base_prompt}

You have access to tools to query system data:

{tool_list}

To use a tool, respond with ONLY the JSON tool call - nothing else:
```json
{{"tool": "tool_name", "arguments": {{"param1": "value1"}}}}
```

IMPORTANT RULES:
1. When calling a tool, output ONLY the JSON - no other text before or after
2. DO NOT make up or guess tool results - wait for the actual response
3. After receiving real tool results, then provide your analysis
4. If you don't need to call a tool, respond directly to the user
5. Use fuzzy name matching - you don't need exact hostnames
6. Never fabricate data - only use actual tool results"""


def _auto_title_conversation(db_manager, conversation_id: str, first_message: str):
    """Auto-generate a title from the first message"""
    # Simple: use first 50 chars of message
    title = first_message[:50]
    if len(first_message) > 50:
        title += "..."
    db_manager.update_conversation_title(conversation_id, title)


# ==================== STATUS ENDPOINTS ====================

@router.get("/status")
async def get_ai_status(db_manager = Depends(get_db_manager)):
    """Get AI service status"""
    ai_service = get_ai_service(db_manager)
    
    if not ai_service:
        return {
            "enabled": False,
            "ready": False,
            "message": "AI service not initialized"
        }
    
    info = ai_service.get_info()
    return {
        "enabled": True,
        "ready": ai_service.is_ready(),
        "provider": info.get("type"),
        "model": info.get("model"),
        "model_loaded": info.get("model_loaded", False)
    }


@router.get("/tools")
async def list_available_tools():
    """List all available AI tools"""
    registry = get_tool_registry()
    tools = registry.get_all_schemas()
    
    # Group by category
    by_category = {}
    for tool in tools:
        category = tool.get("category", "other")
        if category not in by_category:
            by_category[category] = []
        by_category[category].append({
            "name": tool["name"],
            "description": tool["description"]
        })
    
    return {
        "total_tools": len(tools),
        "by_category": by_category
    }


# ==================== PROACTIVE INSIGHTS ENDPOINTS ====================

@router.get("/insights")
async def get_proactive_insights_endpoint(
    db_manager = Depends(get_db_manager)
):
    """
    Get proactive insights about the current system state.
    
    Returns anomalies, trends, correlations, and suggestions.
    """
    insights_service = get_proactive_insights()
    
    try:
        insights = await insights_service.analyze_current_state(db_manager)
        
        return {
            "anomalies": [a.to_markdown() for a in insights.get('anomalies', [])],
            "trends": [t.to_markdown() for t in insights.get('trends', [])],
            "correlations": [c.to_markdown() for c in insights.get('correlations', [])],
            "suggestions": [s.to_markdown() for s in insights.get('suggestions', [])],
            "summary": insights_service.format_insights_summary(insights)
        }
    except Exception as e:
        return {
            "anomalies": [],
            "trends": [],
            "correlations": [],
            "suggestions": [],
            "summary": f"Unable to analyze: {str(e)}"
        }


@router.get("/optimizer/stats")
async def get_optimizer_stats():
    """Get query optimizer statistics (cache hits, etc.)"""
    optimizer = get_query_optimizer()
    return optimizer.get_stats()


@router.post("/optimizer/invalidate")
async def invalidate_cache(query_type: Optional[str] = None):
    """Invalidate query cache"""
    optimizer = get_query_optimizer()
    optimizer.invalidate_cache(query_type)
    return {"success": True, "invalidated": query_type or "all"}


# ==================== PHASE 6: HELP ENDPOINTS ====================

@router.get("/help")
async def get_help():
    """Get help documentation overview"""
    help_service = get_help_service()
    return {
        "quick_start": help_service.get_quick_start_guide(),
        "categories": help_service.get_categories(),
        "features": list(help_service.features.keys())
    }


@router.get("/help/examples")
async def get_examples(
    category: Optional[str] = None,
    difficulty: Optional[str] = None,
    limit: int = Query(10, ge=1, le=50)
):
    """Get example queries, optionally filtered"""
    help_service = get_help_service()
    examples = help_service.get_examples(
        category=category,
        difficulty=difficulty,
        limit=limit
    )
    return {
        "examples": [
            {
                "query": e.query,
                "description": e.description,
                "category": e.category,
                "difficulty": e.difficulty
            }
            for e in examples
        ]
    }


@router.get("/help/tips")
async def get_tips(category: Optional[str] = None):
    """Get tips and best practices"""
    help_service = get_help_service()
    return {
        "tips": help_service.get_tips(category=category)
    }


@router.get("/help/feature/{feature_name}")
async def get_feature_help(feature_name: str):
    """Get detailed documentation for a feature"""
    help_service = get_help_service()
    features = help_service.get_feature_docs(feature_name)
    
    if not features or feature_name not in features:
        raise HTTPException(status_code=404, detail="Feature not found")
    
    feature = features[feature_name]
    return {
        "feature": {
            "title": feature.title,
            "description": feature.description,
            "capabilities": feature.capabilities,
            "limitations": feature.limitations,
            "tips": feature.tips
        },
        "markdown": HelpFormatter.format_feature_markdown(feature)
    }


@router.get("/help/search")
async def search_help(q: str):
    """Search help content"""
    help_service = get_help_service()
    results = help_service.search_help(q)
    
    return {
        "query": q,
        "results": {
            "examples": [
                {"query": e.query, "description": e.description}
                for e in results["examples"]
            ],
            "features": [
                {"title": f.title, "description": f.description}
                for f in results["features"]
            ],
            "tips": results["tips"]
        }
    }


# ==================== PHASE 6: SECURITY ENDPOINTS ====================

@router.get("/security/status")
async def get_security_status():
    """Get security service status"""
    security = get_security_service()
    return security.get_status()


@router.get("/resilience/status")
async def get_resilience_status():
    """Get resilience service status (circuit breakers)"""
    resilience = get_resilience_service()
    return resilience.get_status()
