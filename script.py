import os
from dotenv import load_dotenv
import base64
import time
import random
import json
from datetime import datetime, timedelta, timezone
import requests
from playwright.sync_api import sync_playwright
import io
import numpy as np
from PIL import Image

# Monkey patch for Pillow 10+ compatibility (removed ANTIALIAS)
if not hasattr(Image, 'ANTIALIAS'):
    Image.ANTIALIAS = Image.LANCZOS

from moviepy.editor import VideoFileClip, ImageClip, concatenate_videoclips, AudioFileClip
import moviepy.audio.fx.all as afx
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request
import pytumblr

# Load environment variables from .env file (for local testing)
load_dotenv()

# ============================================================================
# SOCIAL MEDIA SHARING
# ============================================================================

def get_permalink(date_obj):
    """Return the canonical Wordle answer page URL."""
    return "https://wordsolverx.com/wordle-answer-today"

def upload_to_facebook(video_path, title, permalink):
    """Upload video to Facebook Page."""
    access_token = os.environ.get('FACEBOOK_ACCESS_TOKEN', '').strip()
    page_id = "964134700097059" # Wordsolverx ID
    
    if not access_token:
        print("Facebook Access Token missing. Skipping upload.")
        return None

    print(f"Uploading to Facebook Page: {page_id}...")
    url = f"https://graph-video.facebook.com/v19.0/{page_id}/videos"
    
    payload = {
        'title': title,
        'description': f"Today's Wordle Solution! \n\nCheck out the answer and hints: {permalink}\n\n#Wordle #WordleAnswer #WordSolverX",
        'access_token': access_token
    }
    
    files = {
        'file': open(video_path, 'rb')
    }
    
    try:
        response = requests.post(url, data=payload, files=files, timeout=300)
        res_data = response.json()
        if 'id' in res_data:
            video_id = res_data['id']
            print(f"✅ Facebook upload successful! Video ID: {video_id}")
            print(f"🔗 View on Facebook: https://www.facebook.com/{page_id}/videos/{video_id}/")
            return video_id
        else:
            print(f"❌ Facebook upload failed! Response: {json.dumps(res_data, indent=2)}")
    except Exception as e:
        print(f"❌ Error uploading to Facebook: {str(e)}")
    return None

def upload_to_pinterest(video_path, title, permalink):
    """Upload Video Pin to Pinterest production API with automatic token refresh."""
    access_token = os.environ.get('PINTEREST_ACCESS_TOKEN', '').strip()
    refresh_token = os.environ.get('PINTEREST_REFRESH_TOKEN', '').strip()
    client_id = os.environ.get('PINTEREST_CLIENT_ID', '').strip()
    client_secret = os.environ.get('PINTEREST_CLIENT_SECRET', '').strip()
    board_id = os.environ.get('PINTEREST_BOARD_ID', '').strip()
    base_url = "https://api.pinterest.com"

    if not board_id:
        print("Pinterest Board ID missing. Skipping upload.")
        return None

    if access_token:
        print("Using Pinterest Access Token (Production)...")
    elif refresh_token and client_id and client_secret:
        print("Refreshing Pinterest Access Token (Production)...")
        try:
            auth_str = f"{client_id}:{client_secret}"
            encoded_auth = base64.b64encode(auth_str.encode()).decode()
            token_url = f"{base_url}/v5/oauth/token"
            headers = {
                "Authorization": f"Basic {encoded_auth}",
                "Content-Type": "application/x-www-form-urlencoded"
            }
            data = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token
            }
            res = requests.post(token_url, headers=headers, data=data, timeout=30)
            if res.status_code == 200:
                access_token = res.json().get("access_token")
                print("Pinterest Access Token refreshed.")
            else:
                print(f"Pinterest refresh failed: {res.text}")
        except Exception as e:
            print(f"Error refreshing Pinterest token: {e}")

    if not access_token:
        print("Pinterest Access Token missing. Skipping upload.")
        return None

    print("Uploading Video Pin to Pinterest (Production)...")
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    try:
        register_url = f"{base_url}/v5/media"
        res = requests.post(register_url, headers=headers, json={"media_type": "video"}, timeout=30)
        if res.status_code >= 400:
            print(f"Pinterest media registration HTTP error {res.status_code}: {res.text}")
            return None

        media_data = res.json()
        media_id = media_data.get("media_id")
        upload_url = media_data.get("upload_url")
        upload_parameters = media_data.get("upload_parameters")

        if not media_id or not upload_url:
            print(f"Pinterest media registration failed! Response: {json.dumps(media_data, indent=2)}")
            return None

        print("Uploading video file to Pinterest S3...")
        with open(video_path, 'rb') as file_obj:
            files = {'file': file_obj}
            upload_res = requests.post(upload_url, data=upload_parameters, files=files, timeout=300)

        if upload_res.status_code >= 400:
            print(f"Pinterest media upload failed with HTTP {upload_res.status_code}: {upload_res.text}")
            return None

        print("Waiting for Pinterest to process video...")
        media_ready = False
        for _ in range(12):
            time.sleep(10)
            status_res = requests.get(f"{register_url}/{media_id}", headers=headers, timeout=30)
            if status_res.status_code >= 400:
                print(f"Pinterest media status check failed with HTTP {status_res.status_code}: {status_res.text}")
                return None

            status_data = status_res.json()
            status = status_data.get("status")
            print(f"   - Media status: {status}")

            if status == "succeeded":
                media_ready = True
                break
            if status == "failed":
                print(f"Pinterest media processing failed: {status_data}")
                return None

        if not media_ready:
            print("Pinterest media processing timed out.")
            return None

        print("Creating Pin on Pinterest...")
        pin_url = f"{base_url}/v5/pins"
        pin_payload = {
            "board_id": board_id,
            "media_source": {
                "source_type": "video_id",
                "media_id": media_id,
                "cover_image_key_frame_time": 0
            },
            "title": title,
            "description": f"Wordle solution for today! Answer and hints: {permalink}",
            "link": permalink
        }

        res = requests.post(pin_url, headers=headers, json=pin_payload, timeout=30)
        if res.status_code >= 400:
            print(f"Pinterest Pin creation HTTP error {res.status_code}: {res.text}")
            return None

        pin_res = res.json()
        if 'id' in pin_res:
            pin_id = pin_res['id']
            print(f"Pinterest Pin created successfully! Pin ID: {pin_id}")
            print(f"View on Pinterest: https://www.pinterest.com/pin/{pin_id}/")
            return pin_id

        print(f"Pinterest Pin creation failed! Response: {json.dumps(pin_res, indent=2)}")
    except Exception as e:
        print(f"Error uploading to Pinterest: {str(e)}")
    return None

