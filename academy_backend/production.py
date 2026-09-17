"""WSGI entry point for one Waitress process behind the host's HTTPS proxy."""
from email.message import Message
from http import HTTPStatus
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
import os
import threading

from server import Academy, Handler, ROOT


class WSGIHandler(Handler):
    # Reuse the same routing, authorization and output headers as local preview.
    # Waitress owns request parsing, connection limits, timeouts and body limits.
    def __init__(self, academy, environ):
        self.server = SimpleNamespace(app=academy)
        self.path = environ.get('PATH_INFO', '/')
        self.client_address = (environ.get('REMOTE_ADDR', 'unknown'), 0)
        self.headers = Message()
        for key, value in environ.items():
            if key.startswith('HTTP_'):
                self.headers[key[5:].replace('_', '-')] = value
        for key in ('CONTENT_TYPE', 'CONTENT_LENGTH'):
            if environ.get(key): self.headers[key.replace('_', '-')] = environ[key]
        self.rfile = environ['wsgi.input']
        self.wfile = BytesIO()
        self.response_headers = []
        self.status = 200

    def send_response(self, code, message=None):
        self.status = code

    def send_header(self, name, value):
        self.response_headers.append((name, str(value)))

    def end_headers(self):
        pass


def wsgi_app(academy):
    def application(environ, start_response):
        request = WSGIHandler(academy, environ)
        method = environ.get('REQUEST_METHOD', 'GET')
        if method in ('GET', 'HEAD'):
            request.do_GET()
        elif method == 'POST':
            request.do_POST()
        else:
            request.output({'error': 'Method not allowed.'}, 405)
        start_response(f'{request.status} {HTTPStatus(request.status).phrase}', request.response_headers)
        return [b'' if method == 'HEAD' else request.wfile.getvalue()]
    return application


def main():
    from waitress import serve
    origin = os.environ.get('ACADEMY_ORIGIN', '').rstrip('/')
    parsed = urlsplit(origin)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username:
        raise SystemExit('Set ACADEMY_ORIGIN to the exact HTTPS site origin, without a path.')
    directory = os.environ.get('ACADEMY_DATA_DIR')
    if not directory or not Path(directory).is_absolute():
        raise SystemExit('Set ACADEMY_DATA_DIR to the absolute persistent disk directory.')
    # Applications remain closed on a new deployment until explicitly opened.
    os.environ.setdefault('ACADEMY_ENROLLMENT_OPEN', 'false')
    academy = Academy(directory, origin)
    threading.Thread(target=academy.send_loop, daemon=True).start()
    try:
        serve(wsgi_app(academy), host='0.0.0.0', port=int(os.environ.get('PORT', '10000')),
              threads=4, connection_limit=100, channel_timeout=30,
              max_request_body_size=20000, max_request_header_size=16384,
              clear_untrusted_proxy_headers=True)
    finally:
        academy.stop.set()


if __name__ == '__main__':
    main()
