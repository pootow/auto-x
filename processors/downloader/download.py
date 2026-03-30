#!/usr/bin/env python3
"""
URL Downloader processor - extracts URLs from messages and downloads them.

Reads JSON Lines from stdin, writes results to stdout.
Downloads all http/https URLs found in message text to ~/Downloads/tele/
"""

import json
import logging
import os
import re
import shlex
import subprocess
import sys
import urllib.request
import urllib.error
from pathlib import Path
from urllib.parse import urlparse, unquote

# Add tele module to path for importing log utilities
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tele.log import setup_processor_logging

# Setup logging based on TELE_LOG_LEVEL env var
setup_processor_logging()

logger = logging.getLogger(__name__)

# URL extraction pattern - matches http and https URLs
URL_PATTERN = re.compile(r'https?://[^\s<>"{}|\\^`\[\]]+')

# Default download directory
DOWNLOAD_DIR = Path.home() / "Downloads" / "tele"

# Download timeout in seconds
DOWNLOAD_TIMEOUT = 30

# yt-dlp timeout (5 minutes for large videos)
YTDLPTIMEOUT = 300


def extract_urls(text: str) -> list[str]:
    """Extract all http/https URLs from text."""
    if not text:
        return []
    return URL_PATTERN.findall(text)


def get_filename_from_url(url: str) -> str:
    """Extract filename from URL, with fallback to a hash-based name."""
    parsed = urlparse(url)
    path = unquote(parsed.path)

    # Get the last component of the path
    if path and path != '/':
        filename = Path(path).name
        if filename:
            return filename

    # Fallback: create a name from the netloc and a hash
    import hashlib
    url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
    return f"download_{url_hash}"


def download_with_urllib(url: str, dest_dir: Path) -> tuple[bool, str]:
    """
    Download a file from URL using urllib.

    Returns:
        tuple of (success: bool, message: str)
    """
    try:
        # Ensure destination directory exists
        dest_dir.mkdir(parents=True, exist_ok=True)

        # Get filename and create full path
        filename = get_filename_from_url(url)
        dest_path = dest_dir / filename

        # Download the file with timeout
        logger.debug("Downloading: %s", url)
        with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT) as response:
            data = response.read()
            dest_path.write_bytes(data)

        logger.info("Saved: %s", dest_path)
        return True, str(dest_path)

    except urllib.error.URLError as e:
        logger.error("Download failed for %s: %s", url, e)
        return False, str(e)
    except Exception as e:
        logger.error("Unexpected error downloading %s: %s", url, e)
        return False, str(e)


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

        logger.debug("Running: %s", ' '.join(cmd))
        result = subprocess.run(
            cmd,
            stdout=sys.stderr,  # Redirect yt-dlp stdout to stderr (prevents stdout pollution)
            stderr=subprocess.PIPE,  # Capture stderr for error detection
            text=True,
            timeout=YTDLPTIMEOUT
        )

        if result.returncode == 0:
            logger.info("Downloaded: %s", url)
            return True, "Downloaded"
        else:
            error_msg = result.stderr or "yt-dlp failed"
            logger.error("yt-dlp failed for %s: %s", url, error_msg)
            return False, error_msg

    except subprocess.TimeoutExpired:
        logger.error("Download timed out for %s", url)
        return False, "Download timed out"
    except FileNotFoundError:
        logger.error("yt-dlp not found on PATH")
        return False, "yt-dlp not found"
    except Exception as e:
        logger.error("Unexpected error downloading %s: %s", url, e)
        return False, str(e)


def is_ytdlp_unsupported_error(error_msg: str) -> bool:
    """Check if error message indicates an unsupported URL for yt-dlp."""
    unsupported_indicators = [
        "Unsupported URL",
        "is not a valid URL",
        "ERROR: Unsupported URL",
    ]
    return any(indicator in error_msg for indicator in unsupported_indicators)


def download_file(url: str, dest_dir: Path) -> tuple[bool, str]:
    """
    Download a file from URL, dispatching to yt-dlp or urllib.

    Tries yt-dlp first (supports 1800+ sites like YouTube, Twitter, Instagram).
    If yt-dlp reports unsupported URL, falls back to urllib for direct downloads.

    Returns:
        tuple of (success: bool, message: str)
    """
    # Try yt-dlp first
    success, msg = download_with_ytdlp(url, dest_dir)
    if success:
        return True, msg

    # Check if it's an "unsupported URL" error - fall back to urllib
    if is_ytdlp_unsupported_error(msg):
        logger.info("yt-dlp unsupported, trying urllib: %s", url)
        return download_with_urllib(url, dest_dir)

    # Other yt-dlp errors - don't fallback, just fail
    return False, msg


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
        success, _ = download_file(url, DOWNLOAD_DIR)
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
            logger.error("Invalid JSON: %s", e)
            print(json.dumps({"id": 0, "chat_id": 0, "status": "failed"}))


if __name__ == "__main__":
    main()