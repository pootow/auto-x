#!/usr/bin/env python3
"""
yt-dlp Downloader processor - downloads media from 1800+ sites.

Reads JSON Lines from stdin, writes results to stdout.
Downloads media from supported URLs (YouTube, Twitter/X, Instagram, TikTok, etc.)
to ~/Downloads/tele/

Usage:
    # Basic usage
    echo '{"id":1,"chat_id":123,"text":"https://youtube.com/watch?v=xxx"}' | python processors/downloader/ytdlp.py

    # With CLI args passthrough to yt-dlp
    echo '{"id":1,"chat_id":123,"text":"https://youtube.com/watch?v=xxx"}' | python processors/downloader/ytdlp.py -f best

    # With environment variable for defaults
    YTDLPOPTS="--no-playlist -f best" echo '{"id":1,"chat_id":123,"text":"https://youtube.com/watch?v=xxx"}' | python processors/downloader/ytdlp.py

    # Combined: env var + CLI args (CLI overrides env)
    YTDLPOPTS="--no-playlist" echo '{"id":1,"chat_id":123,"text":"https://youtube.com/watch?v=xxx"}' | python processors/downloader/ytdlp.py -f "bestvideo+bestaudio"
"""

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

# URL extraction pattern - matches http and https URLs
URL_PATTERN = re.compile(r'https?://[^\s<>"{}|\\^`\[\]]+')

# Default download directory
DOWNLOAD_DIR = Path.home() / "Downloads" / "tele"

# Download timeout in seconds (5 minutes for large videos)
DOWNLOAD_TIMEOUT = 300


def extract_urls(text: str) -> list[str]:
    """Extract all http/https URLs from text."""
    if not text:
        return []
    return URL_PATTERN.findall(text)


def get_ytdlp_opts() -> list[str]:
    """
    Get yt-dlp options from environment variable and CLI args.

    Priority (later options override earlier in yt-dlp):
    1. YTDLPOPTS environment variable (user defaults)
    2. CLI arguments passed to this script (per-run overrides)

    Returns:
        List of yt-dlp command-line options.
    """
    opts = []

    # 1. Environment variable defaults
    env_opts = os.environ.get("YTDLPOPTS", "")
    if env_opts:
        opts.extend(shlex.split(env_opts))

    # 2. CLI args passthrough (everything after script name)
    opts.extend(sys.argv[1:])

    return opts


def download_with_ytdlp(url: str, dest_dir: Path) -> tuple[bool, str]:
    """
    Download media using yt-dlp.

    Args:
        url: URL to download from
        dest_dir: Directory to save the downloaded file

    Returns:
        tuple of (success: bool, message: str)
    """
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            "yt-dlp",
            "--paths", str(dest_dir),
            "--output", "%(title)s.%(ext)s",
            *get_ytdlp_opts(),
            url
        ]

        print(f"[INFO] Running: {' '.join(cmd)}", file=sys.stderr)
        result = subprocess.run(
            cmd,
            stdout=sys.stderr,  # Redirect yt-dlp stdout to stderr (prevents stdout pollution)
            stderr=subprocess.PIPE,  # Capture stderr for error detection
            text=True,
            timeout=DOWNLOAD_TIMEOUT
        )

        if result.returncode == 0:
            print(f"[INFO] Downloaded: {url}", file=sys.stderr)
            return True, "Downloaded"
        else:
            error_msg = result.stderr or "yt-dlp failed"
            print(f"[ERROR] yt-dlp failed for {url}: {error_msg}", file=sys.stderr)
            return False, error_msg

    except subprocess.TimeoutExpired:
        print(f"[ERROR] Download timed out for {url}", file=sys.stderr)
        return False, "Download timed out"
    except FileNotFoundError:
        print(f"[ERROR] yt-dlp not found on PATH", file=sys.stderr)
        return False, "yt-dlp not found"
    except Exception as e:
        print(f"[ERROR] Unexpected error downloading {url}: {e}", file=sys.stderr)
        return False, str(e)


def process_message(msg: dict) -> dict:
    """Process a single message and return the result."""
    # Extract required fields
    msg_id = msg.get("id")
    chat_id = msg.get("chat_id")

    # Validate required fields exist
    if msg_id is None or chat_id is None:
        return {
            "id": msg_id or 0,
            "chat_id": chat_id or 0,
            "status": "failed"
        }

    # Get message text
    text = msg.get("text", "")
    if not text:
        # No text, nothing to process
        return {
            "id": msg_id,
            "chat_id": chat_id,
            "status": "success"
        }

    # Extract URLs from text
    urls = extract_urls(text)
    if not urls:
        # No URLs found
        return {
            "id": msg_id,
            "chat_id": chat_id,
            "status": "success"
        }

    # Download each URL
    all_success = True
    for url in urls:
        success, _ = download_with_ytdlp(url, DOWNLOAD_DIR)
        if not success:
            all_success = False

    return {
        "id": msg_id,
        "chat_id": chat_id,
        "status": "success" if all_success else "failed"
    }


def main():
    """Read JSON Lines from stdin, process each, output results."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            msg = json.loads(line)
            result = process_message(msg)
            print(json.dumps(result))
        except json.JSONDecodeError as e:
            print(f"[ERROR] Invalid JSON: {e}", file=sys.stderr)
            print(json.dumps({"id": 0, "chat_id": 0, "status": "failed"}))


if __name__ == "__main__":
    main()