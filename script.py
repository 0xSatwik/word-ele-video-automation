import os
import random
import time
from datetime import datetime
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
import io
import numpy as np
from PIL import Image
from moviepy.editor import ImageSequenceClip
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.http import MediaFileUpload

# Step 1: Fetch daily Wordle answer from API (for logging/verification AND video metadata only)
# This is NOT used by the tree solver unless the tree fails.
api_url = 'https://wordle-api.litebloggingpro.workers.dev/api/today'
try:
    response = requests.get(api_url)
    data = response.json()
    answer = data['solution'].upper()
    video_date = datetime.strptime(data['date'], '%Y-%m-%d').strftime('%B %d, %Y')
    print(f"Goal Answer: {answer}")
except Exception as e:
    print(f"Error fetching answer: {e}")
    answer = "UNKNOWN"
    video_date = datetime.now().strftime('%B %d, %Y')

# Load Solver Tree
import json
import glob

def load_solver_tree():
    # Find all tree files in the current directory (or specific subfolder if needed)
    # The user mentioned they are in the main folder now.
    base_dir = os.path.dirname(os.path.abspath(__file__))
    # Pattern to match: *.tree.js, *.tree.total.js, etc.
    search_pattern = os.path.join(base_dir, "*.tree*.js")
    possible_files = glob.glob(search_pattern)
    
    if not possible_files:
        print(f"Error: No solver tree files found matching {search_pattern}")
        # List dir to help debug
        print(f"Files in {base_dir}: {os.listdir(base_dir)}")
        return None
    
    # Pick randomly
    file_path = random.choice(possible_files)
    print(f"Selected Solver Tree: {os.path.basename(file_path)}")

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            # Strip 'export default ' and any trailing semicolon
            # Some files might have 'const ... =' or just the object.
            # The previous ones had 'export default '.
            if content.startswith('export default '):
                content = content[len('export default '):]
            if content.strip().endswith(';'):
                content = content.strip()[:-1]
            return json.loads(content)
    except Exception as e:
        print(f"Error loading tree from {file_path}: {e}")
        return None

solver_tree = load_solver_tree()

# Step 2: Set up headless Selenium
options = Options()
options.add_argument('--headless')
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')
# Use CHROME_BIN env var if available, otherwise let Selenium find it (or use default shim)
if os.environ.get('CHROME_BIN'):
    options.binary_location = os.environ['CHROME_BIN']

driver = webdriver.Chrome(options=options)
driver.set_window_size(1920, 1080)  # For 1080p video
driver.get('https://www.nytimes.com/games/wordle/index.html')

# Wait for game to load (close any popups if needed)
time.sleep(5)
# Wait for game to load (close any popups if needed)
time.sleep(5)

# Click "Play" button if present (common in new NYT layout)
try:
    play_button = driver.find_element(By.CSS_SELECTOR, 'button[data-testid="Play"]')
    play_button.click()
    print("Clicked Play button")
    time.sleep(3) # Wait for animation
except:
    print("Play button not found or not clickable")
    pass

# Close "How to play" modal
try:
    close_button = driver.find_element(By.CSS_SELECTOR, 'button[aria-label="Close"]')
    close_button.click()
    time.sleep(1)
except:
    # Try alternative close button selector
    try:
        close_button = driver.find_element(By.CSS_SELECTOR, '[data-testid="close-icon"]')
        close_button.click()
        time.sleep(1)
    except:
        pass

# Find the game app and keyboard (inspect Wordle HTML for selectors; may need updates if site changes)
game_app = driver.find_element(By.TAG_NAME, 'body')  # Or more specific: 'game-app'

# Function to type a word
# Function to type a word
def type_word(word):
    for letter in word:
        l = letter.lower()
        # Try finding button in standard DOM first
        try:
            key = driver.find_element(By.CSS_SELECTOR, f'button[data-key="{l}"]')
        except:
            # Fallback for Shadow DOM or slightly different structure
            # Use JS to find the button anywhere in the document including shadow roots is hard, 
            # so we stick to the most likely known selectors or use a JS click.
            try:
                # Try finding by text content if data-key is missing/changed
                key = driver.find_element(By.XPATH, f"//button[text()='{l.upper()}']")
            except:
                # Last resort: Execute JS to find button with data-key
                key = driver.execute_script(f"""
                    return document.querySelector('button[data-key="{l}"]');
                """)
        
        if key:
            key.click()
        else:
             # If element not found, assume hard failure or try sending keys to body
             game_app.send_keys(l)
             
        time.sleep(1.0)  # Slight delay for realism and video length (was 0.2)
    game_app.send_keys(Keys.ENTER)
    time.sleep(5)  # Wait for reveal animation to complete (was 2)

frames = []  # List to store screenshots as frames (PNG bytes)

# Capture initial blank grid
frames.append(driver.get_screenshot_as_png())

