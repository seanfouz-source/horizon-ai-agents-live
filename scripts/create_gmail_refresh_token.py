from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen


SCOPE = "https://www.googleapis.com/auth/gmail.send"


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    server: "OAuthCallbackServer"

    def do_GET(self) -> None:
        params = parse_qs(urlparse(self.path).query)
        self.server.authorization_code = params.get("code", [""])[0]
        self.server.authorization_error = params.get("error", [""])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            b"<html><body><h1>Gmail connected</h1><p>You can return to Codex.</p></body></html>"
        )

    def log_message(self, format: str, *args: object) -> None:
        return


class OAuthCallbackServer(HTTPServer):
    authorization_code: str = ""
    authorization_error: str = ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a Gmail OAuth refresh token for Render report emails.")
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--client-secret", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    redirect_uri = f"http://{args.host}:{args.port}/oauth2callback"
    state = secrets.token_urlsafe(24)
    authorization_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(
        {
            "client_id": args.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
            "login_hint": "sean.fouz@gmail.com",
        }
    )

    print("Opening Google authorization in Chrome.")
    print(f"Redirect URI to add in Google Cloud: {redirect_uri}")
    if args.no_browser:
        print(f"Open this URL:\n{authorization_url}")
    else:
        subprocess.run(["open", "-a", "Google Chrome", authorization_url], check=False)

    server = OAuthCallbackServer((args.host, args.port), OAuthCallbackHandler)
    server.handle_request()
    if server.authorization_error:
        print(f"Google authorization failed: {server.authorization_error}", file=sys.stderr)
        return 1
    if not server.authorization_code:
        print("Google authorization did not return a code.", file=sys.stderr)
        return 1

    token_payload = exchange_code(
        client_id=args.client_id,
        client_secret=args.client_secret,
        code=server.authorization_code,
        redirect_uri=redirect_uri,
    )
    refresh_token = token_payload.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        print("Google did not return a refresh token. Re-run with prompt=consent or remove the old app grant.", file=sys.stderr)
        return 1

    print("\nAdd these to Render as environment variables:")
    print("REPORT_EMAIL_PROVIDER=gmail")
    print("REPORT_EMAIL_FROM=sean.fouz@gmail.com")
    print("GMAIL_SENDER=sean.fouz@gmail.com")
    print(f"GMAIL_CLIENT_ID={args.client_id}")
    print("GMAIL_CLIENT_SECRET=<the same client secret you entered>")
    print(f"GMAIL_REFRESH_TOKEN={refresh_token}")
    return 0


def exchange_code(*, client_id: str, client_secret: str, code: str, redirect_uri: str) -> dict[str, object]:
    request = Request(
        "https://oauth2.googleapis.com/token",
        data=urlencode(
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
