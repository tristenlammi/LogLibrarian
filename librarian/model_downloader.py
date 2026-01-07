"""
Zero Setup Model Downloader

Downloads GGUF models from HuggingFace with:
- Progress tracking
- SHA256 verification
- Resume support for interrupted downloads
- Database cache updates
"""

import os
import hashlib
import asyncio
import aiohttp
import aiofiles
from pathlib import Path
from typing import Callable, Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)


# ==================== MODEL DEFINITIONS ====================

@dataclass
class ModelDefinition:
    """Definition of a downloadable model"""
    id: str
    name: str
    description: str
    size_mb: int
    context_length: int
    url: str
    sha256: str
    filename: str


class ModelCategory(Enum):
    LIGHTWEIGHT = "lightweight"
    TECHNICAL = "technical"
    SMARTEST = "smartest"


# Available models with verified HuggingFace GGUF URLs
# Using Q4_K_M quantization for good balance of quality/size
# Note: Hash verification disabled - HuggingFace models are frequently updated
AVAILABLE_MODELS: Dict[str, ModelDefinition] = {
    "llama-3.2-1b": ModelDefinition(
        id="llama-3.2-1b",
        name="Llama 3.2 1B Instruct",
        description="Lightweight & fast - great for simple tasks",
        size_mb=750,
        context_length=8192,
        url="https://huggingface.co/bartowski/Llama-3.2-1B-Instruct-GGUF/resolve/main/Llama-3.2-1B-Instruct-Q4_K_M.gguf",
        sha256="",  # Skip verification - HuggingFace models update frequently
        filename="llama-3.2-1b-instruct-q4_k_m.gguf"
    ),
    "qwen-2.5-1.5b": ModelDefinition(
        id="qwen-2.5-1.5b",
        name="Qwen 2.5 1.5B Instruct",
        description="Technical focus - excellent for code & logs",
        size_mb=1100,
        context_length=32768,
        url="https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf",
        sha256="",  # Skip verification - HuggingFace models update frequently
        filename="qwen2.5-1.5b-instruct-q4_k_m.gguf"
    ),
    "gemma-2-2b": ModelDefinition(
        id="gemma-2-2b",
        name="Gemma 2 2B Instruct",
        description="Smartest small model - best quality output",
        size_mb=1500,
        context_length=8192,
        url="https://huggingface.co/bartowski/gemma-2-2b-it-GGUF/resolve/main/gemma-2-2b-it-Q4_K_M.gguf",
        sha256="",  # Skip verification - HuggingFace models update frequently
        filename="gemma-2-2b-it-q4_k_m.gguf"
    ),
    "qwen2.5-7b": ModelDefinition(
        id="qwen2.5-7b",
        name="Qwen 2.5 7B Instruct",
        description="Large model - 128k context, best for complex analysis",
        size_mb=4800,
        context_length=131072,
        url="https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF/resolve/main/Qwen2.5-7B-Instruct-Q4_K_M.gguf",
        sha256="",  # Skip verification - HuggingFace models update frequently
        filename="Qwen2.5-7B-Instruct-Q4_K_M.gguf"
    ),
}

# Default models directory
DEFAULT_MODELS_PATH = "/app/data/ai"


# ==================== DOWNLOAD STATUS ====================

@dataclass
class DownloadStatus:
    """Status of a model download"""
    model_id: str
    state: str  # "pending", "downloading", "verifying", "complete", "error"
    progress: float  # 0-100
    downloaded_bytes: int
    total_bytes: int
    speed_mbps: float
    error: Optional[str] = None


# ==================== PROGRESS TRACKING READER ====================

