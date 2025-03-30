"""
Proxy-bonus.py - Enhanced HTTP proxy server

Implemented additional features:
1. Cache expiration handling: Checks Expires header to determine if cache is fresh, implemented time parsing and comparison logic
2. Resource prefetching: When receiving HTML pages, parses and prefetches all referenced resources using regex to identify href and src attributes
3. Custom port support: Able to handle specific port numbers specified in URLs by parsing URL strings to extract hostname and port information

Author: [Your Name]
Date: [Current Date]
"""

import socket
import sys
import os
import re
import threading
import time
import email.utils
import datetime
from urllib.parse import urlparse

# Define global variables
CACHE_DIR = "proxy_cache/"
MAX_CONNECTIONS = 5
BUFFER_SIZE = 8192

def create_cache_dir():
    """Create cache directory if it doesn't exist"""
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)

def generate_cache_filename(url):
    """Convert URL to cache filename"""
    # Replace special characters in URL to use as filename
    return CACHE_DIR + re.sub(r'[^a-zA-Z0-9]', '_', url)

def is_cache_valid(headers):
    """
    Feature 1: Check if cache is still valid
    Determine if cached content is expired by checking Expires header
    
    Parameters:
    - headers: Dictionary of response headers
    
    Returns:
    - Boolean indicating if cache is valid
    """
    if 'Expires' in headers:
        expires_str = headers['Expires']
        try:
            # Parse Expires time string to datetime object
            expires_time = email.utils.parsedate_to_datetime(expires_str)
            current_time = datetime.datetime.now(datetime.timezone.utc)
            
            # If current time is less than expiration time, cache is valid
            return current_time < expires_time
        except (TypeError, ValueError):
            # If parsing fails, consider cache invalid
            return False
    
    # If no Expires header, check Cache-Control
    if 'Cache-Control' in headers:
        cache_control = headers['Cache-Control']
        
        # If explicitly marked as no-cache, return False
        if 'no-cache' in cache_control or 'no-store' in cache_control:
            return False
            
        # Check for max-age directive
        max_age_match = re.search(r'max-age=(\d+)', cache_control)
        if max_age_match:
            max_age = int(max_age_match.group(1))
            
            # Check for our custom cache-timestamp header
            if 'cache-timestamp' in headers:
                cache_time = float(headers['cache-timestamp'])
                current_time = time.time()
                
                # If less than max-age has passed, cache is valid
                return (current_time - cache_time) < max_age
    
    # By default, be conservative and consider cache invalid
    return False

def extract_headers_from_cache(cache_filename):
    """Extract HTTP headers from cached file"""
    try:
        with open(cache_filename, 'r') as f:
            content = f.read()
            
        # Split headers and body
        header_body_split = content.split('\r\n\r\n', 1)
        if len(header_body_split) != 2:
            return {}
            
        header_section = header_body_split[0]
        headers = {}
        
        # Parse each header field
        for line in header_section.split('\r\n')[1:]:  # Skip first line (status line)
            if ': ' in line:
                name, value = line.split(': ', 1)
                headers[name] = value
                
        return headers
    except Exception as e:
        print(f"Error extracting headers from cache: {e}")
        return {}

def prefetch_resources(html_content, base_url):
    """
    Feature 2: Prefetch resources referenced in HTML
    Parse HTML content, find all href and src attributes, prefetch and cache referenced resources
    
    Parameters:
    - html_content: HTML page content
    - base_url: Base URL of the page, used to build complete URLs
    """
    # Extract hostname and protocol from base URL
    parsed_url = urlparse(base_url)
    base_hostname = parsed_url.netloc
    protocol = parsed_url.scheme or 'http'
    
    # Regex patterns to match href and src attributes
    href_pattern = re.compile(r'href=[\'"]([^\'"]+)[\'"]')
    src_pattern = re.compile(r'src=[\'"]([^\'"]+)[\'"]')
    
    # Extract all matching URLs
    hrefs = href_pattern.findall(html_content)
    srcs = src_pattern.findall(html_content)
    
    # Combine all resource URLs and remove duplicates
    all_resources = list(set(hrefs + srcs))
    
    print(f"Found {len(all_resources)} resources to prefetch")
    
    # Start prefetching thread for each resource
    for resource in all_resources:
        # Skip JavaScript code snippets and empty links
        if resource.startswith('javascript:') or resource == '#' or resource == '':
            continue
            
        # Build complete URL
        if resource.startswith('http'):
            # Already a complete URL
            resource_url = resource
        elif resource.startswith('//'):
            # Protocol-relative URL
            resource_url = f"{protocol}:{resource}"
        elif resource.startswith('/'):
            # Site root-relative URL
            resource_url = f"{protocol}://{base_hostname}{resource}"
        else:
            # Directory-relative URL
            base_path = '/'.join(base_url.split('/')[:-1]) + '/'
            resource_url = f"{base_path}{resource}"
        
        # Create thread for prefetching
        prefetch_thread = threading.Thread(
            target=prefetch_resource,
            args=(resource_url,)
        )
        prefetch_thread.daemon = True  # Set as daemon thread to terminate when main program exits
        prefetch_thread.start()

