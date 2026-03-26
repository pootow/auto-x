"""Tests for ytdlp.py processor metadata mode."""

import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestMetadataMode:
    """Test cases for metadata mode detection and processing."""

    def test_is_metadata_mode_true(self):
        """Test metadata mode detection when both flags present."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "processors" / "downloader"))
        from ytdlp import is_metadata_mode

        opts = ["--write-info-json", "--skip-download", "-f", "best"]
        assert is_metadata_mode(opts) is True

    def test_is_metadata_mode_false_no_skip_download(self):
        """Test metadata mode false when --skip-download missing."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "processors" / "downloader"))
        from ytdlp import is_metadata_mode

        opts = ["--write-info-json", "-f", "best"]
        assert is_metadata_mode(opts) is False

    def test_is_metadata_mode_false_no_write_info_json(self):
        """Test metadata mode false when --write-info-json missing."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "processors" / "downloader"))
        from ytdlp import is_metadata_mode

        opts = ["--skip-download", "-f", "best"]
        assert is_metadata_mode(opts) is False


class TestParseInfoJsonPaths:
    """Test cases for parsing yt-dlp output."""

    def test_parse_single_video_path(self):
        """Test parsing single video info.json path."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "processors" / "downloader"))
        from ytdlp import parse_info_json_paths

        stderr = """[twitter] Extracting URL: https://x.com/test
[twitter] 12345: Downloading GraphQL JSON
[info] Writing video metadata as JSON to: /tmp/Video Title [12345].info.json
"""
        paths = parse_info_json_paths(stderr)
        assert len(paths) == 1
        assert paths[0] == "/tmp/Video Title [12345].info.json"

    def test_parse_playlist_paths(self):
        """Test parsing multiple info.json paths from playlist."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "processors" / "downloader"))
        from ytdlp import parse_info_json_paths

        stderr = """[download] Downloading playlist: Test Playlist
[info] Writing playlist metadata as JSON to: /tmp/Playlist [abc].info.json
[twitter] Playlist abc: Downloading 2 items of 2
[download] Downloading item 1 of 2
[info] Writing video metadata as JSON to: /tmp/Video #1 [abc].info.json
[download] Downloading item 2 of 2
[info] Writing video metadata as JSON to: /tmp/Video #2 [abc].info.json
"""
        paths = parse_info_json_paths(stderr)
        assert len(paths) == 3


class TestSelectBestFormat:
    """Test cases for format selection."""

    def test_select_largest_filesize(self):
        """Test selecting format with largest filesize_approx."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "processors" / "downloader"))
        from ytdlp import select_best_format

        formats = [
            {"format_id": "small", "url": "http://small", "filesize_approx": 1000},
            {"format_id": "large", "url": "http://large", "filesize_approx": 5000},
            {"format_id": "medium", "url": "http://medium", "filesize_approx": 3000},
        ]

        best = select_best_format(formats)
        assert best["format_id"] == "large"
        assert best["filesize_approx"] == 5000

    def test_select_no_formats_with_filesize(self):
        """Test returning None when no formats have filesize_approx."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "processors" / "downloader"))
        from ytdlp import select_best_format

        formats = [
            {"format_id": "audio", "url": "http://audio"},
            {"format_id": "video", "url": "http://video"},
        ]

        best = select_best_format(formats)
        assert best is None

    def test_select_empty_formats(self):
        """Test returning None for empty formats list."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "processors" / "downloader"))
        from ytdlp import select_best_format

        best = select_best_format([])
        assert best is None


class TestRenderTemplate:
    """Test cases for template rendering."""

    def test_render_basic_template(self):
        """Test rendering basic template."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "processors" / "downloader"))
        from ytdlp import render_template

        template = "# {title}\n_Duration: {duration_string}_"
        info = {"title": "Test Video", "duration_string": "5:30"}

        result = render_template(template, info)
        assert result == "# Test Video\n_Duration: 5:30_"

    def test_render_with_missing_field(self):
        """Test rendering with missing field uses default."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "processors" / "downloader"))
        from ytdlp import render_template

        template = "# {title}\nUploader: {uploader}"
        info = {"title": "Test Video"}

        result = render_template(template, info)
        assert "Test Video" in result
        assert "Unknown" in result