def post_to_blogger(video_id, title, permalink, date_str):
    """Create a Blogger post with embedded YouTube video."""
    blog_id = os.environ.get('BLOGGER_BLOG_ID', '').strip()
    refresh_token = os.environ.get('YOUTUBE_REFRESH_TOKEN', '').strip()
    client_id = os.environ.get('YOUTUBE_CLIENT_ID', '').strip()
    client_secret = os.environ.get('YOUTUBE_CLIENT_SECRET', '').strip()

    if not blog_id or not refresh_token:
        print("Blogger credentials missing. Skipping.")
        return None

    print(f"Posting to Blogger: {blog_id}...")
    
    # Get Access Token for Blogger
    try:
        token_res = requests.post('https://oauth2.googleapis.com/token', data={
            'client_id': client_id,
            'client_secret': client_secret,
            'refresh_token': refresh_token,
            'grant_type': 'refresh_token'
        })
        access_token = token_res.json().get('access_token')
        
        url = f"https://www.googleapis.com/blogger/v3/blogs/{blog_id}/posts"
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
        
        youtube_embed = f'<iframe width="560" height="315" src="https://www.youtube.com/embed/{video_id}" frameborder="0" allowfullscreen></iframe>'
        
        content = f"""
        {youtube_embed}
        <br><br>
        <h2>Today's Wordle Answer and Hints for {date_str}</h2>
        <p>Looking for today's Wordle solution? You're in the right place! Watch our step-by-step solver video to see how we cracked today's puzzle.</p>
        <p>For more Wordle answers, archive, and hints, visit our official website:</p>
        <a href="{permalink}">{permalink}</a>
        <br><br>
        <p>Don't forget to bookmark <b>WordsolverX</b> for your daily word game needs!</p>
        """
        
        payload = {
            "kind": "blogger#post",
            "title": title,
            "content": content,
            "labels": ["Wordle", "Wordle Answer", "Word Games"]
        }
        
        response = requests.post(url, headers=headers, json=payload)
        post_data = response.json()
        if 'id' in post_data:
            post_url = post_data.get('url')
            print(f"✅ Blogger post created successfully! Post ID: {post_data['id']}")
            print(f"🔗 View on Blogger: {post_url}")
            return post_data['id']
        else:
            print(f"❌ Blogger post failed! Response: {json.dumps(post_data, indent=2)}")
    except Exception as e:
        print(f"❌ Error posting to Blogger: {str(e)}")
    return None

