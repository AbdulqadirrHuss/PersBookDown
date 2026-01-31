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
]

# VPN Gate API endpoint
VPN_GATE_API = "https://www.vpngate.net/api/iphone/"

# Countries that typically work well (avoid restrictive countries)
PREFERRED_COUNTRIES = ["JP", "KR", "US", "UK", "DE", "NL", "CA", "FR", "CH", "SE"]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}


def test_connectivity():
    """Test if we can access LibGen or Anna's Archive."""
    for url, name in TEST_URLS:
        try:
            req = Request(url, headers=HEADERS)
            response = urlopen(req, timeout=15)
            if response.status == 200:
                print(f"✓ Successfully connected to {name}: {url}")
                return True
        except Exception as e:
            print(f"✗ Cannot access {name} ({url}): {e}")
    return False


def fetch_vpn_servers():
    """Fetch list of VPN servers from VPN Gate."""
    print("Fetching VPN server list from VPN Gate...")
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
                
                # Filter for preferred countries and decent speed
                if server['country'] in PREFERRED_COUNTRIES and server['speed'] > 1000000:
                    servers.append(server)
            except (ValueError, KeyError):
                continue
        
        # Sort by score (higher is better)
        servers.sort(key=lambda x: x['score'], reverse=True)
        print(f"Found {len(servers)} suitable VPN servers")
        return servers[:10]  # Return top 10
        
    except Exception as e:
        print(f"Error fetching VPN servers: {e}")
        return []


def save_ovpn_config(server, filename="/tmp/vpn_config.ovpn"):
    """Decode and save OpenVPN configuration."""
    try:
        config_data = base64.b64decode(server['config']).decode('utf-8')
        
        # Add some compatibility options for Ubuntu runners
        if 'cipher' not in config_data.lower():
            config_data += "\ncipher AES-256-CBC\n"
        
        with open(filename, 'w') as f:
            f.write(config_data)
        
        return filename
    except Exception as e:
        print(f"Error saving config: {e}")
        return None


def connect_vpn(config_file):
    """Connect to VPN using OpenVPN."""
    try:
        # Start OpenVPN in background
        print(f"Connecting to VPN...")
        process = subprocess.Popen(
            ['sudo', 'openvpn', '--config', config_file, '--daemon', '--log', '/tmp/openvpn.log'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Wait for connection to establish
        for i in range(30):  # Wait up to 30 seconds
            time.sleep(1)
            
            # Check if tun interface is up
            result = subprocess.run(['ip', 'addr', 'show', 'tun0'], capture_output=True)
            if result.returncode == 0:
                print("VPN connected successfully!")
                return True
                
            # Check OpenVPN log for errors
            if os.path.exists('/tmp/openvpn.log'):
                with open('/tmp/openvpn.log', 'r') as f:
                    log = f.read()
                    if 'Initialization Sequence Completed' in log:
                        print("VPN connected successfully!")
                        return True
                    if 'AUTH_FAILED' in log or 'Connection refused' in log:
                        print("VPN connection failed (auth/connection error)")
                        return False
        
        print("VPN connection timeout")
        return False
        
    except Exception as e:
        print(f"Error connecting to VPN: {e}")
        return False


def disconnect_vpn():
    """Disconnect from VPN."""
    try:
        subprocess.run(['sudo', 'killall', 'openvpn'], capture_output=True)
        time.sleep(2)
    except:
        pass


def main():
    """Main function to find working VPN and verify connectivity."""
    print("=" * 60)
    print("VPN Connection Helper")
    print("=" * 60)
    
    # First, test without VPN
    print("\nTesting connectivity without VPN...")
    if test_connectivity():
        print("\n✓ Sites are accessible without VPN!")
        sys.exit(0)
    
    print("\nSites are blocked. Attempting VPN connection...")
    
    # Fetch available VPN servers
    servers = fetch_vpn_servers()
    
    if not servers:
        print("No VPN servers available")
        sys.exit(1)
    
    # Try each server
    for i, server in enumerate(servers):
        print(f"\n[{i+1}/{len(servers)}] Trying {server['country']} server: {server['hostname']}")
        
        # Disconnect any existing VPN
        disconnect_vpn()
        
        # Save config
        config_file = save_ovpn_config(server)
        if not config_file:
            continue
        
        # Connect
        if connect_vpn(config_file):
            # Test connectivity through VPN
            time.sleep(3)  # Wait for routing to stabilize
            if test_connectivity():
                print(f"\n✓ SUCCESS! Connected via {server['country']} VPN server")
                sys.exit(0)
            else:
                print(f"VPN connected but sites still blocked, trying next...")
                disconnect_vpn()
        
    print("\n✗ Failed to find working VPN server")
    sys.exit(1)


if __name__ == "__main__":
    main()
