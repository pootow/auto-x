#!/usr/bin/env python3
"""
yt-dlp Downloader processor - downloads media from 1800+ sites.

Reads JSON Lines from stdin, writes results to stdout.
Downloads media from supported URLs (YouTube, Twitter/X, Instagram, TikTok, etc.)
to ~/Downloads/tele/

Usage:
    # Basic usage (direct download, no rich reply)
    echo '{"id":1,"chat_id":123,"text":"https://youtube.com/watch?v=xxx"}' | python processors/downloader/ytdlp.py

    # Metadata mode (rich reply)
    echo '{"id":1,"chat_id":123,"text":"https://youtube.com/watch?v=xxx"}' | python processors/downloader/ytdlp.py --write-info-json --skip-download

    # With CLI args passthrough to yt-dlp
    echo '{"id":1,"chat_id":123,"text":"https://youtube.com/watch?v=xxx"}' | python processors/downloader/ytdlp.py -f best

    # With environment variable for defaults
    YTDLPOPTS="--no-playlist -f best" echo '{"id":1,"chat_id":123,"text":"https://youtube.com/watch?v=xxx"}' | python processors/downloader/ytdlp.py

    # With verbosity flags (prefix + to distinguish from yt-dlp args)
    echo '{"id":1,"chat_id":123,"text":"https://youtube.com/watch?v=xxx"}' | python processors/downloader/ytdlp.py +v
    echo '{"id":1,"chat_id":123,"text":"https://youtube.com/watch?v=xxx"}' | python processors/downloader/ytdlp.py +vv
    echo '{"id":1,"chat_id":123,"text":"https://youtube.com/watch?v=xxx"}' | python processors/downloader/ytdlp.py +vvv

Script Flags (prefixed with +):
    +v    INFO level, print commands
    +vv   DEBUG level, print commands + debug logging
    +vvv  DATAFLOW level, print commands + JSON flow logging
"""

import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

# Add tele module to path for importing log utilities
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tele.log import setup_processor_logging, DATAFLOW


def parse_script_args() -> tuple[int, list[str]]:
    """
    Parse sys.argv to separate script flags from yt-dlp passthrough args.

    Script flags start with '+' (e.g., +v, +vv, +vvv).

    Returns:
        tuple of (verbosity_level, passthrough_args)
        verbosity_level: 0=WARNING, 1=INFO, 2=DEBUG, 3=TRACE
    """
    verbosity = 0
    passthrough = []

    for arg in sys.argv[1:]:
        if arg.startswith('+'):
            # Count 'v' repeats for verbosity level
            if arg.startswith('+v'):
                verbosity = max(verbosity, arg.count('v'))
        else:
            passthrough.append(arg)

    return verbosity, passthrough


# Parse script args first (before logging setup)
_VERBOSITY, _PASSTHROUGH_ARGS = parse_script_args()

# Map verbosity to log levels
_VERBOSITY_LEVELS = {
    0: logging.WARNING,  # default
    1: logging.INFO,     # +v
    2: logging.DEBUG,    # +vv
    3: DATAFLOW,         # +vvv (shows JSON flow)
}

# Setup logging based on verbosity or TELE_LOG_LEVEL env var
setup_processor_logging()
if _VERBOSITY > 0:
    level = _VERBOSITY_LEVELS.get(_VERBOSITY, logging.WARNING)
    root = logging.getLogger()
    root.setLevel(level)
    for handler in root.handlers:
        handler.setLevel(level)

logger = logging.getLogger(__name__)

# URL extraction pattern - matches http and https URLs
URL_PATTERN = re.compile(r'https?://[^\s<>"{}|\\^`\[\]]+')

# Default download directory
DOWNLOAD_DIR = Path("F:/x.com-v")

# Download timeout in seconds (5 minutes for large videos)
DOWNLOAD_TIMEOUT = 1800

# Max video size for Telegram to show directly (50MB)
MAX_TG_VIDEO_SIZE = 50 * 1024 * 1024