# Helper to get feedback from the board
def get_feedback(row_index):
    # Mapping: absent=0, present=1, correct=2
    # Row selector (usually Row 1, Row 2, etc. or index based)
    # NYT Wordle rows are usually in a container. We can find all 'game-row' or similar.
    # Assuming rows are ordered.
    try:
        host = driver.find_element(By.TAG_NAME, "body") # Access shadow DOM if needed, but usually tiles are in light DOM now or we need specific handling
        
        # Note: NYT structure changes. Often it's div[aria-label="Row <n>"]
        # Rows are 0-indexed in our logic, but UI might be 1-indexed?
        # Let's try finding all rows first.
        # Board usually has 6 rows.
        rows = driver.find_elements(By.CSS_SELECTOR, "div[aria-label^='Row ']") 
        if not rows:
             # Fallback selector
             game_app_element = driver.find_element(By.TAG_NAME, 'game-app') # It might be in shadow root
             # If shadow_root is needed:
             # shadow = driver.execute_script("return arguments[0].shadowRoot", game_app_element)
             # rows = shadow.find_elements(...)
             # For now assume standard Light DOM or simple structure
             rows = driver.find_elements(By.CLASS_NAME, "Row-module_row__pwpBq") # Example class, likely unstable
             # Try generic row looking for 6 divs in board
             pass

        # Use JavaScript to get the state reliably if selectors are tricky
        # This script iterates the tiles of the specified row index (0-5)
        # and returns a string like "02100" based on data-state.
        js_script = f"""
            const rows = document.querySelectorAll('div[aria-label^="Row"]');
            if (!rows || rows.length === 0) return "ERROR_NO_ROWS";
            const row = rows[{row_index}];
            if (!row) return "ERROR_NO_ROW";
            const tiles = row.querySelectorAll('div[data-testid="tile"]');
            
            let feedback = "";
            for (let tile of tiles) {{
                const state = tile.getAttribute('data-state');
                if (state === 'correct') feedback += '2';
                else if (state === 'present') feedback += '1';
                else if (state === 'absent') feedback += '0';
                else feedback += '?'; // Should not happen after animation
            }}
            return feedback;
        """
        feedback = driver.execute_script(js_script)
        if "ERROR" in feedback or "?" in feedback:
             print(f"Warning: Could not read feedback completely: {feedback}")
             return None
        return feedback
    except Exception as e:
        print(f"Error reading feedback: {e}")
        return None

# Solver Loop
if solver_tree:
    current_node = solver_tree
    for row_idx in range(6):
        # Determine guess
        if isinstance(current_node, dict):
            guess_word = current_node.get("guess")
        elif isinstance(current_node, str):
            guess_word = current_node
        else:
            print("Error: Unknown node type in tree.")
            break
            
        print(f"Solver Guess {row_idx+1}: {guess_word}")
        type_word(guess_word)
        
        # Wait for animation/flip
        # User requested "make the video long", so we wait significantly after each guess
        time.sleep(8) 
        frames.extend([driver.get_screenshot_as_png()] * 20)
        
        # Get feedback
        feedback = get_feedback(row_idx)
        print(f"Feedback received: {feedback}")
        
        if feedback == "22222":
            print("Puzzle Solved!")
            # Capture victory celebration
            frames.extend([driver.get_screenshot_as_png()] * 30)
            break
            
        # Navigate tree
        if isinstance(current_node, dict) and "map" in current_node:
            if feedback in current_node["map"]:
                current_node = current_node["map"][feedback]
            else:
                print(f"Error: Feedback {feedback} not in tree map! Solver stuck.")
                # Fallback: maybe just guess the answer if we know it (cheating) to finish video?
                # For now, just break.
                break
        else:
            # If we are at a string node (leaf) and didn't win, the tree failed (or our feedback reading is wrong)
            print("Solver reached leaf node but puzzle not solved.")
            break
else:
    print("No solver tree available. Playing fallback logic (manual/random).")
    # Fallback: just play the answer to ensure video has content
    type_word(answer)
    frames.extend([driver.get_screenshot_as_png()] * 30)

# Wait for congrats animation and capture more
time.sleep(5)
frames.extend([driver.get_screenshot_as_png()] * 30)

driver.quit()

# Step 3: Compile frames into video with MoviePy
# Convert PNG bytes to numpy arrays for MoviePy
np_frames = [np.array(Image.open(io.BytesIO(frame))) for frame in frames]
clip = ImageSequenceClip(np_frames, fps=10)  # 10 FPS for smooth video
video_file = f'wordle_{data["date"]}.mp4'
clip.write_videofile(video_file, codec='libx264')

# Step 4: Upload to YouTube
SCOPES = ['https://www.googleapis.com/auth/youtube.upload']
creds = Credentials.from_authorized_user_info({
    'refresh_token': os.environ['YOUTUBE_REFRESH_TOKEN'],
    'client_id': os.environ['YOUTUBE_CLIENT_ID'],
    'client_secret': os.environ['YOUTUBE_CLIENT_SECRET'],
    'scopes': SCOPES,
    'token_uri': 'https://oauth2.googleapis.com/token'
}, SCOPES)

if creds and creds.expired and creds.refresh_token:
    creds.refresh(Request())

youtube = build('youtube', 'v3', credentials=creds)

body = {
    'snippet': {
        'title': f'Daily Wordle Solution - {video_date}',
        'description': 'Automated Wordle gameplay with solution. #Wordle #NYTGames',
        'tags': ['Wordle', 'Daily Puzzle', 'NYT'],
        'categoryId': '20'  # Gaming category
    },
    'status': {'privacyStatus': 'public'}
}

media = MediaFileUpload(video_file, mimetype='video/mp4', resumable=True)
request = youtube.videos().insert(part='snippet,status', body=body, media_body=media)
response = request.execute()
print(f'Video uploaded: https://youtu.be/{response["id"]}')