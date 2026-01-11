import os
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
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.http import MediaFileUpload

# ============================================================================
# UNWORDLE SOLVER - Trie-based word elimination algorithm
# ============================================================================

class Node:
    """A node in the word trie for the Wordle solver."""
    def __init__(self, letters, parent=None):
        self.letters = letters
        self.child_word_count = 0
        self.children = {}
        self.parent = parent

    def add_word(self, word):
        """Add a word to the trie."""
        self.child_word_count += 1
        letter = word[0]
        new_letters = self.letters + letter
        if new_letters not in self.children:
            self.children[new_letters] = Node(new_letters, self)
        next_word = word[1:]
        if len(next_word) > 0:
            self.children[new_letters].add_word(next_word)

    def isolate(self, letter, position):
        """Keep only branches with this letter in this position (for 'correct' feedback)."""
        keys = list(self.children.keys())
        if position > 0:
            for key in keys:
                self.children[key].isolate(letter, position - 1)
        else:
            for key in keys:
                if key[-1] != letter:
                    self.children[key].delete()

    def check_leaves(self, letter):
        """Ensure all leaf words contain this letter (for 'present' feedback)."""
        if letter in self.letters:
            return
        if len(self.children) == 0:
            if letter not in self.letters:
                self.delete()
        else:
            keys = list(self.children.keys())
            for key in keys:
                self.children[key].check_leaves(letter)

    def delete(self):
        """Remove this node and update parent counts."""
        parent_node = self.parent
        if parent_node is None:
            return  # Don't delete root
        self.decrement_parents(self.child_word_count if self.child_word_count > 0 else 1)
        if self.letters in parent_node.children:
            parent_node.children.pop(self.letters)
        if len(parent_node.children) == 0 and parent_node.parent is not None:
            parent_node.delete()
    
    def decrement_parents(self, num):
        """Decrement word count in all parent nodes."""
        if self.parent:
            self.parent.child_word_count -= num
            self.parent.decrement_parents(num)

    def remove(self, letter, position=None):
        """Remove branches containing this letter (optionally at a specific position)."""
        keys = list(self.children.keys())
        for key in keys:
            if position is None:
                if key[-1] == letter:
                    self.children[key].delete()
                else:
                    self.children[key].remove(letter)
            else:
                if position != 0:
                    self.children[key].remove(letter, position - 1)
                else:
                    if key[-1] == letter:
                        self.children[key].delete()

    def pick_best_word(self):
        """Pick the best word to guess based on child word counts."""
        if len(self.children) == 0:
            return self.letters
        
        score = {}
        for child_key in self.children.keys():
            curr_child = self.children[child_key]
            count_str = str(curr_child.child_word_count)
            if count_str not in score:
                score[count_str] = [curr_child.letters]
            else:
                score[count_str].append(curr_child.letters)

        int_scores = [int(s) for s in score.keys()]
        high_score = max(int_scores)
        high_key = score[str(high_score)][0]  # Pick first in case of tie
        return self.children[high_key].pick_best_word()


def apply_result(attempt, result, tree):
    """
    Apply the Wordle feedback to prune the word tree.
    Feedback format: '0' = absent, '1' = present (wrong position), '2' = correct
    """
    for i in range(len(attempt)):
        letter = attempt[i].lower()
        if result[i] == '2':
            # Correct position - keep only branches with this letter here
            tree.isolate(letter, i)
        elif result[i] == '0':
            # Absent - remove all branches with this letter anywhere
            tree.remove(letter)
        elif result[i] == '1':
            # Present - wrong position: remove branches WITH letter at this position,
            # but ensure leaves contain this letter
            tree.remove(letter, i)
            tree.check_leaves(letter)


def build_word_tree(word_file_path):
    """Build the word trie from a word list file."""
    print(f"Loading word list from: {word_file_path}")
    root_node = Node('')
    word_count = 0
    
    try:
        with open(word_file_path, 'r', encoding='utf-8') as f:
            for line in f:
                word = line.strip().lower()
                if len(word) == 5 and word.isalpha():
                    root_node.add_word(word)
                    word_count += 1
    except Exception as e:
        print(f"Error loading word list: {e}")
        return None
    
    print(f"Loaded {word_count} valid 5-letter words")
    return root_node


# ============================================================================
# MAIN SCRIPT
# ============================================================================

# Step 1: Fetch daily Wordle metadata from API (for video title only)
api_url = 'https://wordle-api.litebloggingpro.workers.dev/api/today'
try:
    response = requests.get(api_url)
    data = response.json()
    video_date = datetime.strptime(data['date'], '%Y-%m-%d').strftime('%B %d, %Y')
    puzzle_date = data['date']
    # We do NOT use the answer - the solver figures it out!
    print(f"Puzzle Date: {puzzle_date}")
except Exception as e:
    print(f"Error fetching puzzle info: {e}")
    video_date = datetime.now().strftime('%B %d, %Y')
    puzzle_date = datetime.now().strftime('%Y-%m-%d')

# Step 2: Build the word tree using words.txt
base_dir = os.path.dirname(os.path.abspath(__file__))
word_file = os.path.join(base_dir, 'words.txt')
solver_tree = build_word_tree(word_file)

if solver_tree is None or solver_tree.child_word_count == 0:
    print("ERROR: Failed to build word tree. Cannot proceed.")
    exit(1)

# Step 3: Set up headless Selenium with anti-detection measures
options = Options()
options.add_argument('--headless=new')  # New headless mode (less detectable)
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')
options.add_argument('--disable-blink-features=AutomationControlled')  # Hide automation
options.add_argument('--disable-infobars')
options.add_argument('--disable-extensions')
options.add_argument('--disable-gpu')
options.add_argument('--window-size=1920,1080')

