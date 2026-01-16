# Daily Wordle Solution Video Automator

**Fully automated tool that creates and uploads daily Wordle solution videos to YouTube.**

This project uses GitHub Actions to run every day:
1. Fetches today's Wordle answer from a public API
2. Automates a headless browser (Selenium + Chrome) to play the official NYT Wordle game
3. Types 1-5 random valid wrong guesses + the correct answer
4. Captures screenshots during gameplay
5. Compiles them into a short MP4 video showing the solving process + congratulations screen
6. Uploads the video to YouTube automatically

**Result**: Daily video like "Daily Wordle Solution - January 11, 2026" on your channel.

### Features
- Headless automation (no visible browser needed)
- Realistic gameplay simulation with random wrong guesses from a valid word pool
- Frame-based video creation (no real screen recording required)
- Secure YouTube upload via OAuth refresh token
- Completely free (runs on GitHub Actions free tier)

### Requirements & Technologies
- Python 3.11
- Libraries: Selenium, MoviePy 1.0.3 (pinned due to breaking changes in v2+), Google API Client
- GitHub Actions (Ubuntu runner)
- YouTube Data API v3 credentials (Desktop app OAuth client)
- Public Wordle API: https://wordle-api.litebloggingpro.workers.dev/api/today

### How It Works (Step-by-Step)
1. **Scheduled Trigger** → GitHub Actions cron job runs daily at 5:00 UTC
2. **Fetch Answer** → HTTP GET to the API → extracts `solution` (e.g., "TRIAL")
3. **Browser Automation** → Headless Chrome opens nytimes.com/games/wordle
   - Closes popups if any
   - Types 1-5 random 5-letter wrong words (from hardcoded valid list)
   - Types the correct answer
   - Captures screenshot after each submission + extra frames on congrats screen
4. **Video Creation** → MoviePy combines screenshots into MP4 (10 FPS, with delays for animation feel)
5. **Upload** → Uses stored OAuth refresh token to post video publicly to YouTube
   - Title: "Daily Wordle Solution - [Date]"
   - Category: Gaming, tags: #Wordle #NYTGames

### Setup Instructions (One-Time)
1. **Create GitHub Repository**
   - Make it public (unlimited Actions minutes)

2. **Add Files**
   - `script.py` → main automation script (copy from your working version)
   - `.github/workflows/daily-wordle.yml` → the workflow above

3. **Set Up YouTube API Credentials**
   - Go to https://console.cloud.google.com/apis/credentials
   - Create **Desktop app** OAuth client ID (not Web app!)
   - Download `client_secrets.json`
   - Run the local helper script (get_refresh_token.py) to generate refresh token:
     - Install deps: `pip install google-auth-oauthlib google-api-python-client`
     - Run: `python get_refresh_token.py` (use fixed port 8080, add http://localhost:8080/ to console redirect URIs)
   - Copy `refresh_token` from output

4. **Add GitHub Secrets**
   - Repo Settings → Secrets and variables → Actions
   - Add:
     - `YOUTUBE_CLIENT_ID`     (from client_secrets.json)
     - `YOUTUBE_CLIENT_SECRET` (from client_secrets.json)
     - `YOUTUBE_REFRESH_TOKEN` (the long string you got)

5. **Test It**
   - Go to repo → **Actions** tab
   - Select "Daily Wordle Video" → **Run workflow** (manual trigger)
   - Watch logs → verify video upload link in output

### Important Notes & Troubleshooting
- **Legal**: Scraping NYT Wordle is in a gray area — use responsibly, for personal/educational purposes only. Videos may fall under fair use.
- **Site Changes**: NYT updates Wordle UI occasionally → selectors (keyboard/buttons) may break → update CSS selectors in `script.py` if automation fails.
- **MoviePy Version**: Pinned to 1.0.3 because v2+ removed `moviepy.editor` (breaking change). Do **not** remove the version pin!
- **First Run**: May take 3-8 minutes (deps install + browser automation)
- **Debugging**: Check Actions logs for errors. Common fixes:
  - Auth issues → regenerate refresh token
  - Import errors → confirm `moviepy==1.0.3` in pip install line

---

## Social Media Sharing (Automatic)

After uploading to YouTube, the script automatically shares to:
- **Facebook** (Video to your Page)
- **Pinterest** (Video Pin)
- **Blogger** (Embedded YouTube video post)

### GitHub Secrets Required

| Secret Name | Description | How to Get |
|-------------|-------------|------------|
| `YOUTUBE_CLIENT_ID` | Google OAuth Client ID | Google Cloud Console |
| `YOUTUBE_CLIENT_SECRET` | Google OAuth Client Secret | Google Cloud Console |
| `YOUTUBE_REFRESH_TOKEN` | YouTube API Refresh Token | Run `get_refresh_token.py` |
| `FACEBOOK_ACCESS_TOKEN` | Facebook Page Access Token | Graph API Explorer with `publish_video` permission |
| `PINTEREST_ACCESS_TOKEN` | Pinterest Sandbox Access Token | Run `pinterest_oauth.py`, type `yes` for Sandbox |
| `PINTEREST_BOARD_ID` | Your Pinterest Board ID | Shown after running `pinterest_oauth.py` |
| `PINTEREST_CLIENT_ID` | Pinterest App ID | Pinterest Developer Portal |
| `PINTEREST_CLIENT_SECRET` | Pinterest App Secret | Pinterest Developer Portal |
| `BLOGGER_BLOG_ID` | Your Blogger Blog ID | From Blogger URL or API |

### Pinterest Notes (IMPORTANT!)
- Your Pinterest app is currently in **Trial mode** → must use **Sandbox API**
- `PINTEREST_USE_SANDBOX` defaults to `true` in the workflow
- To switch to Production:
  1. Go to [Pinterest Developer Portal](https://developers.pinterest.com/apps/)
  2. Click **"Request Standard Access"**
  3. Once approved, set `PINTEREST_USE_SANDBOX=false` in GitHub Secrets
  4. Regenerate tokens with `pinterest_oauth.py` (type `no` for Production)

### Local Development

1. Copy `.env.example` to `.env` (or create one with the secrets above)
2. Install: `pip install python-dotenv`
3. Run: `python script.py`

The script will:
- Upload to YouTube if `YOUTUBE_REFRESH_TOKEN` exists
- Share to Facebook if `FACEBOOK_ACCESS_TOKEN` exists
- Share to Pinterest if `PINTEREST_ACCESS_TOKEN` or `PINTEREST_REFRESH_TOKEN` exists
- Post to Blogger if YouTube upload succeeded and `BLOGGER_BLOG_ID` exists

Use `SKIP_FACEBOOK=true`, `SKIP_PINTEREST=true`, or `SKIP_BLOGGER=true` in `.env` to disable specific platforms.

---

Happy automating! If you fork/improve this, feel free to share.

Created by [Your Name / @0xSatwik] – January 2026
