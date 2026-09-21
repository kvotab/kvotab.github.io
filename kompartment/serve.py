#!/usr/bin/env python3
"""
Development server for Kompartment.

`python3 -m http.server` sends only Last-Modified, with no Cache-Control and no
ETag. Browsers are then free to reuse JavaScript modules they already hold --
and a Worker keeps its own module cache on top of the page's, so edited code can
keep running for a surprisingly long time. That produces confusing failures
where the page reports something the source on disk no longer says.

This server sends `Cache-Control: no-store` for everything, so a plain refresh
always picks up the current files.

    python3 serve.py [port]

Defaults to port 8080. Serves the directory the script lives in.
"""

import http.server
import os
import socketserver
import sys

# A few types the stdlib guesses wrongly or not at all on some systems.
EXTRA_TYPES = {
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".json": "application/json",
    ".css": "text/css",
    ".svg": "image/svg+xml",
    ".eco": "application/zip",
}


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        **EXTRA_TYPES,
    }

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        # The two headers a <meta> tag cannot carry. index.html holds the rest
        # of the policy, where it is next to the reasons for each entry;
        # anything serving this in earnest should send that one as a header
        # too, and these with it.
        # 'self', not 'none': the page next to this one (kompartment.html on
        # the site) frames the tool, and that is same-origin.
        self.send_header("Content-Security-Policy", "frame-ancestors 'self'")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def log_message(self, fmt, *args):
        # One line per request, without the noisy timestamp prefix.
        sys.stderr.write("  %s\n" % (fmt % args))


class Server(socketserver.ThreadingTCPServer):
    # Restarting the server should not fail because the port is in TIME_WAIT.
    allow_reuse_address = True
    daemon_threads = True


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    root = os.path.dirname(os.path.abspath(__file__))
    os.chdir(root)

    # Loopback only. `("", port)` binds every interface, and this server hands
    # out the whole project directory with listings on -- so on any shared
    # network (an office, a hotel, a conference) it published these files to
    # every host on the subnet. There is no reason a development server for a
    # single-user editor should be reachable from another machine.
    try:
        with Server(("127.0.0.1", port), NoCacheHandler) as httpd:
            print(f"Kompartment on http://localhost:{port}/")
            print(f"  serving {root} (to this machine only)")
            print("  caching disabled, so a plain refresh picks up edits")
            print("  Ctrl+C to stop")
            httpd.serve_forever()
    except OSError as e:
        print(f"Could not listen on port {port}: {e}")
        print(f"Another server may already be running. Try: python3 serve.py {port + 1}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