# Realistic user agent to avoid detection
options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

# Exclude automation switches
options.add_experimental_option('excludeSwitches', ['enable-automation'])
options.add_experimental_option('useAutomationExtension', False)

if os.environ.get('CHROME_BIN'):
    options.binary_location = os.environ['CHROME_BIN']

driver = webdriver.Chrome(options=options)

# Execute stealth scripts to hide webdriver presence
driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
    'source': '''
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5]
        });
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en']
        });
        window.chrome = { runtime: {} };
    '''
})

driver.set_window_size(1920, 1080)
print("Opening NYT Wordle...")
driver.get('https://www.nytimes.com/games/wordle/index.html')

# Wait for page load
time.sleep(5)

# Click "Play" button if present
try:
    play_button = driver.find_element(By.CSS_SELECTOR, 'button[data-testid="Play"]')
    play_button.click()
    print("Clicked Play button")
    time.sleep(3)
except Exception as e:
    print(f"Play button not found: {e}")

# Close "How to play" modal
try:
    close_button = driver.find_element(By.CSS_SELECTOR, 'button[aria-label="Close"]')
    close_button.click()
    time.sleep(1)
except:
    try:
        close_button = driver.find_element(By.CSS_SELECTOR, '[data-testid="close-icon"]')
        close_button.click()
        time.sleep(1)
    except:
        pass

game_app = driver.find_element(By.TAG_NAME, 'body')

def type_word(word):
    """Type a word into the Wordle game."""
    print(f"Typing word: {word.upper()}")
    for letter in word:
        l = letter.lower()
        try:
            key = driver.find_element(By.CSS_SELECTOR, f'button[data-key="{l}"]')
            key.click()
        except:
            try:
                key = driver.find_element(By.XPATH, f"//button[text()='{l.upper()}']")
                key.click()
            except:
                key = driver.execute_script(f'return document.querySelector(\'button[data-key="{l}"]\');')
                if key:
                    key.click()
                else:
                    game_app.send_keys(l)
        time.sleep(0.5)  # Delay between letters for visual effect
    
    game_app.send_keys(Keys.ENTER)
    time.sleep(3)  # Wait for tile flip animation


def get_feedback(row_index):
    """
    Read the feedback from the Wordle board for a specific row.
    Returns a string like '02100' where:
    - '0' = absent (gray)
    - '1' = present (yellow)  
    - '2' = correct (green)
    """
    time.sleep(2)  # Extra wait for animation
    
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
            else feedback += '?';
        }}
        return feedback;
    """
    feedback = driver.execute_script(js_script)
    print(f"Row {row_index + 1} feedback: {feedback}")
    
    if "ERROR" in str(feedback) or "?" in str(feedback):
        print(f"Warning: Could not read feedback completely: {feedback}")
        return None
    return feedback


# ============================================================================
# SOLVER LOOP
# ============================================================================

frames = []
frames.append(driver.get_screenshot_as_png())  # Capture initial state

solved = False
for round_num in range(6):
    # Get best word from solver
    best_word = solver_tree.pick_best_word()
    possible_words = solver_tree.child_word_count
    print(f"\n=== Round {round_num + 1} ===")
    print(f"Best guess: {best_word.upper()} (from {possible_words} possible words)")
    
    # Type the word
    type_word(best_word)
    
    # Capture frames for video
    time.sleep(3)
    frames.extend([driver.get_screenshot_as_png()] * 20)
    
    # Get feedback
    feedback = get_feedback(round_num)
    
    if feedback is None:
        print("ERROR: Could not read feedback from game board!")
        break
    
    if feedback == "22222":
        print(f"\n🎉 SOLVED! The word was: {best_word.upper()}")
        solved = True
        frames.extend([driver.get_screenshot_as_png()] * 30)
        break
    
    # Apply feedback to prune the tree
    try:
        apply_result(best_word, feedback, solver_tree)
        remaining = solver_tree.child_word_count
        print(f"After pruning: {remaining} words remaining")
        
        if remaining == 0:
            print("ERROR: No words remaining after pruning!")
            break
    except Exception as e:
        print(f"Error applying result: {e}")
        break

if not solved:
    print("Could not solve the puzzle in 6 attempts.")

# Capture final state
time.sleep(3)
frames.extend([driver.get_screenshot_as_png()] * 30)

driver.quit()

# ============================================================================
# VIDEO CREATION
# ============================================================================

print("\nCreating video...")
np_frames = [np.array(Image.open(io.BytesIO(frame))) for frame in frames]
clip = ImageSequenceClip(np_frames, fps=10)
video_file = f'wordle_{puzzle_date}.mp4'
clip.write_videofile(video_file, codec='libx264')

# ============================================================================
# YOUTUBE UPLOAD
# ============================================================================

print("\nUploading to YouTube...")
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
        'description': 'Automated Wordle gameplay using intelligent word elimination. #Wordle #NYTGames',
        'tags': ['Wordle', 'Daily Puzzle', 'NYT', 'Word Game', 'Puzzle Solver'],
        'categoryId': '20'
    },
    'status': {'privacyStatus': 'public'}
}

media = MediaFileUpload(video_file, mimetype='video/mp4', resumable=True)
request = youtube.videos().insert(part='snippet,status', body=body, media_body=media)
response = request.execute()
print(f'✅ Video uploaded: https://youtu.be/{response["id"]}')