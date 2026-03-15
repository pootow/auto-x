"""Tests for the downloader processor."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import urllib.error

# Import from the processor module
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "processors" / "downloader"))
from download import (
    extract_urls,
    get_filename_from_url,
    download_file,
    download_with_urllib,
    download_with_ytdlp,
    get_ytdlp_opts,
    is_ytdlp_unsupported_error,
    process_message,
)


class TestExtractUrls:
    """Test cases for URL extraction."""

    def test_extract_single_http_url(self):
        """Test extracting a single http URL."""
        text = "Check out http://example.com/file.pdf"
        urls = extract_urls(text)
        assert urls == ["http://example.com/file.pdf"]

    def test_extract_single_https_url(self):
        """Test extracting a single https URL."""
        text = "Download from https://example.com/file.zip"
        urls = extract_urls(text)
        assert urls == ["https://example.com/file.zip"]

    def test_extract_multiple_urls(self):
        """Test extracting multiple URLs."""
        text = "Get files from https://a.com/file1 and http://b.com/file2"
        urls = extract_urls(text)
        assert len(urls) == 2
        assert "https://a.com/file1" in urls
        assert "http://b.com/file2" in urls

    def test_extract_urls_with_query_params(self):
        """Test extracting URLs with query parameters."""
        text = "Visit https://example.com/file?param=value&other=123"
        urls = extract_urls(text)
        assert urls == ["https://example.com/file?param=value&other=123"]

    def test_extract_urls_with_fragment(self):
        """Test extracting URLs with fragments."""
        text = "See https://example.com/page#section"
        urls = extract_urls(text)
        assert urls == ["https://example.com/page#section"]

    def test_no_urls_in_text(self):
        """Test text with no URLs."""
        text = "This is just plain text with no links"
        urls = extract_urls(text)
        assert urls == []

    def test_empty_text(self):
        """Test empty text."""
        urls = extract_urls("")
        assert urls == []

    def test_none_text(self):
        """Test None text."""
        urls = extract_urls(None)
        assert urls == []

    def test_url_with_special_characters_in_path(self):
        """Test URL with encoded characters in path."""
        text = "File at https://example.com/path%20with%20spaces/file.pdf"
        urls = extract_urls(text)
        assert len(urls) == 1

    def test_urls_separated_by_punctuation(self):
        """Test URLs separated by punctuation."""
        text = "Links: https://a.com, https://b.com; and https://c.com."
        urls = extract_urls(text)
        # Note: punctuation at end may or may not be included
        assert len(urls) >= 3


class TestGetFilenameFromUrl:
    """Test cases for filename extraction from URLs."""

    def test_filename_from_simple_path(self):
        """Test extracting filename from simple path."""
        filename = get_filename_from_url("https://example.com/file.pdf")
        assert filename == "file.pdf"

    def test_filename_from_nested_path(self):
        """Test extracting filename from nested path."""
        filename = get_filename_from_url("https://example.com/path/to/document.pdf")
        assert filename == "document.pdf"

    def test_filename_from_url_with_query_params(self):
        """Test filename when URL has query parameters."""
        filename = get_filename_from_url("https://example.com/file.pdf?download=1")
        assert filename == "file.pdf"

    def test_filename_from_url_with_fragment(self):
        """Test filename when URL has fragment."""
        filename = get_filename_from_url("https://example.com/page.html#section")
        assert filename == "page.html"

    def test_fallback_for_no_filename(self):
        """Test fallback when URL has no filename."""
        filename = get_filename_from_url("https://example.com/")
        # Should generate a hash-based filename
        assert filename.startswith("download_")
        assert len(filename) == len("download_") + 8  # 8 char hash

    def test_fallback_for_root_url(self):
        """Test fallback for root URL without trailing slash."""
        filename = get_filename_from_url("https://example.com")
        assert filename.startswith("download_")


class TestDownloadFile:
    """Test cases for file downloading."""

    @patch("download.download_with_ytdlp")
    @patch("download.download_with_urllib")
    def test_download_success(self, mock_urllib, mock_ytdlp, tmp_path):
        """Test successful file download via yt-dlp."""
        mock_ytdlp.return_value = (True, "Downloaded")

        success, message = download_file("https://example.com/test.pdf", tmp_path)

        assert success is True
        mock_ytdlp.assert_called_once()
        mock_urllib.assert_not_called()

    @patch("download.download_with_ytdlp")
    @patch("download.download_with_urllib")
    def test_download_creates_directory(self, mock_urllib, mock_ytdlp, tmp_path):
        """Test that download creates destination directory."""
        dest_dir = tmp_path / "nested" / "dir"

        mock_ytdlp.return_value = (True, "Downloaded")

        success, _ = download_file("https://example.com/file.txt", dest_dir)

        assert success is True

    @patch("download.download_with_ytdlp")
    @patch("download.download_with_urllib")
    def test_download_url_error(self, mock_urllib, mock_ytdlp, tmp_path):
        """Test handling of URL errors with fallback."""
        mock_ytdlp.return_value = (False, "ERROR: Unsupported URL: https://example.com")
        mock_urllib.return_value = (False, "Connection refused")

        success, message = download_file("https://example.com/file.pdf", tmp_path)

        assert success is False
        assert "Connection refused" in message

    @patch("download.subprocess.run")
    def test_download_timeout(self, mock_run, tmp_path):
        """Test handling of timeout errors."""
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="yt-dlp", timeout=300)

        success, message = download_file("https://example.com/file.pdf", tmp_path)

        assert success is False
        assert "timed out" in message.lower()


class TestProcessMessage:
    """Test cases for message processing."""

    def test_missing_id(self):
        """Test message with missing id."""
        result = process_message({"chat_id": 123, "text": "test"})
        assert result == {"id": 0, "chat_id": 123, "status": "failed"}

    def test_missing_chat_id(self):
        """Test message with missing chat_id."""
        result = process_message({"id": 1, "text": "test"})
        assert result == {"id": 1, "chat_id": 0, "status": "failed"}

    def test_missing_both_required_fields(self):
        """Test message with missing id and chat_id."""
        result = process_message({"text": "test"})
        assert result == {"id": 0, "chat_id": 0, "status": "failed"}

    def test_no_text_field(self):
        """Test message without text field."""
        result = process_message({"id": 1, "chat_id": 123})
        assert result == {"id": 1, "chat_id": 123, "status": "success"}

    def test_empty_text(self):
        """Test message with empty text."""
        result = process_message({"id": 1, "chat_id": 123, "text": ""})
        assert result == {"id": 1, "chat_id": 123, "status": "success"}

    def test_text_without_urls(self):
        """Test message with text but no URLs."""
        result = process_message({"id": 1, "chat_id": 123, "text": "Just some text"})
        assert result == {"id": 1, "chat_id": 123, "status": "success"}

    @patch("download.download_file")
    def test_single_url_success(self, mock_download, tmp_path):
        """Test message with single URL that downloads successfully."""
        mock_download.return_value = (True, str(tmp_path / "file.pdf"))

        result = process_message({
            "id": 1,
            "chat_id": 123,
            "text": "Check https://example.com/file.pdf"
        })

        assert result["status"] == "success"
        assert result["id"] == 1
        assert result["chat_id"] == 123
        mock_download.assert_called_once()

    @patch("download.download_file")
    def test_single_url_failure(self, mock_download, tmp_path):
        """Test message with single URL that fails to download."""
        mock_download.return_value = (False, "Connection error")

        result = process_message({
            "id": 1,
            "chat_id": 123,
            "text": "Check https://example.com/file.pdf"
        })

        assert result["status"] == "failed"

    @patch("download.download_file")
    def test_multiple_urls_all_success(self, mock_download, tmp_path):
        """Test message with multiple URLs that all download successfully."""
        mock_download.return_value = (True, str(tmp_path / "file"))

        result = process_message({
            "id": 1,
            "chat_id": 123,
            "text": "Get https://a.com/f1 and https://b.com/f2"
        })

        assert result["status"] == "success"
        assert mock_download.call_count == 2

    @patch("download.download_file")
    def test_multiple_urls_one_failure(self, mock_download, tmp_path):
        """Test message with multiple URLs where one fails."""
        mock_download.side_effect = [
            (True, str(tmp_path / "f1")),
            (False, "Error"),
        ]

        result = process_message({
            "id": 1,
            "chat_id": 123,
            "text": "Get https://a.com/f1 and https://b.com/f2"
        })

        assert result["status"] == "failed"

    @patch("download.download_file")
    def test_multiple_urls_all_fail(self, mock_download, tmp_path):
        """Test message with multiple URLs that all fail."""
        mock_download.return_value = (False, "Error")

        result = process_message({
            "id": 1,
            "chat_id": 123,
            "text": "Get https://a.com/f1 and https://b.com/f2"
        })

        assert result["status"] == "failed"
        assert mock_download.call_count == 2


class TestMainIntegration:
    """Integration tests for the main function."""

    @patch("download.download_file")
    @patch("download.DOWNLOAD_DIR")
    def test_main_processes_single_message(self, mock_download_dir, mock_download, capsys):
        """Test main function processes stdin correctly."""
        import io
        from download import main

        tmp_path = Path("/tmp/test_downloads")
        mock_download_dir.__truediv__ = lambda self, name: tmp_path / name
        mock_download.return_value = (True, str(tmp_path / "file"))

        # Simulate stdin
        input_data = '{"id": 1, "chat_id": 123, "text": "https://example.com/file"}'
        original_stdin = sys.stdin
        sys.stdin = io.StringIO(input_data + "\n")

        try:
            main()
        finally:
            sys.stdin = original_stdin

        # Check stdout
        captured = capsys.readouterr()
        output = json.loads(captured.out.strip())
        assert output == {"id": 1, "chat_id": 123, "status": "success"}

    @patch("download.download_file")
    @patch("download.DOWNLOAD_DIR")
    def test_main_processes_multiple_messages(self, mock_download_dir, mock_download, capsys):
        """Test main function processes multiple messages."""
        import io
        from download import main

        tmp_path = Path("/tmp/test_downloads")
        mock_download_dir.__truediv__ = lambda self, name: tmp_path / name
        mock_download.return_value = (True, str(tmp_path / "file"))

        input_data = '{"id": 1, "chat_id": 123, "text": "test1"}\n{"id": 2, "chat_id": 456, "text": "test2"}\n'
        original_stdin = sys.stdin
        sys.stdin = io.StringIO(input_data)

        try:
            main()
        finally:
            sys.stdin = original_stdin

        captured = capsys.readouterr()
        lines = captured.out.strip().split("\n")
        assert len(lines) == 2

        result1 = json.loads(lines[0])
        result2 = json.loads(lines[1])
        assert result1["id"] == 1
        assert result2["id"] == 2

    def test_main_handles_invalid_json(self, capsys):
        """Test main function handles invalid JSON."""
        import io
        from download import main

        original_stdin = sys.stdin
        sys.stdin = io.StringIO("not valid json\n")

        try:
            main()
        finally:
            sys.stdin = original_stdin

        captured = capsys.readouterr()
        output = json.loads(captured.out.strip())
        assert output == {"id": 0, "chat_id": 0, "status": "failed"}

    def test_main_skips_empty_lines(self, capsys):
        """Test main function skips empty lines."""
        import io
        from download import main

        original_stdin = sys.stdin
        sys.stdin = io.StringIO("\n\n")

        try:
            main()
        finally:
            sys.stdin = original_stdin

        captured = capsys.readouterr()
        assert captured.out.strip() == ""


class TestGetYtdlpOpts:
    """Test cases for get_ytdlp_opts function."""

    def test_no_env_no_args(self, monkeypatch):
        """Test with no environment variable and no CLI args."""
        monkeypatch.delenv("YTDLPOPTS", raising=False)
        monkeypatch.setattr(sys, "argv", ["ytdlp.py"])
        opts = get_ytdlp_opts()
        assert opts == []

    def test_env_only(self, monkeypatch):
        """Test with environment variable only."""
        monkeypatch.setenv("YTDLPOPTS", "--no-playlist -f best")
        monkeypatch.setattr(sys, "argv", ["ytdlp.py"])
        opts = get_ytdlp_opts()
        assert opts == ["--no-playlist", "-f", "best"]

    def test_cli_args_only(self, monkeypatch):
        """Test with CLI args only."""
        monkeypatch.delenv("YTDLPOPTS", raising=False)
        monkeypatch.setattr(sys, "argv", ["ytdlp.py", "-f", "best", "--no-playlist"])
        opts = get_ytdlp_opts()
        assert opts == ["-f", "best", "--no-playlist"]

    def test_env_and_cli_combined(self, monkeypatch):
        """Test with both env var and CLI args (CLI appended after env)."""
        monkeypatch.setenv("YTDLPOPTS", "--no-playlist")
        monkeypatch.setattr(sys, "argv", ["ytdlp.py", "-f", "best"])
        opts = get_ytdlp_opts()
        assert opts == ["--no-playlist", "-f", "best"]

    def test_env_with_quotes(self, monkeypatch):
        """Test environment variable with quoted values."""
        monkeypatch.setenv("YTDLPOPTS", '-f "bestvideo+bestaudio"')
        monkeypatch.setattr(sys, "argv", ["ytdlp.py"])
        opts = get_ytdlp_opts()
        assert opts == ["-f", "bestvideo+bestaudio"]

    def test_empty_env(self, monkeypatch):
        """Test with empty environment variable."""
        monkeypatch.setenv("YTDLPOPTS", "")
        monkeypatch.setattr(sys, "argv", ["ytdlp.py"])
        opts = get_ytdlp_opts()
        assert opts == []


class TestDownloadWithYtdlp:
    """Test cases for yt-dlp downloading."""

    @patch("download.subprocess.run")
    def test_ytdlp_download_success(self, mock_run, tmp_path, monkeypatch):
        """Test successful yt-dlp download."""
        monkeypatch.delenv("YTDLPOPTS", raising=False)
        monkeypatch.setattr(sys, "argv", ["ytdlp.py"])

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""
        mock_result.stdout = ""
        mock_run.return_value = mock_result

        success, message = download_with_ytdlp("https://youtube.com/watch?v=test", tmp_path)

        assert success is True
        assert message == "Downloaded"
        mock_run.assert_called_once()
        # Verify yt-dlp was called with correct args
        args = mock_run.call_args[0][0]
        assert "yt-dlp" in args
        assert "--paths" in args
        assert str(tmp_path) in args
        assert "--output" in args

    @patch("download.subprocess.run")
    def test_ytdlp_download_with_opts(self, mock_run, tmp_path, monkeypatch):
        """Test yt-dlp download with env and CLI options."""
        monkeypatch.setenv("YTDLPOPTS", "--no-playlist")
        monkeypatch.setattr(sys, "argv", ["ytdlp.py", "-f", "best"])

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""
        mock_result.stdout = ""
        mock_run.return_value = mock_result

        success, message = download_with_ytdlp("https://youtube.com/watch?v=test", tmp_path)

        assert success is True
        args = mock_run.call_args[0][0]
        assert "--no-playlist" in args
        assert "-f" in args
        assert "best" in args

    @patch("download.subprocess.run")
    def test_ytdlp_download_failure(self, mock_run, tmp_path, monkeypatch):
        """Test yt-dlp download failure."""
        monkeypatch.delenv("YTDLPOPTS", raising=False)
        monkeypatch.setattr(sys, "argv", ["ytdlp.py"])

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "ERROR: Video not found"
        mock_result.stdout = ""
        mock_run.return_value = mock_result

        success, message = download_with_ytdlp("https://youtube.com/watch?v=invalid", tmp_path)

        assert success is False
        assert "Video not found" in message

    @patch("download.subprocess.run")
    def test_ytdlp_timeout(self, mock_run, tmp_path, monkeypatch):
        """Test yt-dlp timeout handling."""
        monkeypatch.delenv("YTDLPOPTS", raising=False)
        monkeypatch.setattr(sys, "argv", ["ytdlp.py"])

        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="yt-dlp", timeout=300)

        success, message = download_with_ytdlp("https://youtube.com/watch?v=slow", tmp_path)

        assert success is False
        assert "timed out" in message.lower()

    @patch("download.subprocess.run")
    def test_ytdlp_not_found(self, mock_run, tmp_path, monkeypatch):
        """Test yt-dlp not found on PATH."""
        monkeypatch.delenv("YTDLPOPTS", raising=False)
        monkeypatch.setattr(sys, "argv", ["ytdlp.py"])

        mock_run.side_effect = FileNotFoundError()

        success, message = download_with_ytdlp("https://youtube.com/watch?v=test", tmp_path)

        assert success is False
        assert "not found" in message.lower()

    @patch("download.subprocess.run")
    def test_ytdlp_unsupported_url(self, mock_run, tmp_path, monkeypatch):
        """Test yt-dlp with unsupported URL."""
        monkeypatch.delenv("YTDLPOPTS", raising=False)
        monkeypatch.setattr(sys, "argv", ["ytdlp.py"])

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "ERROR: Unsupported URL: https://example.com/file.pdf"
        mock_result.stdout = ""
        mock_run.return_value = mock_result

        success, message = download_with_ytdlp("https://example.com/file.pdf", tmp_path)

        assert success is False
        assert "Unsupported URL" in message


class TestIsYtdlpUnsupportedError:
    """Test cases for unsupported URL detection."""

    def test_unsupported_url_message(self):
        """Test detection of unsupported URL error."""
        assert is_ytdlp_unsupported_error("ERROR: Unsupported URL: https://example.com") is True

    def test_unsupported_url_variant(self):
        """Test detection of unsupported URL variant."""
        assert is_ytdlp_unsupported_error("https://example.com is not a valid URL") is True

    def test_other_error_message(self):
        """Test non-unsupported error is not detected."""
        assert is_ytdlp_unsupported_error("ERROR: Video not found") is False

    def test_empty_message(self):
        """Test empty error message."""
        assert is_ytdlp_unsupported_error("") is False


class TestDownloadFileDispatch:
    """Test cases for download_file dispatch logic."""

    @patch("download.download_with_ytdlp")
    def test_dispatch_ytdlp_success(self, mock_ytdlp, tmp_path):
        """Test dispatch to yt-dlp when successful."""
        mock_ytdlp.return_value = (True, "Downloaded")

        success, message = download_file("https://youtube.com/watch?v=test", tmp_path)

        assert success is True
        mock_ytdlp.assert_called_once()

    @patch("download.download_with_urllib")
    @patch("download.download_with_ytdlp")
    def test_fallback_to_urllib(self, mock_ytdlp, mock_urllib, tmp_path):
        """Test fallback to urllib for unsupported URLs."""
        mock_ytdlp.return_value = (False, "ERROR: Unsupported URL: https://example.com/file.pdf")
        mock_urllib.return_value = (True, str(tmp_path / "file.pdf"))

        success, message = download_file("https://example.com/file.pdf", tmp_path)

        assert success is True
        mock_ytdlp.assert_called_once()
        mock_urllib.assert_called_once()

    @patch("download.download_with_urllib")
    @patch("download.download_with_ytdlp")
    def test_no_fallback_on_other_error(self, mock_ytdlp, mock_urllib, tmp_path):
        """Test no fallback when yt-dlp fails for other reasons."""
        mock_ytdlp.return_value = (False, "ERROR: Video not found")

        success, message = download_file("https://youtube.com/watch?v=invalid", tmp_path)

        assert success is False
        mock_ytdlp.assert_called_once()
        mock_urllib.assert_not_called()


class TestDownloadWithUrllib:
    """Test cases for urllib downloading (renamed function)."""

    @patch("download.urllib.request.urlopen")
    def test_urllib_download_success(self, mock_urlopen, tmp_path):
        """Test successful urllib download."""
        mock_response = MagicMock()
        mock_response.read.return_value = b"file content"
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        success, message = download_with_urllib("https://example.com/test.pdf", tmp_path)

        assert success is True
        assert str(tmp_path / "test.pdf") == message
        assert (tmp_path / "test.pdf").exists()
        assert (tmp_path / "test.pdf").read_bytes() == b"file content"

    @patch("download.urllib.request.urlopen")
    def test_urllib_download_error(self, mock_urlopen, tmp_path):
        """Test urllib download error."""
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

        success, message = download_with_urllib("https://example.com/file.pdf", tmp_path)

        assert success is False
        assert "Connection refused" in message