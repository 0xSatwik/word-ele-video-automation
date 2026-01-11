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

# Step 1: Fetch daily Wordle answer from API
api_url = 'https://wordle-api.litebloggingpro.workers.dev/api/today'
response = requests.get(api_url)
data = response.json()
answer = data['solution'].upper()
video_date = datetime.strptime(data['date'], '%Y-%m-%d').strftime('%B %d, %Y')

# List of 15 valid 5-letter words for random wrong guesses (from Wordle guess list)
valid_words = ['AAHED', 'AALII', 'AARGH', 'AARTI', 'ABACA', 'ABACI', 'ABACS', 'ABAFT', 'ABAKA', 'ABAMP', 'ABAND', 'ABASH', 'ABASK', 'ABAYA', 'ABBAS']

# Select 1-5 unique wrong words (exclude answer if in list)
available_wrongs = [w for w in valid_words if w != answer]
num_wrong = random.randint(1, 5)  # Up to 5 wrong to fit Wordle's 6-guess limit
wrong_words = random.sample(available_wrongs, min(num_wrong, len(available_wrongs)))

# Step 2: Set up headless Selenium
options = Options()
options.add_argument('--headless')
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')
driver = webdriver.Chrome(options=options)
driver.set_window_size(1920, 1080)  # For 1080p video
driver.get('https://www.nytimes.com/games/wordle/index.html')

# Wait for game to load (close any popups if needed)
time.sleep(5)
try:
    close_button = driver.find_element(By.CSS_SELECTOR, '[data-testid="close-icon"]')
    close_button.click()
except:
    pass

# Find the game app and keyboard (inspect Wordle HTML for selectors; may need updates if site changes)
game_app = driver.find_element(By.TAG_NAME, 'body')  # Or more specific: 'game-app'

# Function to type a word
def type_word(word):
    for letter in word:
        key = driver.find_element(By.CSS_SELECTOR, f'button[data-key="{letter.lower()}"]')
        key.click()
        time.sleep(0.2)  # Slight delay for realism
    game_app.send_keys(Keys.ENTER)
    time.sleep(2)  # For animation to complete

frames = []  # List to store screenshots as frames (PNG bytes)

# Capture initial blank grid
frames.append(driver.get_screenshot_as_png())

# Type wrong words
for wrong in wrong_words:
    type_word(wrong)
    frames.extend([driver.get_screenshot_as_png()] * 15)  # Duplicate frames for slowdown (adjust for FPS)

# Type correct answer
type_word(answer)
frames.extend([driver.get_screenshot_as_png()] * 30)  # Longer on congrats screen

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