def prefetch_resource(url):
    """
    Prefetch a single resource and cache it
    
    Parameters:
    - url: URL of the resource to prefetch
    """
    try:
        print(f"Prefetching: {url}")
        
        # Parse URL
        parsed_url = urlparse(url)
        hostname = parsed_url.netloc
        path = parsed_url.path or '/'
        
        # Check for port number
        if ':' in hostname:
            hostname, port = hostname.split(':', 1)
            port = int(port)
        else:
            port = 80  # Default HTTP port
        
        # Create socket connection
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_socket.settimeout(5)  # Set timeout to avoid blocking for too long
        
        try:
            client_socket.connect((hostname, port))
            
            # Construct HTTP request
            request = f"GET {path} HTTP/1.1\r\n"
            request += f"Host: {hostname}\r\n"
            request += "Connection: close\r\n"
            request += "\r\n"
            
            # Send request
            client_socket.sendall(request.encode())
            
            # Receive response
            response = b''
            while True:
                data = client_socket.recv(BUFFER_SIZE)
                if not data:
                    break
                response += data
            
            # Save response to cache
            if response:
                cache_filename = generate_cache_filename(url)
                with open(cache_filename, 'wb') as f:
                    f.write(response)
                    
                # Add cache timestamp
                with open(cache_filename, 'r+') as f:
                    content = f.read()
                    # Add our timestamp between headers and body
                    header_body = content.split('\r\n\r\n', 1)
                    if len(header_body) == 2:
                        header, body = header_body
                        header += f"\r\ncache-timestamp: {time.time()}"
                        f.seek(0)
                        f.write(f"{header}\r\n\r\n{body}")
                
                print(f"Successfully prefetched and cached: {url}")
        finally:
            client_socket.close()
    except Exception as e:
        print(f"Error prefetching {url}: {e}")

def extract_server_info(url):
    """
    Feature 3: Handle port numbers specified in URLs
    Parse URL to extract hostname, port number, and path
    
    Parameters:
    - url: URL with or without port number
    
    Returns:
    - Tuple: (hostname, port, path)
    """
    # Remove protocol prefix
    if '://' in url:
        url = url.split('://', 1)[1]
    
    # Extract hostname and possible port number
    if '/' in url:
        server_info = url.split('/', 1)[0]
        path = '/' + url.split('/', 1)[1]
    else:
        server_info = url
        path = '/'
    
    # Check if port number is specified
    if ':' in server_info:
        hostname, port_str = server_info.split(':', 1)
        try:
            port = int(port_str)
            print(f"Custom port detected: {port}")
        except ValueError:
            port = 80  # Default HTTP port
    else:
        hostname = server_info
        port = 80
    
    return hostname, port, path

