"""
AI Service Module - Provider Pattern Implementation

Supports multiple AI backends:
- CloudProvider: OpenAI API (GPT-4, GPT-3.5-turbo)
- LocalProvider: Local inference engine (llama.cpp, etc.)

Now with Tool System:
- Tools allow AI to query system data (agents, logs, bookmarks, alerts)
- Safety limits prevent runaway queries
- Multiple turns allow iterative data gathering
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
import httpx
import asyncio
import json
from dataclasses import dataclass

# Import tool system
from ai_tools import (
    ToolRegistry, ToolExecutor, ToolCallParser, ToolResult,
    estimate_tokens, truncate_results
)


# ==================== DATA CLASSES ====================

@dataclass
class AISettings:
    """AI configuration settings from database"""
    provider: str = "local"  # "local" or "openai"
    local_model_id: str = "gemma-2-2b"
    openai_key: str = ""
    feature_flags: Dict[str, bool] = None
    
    def __post_init__(self):
        if self.feature_flags is None:
            self.feature_flags = {
                "daily_briefing": True,
                "tips": True,
                "alert_analysis": True,
                "post_mortem": True
            }


@dataclass
class GenerationResult:
    """Result from AI generation"""
    success: bool
    content: str = ""
    error: str = ""
    tokens_used: int = 0
    model: str = ""


# ==================== PROVIDER INTERFACE ====================

class AIProvider(ABC):
    """Abstract base class for AI providers"""
    
    @abstractmethod
    async def generate(self, prompt: str, system_prompt: str = None, 
                       max_tokens: int = 1024, temperature: float = 0.7) -> GenerationResult:
        """
        Generate text from a prompt.
        
        Args:
            prompt: The user prompt/question
            system_prompt: Optional system context
            max_tokens: Maximum tokens to generate
            temperature: Creativity (0.0-1.0)
            
        Returns:
            GenerationResult with success status and content/error
        """
        pass
    
    @abstractmethod
    def is_ready(self) -> bool:
        """
        Check if the provider is ready to generate.
        
        Returns:
            True if model is loaded (local) or API key is valid (cloud)
        """
        pass
    
    @abstractmethod
    async def load_model(self, model_id: str) -> bool:
        """
        Load a specific model (primarily for local provider).
        
        Args:
            model_id: The model identifier to load
            
        Returns:
            True if model loaded successfully
        """
        pass
    
    @abstractmethod
    async def unload_model(self) -> bool:
        """
        Unload the current model to free resources.
        
        Returns:
            True if unloaded successfully
        """
        pass
    
    @abstractmethod
    def get_info(self) -> Dict[str, Any]:
        """
        Get provider information and status.
        
        Returns:
            Dict with provider details
        """
        pass


# ==================== CLOUD PROVIDER (OpenAI) ====================

class CloudProvider(AIProvider):
    """OpenAI API provider implementation"""
    
    OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
    DEFAULT_MODEL = "gpt-4o-mini"
    
    def __init__(self, api_key: str, model: str = None):
        self.api_key = api_key
        self.model = model or self.DEFAULT_MODEL
        self._validated = False
        self._last_error = ""
    
    async def generate(self, prompt: str, system_prompt: str = None,
                       max_tokens: int = 1024, temperature: float = 0.7) -> GenerationResult:
        """Generate text using OpenAI API"""
        
        if not self.api_key:
            return GenerationResult(
                success=False,
                error="OpenAI API key not configured"
            )
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature
        }
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    self.OPENAI_API_URL,
                    headers=headers,
                    json=payload
                )
                
                if response.status_code == 401:
                    self._validated = False
                    return GenerationResult(
                        success=False,
                        error="Invalid OpenAI API key"
                    )
                
                if response.status_code == 429:
                    return GenerationResult(
                        success=False,
                        error="Rate limited - please try again later"
                    )
                
                if response.status_code != 200:
                    return GenerationResult(
                        success=False,
                        error=f"OpenAI API error: {response.status_code}"
                    )
                
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                tokens = data.get("usage", {}).get("total_tokens", 0)
                
                self._validated = True
                
                return GenerationResult(
                    success=True,
                    content=content,
                    tokens_used=tokens,
                    model=self.model
                )
                
        except httpx.TimeoutException:
            return GenerationResult(
                success=False,
                error="Request timed out"
            )
        except Exception as e:
            self._last_error = str(e)
            return GenerationResult(
                success=False,
                error=f"Request failed: {str(e)}"
            )
    
    async def generate_stream(self, prompt: str, system_prompt: str = None,
                              max_tokens: int = 1024, temperature: float = 0.7):
        """
        Generate text with streaming from OpenAI API.
        
        Yields:
            dict with 'token' key for each generated token
            Final dict has 'done': True
        """
        if not self.api_key:
            yield {"error": "OpenAI API key not configured", "done": True}
            return
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True
        }
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                async with client.stream(
                    "POST",
                    self.OPENAI_API_URL,
                    headers=headers,
                    json=payload
                ) as response:
                    if response.status_code != 200:
                        yield {"error": f"OpenAI API error: {response.status_code}", "done": True}
                        return
                    
                    full_content = ""
                    tokens_generated = 0
                    
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            data_str = line[6:]
                            if data_str == "[DONE]":
                                break
                            try:
                                data = json.loads(data_str)
                                delta = data["choices"][0].get("delta", {})
                                token = delta.get("content", "")
                                if token:
                                    full_content += token
                                    tokens_generated += 1
                                    yield {"token": token, "done": False}
                            except json.JSONDecodeError:
                                continue
                    
                    self._validated = True
                    yield {
                        "done": True,
                        "content": full_content,
                        "tokens_used": tokens_generated
                    }
                    
        except httpx.TimeoutException:
            yield {"error": "Request timed out", "done": True}
        except Exception as e:
            self._last_error = str(e)
            yield {"error": f"Request failed: {str(e)}", "done": True}
    
    def is_ready(self) -> bool:
        """Check if API key is configured"""
        return bool(self.api_key and len(self.api_key) > 20)
    
    async def load_model(self, model_id: str) -> bool:
        """Set the model to use (no actual loading for cloud)"""
        self.model = model_id
        return True
    
    async def unload_model(self) -> bool:
        """No-op for cloud provider"""
        return True
    
    def get_info(self) -> Dict[str, Any]:
        """Get provider status"""
        return {
            "type": "cloud",
            "provider": "openai",
            "model": self.model,
            "ready": self.is_ready(),
            "validated": self._validated,
            "has_key": bool(self.api_key)
        }


# ==================== LOCAL PROVIDER ====================

class LocalProvider(AIProvider):
    """
    Local inference provider using llama-cpp-python.
    
    Uses the llama-cpp-python library for direct in-process inference,
    eliminating the need for external binaries with library dependencies.
    
    Supports GPU acceleration:
    - NVIDIA CUDA
    - AMD ROCm  
    - Intel Arc (SYCL)
    - CPU fallback
    """
    
    # Model registry
    AVAILABLE_MODELS = {
        "gemma-2-2b": {
            "name": "Gemma 2 2B",
            "size_gb": 1.5,
            "context_length": 8192,
        },
        "phi-3-mini": {
            "name": "Phi-3 Mini",
            "size_gb": 2.2,
            "context_length": 4096,
        },
        "llama-3.2-1b": {
            "name": "Llama 3.2 1B",
            "size_gb": 0.7,
            "context_length": 8192,
        },
        "qwen2.5-1.5b": {
            "name": "Qwen 2.5 1.5B",
            "size_gb": 1.0,
            "context_length": 32768,
        },
        "qwen2.5-7b": {
            "name": "Qwen 2.5 7B",
            "size_gb": 4.7,
            "context_length": 131072,
        }
    }
    
    # Singleton model instance (shared across requests)
    _llm = None
    _loaded_model_id = None
    _load_lock = None
    _db_manager = None  # Reference to db_manager for settings
    
    def __init__(self, model_id: str = "gemma-2-2b", models_path: str = "/app/data/ai", db_manager=None):
        self.model_id = model_id
        self.models_path = models_path
        self._last_error = ""
        
        if db_manager:
            LocalProvider._db_manager = db_manager
        
        # Initialize async lock if needed
        if LocalProvider._load_lock is None:
            import asyncio
            try:
                LocalProvider._load_lock = asyncio.Lock()
            except RuntimeError:
                # No event loop yet, will be created later
                pass
    
    def _get_gpu_layers(self) -> int:
        """
        Get number of GPU layers to offload based on configured backend.
        
        Returns:
            Number of GPU layers (0 for CPU, -1 for all layers on GPU)
        """
        if LocalProvider._db_manager is None:
            return 0
        
        backend = LocalProvider._db_manager.get_system_setting('ai_backend')
        
        if backend in ('cuda', 'rocm', 'sycl'):
            # Offload all layers to GPU for maximum performance
            return -1
        
        # CPU fallback
        return 0
    
    def _get_model_filename(self, model_id: str) -> str:
        """Get the filename for a model"""
        model_files = {
            "gemma-2-2b": "gemma-2-2b-it-q4_k_m.gguf",
            "llama-3.2-1b": "Llama-3.2-1B-Instruct-Q4_K_M.gguf", 
            "qwen-2.5-1.5b": "qwen2.5-1.5b-instruct-q4_k_m.gguf",
            "qwen2.5-7b": "Qwen2.5-7B-Instruct-Q4_K_M.gguf",
            "phi-3-mini": "Phi-3-mini-4k-instruct-q4.gguf"
        }
        return model_files.get(model_id, f"{model_id}.gguf")
    
    def _get_model_path(self, model_id: str = None) -> str:
        """Get full path to model file"""
        from pathlib import Path
        mid = model_id or self.model_id
        return str(Path(self.models_path) / self._get_model_filename(mid))
    
    def _ensure_model_loaded(self) -> bool:
        """Ensure the model is loaded into memory (synchronous)"""
        from pathlib import Path
        
        model_path = self._get_model_path()
        
        # Check if correct model is already loaded
        if LocalProvider._llm is not None and LocalProvider._loaded_model_id == self.model_id:
            return True
        
        # Check if model file exists
        if not Path(model_path).exists():
            self._last_error = f"Model file not found: {model_path}"
            return False
        
        # Unload existing model if different
        if LocalProvider._llm is not None:
            del LocalProvider._llm
            LocalProvider._llm = None
            LocalProvider._loaded_model_id = None
        
        # Load new model
        try:
            from llama_cpp import Llama
            
            print(f"Loading model: {self.model_id} from {model_path}")
            
            # Determine context size based on model
            model_info = self.AVAILABLE_MODELS.get(self.model_id, {})
            n_ctx = min(model_info.get("context_length", 4096), 4096)  # Cap at 4096 for memory
            
            # Get GPU layers based on configured backend
            n_gpu_layers = self._get_gpu_layers()
            backend = "GPU" if n_gpu_layers != 0 else "CPU"
            print(f"Using {backend} acceleration (n_gpu_layers={n_gpu_layers})")
            
            LocalProvider._llm = Llama(
                model_path=model_path,
                n_ctx=n_ctx,
                n_threads=4,  # Use 4 threads for inference
                n_gpu_layers=n_gpu_layers,
                verbose=False,
                chat_format="chatml"  # Works for most instruction-tuned models
            )
            LocalProvider._loaded_model_id = self.model_id
            
            # Update database that model is loaded
            if LocalProvider._db_manager:
                LocalProvider._db_manager.set_system_setting('ai_current_model', self.model_id)
                LocalProvider._db_manager.set_system_setting('ai_model_loaded', 'true')
            
            print(f"Model {self.model_id} loaded successfully")
            return True
            
        except ImportError as e:
            self._last_error = f"llama-cpp-python not installed: {e}"
            return False
        except Exception as e:
            self._last_error = f"Failed to load model: {e}"
            print(f"Model loading error: {e}")
            return False
    
    async def generate(self, prompt: str, system_prompt: str = None,
                       max_tokens: int = 1024, temperature: float = 0.7) -> GenerationResult:
        """Generate text using local model via llama-cpp-python"""
        import asyncio
        
        # Ensure lock exists
        if LocalProvider._load_lock is None:
            LocalProvider._load_lock = asyncio.Lock()
        
        # Load model if needed (with lock to prevent concurrent loading)
        async with LocalProvider._load_lock:
            if not self._ensure_model_loaded():
                return GenerationResult(
                    success=False,
                    error=self._last_error or "Failed to load model"
                )
        
        # Build messages for chat completion
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        try:
            # Run inference in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: LocalProvider._llm.create_chat_completion(
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    stop=["<|im_end|>", "<|endoftext|>", "</s>"]
                )
            )
            
            content = result["choices"][0]["message"]["content"]
            tokens_used = result.get("usage", {}).get("total_tokens", 0)
            
            return GenerationResult(
                success=True,
                content=content.strip(),
                tokens_used=tokens_used,
                model=self.model_id
            )
            
        except Exception as e:
            self._last_error = str(e)
            return GenerationResult(
                success=False,
                error=f"Generation failed: {e}"
            )
    
    async def generate_stream(self, prompt: str, system_prompt: str = None,
                              max_tokens: int = 1024, temperature: float = 0.7):
        """
        Generate text with streaming (yields tokens one at a time).
        
        Yields:
            dict with 'token' key for each generated token
            Final dict has 'done': True and total 'tokens_used'
        """
        import asyncio
        
        # Ensure lock exists
        if LocalProvider._load_lock is None:
            LocalProvider._load_lock = asyncio.Lock()
        
        # Load model if needed
        async with LocalProvider._load_lock:
            if not self._ensure_model_loaded():
                yield {"error": self._last_error or "Failed to load model", "done": True}
                return
        
        # Build messages
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        try:
            # Use streaming API
            stream = LocalProvider._llm.create_chat_completion(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stop=["<|im_end|>", "<|endoftext|>", "</s>"],
                stream=True
            )
            
            full_content = ""
            tokens_generated = 0
            
            # Iterate through stream in executor to not block
            loop = asyncio.get_event_loop()
            
            def get_next_chunk():
                try:
                    return next(stream)
                except StopIteration:
                    return None
            
            while True:
                chunk = await loop.run_in_executor(None, get_next_chunk)
                if chunk is None:
                    break
                
                # Extract token from chunk
                if chunk.get("choices"):
                    delta = chunk["choices"][0].get("delta", {})
                    token = delta.get("content", "")
                    if token:
                        full_content += token
                        tokens_generated += 1
                        yield {"token": token, "done": False}
            
            yield {
                "done": True,
                "content": full_content,
                "tokens_used": tokens_generated
            }
            
        except Exception as e:
            self._last_error = str(e)
            yield {"error": str(e), "done": True}
    
    def is_ready(self) -> bool:
        """Check if the provider can generate (model loaded or can be loaded)"""
        # If model is already loaded, we're ready
        if LocalProvider._llm is not None and LocalProvider._loaded_model_id == self.model_id:
            return True
        
        # Check if model file exists
        from pathlib import Path
        model_path = Path(self.models_path) / self._get_model_filename(self.model_id)
        if not model_path.exists():
            return False
        
        # Try to load the model (this is called when checking readiness)
        return self._ensure_model_loaded()
    
    async def load_model(self, model_id: str) -> bool:
        """Load a specific model"""
        if model_id not in self.AVAILABLE_MODELS:
            self._last_error = f"Unknown model: {model_id}"
            return False
        
        self.model_id = model_id
        return self._ensure_model_loaded()
    
    async def unload_model(self) -> bool:
        """Unload the current model to free memory"""
        if LocalProvider._llm is not None:
            del LocalProvider._llm
            LocalProvider._llm = None
            LocalProvider._loaded_model_id = None
            
            # Update database
            if LocalProvider._db_manager:
                LocalProvider._db_manager.set_system_setting('ai_model_loaded', 'false')
        return True
    
    def get_info(self) -> Dict[str, Any]:
        """Get provider status"""
        model_info = self.AVAILABLE_MODELS.get(self.model_id, {})
        
        return {
            "type": "local",
            "provider": "local",
            "model": self.model_id,
            "model_name": model_info.get("name", self.model_id),
            "ready": self.is_ready(),
            "model_loaded": LocalProvider._llm is not None,
            "loaded_model": LocalProvider._loaded_model_id,
            "available_models": list(self.AVAILABLE_MODELS.keys()),
            "last_error": self._last_error
        }
    
    @classmethod
    def get_available_models(cls) -> Dict[str, Any]:
        """Get list of available local models"""
        return cls.AVAILABLE_MODELS.copy()


# ==================== AI SERVICE ====================

class AIService:
    """
    Main AI Service that manages providers.
    
    Usage:
        settings = AISettings(provider="openai", openai_key="sk-...")
        service = init_ai_service(settings)
        
        if service.is_ready():
            result = await service.generate("Summarize these logs...")
    """
    
    def __init__(self, provider: AIProvider, settings: AISettings):
        self._provider = provider
        self._settings = settings
    
    @property
    def provider(self) -> AIProvider:
        """Get the active provider"""
        return self._provider
    
    @property
    def settings(self) -> AISettings:
        """Get current settings"""
        return self._settings
    
    def is_ready(self) -> bool:
        """Check if the service is ready to generate"""
        return self._provider.is_ready()
    
    async def generate(self, prompt: str, system_prompt: str = None,
                       max_tokens: int = 1024, temperature: float = 0.7) -> GenerationResult:
        """Generate text using the active provider"""
        return await self._provider.generate(prompt, system_prompt, max_tokens, temperature)
    
    async def load_model(self, model_id: str) -> bool:
        """Load a model (for local provider)"""
        return await self._provider.load_model(model_id)
    
    async def unload_model(self) -> bool:
        """Unload the current model"""
        return await self._provider.unload_model()
    
    def get_info(self) -> Dict[str, Any]:
        """Get service information"""
        provider_info = self._provider.get_info()
        return {
            **provider_info,
            "feature_flags": self._settings.feature_flags,
            "configured_provider": self._settings.provider
        }
    
    def is_feature_enabled(self, feature: str) -> bool:
        """Check if a feature is enabled"""
        return self._settings.feature_flags.get(feature, False)
    
    async def generate_stream(self, prompt: str, system_prompt: str = None,
                              max_tokens: int = 1024, temperature: float = 0.7):
        """
        Generate text with streaming.
        
        Yields dicts with 'token' for each generated token.
        Final dict has 'done': True.
        """
        if hasattr(self._provider, 'generate_stream'):
            async for chunk in self._provider.generate_stream(
                prompt, system_prompt, max_tokens, temperature
            ):
                yield chunk
        else:
            # Fallback to non-streaming
            result = await self._provider.generate(prompt, system_prompt, max_tokens, temperature)
            if result.success:
                yield {"token": result.content, "done": False}
                yield {"done": True, "content": result.content, "tokens_used": result.tokens_used}
            else:
                yield {"error": result.error, "done": True}
    
    async def generate_with_tools(
        self,
        prompt: str,
        db_manager,
        system_prompt: str = None,
        max_tokens: int = 2048,
        temperature: float = 0.3,
        max_turns: int = 3
    ) -> GenerationResult:
        """
        Generate response with tool calling capability.
        
        The AI can call tools to fetch data from the system, then
        synthesize a response based on the retrieved information.
        
        Args:
            prompt: User question
            db_manager: Database manager for tool execution
            system_prompt: Optional system context
            max_tokens: Max tokens per generation
            temperature: Lower is more focused
            max_turns: Maximum tool-calling iterations
            
        Returns:
            GenerationResult with final response
        """
        # Get available tools for the system prompt
        tool_schemas = ToolRegistry.get_tool_schemas()
        
        # Build enhanced system prompt with tool instructions
        tool_prompt = self._build_tool_system_prompt(system_prompt, tool_schemas)
        
        # Initialize executor
        executor = ToolExecutor(db_manager)
        
        # Track conversation for multi-turn
        messages = [prompt]
        tool_results_text = ""
        total_tokens = 0
        
        for turn in range(max_turns):
            # Build full prompt with any previous tool results
            full_prompt = prompt
            if tool_results_text:
                full_prompt = f"{prompt}\n\n[Tool Results from previous queries]\n{tool_results_text}"
            
            # Generate
            result = await self._provider.generate(
                full_prompt,
                tool_prompt,
                max_tokens,
                temperature
            )
            
            if not result.success:
                return result
            
            total_tokens += result.tokens_used
            
            # Check for tool calls in response
            tool_calls = ToolCallParser.parse(result.content)
            
            if not tool_calls:
                # No tool calls - this is the final response
                return GenerationResult(
                    success=True,
                    content=result.content,
                    tokens_used=total_tokens,
                    model=result.model
                )
            
            # Execute tool calls
            new_results = []
            for call in tool_calls:
                tool_result = await executor.execute_tool(
                    call.get('tool') or call.get('name'),
                    call.get('arguments') or call.get('args', {})
                )
                
                if tool_result:
                    # Format result for context
                    result_text = self._format_tool_result(
                        call.get('tool') or call.get('name'),
                        tool_result
                    )
                    new_results.append(result_text)
            
            if new_results:
                tool_results_text += "\n".join(new_results) + "\n"
            
            # Check if we should continue
            if executor.total_tokens_used >= 4000:
                # Token budget reached, force final response
                final_prompt = f"{prompt}\n\n[Tool Results]\n{tool_results_text}\n\nPlease provide your response based on the data above. Do not make additional tool calls."
                
                final_result = await self._provider.generate(
                    final_prompt,
                    system_prompt,  # Use original without tool instructions
                    max_tokens,
                    temperature
                )
                
                return GenerationResult(
                    success=final_result.success,
                    content=final_result.content,
                    tokens_used=total_tokens + final_result.tokens_used,
                    model=final_result.model,
                    error=final_result.error
                )
        
        # Max turns reached - generate final response
        final_prompt = f"{prompt}\n\n[Tool Results]\n{tool_results_text}\n\nPlease provide your final response."
        
        final_result = await self._provider.generate(
            final_prompt,
            system_prompt,
            max_tokens,
            temperature
        )
        
        return GenerationResult(
            success=final_result.success,
            content=final_result.content,
            tokens_used=total_tokens + final_result.tokens_used,
            model=final_result.model,
            error=final_result.error
        )
    
    def _build_tool_system_prompt(self, base_prompt: str, tool_schemas: List[Dict]) -> str:
        """Build system prompt with tool instructions"""
        
        tool_list = "\n".join([
            f"- {t['name']}: {t['description']}"
            for t in tool_schemas
        ])
        
        tool_instructions = f"""You are Librarian, an AI assistant for a log management and monitoring system.

