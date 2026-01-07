import os
import hashlib
from fastapi import APIRouter, HTTPException, Depends, Header
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
import logging

# Configure logging
logger = logging.getLogger("librarian.updates")

router = APIRouter(prefix="/api/agents/updates", tags=["Agent Updates"])

# Constants
# Use path relative to this file (routers/agent_updates.py) -> ../static/agents
AGENTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static", "agents"))

class UpdateCheckResponse(BaseModel):
    available: bool
    version: str
    url: str
    checksum: Optional[str] = None

def get_latest_version(platform: str, arch: str) -> Optional[str]:
    """
    Check the static directory for the latest version.
    Structure: librarian/static/agents/{platform}/{arch}/scribe[-{version}][.exe]
    
    For this MVP, we will assume a text file 'LATEST' exists in the directory
    containing the version number.
    """
    try:
        target_dir = os.path.join(AGENTS_DIR, platform, arch)
        version_file = os.path.join(target_dir, "LATEST")
        
        if os.path.exists(version_file):
            with open(version_file, "r") as f:
                return f.read().strip()
        return None
    except Exception as e:
        logger.error(f"Error checking version for {platform}/{arch}: {e}")
        return None

def get_binary_checksum(platform: str, arch: str) -> Optional[str]:
    """
    Calculate SHA-256 checksum of the binary file.
    Returns hex-encoded checksum string or None if file not found.
    """
    try:
        target_dir = os.path.join(AGENTS_DIR, platform, arch)
        filename = "scribe.exe" if platform == "windows" else "scribe"
        file_path = os.path.join(target_dir, filename)
        
        if not os.path.exists(file_path):
            return None
        
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            # Read in chunks for large files
            for chunk in iter(lambda: f.read(8192), b""):
                sha256_hash.update(chunk)
        
        return sha256_hash.hexdigest()
    except Exception as e:
        logger.error(f"Error calculating checksum for {platform}/{arch}: {e}")
        return None

@router.get("/check")
async def check_for_update(
    current_version: str, 
    platform: str, 
    arch: str,
    user_agent: Optional[str] = Header(None)
) -> UpdateCheckResponse:
    """
    Check if a newer version is available.
    """
    latest_version = get_latest_version(platform, arch)
    
    if not latest_version:
        return UpdateCheckResponse(available=False, version=current_version, url="")
        
    # Simple semantic version comparison (very basic for MVP)
    # Assumes "0.1.0" format
    if latest_version != current_version:
        download_url = f"/api/agents/updates/download/{platform}/{arch}"
        checksum = get_binary_checksum(platform, arch)
        return UpdateCheckResponse(
            available=True,
            version=latest_version,
            url=download_url,
            checksum=checksum
        )
        
    return UpdateCheckResponse(available=False, version=current_version, url="")

@router.get("/download/{platform}/{arch}")
async def download_update(platform: str, arch: str):
    """
    Download the latest binary for the specific platform/arch.
    """
    latest_version = get_latest_version(platform, arch)
    if not latest_version:
        raise HTTPException(status_code=404, detail="No version info found")
        
    target_dir = os.path.join(AGENTS_DIR, platform, arch)
    
    # Determined filename based on OS
    filename = "scribe.exe" if platform == "windows" else "scribe"
    file_path = os.path.join(target_dir, filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Update binary not found")
        
    return FileResponse(
        path=file_path,
        filename=f"scribe-{latest_version}.exe" if platform == "windows" else f"scribe-{latest_version}",
        media_type="application/octet-stream"
    )