# Pattern to extract info.json file paths from yt-dlp output
INFO_JSON_PATTERN = re.compile(r'\[info\] Writing .*? metadata as JSON to: (.+\.info\.json)')


def escape_html(text: str) -> str:
    """Escape special characters for Telegram HTML format.

    Only <, >, and & need escaping in HTML mode.
    """
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def extract_urls(text: str) -> list[str]:
    """Extract all http/https URLs from text."""
    if not text:
        return []
    return URL_PATTERN.findall(text)


def get_ytdlp_opts(passthrough_args: list[str] | None = None) -> list[str]:
    """
    Get yt-dlp options from environment variable and passthrough args.

    Priority (later options override earlier in yt-dlp):
    1. YTDLPOPTS environment variable (user defaults)
    2. Passthrough args (per-run overrides)

    Returns:
        List of yt-dlp command-line options.
    """
    opts = []

    # 1. Environment variable defaults
    env_opts = os.environ.get("YTDLPOPTS", "")
    if env_opts:
        opts.extend(shlex.split(env_opts))

    # 2. Passthrough args
    if passthrough_args is not None:
        opts.extend(passthrough_args)

    return opts


def is_metadata_mode(opts: list[str]) -> bool:
    """Check if metadata mode is enabled."""
    return "--write-info-json" in opts and "--skip-download" in opts


def parse_info_json_paths(stderr: str) -> list[str]:
    """Parse yt-dlp stderr to find info.json file paths."""
    paths = []
    for match in INFO_JSON_PATTERN.finditer(stderr):
        paths.append(match.group(1))
    return paths


def select_best_format(formats: list[dict]) -> dict | None:
    """Select format with largest filesize_approx."""
    candidates = [f for f in formats if f.get("filesize_approx")]
    if not candidates:
        return None
    return max(candidates, key=lambda f: f.get("filesize_approx", 0))


def get_actual_filesize(url: str) -> int | None:
    """Get actual file size via HTTP HEAD request.

    Returns content-length if available, None if request fails or header missing.
    Uses a short timeout to avoid blocking the pipeline.

    Args:
        url: The media URL to check.

    Returns:
        File size in bytes, or None if unable to determine.
    """
    import urllib.request
    import urllib.error

    try:
        req = urllib.request.Request(url, method="HEAD")
        # Add common headers to improve compatibility
        req.add_header("User-Agent", "Mozilla/5.0")

        with urllib.request.urlopen(req, timeout=10) as response:
            content_length = response.headers.get("Content-Length")
            if content_length:
                return int(content_length)
            logger.debug("No Content-Length header for %s", url)
            return None

    except urllib.error.HTTPError as e:
        logger.debug("HEAD request failed for %s: HTTP %d", url, e.code)
        return None
    except urllib.error.URLError as e:
        logger.debug("HEAD request failed for %s: %s", url, e.reason)
        return None
    except Exception as e:
        logger.debug("HEAD request error for %s: %s", url, e)
        return None


def load_template() -> str:
    """Load reply template from file."""
    template_path = Path(__file__).parent / "reply_template.md"
    if template_path.exists():
        return template_path.read_text(encoding="utf-8")
    # Default template
    return "# {title}\n_Duration: {duration_string}_\nUploader: {uploader}"


def render_template(template: str, info: dict) -> str:
    """Render template with info dict, escaping for HTML."""
    # Prepare template variables with defaults, escaped for HTML
    vars = {
        "title": escape_html(info.get("title", "Unknown")),
        "description": escape_html(info.get("description", "")),
        "duration_string": escape_html(info.get("duration_string", "?")),
        "uploader": escape_html(info.get("uploader", "Unknown")),
        "uploader_id": escape_html(info.get("uploader_id", "Unknown")),
        "webpage_url": escape_html(info.get("webpage_url", "")),
        "filesize_mb": round(info.get("filesize_approx", 0) / 1024 / 1024, 1),
        "like_count": info.get("like_count", 0),
        "repost_count": info.get("repost_count", 0),
        "view_count": info.get("view_count", 0),
    }
    try:
        return template.format(**vars)
    except KeyError as e:
        logger.warning("Missing template variable: %s", e)
        return template.format(**{k: v for k, v in vars.items() if k in template})