def get_nyt_solution(date_str):
    """
    Fetch the solution from the official NYT API for the given date.
    date_str format: YYYY-MM-DD
    """
    try:
        api_url = f"https://www.nytimes.com/svc/wordle/v2/{date_str}.json"
        print(f"Fetching NYT solution from: {api_url}")
        response = requests.get(api_url, timeout=10)
        response.raise_for_status()
        data = response.json()
        solution = data.get("solution")
        if solution:
            return solution.lower()
    except Exception as e:
        print(f"Error fetching NYT solution: {e}")
    return None

def upload_to_tumblr(video_path, title, permalink):
    """Upload video to Tumblr and link the solver page."""
    consumer_key = os.environ.get('TUMBLR_CONSUMER_KEY', '').strip()
    consumer_secret = os.environ.get('TUMBLR_CONSUMER_SECRET', '').strip()
    oauth_token = os.environ.get('TUMBLR_OAUTH_TOKEN', '').strip()
    oauth_secret = os.environ.get('TUMBLR_OAUTH_SECRET', '').strip()
    blog_name = os.environ.get('TUMBLR_BLOG_NAME', '').strip()

    if not all([consumer_key, consumer_secret, oauth_token, oauth_secret, blog_name]):
        print("Tumblr credentials missing. Skipping upload.")
        return None

    try:
        import pytumblr
        client = pytumblr.TumblrRestClient(consumer_key, consumer_secret, oauth_token, oauth_secret)
        
        caption = f"Today's Wordle Solution!<br><br>Check out the answer and hints: <a href='{permalink}'>{permalink}</a><br><br>Use our advanced Wordle Solver: <a href='https://wordsolverx.com/wordle-solver'>https://wordsolverx.com/wordle-solver</a><br><br>#Wordle #WordleAnswer #WordSolverX"
        
        print(f"Uploading to Tumblr blog: {blog_name}...")
        response = client.create_video(blog_name, data=video_path, caption=caption, tags=["Wordle", "Wordle Answer", "WordSolverX"])
        
        if 'id' in response:
            print(f"✅ Tumblr upload successful! Post ID: {response['id']}")
            return response['id']
        else:
            print(f"❌ Tumblr upload failed! Response: {response}")
    except Exception as e:
        print(f"❌ Error uploading to Tumblr: {str(e)}")
    return None



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
        self.decrement_parents(self.child_word_count)
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
    # First, identify which letters are "confirmed" present (Green or Yellow)
    present_letters = set()
    for i in range(len(attempt)):
        if result[i] != '0':
            present_letters.add(attempt[i].lower())

    for i in range(len(attempt)):
        letter = attempt[i].lower()
        if result[i] == '2':
            tree.isolate(letter, i)
        elif result[i] == '1':
            tree.remove(letter, i)
            tree.check_leaves(letter)
        elif result[i] == '0':
            if letter in present_letters:
                # If letter is present elsewhere (Green/Yellow), this Gray mean it's not at THIS position
                # (and potentially limits the count, but for partial logic, position remove is safe)
                tree.remove(letter, i)
            else:
                # If letter is truly not in the word at all, remove it globally
                tree.remove(letter)


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
    """Wait for a random amount of time to simulate human behavior with more natural distribution."""
    # Use normal distribution for more realistic timing
    # Mean is the midpoint, std dev is 1/4 of the range
    mean = (min_seconds + max_seconds) / 2
    std_dev = (max_seconds - min_seconds) / 4
    
    # Generate delay using normal distribution, clamped to min/max
    delay = random.gauss(mean, std_dev)
    delay = max(min_seconds, min(max_seconds, delay))
    
    # 10% chance of a "thinking pause" - longer delay
    if random.random() < 0.1:
        thinking_pause = random.uniform(0.5, 1.5)
        delay += thinking_pause
    
    time.sleep(delay)
    return delay



def get_random_starter():
    """Return a random effective starting word."""
    starters = [
        "ADIEU", "RAISE", "STARE", "ROATE", "ARISE", 
        "TRACE", "CRATE", "SALET", "SLATE", "IRATE"
    ]
    return random.choice(starters)


def get_backup_solution(date_str):
    """
    Fetch the solution from the NYT API (primary) or backup external API.
    date_str format: YYYY-MM-DD
    """
    # Try NYT first
    nyt_solution = get_nyt_solution(date_str)
    if nyt_solution:
        return nyt_solution

    # Fallback to workers API
    try:
        api_url = f"https://wordle-api.litebloggingpro.workers.dev/api/date/{date_str}"
        print(f"Fetching backup solution from: {api_url}")
        response = requests.get(api_url, timeout=10)
        response.raise_for_status()
        data = response.json()
        solution = data.get("solution")
        if solution:
            return solution.lower()
    except Exception as e:
        print(f"Error fetching backup solution: {e}")
    return None


def human_type(page, text, delay_min=0.08, delay_max=0.25):
    """Type text with human-like delays between keystrokes."""
    for char in text:
        page.keyboard.press(char)
        time.sleep(random.uniform(delay_min, delay_max))