class TestSmallLargeVideoLogic:
    """Test cases for small/large video handling."""

    def test_small_video_returns_url(self):
        """Test small video (<=50MB) returns video URL."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "processors" / "downloader"))
        from ytdlp import MAX_TG_VIDEO_SIZE

        # 10MB video
        assert 10 * 1024 * 1024 <= MAX_TG_VIDEO_SIZE

    def test_large_video_threshold(self):
        """Test 50MB threshold."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "processors" / "downloader"))
        from ytdlp import MAX_TG_VIDEO_SIZE

        # 50MB should be the threshold
        assert MAX_TG_VIDEO_SIZE == 50 * 1024 * 1024


class TestGetActualFilesize:
    """Test cases for HTTP HEAD file size detection."""

    def test_get_actual_filesize_success(self):
        """Test successful HEAD request returning content-length."""
        import sys
        import urllib.request
        sys.path.insert(0, str(Path(__file__).parent.parent / "processors" / "downloader"))
        from ytdlp import get_actual_filesize

        mock_response = MagicMock()
        mock_response.headers = {"Content-Length": "52428800"}  # 50MB
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch.object(urllib.request, 'urlopen', return_value=mock_response):
            result = get_actual_filesize("http://example.com/video.mp4")
            assert result == 52428800

    def test_get_actual_filesize_no_content_length(self):
        """Test HEAD request without content-length header returns None."""
        import sys
        import urllib.request
        sys.path.insert(0, str(Path(__file__).parent.parent / "processors" / "downloader"))
        from ytdlp import get_actual_filesize

        mock_response = MagicMock()
        mock_response.headers = {}
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch.object(urllib.request, 'urlopen', return_value=mock_response):
            result = get_actual_filesize("http://example.com/video.mp4")
            assert result is None

    def test_get_actual_filesize_http_error(self):
        """Test HEAD request with HTTP error returns None."""
        import sys
        import urllib.request
        import urllib.error
        sys.path.insert(0, str(Path(__file__).parent.parent / "processors" / "downloader"))
        from ytdlp import get_actual_filesize

        with patch.object(urllib.request, 'urlopen',
                          side_effect=urllib.error.HTTPError("http://example.com", 404, "Not Found", {}, None)):
            result = get_actual_filesize("http://example.com/video.mp4")
            assert result is None

    def test_get_actual_filesize_url_error(self):
        """Test HEAD request with URL error returns None."""
        import sys
        import urllib.request
        import urllib.error
        sys.path.insert(0, str(Path(__file__).parent.parent / "processors" / "downloader"))
        from ytdlp import get_actual_filesize

        with patch.object(urllib.request, 'urlopen',
                          side_effect=urllib.error.URLError("Connection refused")):
            result = get_actual_filesize("http://example.com/video.mp4")
            assert result is None

    def test_get_actual_filesize_uses_head_method(self):
        """Test that HEAD method is used, not GET."""
        import sys
        import urllib.request
        sys.path.insert(0, str(Path(__file__).parent.parent / "processors" / "downloader"))
        from ytdlp import get_actual_filesize

        captured_request = None

        def capture_request(req, *args, **kwargs):
            nonlocal captured_request
            captured_request = req
            mock_response = MagicMock()
            mock_response.headers = {"Content-Length": "1000"}
            mock_response.__enter__ = MagicMock(return_value=mock_response)
            mock_response.__exit__ = MagicMock(return_value=False)
            return mock_response

        with patch.object(urllib.request, 'urlopen', capture_request):
            get_actual_filesize("http://example.com/video.mp4")
            assert captured_request.method == "HEAD"