#!/usr/bin/env python3
"""The static server for the page tests: python3 -m http.server with a longer listen queue.

    python3 resources/tests/serve.py 8765               # the repository, on 127.0.0.1:8765
    python3 resources/tests/serve.py 8765 --bind 0.0.0.0 --directory some/folder

The standard library's server listens with a queue of five connections. A page
that loads a few dozen scripts and modules at once opens more connections than
that at the same moment, and with the macOS and Chrome of late 2026 those past
the queue are lost: a module that never arrives makes the page's script fail to
load, and a browser test fails at its first step, or at random later on ("script
failed to load", "No handler registered"). With a queue of 256 (which the system
may hold lower: 128 on macOS) they all arrive.

Otherwise it is that server: the same request handler and log lines, a thread
for each request. It binds 127.0.0.1 unless --bind says otherwise (python3 -m
http.server binds every interface, which shares the repository and its local/
folders with the network), and serves the repository it is in unless
--directory names another folder. A client that goes away mid-answer (a test
that navigates on) is not logged as an error.
"""
import argparse
import functools
import http.server
import os
import socket
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class Server(http.server.ThreadingHTTPServer):
    """http.server's threading server, with a longer listen queue and no traceback for a client gone."""
    request_queue_size = 256
    daemon_threads = True

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError)):
            return
        super().handle_error(request, client_address)


def main():
    """Serve until interrupted."""
    ap = argparse.ArgumentParser(description=__doc__.split('\n', 1)[0])
    ap.add_argument('port', nargs='?', type=int, default=8000)
    ap.add_argument('--bind', '-b', default='127.0.0.1', metavar='ADDRESS')
    ap.add_argument('--directory', '-d', default=ROOT)
    a = ap.parse_args()
    family, _, _, _, address = socket.getaddrinfo(
        a.bind, a.port, type=socket.SOCK_STREAM, flags=socket.AI_PASSIVE)[0]
    Server.address_family = family
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=a.directory)
    with Server(address, handler) as httpd:
        host, port = httpd.socket.getsockname()[:2]
        url_host = f'[{host}]' if ':' in host else host
        print(f'Serving HTTP on {host} port {port} (http://{url_host}:{port}/) ...', flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print('\nKeyboard interrupt received, exiting.')


if __name__ == '__main__':
    main()
