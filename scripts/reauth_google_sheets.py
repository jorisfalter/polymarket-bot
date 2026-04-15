"""
Re-authenticate Google Sheets OAuth.

Run this locally when the token expires:
  python3 scripts/reauth_google_sheets.py

It will open a browser, ask you to authorize, then save the new
credentials to google-oauth-creds.json which you upload to the server.
"""
import json
import os
import sys

try:
    from google_auth_oauthlib.flow import InstalledAppFlow
except ImportError:
    print("Installing google-auth-oauthlib...")
    os.system(f"{sys.executable} -m pip install google-auth-oauthlib")
    from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

CREDS_FILE = os.path.join(os.path.dirname(__file__), "..", "google-oauth-creds.json")
CLIENT_SECRETS_FILE = os.path.join(os.path.dirname(__file__), "google-client-secrets.json")


def main():
    # Read existing creds to extract client_id and client_secret
    if os.path.exists(CREDS_FILE):
        with open(CREDS_FILE) as f:
            existing = json.load(f)
        client_id = existing.get("client_id")
        client_secret = existing.get("client_secret")
        if not client_id or not client_secret:
            print("ERROR: google-oauth-creds.json is missing client_id or client_secret")
            sys.exit(1)
    else:
        print(f"ERROR: {CREDS_FILE} not found")
        sys.exit(1)

    # Build client secrets format for the flow
    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)

    # Use fixed port 8080 — add http://localhost:8080/ to Google Console if needed
    # Or use OOB flow manually
    import webbrowser
    from google_auth_oauthlib.flow import InstalledAppFlow as _Flow

    flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
    auth_url, _ = flow.authorization_url(prompt="consent")
    print("Open this URL in your browser:")
    print()
    print(auth_url)
    print()
    webbrowser.open(auth_url)
    code = input("Paste the authorization code here: ").strip()
    flow.fetch_token(code=code)
    creds = flow.credentials

    # Save new credentials in the same format as before
    new_creds = {
        "type": "authorized_user",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": creds.refresh_token,
    }

    with open(CREDS_FILE, "w") as f:
        json.dump(new_creds, f, indent=2)

    print(f"\nNew credentials saved to: {CREDS_FILE}")
    print("\nNow upload to server:")
    print(f"  scp {os.path.abspath(CREDS_FILE)} root@100.102.30.80:/opt/polymarket-insider/google-oauth-creds.json")
    print("\nThen restart the container:")
    print("  ssh root@100.102.30.80 'cd /opt/polymarket-insider && docker compose restart'")


if __name__ == "__main__":
    main()
