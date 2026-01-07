"""
GPU Detection Module for Librarian AI

Detects available GPU acceleration options:
- NVIDIA CUDA
- AMD ROCm
- Intel Arc (oneAPI/SYCL)
- CPU fallback
"""

import subprocess
import re
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class GPUInfo:
    """Information about a detected GPU"""
    name: str
    vendor: str
    memory_mb: Optional[int] = None
    driver_version: Optional[str] = None


@dataclass
class DetectionResult:
    """Result of GPU detection"""
    cuda_available: bool = False
    rocm_available: bool = False
    sycl_available: bool = False
    cuda_devices: List[GPUInfo] = None
    rocm_devices: List[GPUInfo] = None
    sycl_devices: List[GPUInfo] = None
    recommended: str = "cpu"
    recommended_reason: str = "No GPU detected"
    
    def __post_init__(self):
        if self.cuda_devices is None:
            self.cuda_devices = []
        if self.rocm_devices is None:
            self.rocm_devices = []
        if self.sycl_devices is None:
            self.sycl_devices = []
    
    def to_dict(self) -> dict:
        return {
            "cuda_available": self.cuda_available,
            "rocm_available": self.rocm_available,
            "sycl_available": self.sycl_available,
            "cuda_devices": [{"name": d.name, "memory_mb": d.memory_mb} for d in self.cuda_devices],
            "rocm_devices": [{"name": d.name, "memory_mb": d.memory_mb} for d in self.rocm_devices],
            "sycl_devices": [{"name": d.name, "memory_mb": d.memory_mb} for d in self.sycl_devices],
            "recommended": self.recommended,
            "recommended_reason": self.recommended_reason
        }