def handle_client_request(client_socket):
    """Handle HTTP requests from clients"""
    try:
        # Receive client request
        request = client_socket.recv(BUFFER_SIZE).decode('utf-8')
        
        # Parse request headers
        first_line = request.split('\n')[0]
        if not first_line:
            client_socket.close()
            return
            
        # Extract URL from first line
        url = first_line.split(' ')[1]
        
        # Handle proxy request URL format
        if url.startswith('http://'):
            http_pos = url.find('://')
            url = url[http_pos + 3:]
        
        # Extract server info using enhanced function with custom port support
        hostname, port, path = extract_server_info(url)
        
        # Construct request to send to remote server
        remote_request = request.replace(first_line, f"GET {path} HTTP/1.1")
        
        # Check cache
        cache_filename = generate_cache_filename(url)
        use_cache = False
        
        if os.path.exists(cache_filename):
            # Extract headers from cached file
            cache_headers = extract_headers_from_cache(cache_filename)
            
            # Check if cache is valid
            if is_cache_valid(cache_headers):
                use_cache = True
                print(f"Using valid cache for {url}")
                
                # Read from cache and send to client
                with open(cache_filename, 'rb') as f:
                    cache_content = f.read()
                client_socket.sendall(cache_content)
                
                # If HTML content, prefetch resources in background
                content_type = cache_headers.get('Content-Type', '')
                if 'text/html' in content_type:
                    # Extract HTML from cache content
                    cache_str = cache_content.decode('utf-8', errors='ignore')
                    body_parts = cache_str.split('\r\n\r\n', 1)
                    if len(body_parts) > 1:
                        html_content = body_parts[1]
                        # Prefetch resources in background
                        full_url = f"http://{hostname}:{port}{path}"
                        threading.Thread(
                            target=prefetch_resources, 
                            args=(html_content, full_url)
                        ).start()
        
        if not use_cache:
            # Create socket to remote server
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_socket.connect((hostname, port))
            
            # Send request to remote server
            server_socket.sendall(remote_request.encode('utf-8'))
            
            # Receive response from remote server
            response = b''
            while True:
                data = server_socket.recv(BUFFER_SIZE)
                if not data:
                    break
                response += data
                
            # Send response to client
            client_socket.sendall(response)
            
            # Save response to cache
            with open(cache_filename, 'wb') as f:
                f.write(response)
            
            # Add cache timestamp
            with open(cache_filename, 'r+') as f:
                content = f.read()
                # Add our timestamp between headers and body
                header_body = content.split('\r\n\r\n', 1)
                if len(header_body) == 2:
                    header, body = header_body
                    header += f"\r\ncache-timestamp: {time.time()}"
                    f.seek(0)
                    f.write(f"{header}\r\n\r\n{body}")
            
            # Check if HTML content
            response_str = response.decode('utf-8', errors='ignore')
            header_parts = response_str.split('\r\n\r\n', 1)
            
            if len(header_parts) > 1:
                headers_str = header_parts[0]
                body = header_parts[1]
                
                # Check Content-Type
                if 'Content-Type: text/html' in headers_str:
                    # Prefetch resources in background
                    full_url = f"http://{hostname}:{port}{path}"
                    threading.Thread(
                        target=prefetch_resources, 
                        args=(body, full_url)
                    ).start()
            
            server_socket.close()
    
    except Exception as e:
        print(f"Error handling request: {e}")
    finally:
        client_socket.close()

def main():
    """Main proxy server function"""
    # Check command line arguments
    if len(sys.argv) <= 1:
        print('Usage: python Proxy-bonus.py <port>')
        sys.exit(1)
    
    # Get port number
    port = int(sys.argv[1])
    
    # Create cache directory
    create_cache_dir()
    
    # Create proxy server socket
    proxy_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    
    # Set socket options to allow address reuse
    proxy_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    # Bind socket to specified port
    proxy_socket.bind(('', port))
    
    # Start listening for connections
    proxy_socket.listen(MAX_CONNECTIONS)
    print(f"Proxy server running on port {port}")
    
    while True:
        try:
            # Accept client connection
            client_socket, addr = proxy_socket.accept()
            print(f"Received connection from {addr[0]}:{addr[1]}")
            
            # Create new thread for each client
            client_thread = threading.Thread(target=handle_client_request, args=(client_socket,))
            client_thread.daemon = True
            client_thread.start()
            
        except KeyboardInterrupt:
            print("Stopping proxy server...")
            break
        except Exception as e:
            print(f"Error: {e}")
    
    # Close proxy socket
    proxy_socket.close()
    print("Proxy server stopped")

if __name__ == "__main__":
    main()