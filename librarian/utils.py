import socket
import os
import platform


def get_lan_ips():
    """
    Returns a list of LAN IPv4 addresses for all non-loopback interfaces.
    Works on both Linux (Docker) and Windows.
    """
    ips = set()
    
    # Method 1: Use socket to find default interface IP (works everywhere)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127."):
            ips.add(ip)
    except Exception:
        pass
    
    # Method 2: Try psutil (cross-platform, may not be installed)
    try:
        import psutil
        for iface, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                    ips.add(addr.address)
    except ImportError:
        pass
    
    # Method 3: Try netifaces (Linux, may not be installed)
    if not ips:
        try:
            import netifaces
            for iface in netifaces.interfaces():
                ifaddresses = netifaces.ifaddresses(iface)
                if netifaces.AF_INET in ifaddresses:
                    for link in ifaddresses[netifaces.AF_INET]:
                        ip = link.get('addr')
                        if ip and not ip.startswith("127."):
                            ips.add(ip)
        except ImportError:
            pass
    
    # Method 4: Parse /proc/net/fib_trie (Linux only, no deps)
    if not ips and platform.system() == "Linux":
        try:
            with open('/proc/net/fib_trie', 'r') as f:
                content = f.read()
                import re
                # Look for LOCAL entries which are local IP addresses
                for match in re.finditer(r'/32 host LOCAL\n\s+\|-- (\d+\.\d+\.\d+\.\d+)', content):
                    ip = match.group(1)
                    if not ip.startswith("127."):
                        ips.add(ip)
        except Exception:
            pass
    
    return sorted(ips)


def get_best_lan_ip():
    """
    Returns the most likely LAN IP (prefers default gateway subnet).
    Returns empty string if no suitable LAN IP can be found.
    NEVER returns 127.0.0.1 - callers should handle empty string appropriately.
    """
    try:
        # Try to connect to a common LAN address to get the default interface
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        # Verify it's not localhost (can happen in some container setups)
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    
    # Fallback: first non-loopback IP from get_lan_ips()
    ips = get_lan_ips()
    if ips:
        return ips[0]
    
    # Return empty string instead of 127.0.0.1 - caller must handle this
    return ""
