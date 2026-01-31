#!/bin/bash
# Ebook Download Script - Pure Shell
# Uses curl to search LibGen, extract MD5, download via IPFS gateways

set -e

DOWNLOADS_DIR="downloads"
mkdir -p "$DOWNLOADS_DIR"

# IPFS Gateways (CDN-backed, rarely blocked)
IPFS_GATEWAYS=(
    "https://cloudflare-ipfs.com/ipfs"
    "https://ipfs.io/ipfs"
    "https://gateway.pinata.cloud/ipfs"
    "https://dweb.link/ipfs"
)

# Function to search LibGen and get MD5
search_libgen() {
    local query="$1"
    local encoded_query=$(echo "$query" | sed 's/ /+/g')
    
    echo "=== Searching LibGen for: $query ==="
    
    # Try different mirrors
    local mirrors=("libgen.is" "libgen.rs" "libgen.st")
    
    for mirror in "${mirrors[@]}"; do
        echo "Trying mirror: $mirror"
        
        local url="https://${mirror}/search.php?req=${encoded_query}&lg_topic=libgen&open=0&view=simple&res=25&phrase=1&column=def"
        
        # Fetch search results with browser-like headers
        local response=$(curl -sL -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36" \
            -H "Accept: text/html,application/xhtml+xml" \
            -H "Accept-Language: en-US,en;q=0.9" \
            --connect-timeout 30 \
            --max-time 60 \
            "$url" 2>/dev/null || echo "")
        
        if [ -z "$response" ]; then
            echo "  No response from $mirror"
            continue
        fi
        
        # Extract MD5 from response (pattern: /main/MD5 or md5=MD5)
        local md5=$(echo "$response" | grep -oP '(?<=/main/|md5=)[A-Fa-f0-9]{32}' | head -1)
        
        if [ -n "$md5" ]; then
            echo "  Found MD5: $md5"
            echo "$md5"
            return 0
        else
            echo "  No MD5 found on $mirror"
        fi
    done
    
    echo "  Failed to find book on LibGen"
    return 1
}

# Function to get IPFS CID from library.lol
get_ipfs_cid() {
    local md5="$1"
    
    echo "=== Getting IPFS CID from library.lol ==="
    
    local url="https://library.lol/main/${md5}"
    
    local response=$(curl -sL -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36" \
        --connect-timeout 30 \
        --max-time 60 \
        "$url" 2>/dev/null || echo "")
    
    if [ -z "$response" ]; then
        echo "  No response from library.lol"
        return 1
    fi
    
    # Extract IPFS CID from response
    local cid=$(echo "$response" | grep -oP '(?<=/ipfs/)[A-Za-z0-9]+' | head -1)
    
    if [ -n "$cid" ]; then
        echo "  Found IPFS CID: $cid"
        echo "$cid"
        return 0
    fi
    
    # Try to extract direct download link
    local download_link=$(echo "$response" | grep -oP 'href="[^"]*get\.php[^"]*"' | head -1 | sed 's/href="//;s/"//')
    
    if [ -n "$download_link" ]; then
        echo "  Found direct link: $download_link"
        echo "DIRECT:$download_link"
        return 0
    fi
    
    echo "  No IPFS CID or download link found"
    return 1
}

# Function to download from IPFS gateways
download_from_ipfs() {
    local cid="$1"
    local filename="$2"
    
    echo "=== Downloading from IPFS gateways ==="
    
    for gateway in "${IPFS_GATEWAYS[@]}"; do
        echo "Trying: $gateway"
        
        local url="${gateway}/${cid}"
        
        if curl -sL -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36" \
            --connect-timeout 30 \
            --max-time 300 \
            -o "${DOWNLOADS_DIR}/${filename}" \
            "$url" 2>/dev/null; then
            
            # Check if file was downloaded and has content
            if [ -f "${DOWNLOADS_DIR}/${filename}" ] && [ -s "${DOWNLOADS_DIR}/${filename}" ]; then
                local size=$(stat -c%s "${DOWNLOADS_DIR}/${filename}" 2>/dev/null || stat -f%z "${DOWNLOADS_DIR}/${filename}" 2>/dev/null)
                if [ "$size" -gt 10000 ]; then
                    echo "  SUCCESS! Downloaded: ${filename} (${size} bytes)"
                    return 0
                else
                    echo "  File too small (${size} bytes), trying next gateway"
                    rm -f "${DOWNLOADS_DIR}/${filename}"
                fi
            fi
        fi
    done
    
    echo "  Failed all IPFS gateways"
    return 1
}

# Function to download directly
download_direct() {
    local url="$1"
    local filename="$2"
    
    echo "=== Downloading directly ==="
    echo "URL: $url"
    
    if curl -sL -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36" \
        --connect-timeout 30 \
        --max-time 300 \
        -o "${DOWNLOADS_DIR}/${filename}" \
        "$url" 2>/dev/null; then
        
        if [ -f "${DOWNLOADS_DIR}/${filename}" ] && [ -s "${DOWNLOADS_DIR}/${filename}" ]; then
            local size=$(stat -c%s "${DOWNLOADS_DIR}/${filename}" 2>/dev/null || stat -f%z "${DOWNLOADS_DIR}/${filename}" 2>/dev/null)
            if [ "$size" -gt 10000 ]; then
                echo "  SUCCESS! Downloaded: ${filename} (${size} bytes)"
                return 0
            fi
        fi
    fi
    
    rm -f "${DOWNLOADS_DIR}/${filename}"
    echo "  Direct download failed"
    return 1
}

# Main function to process a search term
process_search() {
    local query="$1"
    local safe_name=$(echo "$query" | tr -cd '[:alnum:] ' | tr ' ' '_' | cut -c1-50)
    
    echo ""
    echo "========================================"
    echo "Processing: $query"
    echo "========================================"
    
    # Step 1: Search LibGen for MD5
    local md5=$(search_libgen "$query")
    
    if [ -z "$md5" ]; then
        echo "FAILED: Could not find book on LibGen"
        return 1
    fi
    
    # Step 2: Get IPFS CID or direct link
    local result=$(get_ipfs_cid "$md5")
    
    if [ -z "$result" ]; then
        echo "FAILED: Could not get download link"
        return 1
    fi
    
    # Step 3: Download
    if [[ "$result" == DIRECT:* ]]; then
        # Direct download
        local direct_url="${result#DIRECT:}"
        download_direct "$direct_url" "${safe_name}.pdf" && return 0
    else
        # IPFS download
        download_from_ipfs "$result" "${safe_name}.pdf" && return 0
    fi
    
    echo "FAILED: All download methods failed"
    return 1
}

# Main
echo "========================================"
echo "Ebook Download Script (Pure Shell)"
echo "========================================"
echo ""

if [ ! -f "search_terms.txt" ]; then
    echo "ERROR: search_terms.txt not found"
    exit 1
fi

echo "Search terms:"
cat -n search_terms.txt
echo ""

success=0
failed=0

while IFS= read -r term || [ -n "$term" ]; do
    if [ -n "$term" ]; then
        if process_search "$term"; then
            ((success++))
        else
            ((failed++))
        fi
        sleep 2
    fi
done < search_terms.txt

echo ""
echo "========================================"
echo "SUMMARY"
echo "========================================"
echo "Successful: $success"
echo "Failed: $failed"
echo ""
echo "Downloaded files:"
ls -la "$DOWNLOADS_DIR/" 2>/dev/null || echo "No files"
