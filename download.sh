#!/bin/bash
# Ebook Download Script - welib.org only
# Uses curl with browser headers, slow downloads, wait between requests

set -e

DOWNLOADS_DIR="downloads"
mkdir -p "$DOWNLOADS_DIR"

# User agent to look like a real browser
USER_AGENT="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Function to search welib.org
search_welib() {
    local query="$1"
    local encoded_query=$(echo "$query" | sed 's/ /%20/g')
    
    echo "=== Searching welib.org for: $query ==="
    
    # Common welib.org search URL pattern (similar to Anna's Archive)
    local url="https://welib.org/search?q=${encoded_query}"
    
    echo "URL: $url"
    echo "Waiting 5 seconds before request..."
    sleep 5
    
    # Fetch search results
    local response=$(curl -sL \
        -A "$USER_AGENT" \
        -H "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8" \
        -H "Accept-Language: en-US,en;q=0.9" \
        -H "Accept-Encoding: gzip, deflate, br" \
        -H "Connection: keep-alive" \
        -H "Upgrade-Insecure-Requests: 1" \
        --compressed \
        --connect-timeout 60 \
        --max-time 120 \
        "$url" 2>&1)
    
    echo "Response length: ${#response} characters"
    
    if [ -z "$response" ] || [ ${#response} -lt 500 ]; then
        echo "ERROR: No response or response too short"
        echo "Raw response: $response"
        return 1
    fi
    
    # Save response for debugging
    echo "$response" > /tmp/welib_search_response.html
    echo "Saved response to /tmp/welib_search_response.html"
    
    # Try to extract MD5 links (welib uses MD5 format like Anna's Archive)
    # Pattern: /md5/XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
    local md5=$(echo "$response" | grep -oP '(?<=/md5/)[a-fA-F0-9]{32}' | head -1)
    
    if [ -n "$md5" ]; then
        echo "Found MD5: $md5"
        echo "$md5"
        return 0
    fi
    
    # Alternative: try to find any download link
    local download_link=$(echo "$response" | grep -oP 'href="[^"]*download[^"]*"' | head -1 | sed 's/href="//;s/"$//')
    
    if [ -n "$download_link" ]; then
        echo "Found download link: $download_link"
        echo "LINK:$download_link"
        return 0
    fi
    
    echo "No results found"
    echo "First 2000 chars of response:"
    echo "$response" | head -c 2000
    return 1
}

# Function to get download page from MD5
get_download_page() {
    local md5="$1"
    
    echo "=== Getting download page for MD5: $md5 ==="
    
    local url="https://welib.org/md5/${md5}"
    
    echo "URL: $url"
    echo "Waiting 5 seconds..."
    sleep 5
    
    local response=$(curl -sL \
        -A "$USER_AGENT" \
        -H "Accept: text/html,application/xhtml+xml" \
        -H "Accept-Language: en-US,en;q=0.9" \
        --compressed \
        --connect-timeout 60 \
        --max-time 120 \
        "$url" 2>&1)
    
    echo "Response length: ${#response} characters"
    
    # Save for debugging
    echo "$response" > /tmp/welib_md5_response.html
    
    # Look for slow download link
    local slow_link=$(echo "$response" | grep -oP 'href="[^"]*slow[^"]*"' | head -1 | sed 's/href="//;s/"$//')
    
    if [ -n "$slow_link" ]; then
        echo "Found slow download link: $slow_link"
        # Make sure it's a full URL
        if [[ ! "$slow_link" == http* ]]; then
            slow_link="https://welib.org${slow_link}"
        fi
        echo "$slow_link"
        return 0
    fi
    
    # Try any download link
    local any_link=$(echo "$response" | grep -oP 'href="[^"]*\.pdf[^"]*"|href="[^"]*\.epub[^"]*"' | head -1 | sed 's/href="//;s/"$//')
    
    if [ -n "$any_link" ]; then
        echo "Found file link: $any_link"
        if [[ ! "$any_link" == http* ]]; then
            any_link="https://welib.org${any_link}"
        fi
        echo "$any_link"
        return 0
    fi
    
    echo "No download link found on page"
    return 1
}

# Function to download file
download_file() {
    local url="$1"
    local filename="$2"
    
    echo "=== Downloading file ==="
    echo "URL: $url"
    echo "Saving as: $filename"
    echo "Waiting 10 seconds before download (slow server)..."
    sleep 10
    
    # Download with long timeout for slow servers
    if curl -sL \
        -A "$USER_AGENT" \
        -H "Accept: */*" \
        -H "Accept-Language: en-US,en;q=0.9" \
        --compressed \
        --connect-timeout 120 \
        --max-time 600 \
        -o "${DOWNLOADS_DIR}/${filename}" \
        "$url" 2>&1; then
        
        if [ -f "${DOWNLOADS_DIR}/${filename}" ]; then
            local size=$(stat -c%s "${DOWNLOADS_DIR}/${filename}" 2>/dev/null || stat -f%z "${DOWNLOADS_DIR}/${filename}" 2>/dev/null || echo "0")
            
            if [ "$size" -gt 10000 ]; then
                echo "SUCCESS! Downloaded: ${filename} (${size} bytes)"
                return 0
            else
                echo "File too small (${size} bytes) - probably error page"
                cat "${DOWNLOADS_DIR}/${filename}" 2>/dev/null | head -c 500
                rm -f "${DOWNLOADS_DIR}/${filename}"
            fi
        fi
    fi
    
    echo "Download failed"
    return 1
}

# Main function to process a search term
process_search() {
    local query="$1"
    local safe_name=$(echo "$query" | tr -cd '[:alnum:] ' | tr ' ' '_' | cut -c1-50)
    
    echo ""
    echo "========================================================"
    echo "Processing: $query"
    echo "========================================================"
    
    # Step 1: Search
    local result=$(search_welib "$query")
    
    if [ -z "$result" ]; then
        echo "FAILED: No search results"
        return 1
    fi
    
    # Step 2: Handle result
    if [[ "$result" == LINK:* ]]; then
        # Direct link found
        local link="${result#LINK:}"
        download_file "$link" "${safe_name}.pdf" && return 0
    else
        # MD5 found - get download page
        local download_url=$(get_download_page "$result")
        
        if [ -n "$download_url" ]; then
            download_file "$download_url" "${safe_name}.pdf" && return 0
        fi
    fi
    
    echo "FAILED: Could not download"
    return 1
}

# Main
echo "========================================================"
echo "Ebook Download Script - welib.org"
echo "========================================================"
echo ""
echo "NOTE: Using slow servers with long waits between requests"
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
            ((success++)) || true
        else
            ((failed++)) || true
        fi
        
        echo ""
        echo "Waiting 30 seconds before next search..."
        sleep 30
    fi
done < search_terms.txt

echo ""
echo "========================================================"
echo "SUMMARY"
echo "========================================================"
echo "Successful: $success"
echo "Failed: $failed"
echo ""
echo "Downloaded files:"
ls -la "$DOWNLOADS_DIR/" 2>/dev/null || echo "No files"

# Show debug files
echo ""
echo "Debug files in /tmp:"
ls -la /tmp/welib*.html 2>/dev/null || echo "No debug files"