class ProgressReader:
    """Wraps an async stream to track download progress"""
    
    def __init__(self, response: aiohttp.ClientResponse, 
                 callback: Callable[[float, int, int], None] = None):
        self.response = response
        self.callback = callback
        self.total_size = int(response.headers.get('content-length', 0))
        self.downloaded = 0
        self._last_callback_time = 0
    
    async def read_chunks(self, chunk_size: int = 1024 * 1024):  # 1MB chunks
        """Yield chunks while tracking progress"""
        import time
        
        async for chunk in self.response.content.iter_chunked(chunk_size):
            self.downloaded += len(chunk)
            
            # Throttle callbacks to every 100ms
            current_time = time.time()
            if self.callback and (current_time - self._last_callback_time > 0.1):
                progress = (self.downloaded / self.total_size * 100) if self.total_size > 0 else 0
                self.callback(progress, self.downloaded, self.total_size)
                self._last_callback_time = current_time
            
            yield chunk
        
        # Final callback at 100%
        if self.callback and self.total_size > 0:
            self.callback(100.0, self.downloaded, self.total_size)


# ==================== MODEL DOWNLOADER ====================

class ModelDownloader:
    """
    Downloads and manages local AI models.
    
    Usage:
        downloader = ModelDownloader(db_manager)
        
        # Download with progress callback
        success = await downloader.download_model(
            "gemma-2-2b",
            progress_callback=lambda p, d, t: print(f"{p:.1f}%")
        )
    """
    
    def __init__(self, db_manager=None, models_path: str = None):
        self.db_manager = db_manager
        self.models_path = Path(models_path or DEFAULT_MODELS_PATH)
        self._active_downloads: Dict[str, DownloadStatus] = {}
    
    def get_model_path(self, model_id: str) -> Path:
        """Get the full path for a model file"""
        if model_id not in AVAILABLE_MODELS:
            raise ValueError(f"Unknown model: {model_id}")
        
        model = AVAILABLE_MODELS[model_id]
        return self.models_path / model.filename
    
    def is_model_downloaded(self, model_id: str) -> bool:
        """Check if a model file exists and is complete"""
        try:
            model_path = self.get_model_path(model_id)
            if not model_path.exists():
                return False
            
            # Check if file size matches expected
            model = AVAILABLE_MODELS[model_id]
            actual_size = model_path.stat().st_size
            expected_size = model.size_mb * 1024 * 1024
            
            # Allow 10% tolerance for size estimation
            return actual_size > expected_size * 0.9
        except Exception:
            return False
    
    def get_download_status(self, model_id: str) -> Optional[DownloadStatus]:
        """Get the current download status for a model"""
        return self._active_downloads.get(model_id)
    
    async def download_model(
        self,
        model_id: str,
        progress_callback: Callable[[float, int, int], None] = None,
        verify_hash: bool = True,
        max_retries: int = 3,
        retry_delay: float = 5.0
    ) -> bool:
        """
        Download a model with progress tracking and retry logic.
        
        Args:
            model_id: The model identifier to download
            progress_callback: Called with (progress_percent, downloaded_bytes, total_bytes)
            verify_hash: Whether to verify SHA256 after download
            max_retries: Maximum number of retry attempts on failure
            retry_delay: Delay in seconds between retry attempts
            
        Returns:
            True if download successful, False otherwise
        """
        
        if model_id not in AVAILABLE_MODELS:
            logger.error(f"Unknown model: {model_id}")
            return False
        
        model = AVAILABLE_MODELS[model_id]
        model_path = self.get_model_path(model_id)
        
        # Check if already downloaded
        if self.is_model_downloaded(model_id):
            logger.info(f"Model {model_id} already downloaded at {model_path}")
            if progress_callback:
                progress_callback(100.0, model.size_mb * 1024 * 1024, model.size_mb * 1024 * 1024)
            return True
        
        # Create models directory if needed
        self.models_path.mkdir(parents=True, exist_ok=True)
        
        # Initialize download status
        self._active_downloads[model_id] = DownloadStatus(
            model_id=model_id,
            state="downloading",
            progress=0,
            downloaded_bytes=0,
            total_bytes=model.size_mb * 1024 * 1024,
            speed_mbps=0
        )
        
        # Update database
        if self.db_manager:
            self.db_manager.upsert_ai_model_cache(
                model_id=model_id,
                file_path=str(model_path),
                file_size_mb=model.size_mb,
                is_downloaded=False,
                download_progress=0
            )
        
        temp_path = model_path.with_suffix('.tmp')
        last_error = None
        
        for attempt in range(1, max_retries + 1):
            try:
                if attempt > 1:
                    logger.info(f"Retry attempt {attempt}/{max_retries} for {model_id}")
                    await asyncio.sleep(retry_delay)
                    
                    # Reset status for retry
                    self._active_downloads[model_id].state = "downloading"
                    self._active_downloads[model_id].error = None
                
                # Download with resume support
                headers = {}
                start_byte = 0
                
                # Check for partial download
                if temp_path.exists():
                    start_byte = temp_path.stat().st_size
                    headers['Range'] = f'bytes={start_byte}-'
                    logger.info(f"Resuming download from byte {start_byte}")
                
                timeout = aiohttp.ClientTimeout(total=None, sock_read=60)
                
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(model.url, headers=headers) as response:
                        
                        if response.status == 416:
                            # Range not satisfiable - file might be complete or corrupted
                            logger.warning("Range not satisfiable, restarting download")
                            if temp_path.exists():
                                temp_path.unlink()
                            start_byte = 0
                            
                            # Retry without range header
                            async with session.get(model.url) as retry_response:
                                await self._download_to_file(
                                    retry_response, temp_path, model_id, 
                                    progress_callback, "wb"
                                )
                        
                        elif response.status in (200, 206):
                            mode = "ab" if response.status == 206 else "wb"
                            await self._download_to_file(
                                response, temp_path, model_id,
                                progress_callback, mode, start_byte
                            )
                        else:
                            raise Exception(f"HTTP {response.status}: {response.reason}")
                
                # Verify hash if requested and hash is provided
                actual_hash = ""
                if verify_hash and model.sha256:
                    self._active_downloads[model_id].state = "verifying"
                    
                    logger.info(f"Verifying SHA256 hash for {model_id}...")
                    actual_hash = await self._calculate_sha256(temp_path)
                    
                    if actual_hash != model.sha256:
                        logger.error(f"Hash mismatch! Expected {model.sha256}, got {actual_hash}")
                        temp_path.unlink()
                        last_error = "Hash verification failed"
                        self._active_downloads[model_id].state = "error"
                        self._active_downloads[model_id].error = last_error
                        continue  # Retry
                else:
                    logger.info(f"Skipping hash verification for {model_id}")
                
                # Rename temp file to final name
                if model_path.exists():
                    model_path.unlink()
                temp_path.rename(model_path)
                
                # Update database
                if self.db_manager:
                    self.db_manager.mark_ai_model_downloaded(model_id, actual_hash)
                
                self._active_downloads[model_id].state = "complete"
                self._active_downloads[model_id].progress = 100
                
                logger.info(f"Successfully downloaded {model_id} to {model_path}")
                return True
                
            except asyncio.CancelledError:
                logger.info(f"Download cancelled for {model_id}")
                self._active_downloads[model_id].state = "error"
                self._active_downloads[model_id].error = "Cancelled"
                return False
                
            except Exception as e:
                last_error = str(e)
                logger.error(f"Download attempt {attempt} failed for {model_id}: {e}")
                self._active_downloads[model_id].state = "error"
                self._active_downloads[model_id].error = last_error
                
                if attempt < max_retries:
                    logger.info(f"Will retry in {retry_delay} seconds...")
        
        # All retries failed
        logger.error(f"All {max_retries} download attempts failed for {model_id}")
        
        if self.db_manager:
            self.db_manager.upsert_ai_model_cache(
                model_id=model_id,
                file_path=str(model_path),
                file_size_mb=model.size_mb,
                is_downloaded=False,
                download_progress=self._active_downloads[model_id].progress
            )
        
        return False
    
    async def _download_to_file(
        self,
        response: aiohttp.ClientResponse,
        path: Path,
        model_id: str,
        progress_callback: Callable,
        mode: str,
        start_byte: int = 0
    ):
        """Download response content to file with progress tracking"""
        import time
        
        total_size = int(response.headers.get('content-length', 0)) + start_byte
        downloaded = start_byte
        last_time = time.time()
        last_downloaded = downloaded
        
        async with aiofiles.open(path, mode) as f:
            async for chunk in response.content.iter_chunked(1024 * 1024):  # 1MB chunks
                await f.write(chunk)
                downloaded += len(chunk)
                
                # Calculate speed
                current_time = time.time()
                elapsed = current_time - last_time
                
                if elapsed >= 0.5:  # Update every 500ms
                    bytes_delta = downloaded - last_downloaded
                    speed_mbps = (bytes_delta / elapsed) / (1024 * 1024)
                    
                    progress = (downloaded / total_size * 100) if total_size > 0 else 0
                    
                    # Update status
                    status = self._active_downloads.get(model_id)
                    if status:
                        status.progress = progress
                        status.downloaded_bytes = downloaded
                        status.total_bytes = total_size
                        status.speed_mbps = speed_mbps
                    
                    # Update database periodically
                    if self.db_manager and int(progress) % 5 == 0:
                        self.db_manager.update_ai_model_progress(model_id, progress)
                    
                    # Callback
                    if progress_callback:
                        progress_callback(progress, downloaded, total_size)
                    
                    last_time = current_time
                    last_downloaded = downloaded
        
        # Final progress update
        if progress_callback:
            progress_callback(100.0, downloaded, total_size)
    
    async def _calculate_sha256(self, path: Path) -> str:
        """Calculate SHA256 hash of a file"""
        sha256_hash = hashlib.sha256()
        
        async with aiofiles.open(path, 'rb') as f:
            while True:
                chunk = await f.read(1024 * 1024)  # 1MB chunks
                if not chunk:
                    break
                sha256_hash.update(chunk)
        
        return sha256_hash.hexdigest()
    
    async def delete_model(self, model_id: str) -> bool:
        """Delete a downloaded model"""
        try:
            model_path = self.get_model_path(model_id)
            
            if model_path.exists():
                model_path.unlink()
            
            # Also delete temp file if exists
            temp_path = model_path.with_suffix('.tmp')
            if temp_path.exists():
                temp_path.unlink()
            
            # Update database
            if self.db_manager:
                self.db_manager.delete_ai_model_cache(model_id)
            
            # Update current model setting if this was the active model
            if self.db_manager:
                current_model = self.db_manager.get_system_setting('ai_current_model')
                if current_model == model_id:
                    self.db_manager.set_system_setting('ai_current_model', '')
                    self.db_manager.set_system_setting('ai_model_loaded', 'false')
            
            logger.info(f"Deleted model {model_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete model {model_id}: {e}")
            return False
    
    def get_current_model(self) -> Optional[str]:
        """Get the currently selected model ID from database"""
        if self.db_manager:
            return self.db_manager.get_system_setting('ai_current_model') or None
        return None
    
    def set_current_model(self, model_id: str) -> bool:
        """
        Set the current model. Enforces single model policy.
        
        Args:
            model_id: The model to set as current (must be downloaded)
            
        Returns:
            True if successful, False otherwise
        """
        if model_id and model_id not in AVAILABLE_MODELS:
            logger.error(f"Unknown model: {model_id}")
            return False
        
        if model_id and not self.is_model_downloaded(model_id):
            logger.error(f"Model {model_id} is not downloaded")
            return False
        
        if self.db_manager:
            self.db_manager.set_system_setting('ai_current_model', model_id or '')
            # Reset loaded state when changing models
            self.db_manager.set_system_setting('ai_model_loaded', 'false')
            logger.info(f"Set current model to: {model_id or '(none)'}")
            return True
        
        return False
    
    def get_downloaded_models(self) -> list:
        """Get list of all downloaded model IDs"""
        return [
            model_id for model_id in AVAILABLE_MODELS
            if self.is_model_downloaded(model_id)
        ]
    
    def get_all_models_status(self) -> list:
        """Get status of all available models"""
        models = []
        
        for model_id, definition in AVAILABLE_MODELS.items():
            model_path = self.get_model_path(model_id)
            is_downloaded = self.is_model_downloaded(model_id)
            
            # Check for active download
            active_status = self._active_downloads.get(model_id)
            
            status = {
                "id": model_id,
                "name": definition.name,
                "description": definition.description,
                "size_mb": definition.size_mb,
                "context_length": definition.context_length,
                "is_downloaded": is_downloaded,
                "file_path": str(model_path) if is_downloaded else None,
                "download_status": None
            }
            
            if active_status:
                status["download_status"] = {
                    "state": active_status.state,
                    "progress": active_status.progress,
                    "downloaded_mb": active_status.downloaded_bytes / (1024 * 1024),
                    "total_mb": active_status.total_bytes / (1024 * 1024),
                    "speed_mbps": active_status.speed_mbps,
                    "error": active_status.error
                }
            
            models.append(status)
        
        return models
    
    # ==================== RUNNER MANAGEMENT ====================
    
    def get_runner_path(self) -> Path:
        """Get the path to the llama-server binary"""
        import platform
        system = platform.system().lower()
        if system == "windows":
            return self.models_path / "llama-server.exe"
        return self.models_path / "llama-server"
    
    def is_runner_ready(self) -> bool:
        """Check if the llama-server binary exists and is executable"""
        runner_path = self.get_runner_path()
        if not runner_path.exists():
            return False
        # Check file size is reasonable (at least 1MB)
        return runner_path.stat().st_size > 1024 * 1024
    
    def get_runner_status(self) -> dict:
        """Get runner download status"""
        runner_status = self._active_downloads.get("__runner__")
        is_ready = self.is_runner_ready()
        
        result = {
            "ready": is_ready,
            "path": str(self.get_runner_path()) if is_ready else None,
            "download_status": None
        }
        
        if runner_status:
            result["download_status"] = {
                "state": runner_status.state,
                "progress": runner_status.progress,
                "downloaded_mb": runner_status.downloaded_bytes / (1024 * 1024),
                "total_mb": runner_status.total_bytes / (1024 * 1024),
                "speed_mbps": runner_status.speed_mbps,
                "error": runner_status.error
            }
        
        return result
    
    async def download_runner(self, progress_callback: Callable[[float, int, int], None] = None) -> bool:
        """
        Download the llama-server binary for the current platform.
        
        Uses llama.cpp releases from GitHub.
        """
        import platform
        import zipfile
        import tarfile
        import io
        
        system = platform.system().lower()
        machine = platform.machine().lower()
        
        # Determine download URL based on platform
        # Using llama.cpp b7574 release from ggml-org (latest stable)
        base_url = "https://github.com/ggml-org/llama.cpp/releases/download/b7574"
        
        if system == "linux":
            if "arm" in machine or "aarch64" in machine:
                archive_name = "llama-b7574-bin-ubuntu-arm64.tar.gz"
            else:
                archive_name = "llama-b7574-bin-ubuntu-x64.tar.gz"
            binary_name = "llama-server"
            is_tarball = True
        elif system == "darwin":  # macOS
            archive_name = "llama-b7574-bin-macos-arm64.tar.gz"
            binary_name = "llama-server"
            is_tarball = True
        elif system == "windows":
            archive_name = "llama-b7574-bin-win-cuda-cu12.2.0-x64.zip"
            binary_name = "llama-server.exe"
            is_tarball = False
        else:
            logger.error(f"Unsupported platform: {system}")
            return False
        
        download_url = f"{base_url}/{archive_name}"
        runner_path = self.get_runner_path()
        
        # Create directory if needed
        self.models_path.mkdir(parents=True, exist_ok=True)
        
        # Initialize download status
        self._active_downloads["__runner__"] = DownloadStatus(
            model_id="__runner__",
            state="downloading",
            progress=0,
            downloaded_bytes=0,
            total_bytes=100 * 1024 * 1024,  # Estimate ~100MB
            speed_mbps=0
        )
        
        logger.info(f"Downloading llama-server from {download_url}")
        
        try:
            import time
            start_time = time.time()
            
            async with aiohttp.ClientSession() as session:
                async with session.get(download_url) as response:
                    if response.status != 200:
                        raise Exception(f"Download failed: HTTP {response.status}")
                    
                    total_size = int(response.headers.get('content-length', 100 * 1024 * 1024))
                    self._active_downloads["__runner__"].total_bytes = total_size
                    
                    # Download archive to memory
                    downloaded = 0
                    chunks = []
                    
                    async for chunk in response.content.iter_chunked(1024 * 1024):  # 1MB chunks
                        chunks.append(chunk)
                        downloaded += len(chunk)
                        
                        # Update progress
                        elapsed = time.time() - start_time
                        speed = (downloaded / (1024 * 1024)) / elapsed if elapsed > 0 else 0
                        progress = (downloaded / total_size * 100) if total_size > 0 else 0
                        
                        self._active_downloads["__runner__"].progress = progress
                        self._active_downloads["__runner__"].downloaded_bytes = downloaded
                        self._active_downloads["__runner__"].speed_mbps = speed
                        
                        if progress_callback:
                            progress_callback(progress, downloaded, total_size)
                        
                        logger.debug(f"Runner download: {progress:.1f}% ({speed:.1f} MB/s)")
                    
                    archive_data = b''.join(chunks)
            
            # Extract llama-server from archive
            self._active_downloads["__runner__"].state = "extracting"
            logger.info(f"Extracting {binary_name} from archive...")
            
            archive_io = io.BytesIO(archive_data)
            
            if archive_name.endswith('.zip'):
                with zipfile.ZipFile(archive_io, 'r') as zf:
                    # Find llama-server in archive
                    for name in zf.namelist():
                        if name.endswith(binary_name):
                            logger.info(f"Found {name} in archive")
                            with zf.open(name) as src:
                                with open(runner_path, 'wb') as dst:
                                    dst.write(src.read())
                            break
                    else:
                        raise Exception(f"{binary_name} not found in archive")
            else:
                with tarfile.open(fileobj=archive_io, mode='r:gz') as tf:
                    for member in tf.getmembers():
                        if member.name.endswith(binary_name):
                            logger.info(f"Found {member.name} in archive")
                            f = tf.extractfile(member)
                            with open(runner_path, 'wb') as dst:
                                dst.write(f.read())
                            break
                    else:
                        raise Exception(f"{binary_name} not found in archive")
            
            # Make executable on Unix
            if system != "windows":
                import stat
                runner_path.chmod(runner_path.stat().st_mode | stat.S_IEXEC)
            
            self._active_downloads["__runner__"].state = "complete"
            self._active_downloads["__runner__"].progress = 100
            
            logger.info(f"Runner installed at {runner_path}")
            return True
            
        except Exception as e:
            logger.error(f"Runner download failed: {e}")
            self._active_downloads["__runner__"].state = "error"
            self._active_downloads["__runner__"].error = str(e)
            return False


# ==================== SINGLETON ====================

_downloader: Optional[ModelDownloader] = None


def get_model_downloader(db_manager=None, models_path: str = None) -> ModelDownloader:
    """Get or create the global model downloader instance"""
    global _downloader
    
    if _downloader is None:
        _downloader = ModelDownloader(db_manager, models_path)
    elif db_manager is not None and _downloader.db_manager is None:
        _downloader.db_manager = db_manager
    
    return _downloader


# ==================== UTILITY FUNCTIONS ====================

def get_available_models() -> Dict[str, Dict[str, Any]]:
    """Get info about all available models"""
    return {
        model_id: {
            "id": m.id,
            "name": m.name,
            "description": m.description,
            "size_mb": m.size_mb,
            "context_length": m.context_length
        }
        for model_id, m in AVAILABLE_MODELS.items()
    }


def get_recommended_model() -> str:
    """Get the recommended default model"""
    return "gemma-2-2b"  # Best balance of quality and size
