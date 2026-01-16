# get_refresh_token.py
import os
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials

# === CHANGE THESE TWO LINES ONLY ===
CLIENT_SECRETS_FILE = "client_secrets.json"          # path to your downloaded JSON
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/blogger"
]

def main():
    flow = InstalledAppFlow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES
    )

    # Option A: Easiest - opens browser automatically (recommended)
    credentials = flow.run_local_server(port=0)   # port=0 picks random free port

    # Option B: If you prefer copy-paste in terminal (no browser window opens)
    # credentials = flow.run_console()

    # Print the refresh token
    if credentials.refresh_token:
        print("\n" + "="*60)
        print("YOUR REFRESH TOKEN (copy this!):")
        print(credentials.refresh_token)
        print("="*60 + "\n")
        
        # Optional: also save the full credentials as JSON (recommended)
        token_file = "token.json"
        with open(token_file, "w") as f:
            f.write(credentials.to_json())
        print(f"Full credentials also saved to: {os.path.abspath(token_file)}")
    else:
        print("No refresh token received. Something went wrong.")

if __name__ == "__main__":
    main()