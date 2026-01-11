import os
import time
import random
from datetime import datetime, timedelta, timezone
import requests
from playwright.sync_api import sync_playwright
import io
import numpy as np
from PIL import Image
# Monkey patch for Pillow 10+ compatibility (removed ANTIALIAS)
if not hasattr(Image, 'ANTIALIAS'):
    Image.ANTIALIAS = Image.LANCZOS
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

# Step 1: Calculate Date (Strictly IST for Indian Audience)
# We want the video to represent the "Day" in India.
# If running at 18:32 UTC (00:02 IST), we want the NEW day.
# If running manually at 23:00 IST, we want the CURRENT day.
# UTC + 5:30 always gives the correct "Local Date" in India.

utc_now = datetime.now(timezone.utc)
ist_now = utc_now + timedelta(hours=5, minutes=30)

video_date = ist_now.strftime('%B %d, %Y')  # e.g., "January 12, 2026"
video_date_short = ist_now.strftime('%d %b %Y')  # e.g., "12 Jan 2026"
puzzle_date = ist_now.strftime('%Y-%m-%d')  # 2026-01-12

print(f"UTC Time: {utc_now}")
print(f"IST Time: {ist_now}")
print(f"Puzzle Date (Target): {puzzle_date}")
print(f"Formatted Date: {video_date}")

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
    
    # Create context with video recording enabled AND Indian Location Simulation
    # This ensures we get the "new day" puzzle if running after midnight IST
    context = browser.new_context(
        viewport={'width': 1920, 'height': 1080},
        record_video_dir='.',
        record_video_size={'width': 1920, 'height': 1080},
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        timezone_id='Asia/Kolkata',
        locale='en-IN',
        geolocation={'latitude': 28.6139, 'longitude': 77.2090}, # New Delhi
        permissions=['geolocation']
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
    
    def clean_up_ui(page):
        """Hide specific popups and overlays using targeted locators."""
        print("Cleaning up UI (hiding popups)...")
        try:
            # 1. Hide "Create a free account" / Login modals
            # We look for the specific text, then find the closest modal/dialog wrapper to hide
            targets = [
                "Create a free account",
                "Log In",
                "Subscribe",
                "You have been blocked",
                "suspect that you are a bot"
            ]
            
            for text in targets:
                try:
                    # Find element containing text
                    element = page.get_by_text(text, exact=False).first
                    if element.is_visible():
                        print(f"Found blocking element with text: '{text}'")
                        # Evaluate JS to hide the closest parent dialog or absolute overlay
                        element.evaluate("""el => {
                            const modal = el.closest('div[role="dialog"]') || el.closest('.Modal-module_modalOverlay__eaFhH') || el.closest('div[class*="modal"]');
                            if (modal) {
                                modal.style.display = 'none';
                                modal.style.visibility = 'hidden';
                            } else {
                                // Fallback: hide the element itself and its immediate parents if they are overlays
                                el.style.display = 'none';
                                let parent = el.parentElement;
                                while (parent && (window.getComputedStyle(parent).position === 'absolute' || window.getComputedStyle(parent).position === 'fixed')) {
                                    parent.style.display = 'none';
                                    parent = parent.parentElement;
                                }
                            }
                        }""")
                except Exception as e:
                    # Element not found or other minor error, ignore
                    pass

            # 2. Hide Bottom Banner specifically
            try:
                page.evaluate("document.querySelector('div[data-testid=\"bottom-banner\"]')?.remove()")
            except:
                pass
            
            # 3. Generic sweep for NYT "Toast" messages
            try:
                page.evaluate("document.querySelectorAll('div[data-testid=\"toast-message\"]').forEach(el => el.style.display = 'none')")
            except:
                pass

            human_delay(0.5, 1.0)
        except Exception as e:
            print(f"Error cleaning UI: {e}")

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
            clean_up_ui(page) # Hide popups so we can see the board clearly
            human_delay(4, 6) # Longer delay to show the winning board
            break
        
        try:
            apply_result(best_word, feedback, solver_tree)
            remaining = max(0, solver_tree.child_word_count) # Prevent negative counts in display
            print(f"After pruning: {remaining} words remaining")
            
            if remaining == 0:
                print("ERROR: No words remaining!")
                break
        except Exception as e:
            print(f"Error applying result: {e}")
            break
    
    if not solved:
        print("Could not solve in 6 attempts.")
        clean_up_ui(page)
    
    # Final delay to capture end state
    human_delay(2, 3)
    
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
    
    # Create intro from image (5 seconds as requested)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    intro_image_path = os.path.join(base_dir, 'intro.png')
    
    print(f"Looking for intro image at: {intro_image_path}")
    if os.path.exists(intro_image_path):
        # Create ImageClip
        intro_clip = ImageClip(intro_image_path).set_duration(5).set_fps(24)
        # Resize to match gameplay video exactly
        intro_clip = intro_clip.resize(width=1920, height=1080)
        
        # Combine intro + gameplay
        final_clip = concatenate_videoclips([intro_clip, gameplay_clip], method="compose")
        print("Added intro to video successfully")
    else:
        print("WARNING: Intro image not found! Using gameplay only.")
        print(f"Current Directory Contents: {os.listdir(base_dir)}")
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



📅 Puzzle Date: {video_date}

⭐ Like & Subscribe for daily Wordle solutions!

#Wordle #WordleAnswer #Wordle{puzzle_date.replace('-', '')} #TodaysWordle #WordleSolution #WordleHints #NYTWordle #DailyWordle #WordGame #PuzzleGames
"""

# Read and append default description if it exists
description_file_path = os.path.join(base_dir, 'description.txt')
if os.path.exists(description_file_path):
    try:
        with open(description_file_path, 'r', encoding='utf-8') as f:
            default_description = f.read()
            video_description += f"\n\n{default_description}"
        print("Appended default description from description.txt")
    except Exception as e:
        print(f"Warning: Could not read description.txt: {e}")

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
try:
    request = youtube.videos().insert(part='snippet,status', body=body, media_body=media)
    response = request.execute()
    print(f'✅ Video uploaded: https://youtu.be/{response["id"]}')
except Exception as e:
    if "uploadLimitExceeded" in str(e):
        print("\n⚠️ YouTube Upload Limit Exceeded for today.")
        print(f"The video file '{final_video_file}' has been saved locally.")
        print("Please upload it manually later.")
    else:
        print(f"\n❌ Error uploading to YouTube: {e}")
        print(f"The video file '{final_video_file}' is saved locally.")