def dismiss_ad_interstitial(page, max_wait=15, max_retries=3):
    """
    Dismiss the NYT 'Advertisement' interstitial that appears after
    clicking the Play button. Introduced by NYT in mid-2026.

    The modal has:
      - role="dialog"
      - aria-label="Advertisement"
      - class starting with 'AdInterstitial-module_modalOverlay__'
      - a button with text 'Continue to Wordle'

    The original script's close-button selectors (button[aria-label="Close"]
    and [data-testid="close-icon"]) do NOT match this new modal, so the
    gameplay video was being recorded with the ad overlay on top and no
    letters were ever typed into the actual game.
    """
    print("Looking for NYT ad interstitial to dismiss...")
    for attempt in range(1, max_retries + 1):
        try:
            ad_dialog = page.locator(
                'div[role="dialog"][aria-label="Advertisement"]'
            )
            try:
                ad_dialog.wait_for(state="visible", timeout=max_wait * 1000)
            except Exception:
                print("  No ad interstitial found within timeout (OK).")
                return True

            print(
                f"  Attempt {attempt}: Ad interstitial detected. "
                "Clicking 'Continue to Wordle'..."
            )

            # Try several selectors in order of preference.
            clicked = False
            candidates = [
                ("role button text",
                 page.get_by_role("button", name="Continue to Wordle")),
                ("dialog button has-text",
                 page.locator(
                     'div[role="dialog"][aria-label="Advertisement"] '
                     'button:has-text("Continue to Wordle")'
                 )),
                ("text exact",
                 page.get_by_text("Continue to Wordle", exact=True).first),
            ]
            for desc, locator in candidates:
                try:
                    if locator.is_visible(timeout=1000):
                        locator.click()
                        print(f"  Clicked via: {desc}")
                        clicked = True
                        break
                except Exception:
                    continue

            if not clicked:
                # Last-resort: JS click on any element with matching text.
                page.evaluate("""
                    () => {
                        const all = Array.from(
                            document.querySelectorAll('button, a, [role="button"], div, span')
                        );
                        const el = all.find(e => {
                            const t = (e.innerText || '').trim().toLowerCase();
                            return t === 'continue to wordle' ||
                                   t.endsWith('continue to wordle');
                        });
                        if (el) { el.click(); return true; }
                        return false;
                    }
                """)
                print("  Clicked via JS fallback")
                clicked = True

            # Wait for the dialog to disappear.
            try:
                ad_dialog.wait_for(state="hidden", timeout=5000)
                print("  Ad interstitial dismissed successfully.")
                time.sleep(1.2)  # small buffer for fade-out / transition
                return True
            except Exception:
                print("  Ad still visible after click, retrying...")
                time.sleep(1.0)
        except Exception as e:
            print(f"  dismiss_ad_interstitial attempt {attempt} error: {e}")
            time.sleep(1.0)

    print("  WARNING: Could not fully dismiss ad interstitial after retries.")
    return False