You have access to the following tools to query system data:

{tool_list}

To use a tool, respond with a JSON object in this format:
```json
{{"tool": "tool_name", "arguments": {{"param1": "value1"}}}}
```

Guidelines:
1. Only call tools when you need specific data to answer the question
2. Use fuzzy name matching - you don't need exact hostnames
3. Prefer summary tools (get_system_health, count_logs) over detailed queries
4. After receiving tool results, synthesize a clear, helpful response
5. If you have enough information, respond directly without tool calls

{base_prompt or ''}"""
        
        return tool_instructions
    
    def _format_tool_result(self, tool_name: str, result: ToolResult) -> str:
        """Format a tool result for inclusion in context"""
        
        if not result.success:
            return f"[{tool_name}] Error: {result.error}"
        
        # Truncate if needed
        data = result.data
        if isinstance(data, dict):
            data_str = json.dumps(data, indent=2, default=str)
        else:
            data_str = str(data)
        
        if len(data_str) > 2000:
            data_str = truncate_results(data, max_tokens=500)
        
        return f"[{tool_name}] Result:\n{data_str}"


# ==================== FACTORY ====================

def _register_all_tools():
    """Import all tool modules to register their tools"""
    try:
        import ai_tools_scribes
        import ai_tools_logs
        import ai_tools_bookmarks
        import ai_tools_alerts
    except ImportError as e:
        print(f"Warning: Could not import all tool modules: {e}")


def init_ai_service(settings: AISettings, db_manager=None) -> AIService:
    """
    Factory function to create an AI service with the appropriate provider.
    
    Args:
        settings: AISettings from database
        db_manager: Optional database manager for settings access
        
    Returns:
        AIService instance configured with the correct provider
    """
    # Register all tools on first init
    _register_all_tools()
    
    if settings.provider == "openai":
        provider = CloudProvider(
            api_key=settings.openai_key,
            model="gpt-4o-mini"  # Default model
        )
    else:
        # Default to local provider
        provider = LocalProvider(
            model_id=settings.local_model_id,
            db_manager=db_manager
        )
    
    return AIService(provider, settings)


def init_ai_service_from_db(db_manager) -> AIService:
    """
    Initialize AI service from database settings.
    
    Args:
        db_manager: DatabaseManager instance
        
    Returns:
        AIService instance
    """
    db_settings = db_manager.get_ai_settings()
    
    settings = AISettings(
        provider=db_settings.get("provider", "local"),
        local_model_id=db_settings.get("local_model_id", "gemma-2-2b"),
        openai_key=db_settings.get("openai_key", ""),
        feature_flags=db_settings.get("feature_flags", {})
    )
    
    return init_ai_service(settings, db_manager)


# ==================== SINGLETON INSTANCE ====================

_ai_service: Optional[AIService] = None


def get_ai_service(db_manager=None) -> Optional[AIService]:
    """
    Get or create the global AI service instance.
    
    Args:
        db_manager: Optional DatabaseManager to initialize from
        
    Returns:
        AIService instance or None if not initialized
    """
    global _ai_service
    
    if _ai_service is None and db_manager is not None:
        _ai_service = init_ai_service_from_db(db_manager)
    
    return _ai_service


def reload_ai_service(db_manager) -> AIService:
    """
    Reload the AI service with fresh settings from database.
    Call this after settings are updated.
    
    Args:
        db_manager: DatabaseManager instance
        
    Returns:
        New AIService instance
    """
    global _ai_service
    _ai_service = init_ai_service_from_db(db_manager)
    return _ai_service
