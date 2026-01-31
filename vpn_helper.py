#!/usr/bin/env python3
"""
VPN Connection Helper Script

Fetches free VPN configurations from VPN Gate and attempts to connect
until LibGen or Anna's Archive becomes accessible.
"""

import base64
import csv
import io
import os
import subprocess
import sys
import time
from urllib.request import urlopen, Request
from urllib.error import URLError

# Sites to test connectivity
TEST_URLS = [
    ("https://libgen.li", "LibGen"),
    ("https://libgen.is", "LibGen"),
    ("https://annas-archive.org", "Anna's Archive"),
    ("https://annas-archive.gs", "Anna's Archive"),
]

# VPN Gate API endpoint
VPN_GATE_API = "https://www.vpngate.net/api/iphone/"

# Countries that typically have good connectivity
PREFERRED_COUNTRIES = ["JP", "KR", "US", "CA", "DE", "NL", "UK", "FR", "CH", "SE", "SG", "TW"]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}


def run_cmd(cmd, timeout=30):
    """Run a shell command and return output."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return result.returncode == 0, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return False, "Timeout"
    except Exception as e:
        return False, str(e)


def test_connectivity():
    """Test if we can access LibGen or Anna's Archive."""
    for url, name in TEST_URLS:
        try:
            print(f"Testing {name}: {url}")
            req = Request(url, headers=HEADERS)
            response = urlopen(req, timeout=15)
            if response.status == 200:
                print(f"✓ Successfully connected to {name}: {url}")
                return True
        except Exception as e:
            print(f"✗ Cannot access {name} ({url}): {type(e).__name__}")
    return False


def test_dns():
    """Test DNS resolution."""
    print("\nTesting DNS resolution...")
    for domain in ["libgen.is", "libgen.li", "annas-archive.org"]:
        success, output = run_cmd(f"dig +short {domain}", timeout=10)
        if success and output.strip():
            print(f"  ✓ {domain} resolves to: {output.strip()[:50]}")
            return True
        else:
            print(f"  ✗ {domain} DNS failed")
    return False


def fetch_vpn_servers():
    """Fetch list of VPN servers from VPN Gate."""
    print("\nFetching VPN server list from VPN Gate...")
    try:
        req = Request(VPN_GATE_API, headers=HEADERS)
        response = urlopen(req, timeout=30)
        data = response.read().decode('utf-8')
        
        # Parse CSV data (skip first line with *)
        lines = data.split('\n')
        csv_data = '\n'.join(lines[1:])  # Skip the first line
        
        servers = []
        reader = csv.DictReader(io.StringIO(csv_data))
        
        for row in reader:
            try:
                if not row.get('OpenVPN_ConfigData_Base64'):
                    continue
                    
                server = {
                    'hostname': row.get('HostName', ''),
                    'ip': row.get('IP', ''),
                    'country': row.get('CountryShort', ''),
                    'speed': int(row.get('Speed', 0)),
                    'ping': int(row.get('Ping', 999)),
                    'score': int(row.get('Score', 0)),
                    'config': row.get('OpenVPN_ConfigData_Base64', ''),
                }
                
                # Filter for preferred countries and decent speed (>5 Mbps)
                if server['country'] in PREFERRED_COUNTRIES and server['speed'] > 5000000:
                    servers.append(server)
            except (ValueError, KeyError):
                continue
        
        # Sort by score (higher is better)
        servers.sort(key=lambda x: x['score'], reverse=True)
        print(f"Found {len(servers)} suitable VPN servers")
        return servers[:15]  # Return top 15
        
    except Exception as e:
        print(f"Error fetching VPN servers: {e}")
        return []


def save_ovpn_config(server, filename="/tmp/vpn_config.ovpn"):
    """Decode and save OpenVPN configuration with DNS push enabled."""
    try:
        config_data = base64.b64decode(server['config']).decode('utf-8')
        
        # Add options for better compatibility and DNS handling
        extra_options = """
# Added for GitHub Actions compatibility
script-security 2
up /etc/openvpn/update-resolv-conf
down /etc/openvpn/update-resolv-conf
dhcp-option DNS 8.8.8.8
dhcp-option DNS 1.1.1.1
"""
        
        # Check if we have resolvconf installed
        if os.path.exists('/etc/openvpn/update-resolv-conf'):
            config_data += extra_options
        
        with open(filename, 'w') as f:
            f.write(config_data)
        
        return filename
    except Exception as e:
        print(f"Error saving config: {e}")
        return None


