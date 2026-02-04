"""
NotebookLM Batch Downloader - Downloads audio/video from NotebookLM notebooks.
Two-step process: 1) List notebooks with titles, 2) Scan selected for media
"""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Callable
import re
import subprocess
import time
import json
import os
from datetime import datetime
import requests
from playwright.sync_api import sync_playwright


USER_DATA_DIR = Path.home() / ".notebooklm_chrome_profile"
DEBUGGING_PORT = 9222

# UUID pattern for notebook IDs
UUID_PATTERN = r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}'

# Cache configuration
CACHE_FILE_NAME = "notebooks_cache.json"
CACHE_VERSION = 1


@dataclass
class NotebookInfo:
    project_id: str
    title: str
    emoji: str
    audio_artifacts: List[dict]
    video_artifacts: List[dict]


@dataclass
class DownloadProgress:
    current: int
    total: int
    current_file: str
    status: str


def find_chrome_path() -> Optional[str]:
    possible_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "Application" / "chrome.exe",
    ]
    for path in possible_paths:
        if Path(path).exists():
            return str(path)
    return None


def is_chrome_running() -> bool:
    try:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(('localhost', DEBUGGING_PORT))
        sock.close()
        return result == 0
    except:
        return False


def launch_chrome():
    if is_chrome_running():
        return True

    chrome_path = find_chrome_path()
    if not chrome_path:
        return False

    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

    subprocess.Popen([
        chrome_path,
        f"--remote-debugging-port={DEBUGGING_PORT}",
        f"--user-data-dir={USER_DATA_DIR}",
        "--no-first-run",
        "--no-default-browser-check",
        "https://notebooklm.google.com/"
    ])

    for _ in range(30):
        if is_chrome_running():
            return True
        time.sleep(1)

    return False


def connect_to_chrome():
    pw = sync_playwright().start()
    try:
        browser = pw.chromium.connect_over_cdp(f"http://localhost:{DEBUGGING_PORT}")
        return pw, browser
    except Exception as e:
        try:
            pw.stop()
        except:
            pass
        raise e


def safe_disconnect(pw, browser):
    time.sleep(0.5)
    try:
        browser.close()
    except:
        pass
    time.sleep(0.2)
    try:
        pw.stop()
    except:
        pass