def download_with_aria2c(url: str, dest_dir: Path, filename: str) -> tuple[bool, str]:
    """Download file using aria2c with resume support."""
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / filename

        cmd = [
            "aria2c",
            "--continue",
            "--max-connection-per-server=1",
            "--dir", str(dest_dir),
            "--out", filename,
            url
        ]

        logger.info("Running aria2c: %s", ' '.join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=DOWNLOAD_TIMEOUT)

        if result.returncode == 0:
            logger.info("Downloaded with aria2c: %s", dest_path)
            return True, str(dest_path)
        else:
            error = result.stderr or "aria2c failed"
            logger.error("aria2c failed: %s", error)
            return False, error

    except subprocess.TimeoutExpired:
        return False, "Download timed out"
    except FileNotFoundError:
        return False, "aria2c not found"
    except Exception as e:
        return False, str(e)


def download_with_urllib(url: str, dest_dir: Path, filename: str) -> tuple[bool, str]:
    """Download file using urllib with resume support."""
    import urllib.request
    import urllib.error

    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / filename

        # Check for existing partial file
        existing_size = 0
        mode = "wb"
        if dest_path.exists():
            existing_size = dest_path.stat().st_size
            mode = "ab"

        req = urllib.request.Request(url)
        if existing_size > 0:
            req.add_header("Range", f"bytes={existing_size}-")

        with urllib.request.urlopen(req, timeout=60) as response:
            with open(dest_path, mode) as f:
                while True:
                    chunk = response.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)

        logger.info("Downloaded with urllib: %s", dest_path)
        return True, str(dest_path)

    except urllib.error.HTTPError as e:
        if e.code in (403, 404):
            return False, f"HTTP {e.code}: {e.reason}"
        return False, f"HTTP error: {e}"
    except urllib.error.URLError as e:
        return False, f"URL error: {e}"
    except Exception as e:
        return False, str(e)


