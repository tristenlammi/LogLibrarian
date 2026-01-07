from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
from enum import Enum


# ==================== ENUMS ====================

class ReportFrequency(str, Enum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    ANNUALLY = "ANNUALLY"
    MANUAL = "MANUAL"


# ==================== REPORT PROFILES ====================

class ReportProfileCreate(BaseModel):
    name: str = Field(..., description="Profile name (e.g., 'Ocean View Motel Monthly')")
    description: Optional[str] = Field(default=None, description="Optional description")
    frequency: ReportFrequency = Field(default=ReportFrequency.MONTHLY, description="Report generation frequency")
    schedule_hour: Optional[int] = Field(default=7, ge=0, le=23, description="Hour of day to generate report (0-23, default 7 for 7am)")
    sla_target: Optional[float] = Field(default=99.9, description="SLA target percentage (e.g., 99.9)")
    recipient_emails: Optional[List[str]] = Field(default=None, description="Email recipients for future scheduling")
    monitor_scope_tags: Optional[List[str]] = Field(default=None, description="Tag IDs to include monitors by tag")
    monitor_scope_ids: Optional[List[str]] = Field(default=None, description="Specific monitor IDs to include")
    scribe_scope_tags: Optional[List[str]] = Field(default=None, description="Tag IDs to include log sources by tag")
    scribe_scope_ids: Optional[List[str]] = Field(default=None, description="Specific hostnames or source IPs to include")

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Ocean View Motel Monthly",
                "description": "Monthly executive report for Ocean View Motel properties",
                "frequency": "MONTHLY",
                "recipient_emails": ["manager@oceanview.com", "admin@oceanview.com"],
                "monitor_scope_tags": ["tag_001", "tag_002"],
                "monitor_scope_ids": ["bm_abc123"],
                "scribe_scope_tags": ["tag_003"],
                "scribe_scope_ids": ["webserver-01", "192.168.1.100"]
            }
        }


class ReportProfileUpdate(BaseModel):
    name: Optional[str] = Field(default=None, description="Profile name")
    description: Optional[str] = Field(default=None, description="Optional description")
    frequency: Optional[ReportFrequency] = Field(default=None, description="Report generation frequency")
    schedule_hour: Optional[int] = Field(default=None, ge=0, le=23, description="Hour of day to generate report (0-23)")
    sla_target: Optional[float] = Field(default=None, description="SLA target percentage")
    recipient_emails: Optional[List[str]] = Field(default=None, description="Email recipients")
    monitor_scope_tags: Optional[List[str]] = Field(default=None, description="Tag IDs for monitors")
    monitor_scope_ids: Optional[List[str]] = Field(default=None, description="Specific monitor IDs")
    scribe_scope_tags: Optional[List[str]] = Field(default=None, description="Tag IDs for log sources")
    scribe_scope_ids: Optional[List[str]] = Field(default=None, description="Specific hostnames/IPs")


class ReportProfileResponse(BaseModel):
    id: str = Field(..., description="Unique profile identifier")
    tenant_id: str = Field(..., description="Tenant ID")
    name: str = Field(..., description="Profile name")
    description: Optional[str] = Field(default=None, description="Description")
    recipient_emails: List[str] = Field(default_factory=list, description="Email recipients")
    monitor_scope_tags: List[str] = Field(default_factory=list, description="Monitor tag IDs")
    monitor_scope_ids: List[str] = Field(default_factory=list, description="Specific monitor IDs")
    scribe_scope_tags: List[str] = Field(default_factory=list, description="Log source tag IDs")
    scribe_scope_ids: List[str] = Field(default_factory=list, description="Specific hostnames/IPs")
    created_at: str = Field(..., description="Creation timestamp")
    updated_at: str = Field(..., description="Last update timestamp")


# ==================== LOG ENTRIES ====================

class LogEntry(BaseModel):
    template_id: str = Field(..., description="SHA256 hash of the log template")
    template_text: str = Field(..., description="Log template with variables replaced by tokens")
    variables: List[str] = Field(default_factory=list, description="Extracted variable values")
    timestamp: datetime = Field(..., description="Timestamp of the log event")

    class Config:
        json_schema_extra = {
            "example": {
                "template_id": "a1b2c3d4e5f6...",
                "template_text": "[ERROR] Connection from <IP> failed on port <NUM>",
                "variables": ["192.168.1.5", "80"],
                "timestamp": "2025-12-25T10:00:00Z"
            }
        }


class LogBatch(BaseModel):
    logs: List[LogEntry] = Field(..., description="Batch of compressed log entries")

    class Config:
        json_schema_extra = {
            "example": {
                "logs": [
                    {
                        "template_id": "a1b2c3d4e5f6...",
                        "template_text": "[ERROR] Connection from <IP> failed on port <NUM>",
                        "variables": ["192.168.1.5", "80"],
                        "timestamp": "2025-12-25T10:00:00Z"
                    }
                ]
            }
        }


class DiskInfo(BaseModel):
    mountpoint: str = Field(..., description="Disk mount point")
    device: str = Field(default="", description="Device path")
    usage_percent: float = Field(..., description="Disk space usage percentage")
    read_bps: float = Field(default=0.0, description="Disk read speed in bytes per second")
    write_bps: float = Field(default=0.0, description="Disk write speed in bytes per second")
    temperature: float = Field(default=0.0, description="Disk temperature in Celsius")


class ProcessInfo(BaseModel):
    pid: int = Field(..., description="Process ID")
    name: str = Field(..., description="Process name")
    cpu_percent: float = Field(..., description="CPU usage percentage")
    ram_percent: float = Field(..., description="RAM usage percentage")