class NotebookLMDownloader:
    def __init__(self):
        self.cookies: List[dict] = []
        self.session: Optional[requests.Session] = None
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def authenticate(self, on_status: Callable[[str], None] = None) -> bool:
        """Launch Chrome and wait for user to log in."""
        self._cancelled = False

        try:
            if on_status:
                on_status("Launching Chrome...")

            if not launch_chrome():
                if on_status:
                    on_status("Failed to launch Chrome!")
                return False

            time.sleep(2)

            if on_status:
                on_status("Connecting to Chrome...")

            pw, browser = connect_to_chrome()

            try:
                context = browser.contexts[0]
                pages = context.pages
                page = pages[0] if pages else context.new_page()

                if on_status:
                    on_status("Waiting for NotebookLM login...")

                for i in range(120):
                    if self._cancelled:
                        return False

                    url = page.url
                    if "notebooklm.google.com" in url and "accounts.google.com" not in url:
                        break

                    if i % 10 == 0 and on_status:
                        on_status(f"Waiting for login... ({i}s)")

                    time.sleep(1)

                time.sleep(3)

                url = page.url
                if "notebooklm.google.com" not in url:
                    if on_status:
                        on_status("Not logged in!")
                    return False

                self.cookies = context.cookies()

                self.session = requests.Session()
                for cookie in self.cookies:
                    self.session.cookies.set(
                        cookie['name'],
                        cookie['value'],
                        domain=cookie.get('domain', '.google.com')
                    )

                if on_status:
                    on_status(f"Logged in! Got {len(self.cookies)} cookies.")

                return True

            finally:
                safe_disconnect(pw, browser)

        except Exception as e:
            if on_status:
                on_status(f"Error: {str(e)}")
            return False

    def list_notebooks(self, on_status: Callable[[str], None] = None) -> List[NotebookInfo]:
        """
        STEP 1: Quick scan - just get notebook IDs and titles.
        Does NOT scan for media yet (that's done in scan_for_media).
        """
        notebooks = []
        self._cancelled = False

        if not self.cookies:
            if on_status:
                on_status("Not authenticated!")
            return notebooks

        try:
            if on_status:
                on_status("Connecting to Chrome...")

            pw, browser = connect_to_chrome()

            try:
                context = browser.contexts[0]
                page = context.pages[0] if context.pages else context.new_page()

                if on_status:
                    on_status("Loading NotebookLM homepage...")

                page.goto("https://notebooklm.google.com/", wait_until="networkidle", timeout=30000)
                time.sleep(3)

                # Scroll down to load ALL notebooks (lazy loading)
                if on_status:
                    on_status("Scrolling to load all notebooks...")

                prev_count = 0
                stable_rounds = 0
                for scroll_attempt in range(30):
                    # Scroll to bottom
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    # Also scroll any scrollable container
                    page.evaluate("""() => {
                        const containers = document.querySelectorAll('[class*="list"], [class*="grid"], [class*="container"], [class*="scroll"], main');
                        containers.forEach(c => { c.scrollTop = c.scrollHeight; });
                    }""")
                    time.sleep(0.8)

                    # Check how many notebook links we have now
                    cur_count = page.evaluate("""() => {
                        return document.querySelectorAll('a[href*="/notebook/"]').length;
                    }""")

                    if cur_count == prev_count and cur_count > 0:
                        stable_rounds += 1
                        if stable_rounds >= 3:
                            break
                    else:
                        stable_rounds = 0
                    prev_count = cur_count

                # Scroll back to top
                page.evaluate("window.scrollTo(0, 0)")
                time.sleep(0.5)

                # Get notebook cards with titles from homepage
                if on_status:
                    on_status("Finding notebooks on homepage...")

                # Try to get notebooks directly from the page using JavaScript
                notebook_data = page.evaluate("""() => {
                    const notebooks = [];

                    // Method 1: Find all clickable notebook items
                    const items = document.querySelectorAll('a[href*="/notebook/"]');
                    items.forEach(item => {
                        const href = item.getAttribute('href') || '';
                        const match = href.match(/notebook\\/([a-f0-9-]{36})/i);
                        if (match) {
                            // Try to get title from the element or its children
                            let title = '';
                            const titleEl = item.querySelector('h1, h2, h3, [class*="title"], [class*="name"]');
                            if (titleEl) {
                                title = titleEl.textContent.trim();
                            } else {
                                title = item.textContent.trim().substring(0, 100);
                            }
                            notebooks.push({id: match[1], title: title || 'Untitled'});
                        }
                    });

                    // Method 2: Look for any elements with notebook UUIDs in data attributes
                    document.querySelectorAll('[data-notebook-id], [data-id], [data-project-id]').forEach(el => {
                        const id = el.getAttribute('data-notebook-id') ||
                                   el.getAttribute('data-id') ||
                                   el.getAttribute('data-project-id');
                        if (id && /^[a-f0-9-]{36}$/i.test(id)) {
                            const title = el.textContent.trim().substring(0, 100) || 'Untitled';
                            notebooks.push({id: id, title: title});
                        }
                    });

                    // Method 3: Search ALL hrefs in the page for notebook UUIDs
                    document.querySelectorAll('a[href]').forEach(a => {
                        const href = a.getAttribute('href') || '';
                        const match = href.match(/notebook\\/([a-f0-9-]{36})/i);
                        if (match) {
                            let title = '';
                            const titleEl = a.querySelector('h1, h2, h3, [class*="title"], [class*="name"]');
                            if (titleEl) {
                                title = titleEl.textContent.trim();
                            } else {
                                // Get text but limit and clean it
                                title = a.innerText?.split('\\n').filter(l => l.trim()).slice(0, 2).join(' - ').trim() || '';
                            }
                            notebooks.push({id: match[1], title: title.substring(0, 100) || 'Untitled'});
                        }
                    });

                    // Deduplicate by ID
                    const seen = new Set();
                    return notebooks.filter(nb => {
                        if (seen.has(nb.id)) return false;
                        seen.add(nb.id);
                        return true;
                    });
                }""")

                if notebook_data and len(notebook_data) > 0:
                    if on_status:
                        on_status(f"Found {len(notebook_data)} notebooks with titles")

                    for nb in notebook_data:
                        notebooks.append(NotebookInfo(
                            project_id=nb['id'],
                            title=nb['title'][:80] if nb['title'] else 'Untitled',
                            emoji="📓",
                            audio_artifacts=[],
                            video_artifacts=[]
                        ))
                else:
                    # Fallback: Find UUIDs and get titles by visiting each notebook briefly
                    if on_status:
                        on_status("Searching for notebook IDs...")

                    content = page.content()
                    all_uuids = list(set(re.findall(UUID_PATTERN, content, re.IGNORECASE)))

                    if on_status:
                        on_status(f"Found {len(all_uuids)} notebook IDs. Getting titles...")

                    # Process all notebooks
                    for i, uuid in enumerate(all_uuids):
                        if self._cancelled:
                            break

                        try:
                            if on_status and i % 10 == 0:
                                on_status(f"Getting title {i+1}/{len(all_uuids)}...")

                            page.goto(
                                f"https://notebooklm.google.com/notebook/{uuid}",
                                wait_until="domcontentloaded",
                                timeout=10000
                            )
                            time.sleep(1)

                            title = page.title().replace(" - NotebookLM", "").strip()
                            if not title or title == "NotebookLM":
                                title = f"Notebook {i+1}"

                            notebooks.append(NotebookInfo(
                                project_id=uuid,
                                title=title[:80],
                                emoji="📓",
                                audio_artifacts=[],
                                video_artifacts=[]
                            ))

                        except:
                            # Skip invalid notebooks
                            continue

                if on_status:
                    on_status(f"Done! Found {len(notebooks)} notebooks.")

            finally:
                safe_disconnect(pw, browser)

        except Exception as e:
            if on_status:
                on_status(f"Error: {str(e)}")

        return notebooks

    def scan_for_media(self, notebooks: List[NotebookInfo], on_status: Callable[[str], None] = None) -> List[NotebookInfo]:
        """
        STEP 2: Scan selected notebooks for audio/video in their Studio panel.
        Returns notebooks with populated audio_artifacts and video_artifacts.
        """
        if not notebooks:
            return []

        self._cancelled = False

        try:
            if on_status:
                on_status("Connecting to Chrome...")

            pw, browser = connect_to_chrome()

            try:
                context = browser.contexts[0]
                page = context.pages[0] if context.pages else context.new_page()

                total = len(notebooks)
                notebooks_with_media = []

                for i, nb in enumerate(notebooks):
                    if self._cancelled:
                        break

                    try:
                        if on_status:
                            on_status(f"Scanning {i+1}/{total}: {nb.title[:35]}...")

                        # Navigate to notebook with retry
                        for attempt in range(3):
                            try:
                                page.goto(
                                    f"https://notebooklm.google.com/notebook/{nb.project_id}",
                                    wait_until="domcontentloaded",
                                    timeout=30000
                                )
                                break
                            except Exception as nav_err:
                                if attempt < 2:
                                    time.sleep(2)
                                    continue
                                raise nav_err
                        time.sleep(3)

                        # Try to click Studio tab
                        try:
                            studio_clicked = False
                            for selector in ['text=סטודיו', 'text=Studio', 'button:has-text("Studio")', 'button:has-text("סטודיו")']:
                                try:
                                    el = page.locator(selector).first
                                    if el.is_visible(timeout=2000):
                                        el.click()
                                        time.sleep(2)
                                        studio_clicked = True
                                        break
                                except:
                                    continue

                            if studio_clicked and on_status:
                                on_status(f"  Opened Studio panel")
                        except:
                            pass

                        # Find media items - look for rows with more_vert (3-dot menu) at bottom of Studio
                        # These are the actual generated audio/video content
                        nb.audio_artifacts = []
                        nb.video_artifacts = []

                        # Find generated content items - rows with 3-dot menu (more_vert icon)
                        media_count = page.evaluate("""() => {
                            const items = {audio: 0, video: 0, total: 0};

                            // Find all more_vert icons (3-dot menus) which indicate downloadable items
                            const menuIcons = document.querySelectorAll('mat-icon');
                            const processedRows = new Set();

                            menuIcons.forEach(icon => {
                                if (icon.textContent?.trim() === 'more_vert') {
                                    // Find the parent row/container
                                    const row = icon.closest('[class*="row"], [class*="item"], [class*="card"]') || icon.parentElement?.parentElement?.parentElement;
                                    if (row && !processedRows.has(row)) {
                                        processedRows.add(row);
                                        const text = row.textContent || '';
                                        // Check if it's audio or video based on Hebrew text
                                        if (text.includes('סרטון הסבר') || text.includes('סרטון')) {
                                            items.video++;
                                        } else if (text.includes('סקירה קולית') || text.includes('אודיו')) {
                                            items.audio++;
                                        } else {
                                            // Default to video if unclear
                                            items.video++;
                                        }
                                        items.total++;
                                    }
                                }
                            });

                            return items;
                        }""")

                        # Build artifacts based on count
                        for j in range(media_count.get('audio', 0)):
                            nb.audio_artifacts.append({
                                'id': f'audio_{j}',
                                'title': f'Audio {j+1}',
                                'url': 'interactive'
                            })

                        for j in range(media_count.get('video', 0)):
                            nb.video_artifacts.append({
                                'id': f'video_{j}',
                                'title': f'Video {j+1}',
                                'url': 'interactive'
                            })

                        if nb.audio_artifacts or nb.video_artifacts:
                            notebooks_with_media.append(nb)
                            if on_status:
                                on_status(f"  ✓ {len(nb.audio_artifacts)} audio, {len(nb.video_artifacts)} video")
                        else:
                            if on_status:
                                on_status(f"  - No media found")

                    except Exception as e:
                        if on_status:
                            on_status(f"  ⚠ Skipped: {str(e)[:30]}")
                        continue

                total_audio = sum(len(nb.audio_artifacts) for nb in notebooks_with_media)
                total_video = sum(len(nb.video_artifacts) for nb in notebooks_with_media)
                if on_status:
                    on_status(f"Done! {len(notebooks_with_media)} notebooks with media ({total_audio} audio, {total_video} video)")

                return notebooks_with_media

            finally:
                safe_disconnect(pw, browser)

        except Exception as e:
            if on_status:
                on_status(f"Error: {str(e)}")
            return []

    def download_artifacts(
        self,
        notebooks: List[NotebookInfo],
        output_dir: Path,
        download_audio: bool = True,
        download_video: bool = True,
        on_progress: Callable[[DownloadProgress], None] = None
    ) -> List[Path]:
        """Download artifacts by clicking through NotebookLM UI.
        Each notebook gets its own subfolder under output_dir."""
        downloaded = []
        self._cancelled = False

        # Count total items
        total_items = 0
        for nb in notebooks:
            if download_audio:
                total_items += len(nb.audio_artifacts)
            if download_video:
                total_items += len(nb.video_artifacts)

        if total_items == 0:
            return downloaded

        try:
            if on_progress:
                on_progress(DownloadProgress(0, total_items, "Connecting to Chrome...", "downloading"))

            pw, browser = connect_to_chrome()

            try:
                context = browser.contexts[0]
                page = context.pages[0] if context.pages else context.new_page()

                current_item = 0

                for nb in notebooks:
                    if self._cancelled:
                        break

                    # Create a subfolder for this notebook
                    clean_title = self._sanitize_filename(nb.title)
                    nb_folder = output_dir / clean_title
                    nb_folder.mkdir(parents=True, exist_ok=True)

                    # Navigate to notebook
                    if on_progress:
                        on_progress(DownloadProgress(current_item, total_items, f"Opening {nb.title[:30]}...", "downloading"))

                    page.goto(
                        f"https://notebooklm.google.com/notebook/{nb.project_id}",
                        wait_until="domcontentloaded",
                        timeout=30000
                    )
                    time.sleep(3)

                    # Click Studio tab
                    for selector in ['text=סטודיו', 'text=Studio']:
                        try:
                            el = page.locator(selector).first
                            if el.is_visible(timeout=2000):
                                el.click()
                                time.sleep(2)
                                break
                        except:
                            continue

                    # Find all 3-dot menu icons (more_vert) - these indicate downloadable items
                    more_vert_icons = page.locator('mat-icon:text("more_vert")').all()

                    if on_progress:
                        on_progress(DownloadProgress(current_item, total_items, f"Found {len(more_vert_icons)} items in {nb.title[:20]}", "downloading"))

                    for icon_idx, menu_icon in enumerate(more_vert_icons):
                        if self._cancelled:
                            break

                        current_item += 1
                        item_name = f"{nb.title[:25]} - Item {icon_idx + 1}"

                        try:
                            if on_progress:
                                on_progress(DownloadProgress(current_item, total_items, item_name, "downloading"))

                            # Click the 3-dot menu icon
                            menu_icon.click()
                            time.sleep(1)

                            # Set up download handler and click Download option
                            with page.expect_download(timeout=120000) as download_info:
                                # Find and click the download menu item
                                download_option = page.locator('span:text("הורדה"), button:has-text("הורדה"), [role="menuitem"]:has-text("הורדה")').first
                                download_option.click()

                            # Wait for download to complete
                            download = download_info.value
                            suggested_filename = download.suggested_filename or f"video_{icon_idx + 1}.mp4"

                            # Save to notebook subfolder
                            output_path = nb_folder / suggested_filename

                            # Handle duplicate filenames
                            counter = 1
                            stem = output_path.stem
                            suffix = output_path.suffix or '.mp4'
                            while output_path.exists():
                                output_path = nb_folder / f"{stem}_{counter}{suffix}"
                                counter += 1

                            download.save_as(str(output_path))
                            downloaded.append(output_path)

                            if on_progress:
                                on_progress(DownloadProgress(current_item, total_items, f"{clean_title}/{output_path.name}", "completed"))

                            time.sleep(1)

                        except Exception as e:
                            if on_progress:
                                on_progress(DownloadProgress(current_item, total_items, f"{item_name} - {str(e)[:30]}", "failed"))
                            # Press Escape to close any open menus
                            try:
                                page.keyboard.press("Escape")
                                time.sleep(0.5)
                            except:
                                pass
                            continue

                return downloaded

            finally:
                safe_disconnect(pw, browser)

        except Exception as e:
            if on_progress:
                on_progress(DownloadProgress(0, total_items, f"Error: {str(e)[:40]}", "failed"))
            return downloaded

    def _sanitize_filename(self, name: str) -> str:
        return re.sub(r'[<>:"/\\|?*]', '_', name)[:200]

    # ===== CACHING METHODS =====

    def _get_cache_path(self) -> Path:
        """Get path to cache file in app data directory."""
        if os.name == 'nt':
            app_data = Path(os.environ.get('APPDATA', str(Path.home())))
            cache_dir = app_data / 'HebrewTranscriber'
        else:
            cache_dir = Path.home() / '.HebrewTranscriber'
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / CACHE_FILE_NAME

    def load_cache(self) -> dict:
        """Load cached notebooks from JSON file."""
        cache_path = self._get_cache_path()
        if not cache_path.exists():
            return {"version": CACHE_VERSION, "notebooks": [], "last_updated": None}

        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if data.get("version") != CACHE_VERSION:
                return {"version": CACHE_VERSION, "notebooks": [], "last_updated": None}
            return data
        except (json.JSONDecodeError, IOError):
            return {"version": CACHE_VERSION, "notebooks": [], "last_updated": None}

    def save_cache(self, notebooks: List[NotebookInfo]):
        """Save notebooks to cache file."""
        cache_path = self._get_cache_path()
        now = datetime.now().isoformat()

        # Load existing cache to preserve first_seen dates
        existing = self.load_cache()
        existing_by_id = {nb["project_id"]: nb for nb in existing.get("notebooks", [])}

        cache_data = {
            "version": CACHE_VERSION,
            "last_updated": now,
            "notebooks": []
        }

        for nb in notebooks:
            existing_entry = existing_by_id.get(nb.project_id)
            cache_data["notebooks"].append({
                "project_id": nb.project_id,
                "title": nb.title,
                "emoji": nb.emoji,
                "first_seen": existing_entry["first_seen"] if existing_entry else now
            })

        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)

    def get_cached_notebooks(self) -> List[NotebookInfo]:
        """Return notebooks from cache as NotebookInfo objects."""
        cache = self.load_cache()
        return [
            NotebookInfo(
                project_id=nb["project_id"],
                title=nb["title"],
                emoji=nb.get("emoji", "📓"),
                audio_artifacts=[],
                video_artifacts=[]
            )
            for nb in cache.get("notebooks", [])
        ]

    def list_notebooks_with_cache(
        self,
        force_refresh: bool = False,
        on_status: Callable[[str], None] = None
    ) -> tuple:
        """
        List notebooks, using cache when possible.

        Returns:
            (notebooks_list, new_count) - list of all notebooks and count of newly discovered ones
        """
        cached = self.get_cached_notebooks()
        cached_ids = {nb.project_id for nb in cached}

        if force_refresh or not cached:
            # Full refresh - fetch all and replace cache
            if on_status:
                on_status("Force refresh - fetching all notebooks...")
            fresh = self.list_notebooks(on_status)
            self.save_cache(fresh)
            new_count = len(fresh) - len(cached_ids.intersection({nb.project_id for nb in fresh}))
            return fresh, new_count

        # Incremental refresh - fetch and merge
        if on_status:
            on_status("Checking for new notebooks...")
        fresh = self.list_notebooks(on_status)
        fresh_ids = {nb.project_id for nb in fresh}

        # Find new notebooks
        new_ids = fresh_ids - cached_ids
        new_notebooks = [nb for nb in fresh if nb.project_id in new_ids]

        # Also find notebooks that were deleted
        deleted_ids = cached_ids - fresh_ids

        if new_notebooks or deleted_ids:
            if on_status:
                if new_notebooks:
                    on_status(f"Found {len(new_notebooks)} new notebook(s)")
                if deleted_ids:
                    on_status(f"Removed {len(deleted_ids)} deleted notebook(s)")
            # Use fresh list (which already has correct current state)
            all_notebooks = fresh
        else:
            if on_status:
                on_status("No new notebooks found")
            all_notebooks = fresh  # Use fresh to keep order consistent

        # Update cache with current list
        self.save_cache(all_notebooks)

        return all_notebooks, len(new_notebooks)
