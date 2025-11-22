from http.server import SimpleHTTPRequestHandler, HTTPServer
import mimetypes
import os
import logging
from pathlib import Path
from urllib.parse import unquote

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Base directory for serving files (restrict to stego_images folder)
BASE_DIR = Path(__file__).parent.absolute()

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    
    def log_message(self, format, *args):
        """Override to use our logger"""
        logger.info("%s - - %s" % (self.address_string(), format % args))
    
    def translate_path(self, path):
        """Override to restrict file access to BASE_DIR only"""
        # Remove query string and decode URL
        path = unquote(path.split("?")[0])
        
        # Remove leading slash
        path = path.lstrip("/")
        
        # Prevent directory traversal attacks
        if ".." in path or path.startswith("/"):
            logger.warning(f"Blocked suspicious path: {path}")
            return None
        
        # Build full path within BASE_DIR
        full_path = BASE_DIR / path
        
        # Ensure the path is within BASE_DIR (prevent directory traversal)
        try:
            full_path = full_path.resolve()
            if not str(full_path).startswith(str(BASE_DIR.resolve())):
                logger.warning(f"Blocked path outside BASE_DIR: {path}")
                return None
        except (OSError, ValueError) as e:
            logger.error(f"Error resolving path {path}: {e}")
            return None
        
        return str(full_path)
    
    def do_GET(self):
        """Handle GET requests - serve files in binary mode to preserve all bits"""
        try:
            filepath = self.translate_path(self.path)
            
            if filepath is None:
                self.send_error(403, "Forbidden: Invalid path")
                return
            
            if not os.path.isfile(filepath):
                self.send_error(404, "File not found")
                return
            
            # Get file info
            file_size = os.path.getsize(filepath)
            filename = os.path.basename(filepath)
            
            logger.info(f"Serving file: {filename} ({file_size} bytes)")
            
            # Send response headers
            self.send_response(200)
            
            # Set content type
            ctype = mimetypes.guess_type(filepath)[0] or "application/octet-stream"
            self.send_header("Content-Type", ctype)
            
            # Set content length (important for binary files)
            self.send_header("Content-Length", str(file_size))
            
            # Set content disposition with proper quoting
            safe_filename = filename.replace('"', '\\"')
            self.send_header("Content-Disposition", f'attachment; filename="{safe_filename}"')
            
            # Important: Don't use chunked encoding for binary files
            # This ensures exact byte-for-byte transfer
            self.end_headers()
            
            # Read and send file in chunks to handle large files efficiently
            # Using binary mode ("rb") preserves all bits exactly
            chunk_size = 8192  # 8KB chunks
            try:
                with open(filepath, "rb") as f:
                    while True:
                        chunk = f.read(chunk_size)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                
                logger.info(f"Successfully sent file: {filename}")
                
            except IOError as e:
                logger.error(f"Error reading file {filepath}: {e}")
                # Connection might be closed, so we can't send error response
                return
                
        except Exception as e:
            logger.error(f"Unexpected error handling request: {e}")
            try:
                self.send_error(500, f"Internal server error: {str(e)}")
            except:
                pass  # Connection might be closed

if __name__ == "__main__":
    server_address = ("0.0.0.0", 8000)
    httpd = HTTPServer(server_address, Handler)
    
    logger.info(f"Starting server on {server_address[0]}:{server_address[1]}")
    logger.info(f"Serving files from: {BASE_DIR}")
    logger.info("Server ready. Press Ctrl+C to stop.")
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down server...")
        httpd.shutdown()
        logger.info("Server stopped.")
