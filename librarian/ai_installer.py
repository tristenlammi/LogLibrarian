"""
AI Dependency Installer Module for Librarian AI

Handles runtime installation of llama-cpp-python with appropriate GPU support.
Provides progress tracking via callbacks for WebSocket updates.
"""

import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional, List
import importlib.util


class InstallStatus(Enum):
    """Installation status states"""
    IDLE = "idle"
    DETECTING = "detecting"
    INSTALLING = "installing"
    VERIFYING = "verifying"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass
class InstallProgress:
    """Progress update during installation"""
    status: InstallStatus
    message: str
    progress: int = 0  # 0-100
    detail: Optional[str] = None
    error: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "message": self.message,
            "progress": self.progress,
            "detail": self.detail,
            "error": self.error
        }


class AIInstaller:
    """
    Handles installation of AI dependencies at runtime.
    
    This allows the base application to run without AI dependencies,
    only installing them when the user explicitly enables AI features.
    """
    
    def __init__(self):
        self._install_lock = threading.Lock()
        self._is_installing = False
        self._cancel_requested = False
        
    def check_installed(self) -> bool:
        """Check if llama-cpp-python is already installed"""
        try:
            spec = importlib.util.find_spec("llama_cpp")
            return spec is not None
        except Exception:
            return False
    
    def verify_installation(self) -> tuple[bool, Optional[str]]:
        """
        Verify that llama-cpp-python is properly installed and working.
        Returns (success, error_message)
        """
        try:
            # Try to import the module
            from llama_cpp import Llama
            
            # Check version
            import llama_cpp
            version = getattr(llama_cpp, "__version__", "unknown")
            
            return True, f"llama-cpp-python {version} installed successfully"
            
        except ImportError as e:
            return False, f"Import failed: {str(e)}"
        except Exception as e:
            return False, f"Verification failed: {str(e)}"
    
    def install(
        self,
        backend: str,
        progress_callback: Optional[Callable[[InstallProgress], None]] = None
    ) -> tuple[bool, str]:
        """
        Install llama-cpp-python with the specified backend.
        
        Args:
            backend: One of "cuda", "rocm", "sycl", or "cpu"
            progress_callback: Optional callback for progress updates
            
        Returns:
            (success, message) tuple
        """
        if not self._install_lock.acquire(blocking=False):
            return False, "Installation already in progress"
        
        self._is_installing = True
        self._cancel_requested = False
        
        try:
            return self._do_install(backend, progress_callback)
        finally:
            self._is_installing = False
            self._install_lock.release()
    
    def cancel_install(self):
        """Request cancellation of ongoing installation"""
        self._cancel_requested = True
    
    def _report_progress(
        self,
        callback: Optional[Callable[[InstallProgress], None]],
        progress: InstallProgress
    ):
        """Report progress via callback if provided"""
        if callback:
            try:
                callback(progress)
            except Exception:
                pass  # Don't let callback errors stop installation
    
    def _do_install(
        self,
        backend: str,
        callback: Optional[Callable[[InstallProgress], None]]
    ) -> tuple[bool, str]:
        """Internal installation implementation"""
        
        # Step 1: Check if already installed
        self._report_progress(callback, InstallProgress(
            status=InstallStatus.DETECTING,
            message="Checking existing installation...",
            progress=5
        ))
        
        if self.check_installed():
            # Verify it works
            success, msg = self.verify_installation()
            if success:
                self._report_progress(callback, InstallProgress(
                    status=InstallStatus.SUCCESS,
                    message="AI dependencies already installed",
                    progress=100
                ))
                return True, "Already installed and verified"
        
        # Step 2: Build install command based on backend
        self._report_progress(callback, InstallProgress(
            status=InstallStatus.INSTALLING,
            message=f"Installing llama-cpp-python ({backend})...",
            progress=10,
            detail="This may take several minutes"
        ))
        
        cmd = self._get_install_command(backend)
        
        # Step 3: Run installation
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            
            output_lines = []
            progress = 10
            
            while True:
                if self._cancel_requested:
                    process.terminate()
                    self._report_progress(callback, InstallProgress(
                        status=InstallStatus.FAILED,
                        message="Installation cancelled",
                        progress=progress,
                        error="User cancelled installation"
                    ))
                    return False, "Installation cancelled by user"
                
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                
                if line:
                    output_lines.append(line)
                    
                    # Update progress based on output
                    if "Collecting" in line or "Downloading" in line:
                        progress = min(progress + 5, 50)
                    elif "Building" in line:
                        progress = min(progress + 10, 80)
                    elif "Installing" in line:
                        progress = min(progress + 5, 90)
                    
                    self._report_progress(callback, InstallProgress(
                        status=InstallStatus.INSTALLING,
                        message=f"Installing llama-cpp-python ({backend})...",
                        progress=progress,
                        detail=line.strip()[:100]
                    ))
            
            if process.returncode != 0:
                error_output = ''.join(output_lines[-20:])  # Last 20 lines
                self._report_progress(callback, InstallProgress(
                    status=InstallStatus.FAILED,
                    message="Installation failed",
                    progress=progress,
                    error=error_output
                ))
                return False, f"Installation failed with code {process.returncode}"
            
        except Exception as e:
            self._report_progress(callback, InstallProgress(
                status=InstallStatus.FAILED,
                message="Installation error",
                progress=progress,
                error=str(e)
            ))
            return False, f"Installation error: {str(e)}"
        
        # Step 4: Verify installation
        self._report_progress(callback, InstallProgress(
            status=InstallStatus.VERIFYING,
            message="Verifying installation...",
            progress=95
        ))
        
        # Force reimport
        if "llama_cpp" in sys.modules:
            del sys.modules["llama_cpp"]
        
        success, msg = self.verify_installation()
        
        if success:
            self._report_progress(callback, InstallProgress(
                status=InstallStatus.SUCCESS,
                message="Installation complete!",
                progress=100,
                detail=msg
            ))
            return True, msg
        else:
            self._report_progress(callback, InstallProgress(
                status=InstallStatus.FAILED,
                message="Verification failed",
                progress=95,
                error=msg
            ))
            return False, msg
    
    def _get_install_command(self, backend: str) -> List[str]:
        """Get the pip install command for a given backend"""
        base_cmd = [sys.executable, "-m", "pip", "install", "--upgrade"]
        
        if backend == "cuda":
            # CUDA pre-built wheels
            return base_cmd + [
                "llama-cpp-python",
                "--extra-index-url", "https://abetlen.github.io/llama-cpp-python/whl/cu124"
            ]
        elif backend == "rocm":
            # ROCm pre-built wheels (if available)
            # Fall back to building with ROCm support
            return base_cmd + [
                "llama-cpp-python",
                "--extra-index-url", "https://abetlen.github.io/llama-cpp-python/whl/rocm"
            ]
        elif backend == "sycl":
            # SYCL builds are experimental, use CPU for now
            # In the future, may need custom index
            return base_cmd + ["llama-cpp-python"]
        else:
            # CPU build
            return base_cmd + ["llama-cpp-python"]
    
    def uninstall(
        self,
        progress_callback: Optional[Callable[[InstallProgress], None]] = None
    ) -> tuple[bool, str]:
        """Uninstall llama-cpp-python"""
        if not self._install_lock.acquire(blocking=False):
            return False, "Operation in progress"
        
        try:
            self._report_progress(progress_callback, InstallProgress(
                status=InstallStatus.INSTALLING,
                message="Uninstalling llama-cpp-python...",
                progress=50
            ))
            
            result = subprocess.run(
                [sys.executable, "-m", "pip", "uninstall", "-y", "llama-cpp-python"],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode == 0:
                # Clear from sys.modules
                if "llama_cpp" in sys.modules:
                    del sys.modules["llama_cpp"]
                    
                self._report_progress(progress_callback, InstallProgress(
                    status=InstallStatus.SUCCESS,
                    message="Uninstalled successfully",
                    progress=100
                ))
                return True, "Uninstalled successfully"
            else:
                self._report_progress(progress_callback, InstallProgress(
                    status=InstallStatus.FAILED,
                    message="Uninstall failed",
                    progress=50,
                    error=result.stderr
                ))
                return False, f"Uninstall failed: {result.stderr}"
                
        except Exception as e:
            self._report_progress(progress_callback, InstallProgress(
                status=InstallStatus.FAILED,
                message="Uninstall error",
                error=str(e)
            ))
            return False, f"Uninstall error: {str(e)}"
        finally:
            self._install_lock.release()


# Singleton instance
_installer: Optional[AIInstaller] = None


def get_installer() -> AIInstaller:
    """Get the singleton AIInstaller instance"""
    global _installer
    if _installer is None:
        _installer = AIInstaller()
    return _installer


# Quick test if run directly
if __name__ == "__main__":
    installer = get_installer()
    
    print("Checking if llama-cpp-python is installed...")
    installed = installer.check_installed()
    print(f"Installed: {installed}")
    
    if installed:
        success, msg = installer.verify_installation()
        print(f"Verified: {success}")
        print(f"Message: {msg}")