class MetricPoint(BaseModel):
    timestamp: datetime = Field(..., description="Time when metric was collected")
    cpu_percent: float = Field(..., description="CPU usage percentage")
    ram_percent: float = Field(..., description="RAM usage percentage")
    net_sent_bps: float = Field(default=0.0, description="Network upload speed in bytes per second")
    net_recv_bps: float = Field(default=0.0, description="Network download speed in bytes per second")
    disk_read_bps: float = Field(default=0.0, description="Disk read speed in bytes per second")
    disk_write_bps: float = Field(default=0.0, description="Disk write speed in bytes per second")
    ping_latency_ms: float = Field(default=0.0, description="Ping latency in milliseconds")
    cpu_temp: float = Field(default=0.0, description="CPU temperature in Celsius")
    cpu_name: str = Field(default="", description="CPU model name")
    gpu_percent: float = Field(default=0.0, description="GPU usage percentage")
    gpu_temp: float = Field(default=0.0, description="GPU temperature in Celsius")
    gpu_name: str = Field(default="", description="GPU model name")
    is_vm: bool = Field(default=False, description="Whether running in a VM")
    disks: List[DiskInfo] = Field(default_factory=list, description="Per-disk usage and temperature")


class DiskDetails(BaseModel):
    device: str = Field(default="", description="Device name")
    mountpoint: str = Field(default="", description="Mount point")
    fstype: str = Field(default="", description="Filesystem type")
    total_gb: float = Field(default=0.0, description="Total size in GB")
    model: str = Field(default="", description="Disk model")
    serial: str = Field(default="", description="Serial number")
    is_removable: bool = Field(default=False, description="Is removable media")
    is_ssd: bool = Field(default=False, description="Is SSD")


class NetworkInterface(BaseModel):
    name: str = Field(default="", description="Interface name")
    mac: str = Field(default="", description="MAC address")
    ips: List[str] = Field(default_factory=list, description="IP addresses")
    speed: str = Field(default="", description="Link speed")
    is_up: bool = Field(default=False, description="Is interface up")
    is_loopback: bool = Field(default=False, description="Is loopback interface")


class SystemInfo(BaseModel):
    # OS Information
    os: str = Field(default="", description="Operating system")
    os_version: str = Field(default="", description="OS version string")
    platform: str = Field(default="", description="Platform name")
    platform_version: str = Field(default="", description="Platform version")
    kernel_version: str = Field(default="", description="Kernel version")
    hostname: str = Field(default="", description="Hostname")
    uptime: int = Field(default=0, description="System uptime in seconds")
    boot_time: int = Field(default=0, description="Boot timestamp")
    
    # CPU Information
    cpu_model: str = Field(default="", description="CPU model name")
    cpu_cores: int = Field(default=0, description="Physical CPU cores")
    cpu_threads: int = Field(default=0, description="Total CPU threads")
    cpu_freq_mhz: float = Field(default=0.0, description="CPU frequency in MHz")
    cpu_cache: str = Field(default="", description="CPU cache size")
    cpu_arch: str = Field(default="", description="CPU architecture")
    
    # Memory Information
    ram_total_gb: float = Field(default=0.0, description="Total RAM in GB")
    ram_type: str = Field(default="", description="RAM type (DDR4, DDR5, etc.)")
    ram_speed: str = Field(default="", description="RAM speed")
    
    # GPU Information
    gpu_model: str = Field(default="", description="GPU model name")
    gpu_vendor: str = Field(default="", description="GPU vendor")
    gpu_memory_mb: int = Field(default=0, description="GPU memory in MB")
    gpu_driver: str = Field(default="", description="GPU driver version")
    
    # Motherboard Information
    motherboard: str = Field(default="", description="Motherboard model")
    bios_version: str = Field(default="", description="BIOS version")
    manufacturer: str = Field(default="", description="System manufacturer")
    product_name: str = Field(default="", description="Product name")
    serial_number: str = Field(default="", description="Serial number")
    
    # Storage Information
    disks: List[DiskDetails] = Field(default_factory=list, description="Storage devices")
    
    # Network Information
    network_interfaces: List[NetworkInterface] = Field(default_factory=list, description="Network adapters")
    
    # Container/VM detection
    is_vm: bool = Field(default=False, description="Is running in VM")
    vm_type: str = Field(default="", description="VM hypervisor type")
    is_container: bool = Field(default=False, description="Is running in container")
    
    # Timestamp
    collected_at: datetime = Field(default=None, description="When info was collected")


class HeartbeatPayload(BaseModel):
    agent_id: str = Field(..., description="Unique agent identifier")
    hostname: str = Field(..., description="Agent hostname")
    metrics: List[MetricPoint] = Field(..., description="Buffered system metrics")
    status: str = Field(..., description="Agent status: online/offline")
    last_seen_at: datetime = Field(..., description="Last contact timestamp")
    processes: List[ProcessInfo] = Field(default_factory=list, description="Top 10 processes by CPU usage")
    public_ip: str = Field(default="", description="Public IP address")
    load_avg: float = Field(default=0.0, description="15-minute load average")
    connection_address: str = Field(default="", description="The address the agent is currently using to connect")
    system_info: Optional[SystemInfo] = Field(default=None, description="Comprehensive system hardware info")
    auth_token: Optional[str] = Field(default=None, description="Authentication token for agent verification")

    class Config:
        json_schema_extra = {
            "example": {
                "agent_id": "web-server-01-1234567890",
                "hostname": "web-server-01",
                "metrics": [
                    {
                        "timestamp": "2025-12-25T10:00:00Z",
                        "cpu_percent": 45.2,
                        "ram_percent": 68.5
                    },
                    {
                        "timestamp": "2025-12-25T10:00:01Z",
                        "cpu_percent": 46.1,
                        "ram_percent": 68.7
                    }
                ],
                "status": "online",
                "last_seen_at": "2025-12-25T10:00:10Z"
            }
        }