def wait_for_wordle_board(page, max_wait=15):
    """
    Wait until the Wordle board (rows + keyboard) is visible.
    Returns True if the board is ready, False otherwise.
    """
    print("Waiting for Wordle board to be ready...")
    try:
        page.wait_for_selector(
            'div[aria-label^="Row"]', timeout=max_wait * 1000
        )
        rows = page.locator('div[aria-label^="Row"]').count()
        keys = page.locator('button[data-key]').count()
        print(f"  Wordle board ready: {rows} rows, {keys} keyboard keys")
        return rows > 0 and keys > 0
    except Exception as e:
        print(f"  Wordle board not found within {max_wait}s: {e}")
        return False


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
    # Launch browser with enhanced stealth settings
    browser = p.chromium.launch(
        headless=True,
        args=[
            '--disable-blink-features=AutomationControlled',
            '--disable-infobars',
            '--no-sandbox',
            '--disable-dev-shm-usage',
            '--disable-web-security',
            '--disable-features=IsolateOrigins,site-per-process',
            '--disable-site-isolation-trials',
            '--window-size=1920,1080',
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
    
    # Record start time for trimming
    video_start_time = time.time()
    start_trim = 0
    end_trim = None
    
    # Hide automation and prevent popups
    context.add_init_script("""
        // Hide automation signals
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
        window.chrome = { runtime: {} };

        // Inject CSS to prevent popups from displaying.
        // NOTE: We deliberately do NOT hide div[role="dialog"][aria-label="Advertisement"]
        // here because that ad interstitial must be DISMISSED by clicking the
        // "Continue to Wordle" button (handled in dismiss_ad_interstitial()).
        // Hiding it via CSS would leave it as an invisible overlay that
        // still intercepts keyboard focus and breaks gameplay.
        const style = document.createElement('style');
        style.textContent = `
            .Modal-module_modalOverlay__eaFhH { display: none !important; }
            div[data-testid="bottom-banner"] { display: none !important; }
            div[data-testid="toast-message"] { display: none !important; }
        `;

        // Wait for DOM to be ready
        if (document.head) {
            document.head.appendChild(style);
        } else {
            document.addEventListener('DOMContentLoaded', () => {
                document.head.appendChild(style);
            });
        }

        // Monitor for popup elements and remove them immediately.
        // NOTE: Do NOT auto-remove the "Advertisement" interstitial here
        // either — it needs to be dismissed by clicking the button.
        const observer = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                mutation.addedNodes.forEach((node) => {
                    if (node.nodeType === 1) { // Element node
                        const text = node.innerText || '';
                        if (text.includes('Create a free account') ||
                            text.includes('You have been blocked') ||
                            text.includes('suspect that you') ||
                            text.includes('tracking your stats')) {
                            console.log('Blocking popup:', text.substring(0, 50));
                            node.remove();
                        }
                    }
                });
            });
        });

        // Start observing when DOM is ready
        if (document.body) {
            observer.observe(document.body, { childList: true, subtree: true });
        } else {
            document.addEventListener('DOMContentLoaded', () => {
                observer.observe(document.body, { childList: true, subtree: true });
            });
        }
    """)
    
    page = context.new_page()
    
    print("Opening NYT Wordle...")
    page.goto('https://www.nytimes.com/games/wordle/index.html', timeout=60000)
    
    # Wait for page to load like a human would
    print("Waiting for page to load...")
    human_delay(2, 3)
    
    # Click Play button
    try:
        human_delay(1, 2)
        play_button = page.locator('button[data-testid="Play"]')
        if play_button.is_visible():
            play_button.click()
            print("Clicked Play button")
            human_delay(2, 4)
        else:
            print("Play button not visible (may have been auto-played).")
    except Exception as e:
        print(f"Play button not found: {e}")

    # ----------------------------------------------------------------------
    # NEW (mid-2026 fix): NYT now shows an "Advertisement" interstitial
    # (with a "Continue to Wordle" button) right after clicking Play.
    # The old close-button selectors do NOT match this modal, so we must
    # explicitly dismiss it before any gameplay can happen.
    # Without this fix, the bot types into the void (the ad overlay
    # intercepts focus) and the recorded video is just the ad + intro/outro.
    # ----------------------------------------------------------------------
    print("\n--- Dismiss NYT ad interstitial (post-Play) ---")
    dismiss_ad_interstitial(page, max_wait=15, max_retries=3)

    # NEW: Wait for the actual Wordle game board to be visible before
    # starting to type. This prevents typing into the void if the ad
    # wasn't dismissed, and ensures start_trim captures only real gameplay.
    print("\n--- Wait for Wordle board ---")
    board_ready = wait_for_wordle_board(page, max_wait=15)
    if not board_ready:
        print("WARNING: Wordle board not detected. Will attempt gameplay anyway.")

    # Mark the effective start of the video AFTER the ad is dismissed and
    # the board is visible. Previously this was set BEFORE clicking Play,
    # which meant the ad interstitial was included in the final video.
    start_trim = max(0, (time.time() - video_start_time) - 0.5)
    print(f"Start trim set to: {start_trim:.2f} seconds (after ad dismissal)")

    # Close any other modal if present (legacy "How to Play" / "Stats"
    # modals with a Close button — these may or may not appear).
    try:
        human_delay(0.5, 1.5)
        close_button = page.locator('button[aria-label="Close"]')
        if close_button.is_visible():
            close_button.click()
            human_delay(0.5, 1.5)
    except:
        try:
            close_button = page.locator('[data-testid="close-icon"]')
            if close_button.is_visible():
                close_button.click()
                human_delay(0.5, 1.5)
        except:
            pass
    
    def type_word(word):
        """Type a word with human-like behavior including mouse movements."""
        print(f"Typing word: {word.upper()}")
        
        # Random mouse movement before typing (simulate looking at keyboard)
        try:
            page.mouse.move(random.randint(400, 1500), random.randint(600, 900))
            time.sleep(random.uniform(0.1, 0.3))
        except:
            pass
        
        human_delay(0.5, 1.5)
        
        for i, letter in enumerate(word.lower()):
            # Find and click the key button
            try:
                key = page.locator(f'button[data-key="{letter}"]')
                if key.is_visible():
                    # Get key position and hover before clicking
                    box = key.bounding_box()
                    if box:
                        # Move to key with slight randomness
                        target_x = box['x'] + box['width'] / 2 + random.randint(-5, 5)
                        target_y = box['y'] + box['height'] / 2 + random.randint(-5, 5)
                        page.mouse.move(target_x, target_y)
                        time.sleep(random.uniform(0.05, 0.15))
                    key.click()
                else:
                    page.keyboard.press(letter)
            except:
                page.keyboard.press(letter)
            
            # Human-like delay between keystrokes
            human_delay(0.12, 0.35)
            
            # Occasional random mouse movement (simulate hand movement)
            if random.random() < 0.3:
                try:
                    page.mouse.move(random.randint(400, 1500), random.randint(400, 900))
                except:
                    pass
        
        # Move mouse away from keyboard before pressing enter
        try:
            page.mouse.move(random.randint(800, 1200), random.randint(300, 500))
            time.sleep(random.uniform(0.1, 0.2))
        except:
            pass
        
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
            # 1. Aggressive CSS injection to hide all potential popups
            try:
                page.evaluate("""
                    () => {
                        // Inject aggressive CSS rules
                        const style = document.createElement('style');
                        style.id = 'popup-blocker-aggressive';
                        style.textContent = `
                            /* NYT mid-2026 ad interstitial (after Play click) */
                            div[role="dialog"][aria-label="Advertisement"],
                            div[class*="AdInterstitial-module_modalOverlay__"],
                            div[class*="AdInterstitial-module_shortenFadeIn__"] {
                                display: none !important;
                                visibility: hidden !important;
                            }
                            /* Legacy modal classes */
                            div[role="dialog"] { display: none !important; visibility: hidden !important; }
                            .Modal-module_modalOverlay__eaFhH { display: none !important; }
                            div[data-testid="bottom-banner"] { display: none !important; }
                            div[data-testid="toast-message"] { display: none !important; }
                            /* Hide any fixed/absolute positioned high z-index elements that might be popups */
                            body > div[style*="position: fixed"][style*="z-index"] { display: none !important; }
                        `;

                        // Remove existing style if present and add new one
                        const existing = document.getElementById('popup-blocker-aggressive');
                        if (existing) existing.remove();
                        document.head.appendChild(style);
                    }
                """)
            except:
                pass
            
            # 2. Hide "Create a free account" / Login modals by text content
            targets = [
                "Create a free account",
                "Log In",
                "Subscribe",
                "You have been blocked",
                "suspect that you are a bot",
                "tracking your stats"
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
                                modal.remove();
                            } else {
                                // Fallback: Traverse up to find blocking overlay
                                el.style.display = 'none';
                                let parent = el.parentElement;
                                let count = 0;
                                while (parent && parent.tagName !== 'BODY' && count < 10) {
                                    const style = window.getComputedStyle(parent);
                                    if (style.position === 'fixed' || style.position === 'absolute' || parseInt(style.zIndex) > 50) {
                                        parent.style.display = 'none';
                                        parent.style.visibility = 'hidden';
                                    }
                                    if (parent.innerText && (parent.innerText.includes('You have been blocked') || parent.innerText.includes('Create a free account'))) {
                                         parent.style.display = 'none';
                                         parent.remove();
                                    }
                                    parent = parent.parentElement;
                                    count++;
                                }
                            }
                        }""")
                except Exception as e:
                    # Element not found or other minor error, ignore
                    pass

            # 3. Remove all dialogs and modals by role
            try:
                page.evaluate("""
                    () => {
                        document.querySelectorAll('div[role="dialog"]').forEach(el => {
                            el.style.display = 'none';
                            el.remove();
                        });
                    }
                """)
            except:
                pass

            # 4. Hide Bottom Banner specifically
            try:
                page.evaluate("document.querySelector('div[data-testid=\"bottom-banner\"]')?.remove()")
            except:
                pass
            
            # 5. Generic sweep for NYT "Toast" messages
            try:
                page.evaluate("document.querySelectorAll('div[data-testid=\"toast-message\"]').forEach(el => { el.style.display = 'none'; el.remove(); })")
            except:
                pass
            
            # 6. Remove any overlay elements
            try:
                page.evaluate("""
                    () => {
                        // Find and remove overlay elements
                        document.querySelectorAll('div').forEach(el => {
                            const style = window.getComputedStyle(el);
                            if (style.position === 'fixed' && parseInt(style.zIndex) > 100) {
                                const text = el.innerText || '';
                                if (text.includes('Create a free account') ||
                                    text.includes('You have been blocked') ||
                                    text.includes('tracking your stats')) {
                                    el.style.display = 'none';
                                    el.remove();
                                }
                            }
                        });
                    }
                """)
            except:
                pass

            # Small delay to ensure cleanup completes
            time.sleep(0.2)
        except Exception as e:
            print(f"Error cleaning UI: {e}")

    # ========================================================================
    # SOLVER LOOP
    # ========================================================================
    
    solved = False
    for round_num in range(6):
        if round_num == 0:
            # Round 1: Use a random effective starter instead of Trie default
            print("Choosing random starting word...")
            best_word = get_random_starter().lower()
        elif round_num == 5:
            # Round 6 (Last Chance): Try to get guaranteed answer from API
            print("Last attempt! Checking API for backup solution...")
            backup_word = get_backup_solution(puzzle_date)
            if backup_word:
                print(f"API provided solution: {backup_word}")
                best_word = backup_word
            else:
                print("API failed, using best solver guess.")
                best_word = solver_tree.pick_best_word()
        else:
            best_word = solver_tree.pick_best_word()
            
        possible_words = solver_tree.child_word_count
        print(f"\n=== Round {round_num + 1} ===")
        print(f"Best guess: {best_word.upper()} (from {possible_words} if applicable)")
        
        type_word(best_word)
        
        feedback = get_feedback(round_num)
        
        if feedback is None:
            print("ERROR: Could not read feedback!")
            break
        
        if feedback == "22222":
            print(f"\n🎉 SOLVED! The word was: {best_word.upper()}")
            solved = True
            
            # IMMEDIATELY clean up any popups before they appear in video
            print("Cleaning up UI to prevent popups...")
            clean_up_ui(page)
            
            # Wait for green animation to complete
            human_delay(0.5, 1.0)
            
            # Clean up again in case popups appeared during delay
            clean_up_ui(page)
            
            end_trim = time.time() - video_start_time
            print(f"End trim set to: {end_trim:.2f} seconds")
            break
        
        try:
            apply_result(best_word, feedback, solver_tree)
            remaining = max(0, solver_tree.child_word_count) # Prevent negative counts in display
            if remaining == 0:
                print("ERROR: No words remaining!")
                break
        except Exception as e:
            print(f"Error applying result: {e}")
            break
    
    # (Removed redundant if solved block)
    
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
    
    print(f"Looking for intro video at: {os.path.join(base_dir, 'intro.mp4')}")
    
    # Separate Intro from Main Content (Gameplay + Outro)
    # This allows us to apply background music ONLY to the Main Content
    
    intro_clip = None
    content_clips = []

    # 1. INTRO
    intro_video_path = os.path.join(base_dir, 'intro.mp4')
    if os.path.exists(intro_video_path):
        print("Found intro.mp4, preparing intro...")
        intro_clip = VideoFileClip(intro_video_path)
        intro_clip = intro_clip.resize(width=1920, height=1080)
    else:
        # Fallback
        intro_image_path = os.path.join(base_dir, 'intro.png')
        if os.path.exists(intro_image_path):
             print("Found intro.png (fallback), preparing intro...")
             intro_clip = ImageClip(intro_image_path).set_duration(5).set_fps(24).resize(width=1920, height=1080)

    # 2. GAMEPLAY
    # Use the end_trim timestamp if available (set when puzzle solved)
    # This gives us precise control over when to cut the video
    if end_trim and end_trim > start_trim:
        # Add small buffer (1.5s) after solve for animation completion
        video_end_time = end_trim + 1.5
        print(f"Trimming video using solve timestamp: Start={start_trim:.2f}s, End={video_end_time:.2f}s")
        gameplay_clip = gameplay_clip.subclip(start_trim, min(video_end_time, gameplay_clip.duration))
    elif start_trim > 0:
        # Fallback: cut last 4 seconds if we don't have end_trim
        video_end_time = gameplay_clip.duration - 4.0
        if video_end_time > start_trim:
            print(f"Trimming video (fallback): Start={start_trim:.2f}s, End={video_end_time:.2f}s")
            gameplay_clip = gameplay_clip.subclip(start_trim, video_end_time)
    else:
        # Last resort: just cut the last 4 seconds
        video_end_time = gameplay_clip.duration - 4.0
        if video_end_time > 0:
            print(f"Trimming video end only: End={video_end_time:.2f}s")
            gameplay_clip = gameplay_clip.subclip(0, video_end_time)
    
    content_clips.append(gameplay_clip)

    # 3. OUTRO
    outro_image_path = os.path.join(base_dir, 'outro.png')
    if os.path.exists(outro_image_path):
        print(f"Found outro.png, adding to content...")
        outro_clip = ImageClip(outro_image_path).set_duration(5).set_fps(24).resize(width=1920, height=1080)
        content_clips.append(outro_clip)

    # 4. PREPARE MAIN CONTENT (Gameplay + Outro)
    if content_clips:
        main_content_clip = concatenate_videoclips(content_clips, method="compose")
    else:
        main_content_clip = None

    # 5. ADD MUSIC TO MAIN CONTENT
    if main_content_clip:
        songs = [f for f in os.listdir(base_dir) if f.endswith('.mp3') and f.startswith('song')]
        if songs:
            selected_song = random.choice(songs)
            song_path = os.path.join(base_dir, selected_song)
            print(f"Adding background music to main content: {selected_song}")
            
            try:
                audio_clip = AudioFileClip(song_path)
                # Loop audio if shorter than content, or cut if different
                if audio_clip.duration < main_content_clip.duration:
                    final_audio = afx.audio_loop(audio_clip, duration=main_content_clip.duration)
                else:
                    final_audio = audio_clip.subclip(0, main_content_clip.duration)
                
                # Set audio to main content
                main_content_clip = main_content_clip.set_audio(final_audio)
                print("Audio track set successfully on gameplay/outro.")
            except Exception as e:
                print(f"Error processing audio: {e}")
        else:
            print("No background music found.")

    # 6. FINAL ASSEMBLY (Intro + Main Content)
    final_parts = []
    if intro_clip:
        final_parts.append(intro_clip)
    if main_content_clip:
        final_parts.append(main_content_clip)
        
    if final_parts:
        final_clip = concatenate_videoclips(final_parts, method="compose")
        print("Final video assembled.")
    else:
        final_clip = gameplay_clip # Fallback if everything failed

    final_clip.write_videofile(final_video_file, codec='libx264', audio_codec='aac', fps=24)
    final_clip.close()
    gameplay_clip.close()
    
    # Clean up webm
    if os.path.exists(recorded_video_path):
        os.remove(recorded_video_path)
except Exception as e:
    print(f"Video processing error: {e}")
    final_video_file = recorded_video_path

# ============================================================================
# UPLOAD AND SHARING
# ============================================================================

video_id = None
video_uploaded_to_youtube = False

print("\nUploading to YouTube...")

if 'YOUTUBE_REFRESH_TOKEN' not in os.environ:
    print("⚠️ YOUTUBE_REFRESH_TOKEN not found in environment variables.")
    print(f"Video saved locally as: {final_video_file}")
    print("Skipping YouTube upload.")
else:
    SCOPES = ['https://www.googleapis.com/auth/youtube.upload']
    try:
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
        video_title = f"Wordle answer today {video_date} | Today's Wordle answers and solutions & Hints wordsolverx.com"

        video_description = f"""🟩 Wordle Answer today for {video_date}

        wordle anwer today- https://wordsolverx.com/wordle-answer-today

🔗 Try our FREE Wordle Solver:
Solve ANY Wordle game in seconds with our intelligent word elimination tool!

Wordle solver (advanced) solve any 4 to 12 letter wordle- https://wordsolverx.com/wordle-solver


wordle archive and all previous answers- https://wordsolverx.com/wordle-answer-archive

Watch how to solve today's Wordle puzzle step by step! Learn the best strategy to crack the daily Wordle.

Nyt wordle answer today, today's wordle answer, 5 letter wordle answer, ai plays wordle, wordle answer, 

📅 Puzzle Date: {video_date}


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
        request = youtube.videos().insert(part='snippet,status', body=body, media_body=media)
        response = request.execute()
        video_id = response["id"]
        video_uploaded_to_youtube = True
        print(f'✅ Video uploaded: https://youtu.be/{video_id}')

    except Exception as e:
        if "uploadLimitExceeded" in str(e):
            print("\n⚠️ YouTube Upload Limit Exceeded for today.")
            print(f"Reason: {str(e)}")
            print(f"The video file '{final_video_file}' has been saved locally.")
            print("Please upload it manually later.")
        else:
            print(f"\n❌ Error uploading to YouTube: {str(e)}")
            if hasattr(e, 'content'):
                try:
                    error_details = json.loads(e.content)
                    print(f"Details: {json.dumps(error_details, indent=2)}")
                except:
                    print(f"Raw response: {e.content}")
            print(f"The video file '{final_video_file}' is saved locally.")

# --- Social Media Sharing ---
print("\n--- Starting Social Media Sharing ---")
permalink = get_permalink(ist_now)
video_title = f"Wordle {video_date} Answer | Today's Wordle Solution & Hints"

# 1. Facebook
upload_to_facebook(final_video_file, video_title, permalink)

# 2. Pinterest
upload_to_pinterest(final_video_file, video_title, permalink)

# 3. Blogger
if not video_id:
    print("⏭️ Skipping Blogger post because YouTube video_id is missing.")
else:
    post_to_blogger(video_id, video_title, permalink, video_date)

# 4. Tumblr
upload_to_tumblr(final_video_file, video_title, permalink)

# Dev.to and Hashnode publishing removed.
