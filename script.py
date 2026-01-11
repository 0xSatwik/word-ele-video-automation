import os
import time
import random
from datetime import datetime, timedelta
import requests
from playwright.sync_api import sync_playwright
import io
import numpy as np
from PIL import Image
from moviepy.editor import VideoFileClip, ImageClip, concatenate_videoclips
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
        """Keep only branches with this letter in this position."""
        keys = list(self.children.keys())
        if position > 0:
            for key in keys:
                self.children[key].isolate(letter, position - 1)
        else:
            for key in keys:
                if key[-1] != letter:
                    self.children[key].delete()

    def check_leaves(self, letter):
        """Ensure all leaf words contain this letter."""
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
            return
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
        """Remove branches containing this letter."""
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
        """Pick the best word to guess."""
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
        high_key = score[str(high_score)][0]
        return self.children[high_key].pick_best_word()


def apply_result(attempt, result, tree):
    """Apply feedback to prune the word tree."""
    for i in range(len(attempt)):
        letter = attempt[i].lower()
        if result[i] == '2':
            tree.isolate(letter, i)
        elif result[i] == '0':
            tree.remove(letter)
        elif result[i] == '1':
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


def human_delay(min_seconds=1, max_seconds=3):
    """Wait for a random amount of time to simulate human behavior."""
    delay = random.uniform(min_seconds, max_seconds)
    time.sleep(delay)
    return delay


def human_type(page, text, delay_min=0.08, delay_max=0.25):
    """Type text with human-like delays between keystrokes."""
    for char in text:
        page.keyboard.press(char)
        time.sleep(random.uniform(delay_min, delay_max))


# ============================================================================
# MAIN SCRIPT
# ============================================================================

# Step 1: Fetch daily Wordle metadata from API
api_url = 'https://wordle-api.litebloggingpro.workers.dev/api/today'
try:
    response = requests.get(api_url)
    data = response.json()
    # Parse and format date properly
    puzzle_date_obj = datetime.strptime(data['date'], '%Y-%m-%d')
    video_date = puzzle_date_obj.strftime('%B %d, %Y')  # e.g., "January 12, 2026"
    video_date_short = puzzle_date_obj.strftime('%d %b %Y')  # e.g., "12 Jan 2026"
    puzzle_date = data['date']
    puzzle_number = data.get('days_since_launch', '')
    print(f"Puzzle Date: {puzzle_date}")
    print(f"Formatted Date: {video_date}")
except Exception as e:
    print(f"Error fetching puzzle info: {e}")
    puzzle_date_obj = datetime.now()
    video_date = puzzle_date_obj.strftime('%B %d, %Y')
    video_date_short = puzzle_date_obj.strftime('%d %b %Y')
    puzzle_date = puzzle_date_obj.strftime('%Y-%m-%d')
    puzzle_number = ''

# Step 2: Build the word tree
base_dir = os.path.dirname(os.path.abspath(__file__))
word_file = os.path.join(base_dir, 'words.txt')
solver_tree = build_word_tree(word_file)

if solver_tree is None or solver_tree.child_word_count == 0:
    print("ERROR: Failed to build word tree. Cannot proceed.")
    exit(1)

# Step 3: Launch Playwright with video recording
video_file = f'wordle_{puzzle_date}.webm'
final_video_file = f'wordle_{puzzle_date}.mp4'

print("Launching browser with Playwright...")