def process_metadata_mode(urls: list[str]) -> tuple[str, list[dict]]:
    """Process URLs in metadata mode, return status and reply array."""
    template = load_template()
    replies = []

    # Filter out metadata mode flags from passthrough to avoid duplicates
    extra_opts = [a for a in _PASSTHROUGH_ARGS if a not in ("--write-info-json", "--skip-download")]

    for url in urls:
        # Run yt-dlp to get metadata
        cmd = ["yt-dlp", "--write-info-json", "--skip-download", *get_ytdlp_opts(extra_opts), url]

        logger.info("Running: %s", ' '.join(cmd))
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,  # Capture stdout (info.json path may be here)
                stderr=subprocess.PIPE,  # Capture stderr (info.json path may be here too)
                text=True,
                timeout=DOWNLOAD_TIMEOUT
            )

            # Print captured output so user can see yt-dlp logs
            if result.stdout:
                sys.stderr.write(result.stdout)  # To stderr to avoid polluting JSON output
                sys.stderr.flush()
            if result.stderr:
                sys.stderr.write(result.stderr)
                sys.stderr.flush()

            # Parse info.json paths from both stdout and stderr
            info_paths = parse_info_json_paths(result.stdout + result.stderr)

            if not info_paths:
                logger.error("No info.json files found for %s", url)
                return "fatal", []

            # Process each info.json
            for info_path in info_paths:
                try:
                    with open(info_path, 'r', encoding='utf-8') as f:
                        info = json.load(f)
                except (json.JSONDecodeError, FileNotFoundError) as e:
                    logger.error("Failed to load info.json: %s", e)
                    return "error", []

                # Skip if no formats (not a video/audio)
                if "formats" not in info:
                    logger.debug("Skipping non-media info: %s", info_path)
                    continue

                # Select best format
                best_format = select_best_format(info["formats"])
                if not best_format:
                    logger.warning("No formats with filesize_approx for %s", url)
                    return "fatal", []

                media_type = "video" if info.get("_type") == "video" else "audio"
                media_url = best_format.get("url", "")
                thumbnail = info.get("thumbnail", "")

                # Get actual file size via HEAD request for accurate threshold check
                # filesize_approx is unreliable for absolute size (only good for relative comparison)
                actual_size = get_actual_filesize(media_url)
                if actual_size is not None:
                    logger.debug("HEAD content-length: %d bytes for %s", actual_size, url)
                    filesize = actual_size
                else:
                    # Fallback to filesize_approx (may be inaccurate)
                    filesize = best_format.get("filesize_approx", 0)
                    if filesize:
                        logger.warning("Using filesize_approx (%d bytes) for %s", filesize, url)

                # Small video -> return URL, large video -> download and return thumbnail
                if filesize <= MAX_TG_VIDEO_SIZE:
                    # Small video, no download needed
                    pass
                else:
                    # Large video, download for local archive, use thumbnail for reply
                    filename = f"{info.get('id', 'video')}.mp4"
                    if shutil.which("aria2c"):
                        success, _ = download_with_aria2c(media_url, DOWNLOAD_DIR, filename)
                    else:
                        success, _ = download_with_urllib(media_url, DOWNLOAD_DIR, filename)

                    if not success:
                        return "error", []

                    # Use thumbnail for reply
                    media_type = "image"
                    media_url = thumbnail

                # Render text
                text = render_template(template, {**info, "filesize_approx": filesize})

                replies.append({
                    "text": text,
                    "media": {
                        "type": media_type,
                        "url": media_url,
                        "cover": info.get("thumbnail", ""),  # yt-dlp: thumbnail → TG API: cover
                        "duration": int(info.get("duration", 0) or 0),
                        "width": info.get("width", 0),
                        "height": info.get("height", 0),
                    }
                })

        except subprocess.TimeoutExpired:
            return "error", []
        except Exception as e:
            logger.error("Error processing %s: %s", url, e)
            return "error", []

    return "success", replies


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
            "status": "error"
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

    # Check for metadata mode
    opts = get_ytdlp_opts(_PASSTHROUGH_ARGS)
    if is_metadata_mode(opts):
        # Metadata mode: get info, return rich reply
        status, replies = process_metadata_mode(urls)
        result = {
            "id": msg_id,
            "chat_id": chat_id,
            "status": status
        }
        if replies:
            result["reply"] = replies
        return result
    else:
        # Default mode: direct download, no rich reply
        all_success = True
        for url in urls:
            success, _ = download_with_ytdlp(url, DOWNLOAD_DIR)
            if not success:
                all_success = False

        return {
            "id": msg_id,
            "chat_id": chat_id,
            "status": "success" if all_success else "error"
        }


def download_with_ytdlp(url: str, dest_dir: Path) -> tuple[bool, str]:
    """
    Download media using yt-dlp (default mode).

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
            *get_ytdlp_opts(_PASSTHROUGH_ARGS),
            url
        ]

        logger.info("Running: %s", ' '.join(cmd))
        result = subprocess.run(
            cmd,
            stdout=sys.stderr,  # Redirect yt-dlp stdout to stderr (prevents stdout pollution)
            # stderr inherits for real-time progress output
            text=True,
            timeout=DOWNLOAD_TIMEOUT
        )

        if result.returncode == 0:
            logger.info("Downloaded: %s", url)
            return True, "Downloaded"
        else:
            logger.error("yt-dlp failed for %s (exit code %s)", url, result.returncode)
            return False, f"yt-dlp failed (exit code {result.returncode})"

    except subprocess.TimeoutExpired:
        logger.error("Download timed out for %s", url)
        return False, "Download timed out"
    except FileNotFoundError:
        logger.error("yt-dlp not found on PATH")
        return False, "yt-dlp not found"
    except Exception as e:
        logger.error("Unexpected error downloading %s: %s", url, e)
        return False, str(e)


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