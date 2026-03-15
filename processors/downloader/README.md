# URL Downloader Processor

A processor that extracts URLs from Telegram message text and downloads them to a local directory.

## Features

- Extracts all http/https URLs from message text
- Downloads files to `~/Downloads/tele/`
- **yt-dlp integration**: Supports 1800+ sites (YouTube, Twitter/X, Instagram, TikTok, etc.)
- Falls back to urllib for direct file downloads
- Handles download errors gracefully
- Configurable timeouts

## Processors

### download.py (Recommended)

The main processor that automatically dispatches URLs to the appropriate downloader:

1. **yt-dlp**: Used first for all URLs (supports 1800+ sites)
2. **urllib**: Falls back for direct file downloads when yt-dlp doesn't support the URL

### ytdlp.py (Standalone)

A standalone yt-dlp-only processor for when you want explicit control over the downloader.

## Usage

### download.py (Automatic Dispatch)

```bash
# Download from YouTube (uses yt-dlp)
echo '{"id":1,"chat_id":123,"text":"https://www.youtube.com/watch?v=dQw4w9WgXcQ"}' | python processors/downloader/download.py

# Download regular file (yt-dlp falls back to urllib)
echo '{"id":1,"chat_id":123,"text":"https://httpbin.org/json"}' | python processors/downloader/download.py

# Multiple URLs
echo '{"id":1,"chat_id":123,"text":"Check https://youtube.com/watch?v=abc and https://example.com/file.zip"}' | python processors/downloader/download.py
```

### ytdlp.py (yt-dlp Only)

```bash
# Download from YouTube
echo '{"id":1,"chat_id":123,"text":"https://www.youtube.com/watch?v=dQw4w9WgXcQ"}' | python processors/downloader/ytdlp.py

# Download from Twitter/X
echo '{"id":1,"chat_id":123,"text":"https://x.com/user/status/123456"}' | python processors/downloader/ytdlp.py
```

### Use with tele bot mode

```bash
tele --bot --exec "python processors/downloader/download.py" --chat "-1001234567890"
```

## Supported Sites (yt-dlp)

yt-dlp supports 1800+ sites including:

- **Video**: YouTube, Vimeo, Dailymotion, Rumble
- **Social**: Twitter/X, Instagram, TikTok, Facebook
- **Audio**: SoundCloud, Bandcamp
- **And many more**: See `yt-dlp --list-extractors`

## yt-dlp Configuration

### Environment Variable: `YTDLPOPTS`

Set default options for yt-dlp via environment variable:

```bash
# Set default options
export YTDLPOPTS="--no-playlist -f best"

# Use with processor
echo '{"id":1,"text":"https://youtube.com/watch?v=xxx"}' | python processors/downloader/ytdlp.py
```

### CLI Arguments Passthrough

Pass yt-dlp options directly via CLI arguments:

```bash
# Format selection
echo '{"id":1,"text":"https://youtube.com/watch?v=xxx"}' | python processors/downloader/ytdlp.py -f "bestvideo+bestaudio"

# Download playlist
echo '{"id":1,"text":"https://youtube.com/playlist?list=xxx"}' | python processors/downloader/ytdlp.py --yes-playlist

# Use proxy
echo '{"id":1,"text":"https://youtube.com/watch?v=xxx"}' | python processors/downloader/ytdlp.py --proxy socks5://localhost:1080
```

### Combined: Env + CLI

Environment variable provides defaults, CLI arguments override:

```bash
# Env: default to no playlist, CLI: select format
YTDLPOPTS="--no-playlist" echo '{"id":1,"text":"https://youtube.com/watch?v=xxx"}' | python processors/downloader/ytdlp.py -f best
```

### With tele Bot Mode

```bash
# Using -- separator for passthrough
YTDLPOPTS="--no-playlist" tele --bot -- python processors/downloader/ytdlp.py -f best

# Or with explicit exec
tele --bot --exec "python processors/downloader/ytdlp.py -f best" --chat "-1001234567890"
```

### Common Options

| Option | Description |
|--------|-------------|
| `--no-playlist` | Download single video, not entire playlist |
| `--yes-playlist` | Download entire playlist |
| `-f FORMAT` | Select format (e.g., `best`, `bestvideo+bestaudio`) |
| `--proxy URL` | Use proxy server |
| `--cookies FILE` | Use cookies file for restricted content |
| `--no-check-certificate` | Skip SSL verification |

> **Note**: yt-dlp stdout is redirected to stderr, so options like `--print`, `-j`, `-o -` won't pollute the JSON Lines output.

## Input/Output

### Input

Standard message format with `text` field:

```json
{
  "id": 12345,
  "chat_id": -1001234567890,
  "text": "Check out https://example.com/document.pdf"
}
```

### Output

Standard result format:

```json
{
  "id": 12345,
  "chat_id": -1001234567890,
  "status": "success"
}
```

- `status: "success"` - All downloads completed (or no URLs found)
- `status: "failed"` - One or more downloads failed

## Behavior

1. Extracts ALL http/https URLs from the `text` field
2. Tries yt-dlp first for each URL
3. If yt-dlp reports "Unsupported URL", falls back to urllib
4. Downloads each URL to `~/Downloads/tele/`
5. If any download fails, returns `status: "failed"`
6. Downloads are logged to stderr for debugging

## Download Location

Files are saved to:

- **Linux/macOS**: `~/Downloads/tele/`
- **Windows**: `C:\Users\<username>\Downloads\tele\`

The directory is created automatically if it doesn't exist.

## Filename Handling

- Filenames are extracted from the URL path
- If no filename in URL, a hash-based name is generated
- Example: `https://example.com/path/to/file.pdf` → `file.pdf`

## Limitations

- No file type filtering (downloads everything)
- No size limit (yt-dlp: 5 min timeout, urllib: 30 sec timeout)
- No resume support for interrupted downloads
- No authentication for protected URLs
- Requires `yt-dlp` installed and on PATH for full functionality

## Requirements

- **yt-dlp**: Required for video/social media downloads
  ```bash
  pip install yt-dlp
  # or
  brew install yt-dlp
  ```

## Error Handling

- Download errors are logged to stderr
- Failed downloads result in `status: "failed"`
- Processing continues even if individual downloads fail
- Invalid JSON input returns `{"id": 0, "chat_id": 0, "status": "failed"}`

## Further Reading

- [processors/examples/](../examples/) - More example processors
- [docs/contracts.md](../../docs/contracts.md) - Full message format specification