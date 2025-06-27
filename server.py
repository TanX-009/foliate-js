import os
import json
from urllib.parse import urlparse, parse_qs
from http.server import SimpleHTTPRequestHandler, HTTPServer
from email.parser import BytesParser
from email.policy import default
from uuid import uuid4

PORT = 8000
BOOKS_DIR = os.path.abspath("books")
PROGRESS_FILE = "progress.json"
ALLOWED_EXTS = [".epub", ".mobi", ".azw3", ".fb2", ".cbz"]

# Ensure books dir exists
os.makedirs(BOOKS_DIR, exist_ok=True)

# Load or initialize progress storage
if os.path.exists(PROGRESS_FILE):
    with open(PROGRESS_FILE, "r") as f:
        progress_data = json.load(f)
else:
    progress_data = []


def get_progress_for_file(file_name):
    return next(
        (item["progress"] for item in progress_data if item["file"] == file_name), None
    )


class CustomHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed_url = urlparse(self.path)

        if parsed_url.path == "/api/progress":
            query = parse_qs(parsed_url.query)
            file_name = query.get("file", [None])[0]
            if file_name:
                prog = get_progress_for_file(file_name)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(prog).encode())
            else:
                self.send_error(400, "Missing 'file' query param")

        elif parsed_url.path == "/api/list":
            file_list = []
            for root, _, files in os.walk(BOOKS_DIR):
                for f in files:
                    rel_path = os.path.relpath(os.path.join(root, f), BOOKS_DIR)
                    file_list.append(
                        {
                            "file": rel_path,
                            "progress": get_progress_for_file(rel_path) or None,
                        }
                    )
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"files": file_list}, indent=2).encode())

        else:
            super().do_GET()  # Static files

    def do_POST(self):
        if self.path == "/api/progress":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body)
                file = data["file"]
                prog = data["progress"]

                # Overwrite if already exists
                found = False
                for item in progress_data:
                    if item["file"] == file:
                        item["progress"] = prog
                        found = True
                        break
                if not found:
                    progress_data.append({"file": file, "progress": prog})

                with open(PROGRESS_FILE, "w") as f:
                    json.dump(progress_data, f, indent=2)

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "saved"}).encode())

            except Exception as e:
                self.send_error(400, f"Invalid JSON or missing fields: {e}")
        elif self.path == "/api/upload":
            content_type = self.headers.get("Content-Type")
            if not content_type or "multipart/form-data" not in content_type:
                self.send_error(400, "Expected multipart/form-data")
                return

            content_len = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_len)

            # Parse multipart form using email.parser
            data = b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + body
            msg = BytesParser(policy=default).parsebytes(data)

            for part in msg.iter_parts():
                disposition = part.get("Content-Disposition", "")
                if "form-data" not in disposition or "filename=" not in disposition:
                    continue
                filename = part.get_filename()
                ext = os.path.splitext(filename or "")[1].lower()
                if ext not in ALLOWED_EXTS:
                    self.send_error(400, f"File type {ext} not allowed")
                    return
                file_path = os.path.join(
                    BOOKS_DIR, os.path.basename(filename or f"unnamed{uuid4}.{ext}")
                )
                with open(file_path, "wb") as f:
                    f.write(part.get_payload(decode=True))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"Upload successful")
                return

            self.send_error(400, "No file found in upload")
        else:
            self.send_error(404, "Unknown API endpoint")

    def translate_path(self, path):
        # Serve files from /books directory
        full_path = super().translate_path(path)
        rel_path = os.path.relpath(full_path, os.getcwd())
        return os.path.join(BOOKS_DIR, os.path.relpath(rel_path, "books"))

    def log_message(self, format, *args):
        print(
            f"[{self.client_address[0]}] {self.log_date_time_string()} - {format % args}"
        )


if __name__ == "__main__":
    os.chdir(os.getcwd())
    server = HTTPServer(("", PORT), CustomHandler)
    print(f"Serving /books from http://localhost:{PORT}/")
    print("API:")
    print("  GET  /api/list")
    print("  GET  /api/progress?file=...")
    print("  POST /api/progress")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