class GPUDetector:
    """Detect available GPU acceleration options"""
    
    @staticmethod
    def detect() -> DetectionResult:
        """
        Detect all available GPU acceleration options.
        Returns a DetectionResult with available backends and recommendation.
        """
        result = DetectionResult()
        
        # Check NVIDIA CUDA
        cuda_result = GPUDetector._detect_cuda()
        if cuda_result:
            result.cuda_available = True
            result.cuda_devices = cuda_result
            result.recommended = "cuda"
            vram = sum(d.memory_mb or 0 for d in cuda_result)
            result.recommended_reason = f"NVIDIA GPU detected ({len(cuda_result)} device(s), {vram}MB total VRAM)"
        
        # Check AMD ROCm
        rocm_result = GPUDetector._detect_rocm()
        if rocm_result:
            result.rocm_available = True
            result.rocm_devices = rocm_result
            if not result.cuda_available:
                result.recommended = "rocm"
                result.recommended_reason = f"AMD GPU detected ({len(rocm_result)} device(s))"
        
        # Check Intel Arc (oneAPI/SYCL)
        sycl_result = GPUDetector._detect_sycl()
        if sycl_result:
            result.sycl_available = True
            result.sycl_devices = sycl_result
            if result.recommended == "cpu":
                result.recommended = "sycl"
                result.recommended_reason = f"Intel Arc GPU detected ({len(sycl_result)} device(s))"
        
        return result
    
    @staticmethod
    def _detect_cuda() -> Optional[List[GPUInfo]]:
        """Detect NVIDIA GPUs using nvidia-smi"""
        try:
            # Run nvidia-smi to list GPUs
            result = subprocess.run(
                ['nvidia-smi', '--query-gpu=name,memory.total', '--format=csv,noheader,nounits'],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                return None
            
            devices = []
            for line in result.stdout.strip().split('\n'):
                if line.strip():
                    parts = line.split(',')
                    name = parts[0].strip() if len(parts) > 0 else "Unknown NVIDIA GPU"
                    memory = int(parts[1].strip()) if len(parts) > 1 else None
                    devices.append(GPUInfo(
                        name=name,
                        vendor="NVIDIA",
                        memory_mb=memory
                    ))
            
            return devices if devices else None
            
        except FileNotFoundError:
            # nvidia-smi not found
            return None
        except subprocess.TimeoutExpired:
            return None
        except Exception:
            return None
    
    @staticmethod
    def _detect_rocm() -> Optional[List[GPUInfo]]:
        """Detect AMD GPUs using rocm-smi"""
        try:
            # Run rocm-smi to list GPUs
            result = subprocess.run(
                ['rocm-smi', '--showproductname'],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                return None
            
            devices = []
            # Parse rocm-smi output
            for line in result.stdout.strip().split('\n'):
                if 'GPU' in line and ':' in line:
                    name = line.split(':')[-1].strip()
                    devices.append(GPUInfo(
                        name=name,
                        vendor="AMD"
                    ))
            
            # If no devices parsed but command succeeded, try alternative detection
            if not devices:
                result2 = subprocess.run(
                    ['rocm-smi', '-i'],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if result2.returncode == 0 and 'GPU' in result2.stdout:
                    devices.append(GPUInfo(
                        name="AMD GPU (ROCm)",
                        vendor="AMD"
                    ))
            
            return devices if devices else None
            
        except FileNotFoundError:
            # rocm-smi not found
            return None
        except subprocess.TimeoutExpired:
            return None
        except Exception:
            return None
    
    @staticmethod
    def _detect_sycl() -> Optional[List[GPUInfo]]:
        """Detect Intel Arc GPUs using xpu-smi or sycl-ls"""
        try:
            # Try xpu-smi first (Intel's tool)
            result = subprocess.run(
                ['xpu-smi', 'discovery'],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                devices = []
                for line in result.stdout.strip().split('\n'):
                    if 'Device Name' in line:
                        name = line.split(':')[-1].strip()
                        devices.append(GPUInfo(
                            name=name,
                            vendor="Intel"
                        ))
                return devices if devices else None
                
        except FileNotFoundError:
            pass
        except subprocess.TimeoutExpired:
            pass
        except Exception:
            pass
        
        # Try sycl-ls as fallback
        try:
            result = subprocess.run(
                ['sycl-ls'],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                devices = []
                for line in result.stdout.strip().split('\n'):
                    if 'Intel' in line and ('Arc' in line or 'GPU' in line):
                        # Extract device name
                        match = re.search(r'\[(.*?)\]', line)
                        name = match.group(1) if match else "Intel Arc GPU"
                        devices.append(GPUInfo(
                            name=name,
                            vendor="Intel"
                        ))
                return devices if devices else None
                
        except FileNotFoundError:
            pass
        except subprocess.TimeoutExpired:
            pass
        except Exception:
            pass
        
        return None
    
    @staticmethod
    def get_install_package(backend: str) -> str:
        """Get the pip package name for a given backend"""
        packages = {
            "cuda": "llama-cpp-python",
            "rocm": "llama-cpp-python",
            "sycl": "llama-cpp-python",
            "cpu": "llama-cpp-python"
        }
        return packages.get(backend, "llama-cpp-python")
    
    @staticmethod
    def get_install_command(backend: str) -> List[str]:
        """Get the pip install command for a given backend"""
        if backend == "cuda":
            # CUDA requires building with CUDA support
            return [
                "pip", "install", "llama-cpp-python",
                "--extra-index-url", "https://abetlen.github.io/llama-cpp-python/whl/cu124"
            ]
        elif backend == "rocm":
            # ROCm build
            return [
                "pip", "install", "llama-cpp-python",
                "--extra-index-url", "https://abetlen.github.io/llama-cpp-python/whl/rocm"
            ]
        elif backend == "sycl":
            # SYCL/oneAPI build (experimental)
            return [
                "pip", "install", "llama-cpp-python"
            ]
        else:
            # CPU fallback
            return [
                "pip", "install", "llama-cpp-python"
            ]


# Quick test if run directly
if __name__ == "__main__":
    print("Detecting GPUs...")
    result = GPUDetector.detect()
    print(f"\nCUDA available: {result.cuda_available}")
    if result.cuda_devices:
        for dev in result.cuda_devices:
            print(f"  - {dev.name} ({dev.memory_mb}MB)")
    
    print(f"\nROCm available: {result.rocm_available}")
    if result.rocm_devices:
        for dev in result.rocm_devices:
            print(f"  - {dev.name}")
    
    print(f"\nSYCL available: {result.sycl_available}")
    if result.sycl_devices:
        for dev in result.sycl_devices:
            print(f"  - {dev.name}")
    
    print(f"\nRecommended backend: {result.recommended}")
    print(f"Reason: {result.recommended_reason}")