def setup_dns_fallback():
    """Setup fallback DNS servers."""
    print("Setting up fallback DNS...")
    # Add Google and Cloudflare DNS as fallback
    run_cmd("echo 'nameserver 8.8.8.8' | sudo tee -a /etc/resolv.conf")
    run_cmd("echo 'nameserver 1.1.1.1' | sudo tee -a /etc/resolv.conf")
    run_cmd("cat /etc/resolv.conf")


def connect_vpn(config_file):
    """Connect to VPN using OpenVPN."""
    try:
        print(f"Starting OpenVPN connection...")
        
        # Kill any existing OpenVPN processes
        run_cmd("sudo killall openvpn 2>/dev/null || true")
        time.sleep(1)
        
        # Start OpenVPN with the config
        process = subprocess.Popen(
            ['sudo', 'openvpn', '--config', config_file, '--daemon', '--log', '/tmp/openvpn.log'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Wait for connection to establish
        connected = False
        for i in range(45):  # Wait up to 45 seconds
            time.sleep(1)
            
            # Check OpenVPN log for success
            if os.path.exists('/tmp/openvpn.log'):
                with open('/tmp/openvpn.log', 'r') as f:
                    log = f.read()
                    if 'Initialization Sequence Completed' in log:
                        print("✓ VPN connection established!")
                        connected = True
                        break
                    if 'AUTH_FAILED' in log:
                        print("✗ VPN auth failed")
                        return False
                    if 'Connection refused' in log or 'Connection reset' in log:
                        print("✗ VPN connection refused")
                        return False
                    if 'RESOLVE: Cannot resolve host address' in log:
                        print("✗ VPN server DNS resolution failed")
                        return False
            
            # Also check if tun0 interface is up
            success, _ = run_cmd("ip addr show tun0 2>/dev/null | grep inet")
            if success:
                print("✓ VPN tunnel interface is up!")
                connected = True
                break
            
            if i % 10 == 0 and i > 0:
                print(f"  Still waiting for VPN connection... ({i}s)")
        
        if connected:
            # Give it a moment for routing to stabilize
            time.sleep(3)
            
            # Setup DNS through the VPN
            setup_dns_fallback()
            
            return True
        
        print("✗ VPN connection timeout")
        return False
        
    except Exception as e:
        print(f"Error connecting to VPN: {e}")
        return False


def disconnect_vpn():
    """Disconnect from VPN."""
    print("Disconnecting VPN...")
    try:
        run_cmd("sudo killall openvpn 2>/dev/null || true")
        time.sleep(2)
    except:
        pass


def main():
    """Main function to find working VPN and verify connectivity."""
    print("=" * 60)
    print("VPN Connection Helper")
    print("=" * 60)
    
    # First, test without VPN
    print("\n[Step 1] Testing direct connectivity (no VPN)...")
    if test_connectivity():
        print("\n✓ Sites are accessible without VPN! Proceeding with downloads.")
        sys.exit(0)
    
    print("\n[Step 2] Sites are blocked. Setting up VPN...")
    
    # Check DNS
    test_dns()
    
    # Fetch available VPN servers
    servers = fetch_vpn_servers()
    
    if not servers:
        print("\n✗ No VPN servers available from VPN Gate")
        print("Trying to continue without VPN (may fail)...")
        sys.exit(1)
    
    # Try each server
    print(f"\n[Step 3] Trying VPN servers...")
    for i, server in enumerate(servers):
        print(f"\n--- Server {i+1}/{len(servers)}: {server['country']} - {server['hostname']} ({server['ip']}) ---")
        print(f"    Speed: {server['speed']/1000000:.1f} Mbps, Score: {server['score']}")
        
        # Disconnect any existing VPN
        disconnect_vpn()
        
        # Save config
        config_file = save_ovpn_config(server)
        if not config_file:
            print("  ✗ Failed to save config, trying next...")
            continue
        
        # Connect
        if connect_vpn(config_file):
            # Test connectivity through VPN
            print("\n  Testing connectivity through VPN...")
            if test_connectivity():
                print(f"\n{'='*60}")
                print(f"✓ SUCCESS! Connected via {server['country']} VPN server: {server['hostname']}")
                print(f"{'='*60}")
                sys.exit(0)
            else:
                print("  ✗ VPN connected but sites still blocked, trying next server...")
                disconnect_vpn()
        else:
            print("  ✗ Failed to connect, trying next server...")
    
    print("\n" + "=" * 60)
    print("✗ Failed to find working VPN server")
    print("  All servers were tried but none provided access to LibGen/Anna's Archive")
    print("=" * 60)
    sys.exit(1)


if __name__ == "__main__":
    main()