with sync_playwright() as p:
    # Launch browser with stealth settings
    browser = p.chromium.launch(
        headless=True,
        args=[
            '--disable-blink-features=AutomationControlled',
            '--disable-infobars',
            '--no-sandbox',
            '--disable-dev-shm-usage',
        ]
    )
    
    # Create context with video recording enabled
    context = browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        record_video_dir='.',
        record_video_size={'width': 1920, 'height': 1080},
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    )
    
    # Hide automation
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
        window.chrome = { runtime: {} };
    """)
    
    page = context.new_page()
    
    print("Opening NYT Wordle...")
    page.goto('https://www.nytimes.com/games/wordle/index.html')
    
    # Wait for page to load like a human would
    print("Waiting for page to load...")
    human_delay(5, 8)
    
    # Click Play button
    try:
        human_delay(1, 2)
        play_button = page.locator('button[data-testid="Play"]')
        if play_button.is_visible():
            play_button.click()
            print("Clicked Play button")
            human_delay(2, 4)
    except Exception as e:
        print(f"Play button not found: {e}")
    
    # Close modal if present
    try:
        human_delay(1, 2)
        close_button = page.locator('button[aria-label="Close"]')
        if close_button.is_visible():
            close_button.click()
            human_delay(1, 2)
    except:
        try:
            close_button = page.locator('[data-testid="close-icon"]')
            if close_button.is_visible():
                close_button.click()
                human_delay(1, 2)
        except:
            pass
    
    def type_word(word):
        """Type a word with human-like behavior."""
        print(f"Typing word: {word.upper()}")
        human_delay(0.5, 1.5)
        
        for letter in word.lower():
            # Find and click the key button
            try:
                key = page.locator(f'button[data-key="{letter}"]')
                if key.is_visible():
                    key.click()
                else:
                    page.keyboard.press(letter)
            except:
                page.keyboard.press(letter)
            
            # Human-like delay between keystrokes
            human_delay(0.12, 0.35)
        
        # Pause before pressing enter
        human_delay(0.5, 1.0)
        page.keyboard.press('Enter')
        
        # Wait for tile animation
        human_delay(4, 6)
    
    def get_feedback(row_index):
        """Read feedback from the board."""
        human_delay(2, 3)
        
        try:
            feedback = page.evaluate(f"""
                () => {{
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
                }}
            """)
            print(f"Row {row_index + 1} feedback: {feedback}")
            
            if "ERROR" in str(feedback) or "?" in str(feedback):
                return None
            return feedback
        except Exception as e:
            print(f"Error reading feedback: {e}")
            return None
    
    # ========================================================================
    # SOLVER LOOP
    # ========================================================================
    
    solved = False
    for round_num in range(6):
        best_word = solver_tree.pick_best_word()
        possible_words = solver_tree.child_word_count
        print(f"\n=== Round {round_num + 1} ===")
        print(f"Best guess: {best_word.upper()} (from {possible_words} possible words)")
        
        type_word(best_word)
        
        feedback = get_feedback(round_num)
        
        if feedback is None:
            print("ERROR: Could not read feedback!")
            break
        
        if feedback == "22222":
            print(f"\n🎉 SOLVED! The word was: {best_word.upper()}")
            solved = True
            human_delay(3, 5)
            break
        
        try:
            apply_result(best_word, feedback, solver_tree)
            remaining = solver_tree.child_word_count
            print(f"After pruning: {remaining} words remaining")
            
            if remaining == 0:
                print("ERROR: No words remaining!")
                break
        except Exception as e:
            print(f"Error applying result: {e}")
            break
    
    if not solved:
        print("Could not solve in 6 attempts.")
    
    # Final delay to capture end state
    human_delay(3, 5)
    
    # Close browser and save video
    recorded_video_path = page.video.path()
    context.close()
    browser.close()
    
    print(f"Video recorded to: {recorded_video_path}")

# Convert webm to mp4 and add intro
print("Processing video with intro...")
try:
    # Load the gameplay video
    gameplay_clip = VideoFileClip(recorded_video_path)
    
    # Create intro from image (3 seconds)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    intro_image_path = os.path.join(base_dir, 'intro.png')
    
    if os.path.exists(intro_image_path):
        intro_clip = ImageClip(intro_image_path).set_duration(4).resize(gameplay_clip.size)
        # Combine intro + gameplay
        final_clip = concatenate_videoclips([intro_clip, gameplay_clip], method="compose")
        print("Added intro to video")
    else:
        print("Intro image not found, using gameplay only")
        final_clip = gameplay_clip
    
    final_clip.write_videofile(final_video_file, codec='libx264', audio=False, fps=24)
    final_clip.close()
    gameplay_clip.close()
    
    # Clean up webm
    if os.path.exists(recorded_video_path):
        os.remove(recorded_video_path)
except Exception as e:
    print(f"Video processing error: {e}")
    final_video_file = recorded_video_path

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

# SEO-optimized title and description
video_title = f"Wordle {video_date} Answer | Today's Wordle Solution & Hints"

video_description = f"""🟩 Wordle Answer for {video_date}

Watch how to solve today's Wordle puzzle step by step! Learn the best strategy to crack the daily Wordle.

🔗 Try our FREE Wordle Solver: https://WordSolverX.com/wordle-solver
Solve ANY Wordle game in seconds with our intelligent word elimination tool!

📅 Puzzle Date: {video_date}

⭐ Like & Subscribe for daily Wordle solutions!

#Wordle #WordleAnswer #Wordle{puzzle_date.replace('-', '')} #TodaysWordle #WordleSolution #WordleHints #NYTWordle #DailyWordle #WordGame #PuzzleGames
"""

body = {
    'snippet': {
        'title': video_title,
        'description': video_description,
        'tags': [
            'Wordle', 'Wordle Answer', 'Wordle Today', f'Wordle {video_date_short}',
            'Wordle Solution', 'Wordle Hints', 'Daily Wordle', 'NYT Wordle',
            'Word Game', 'Puzzle', 'Wordle Solver', 'How to Solve Wordle',
            'Wordle Strategy', 'Wordle Tips', f'Wordle {puzzle_date}'
        ],
        'categoryId': '20'
    },
    'status': {'privacyStatus': 'public'}
}

media = MediaFileUpload(final_video_file, mimetype='video/mp4', resumable=True)
request = youtube.videos().insert(part='snippet,status', body=body, media_body=media)
response = request.execute()
print(f'✅ Video uploaded: https://youtu.be/{response["id"]}')