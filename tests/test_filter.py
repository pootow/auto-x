"""Tests for the DSL filter engine."""

import pytest
from datetime import datetime

from tele.filter import Lexer, Parser, MessageFilter, create_filter
from tele.filter import TokenType, Token


class MockMessage:
    """Mock message for testing."""

    def __init__(
        self,
        id: int = 1,
        text: str = "",
        sender_id: int = 123,
        date: datetime = None,
        forward=None,
        media=None,
        reactions=None,
    ):
        self.id = id
        self.text = text
        self.sender_id = sender_id
        self.date = date or datetime(2024, 1, 15, 10, 0, 0)
        self.forward = forward
        self.media = media
        self.reactions = reactions


class TestLexer:
    """Test cases for the DSL lexer."""

    def test_tokenize_string(self):
        """Test tokenizing string literals."""
        lexer = Lexer('"hello world"')
        tokens = lexer.tokenize()
        assert len(tokens) == 2
        assert tokens[0].type == TokenType.STRING
        assert tokens[0].value == "hello world"

    def test_tokenize_number(self):
        """Test tokenizing numbers."""
        lexer = Lexer("123")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.NUMBER
        assert tokens[0].value == 123

    def test_tokenize_identifier(self):
        """Test tokenizing identifiers."""
        lexer = Lexer("contains")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.IDENTIFIER
        assert tokens[0].value == "contains"

    def test_tokenize_operators(self):
        """Test tokenizing operators."""
        lexer = Lexer("&& || ! == != < <= > >=")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.AND
        assert tokens[1].type == TokenType.OR
        assert tokens[2].type == TokenType.NOT
        assert tokens[3].type == TokenType.EQ
        assert tokens[4].type == TokenType.NE
        assert tokens[5].type == TokenType.LT
        assert tokens[6].type == TokenType.LE
        assert tokens[7].type == TokenType.GT
        assert tokens[8].type == TokenType.GE

    def test_tokenize_function_call(self):
        """Test tokenizing function calls."""
        lexer = Lexer('contains("test")')
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.IDENTIFIER
        assert tokens[0].value == "contains"
        assert tokens[1].type == TokenType.LPAREN
        assert tokens[2].type == TokenType.STRING
        assert tokens[3].type == TokenType.RPAREN

    def test_tokenize_complex_expression(self):
        """Test tokenizing complex expressions."""
        lexer = Lexer('contains("test") && sender_id == 123')
        tokens = lexer.tokenize()
        # 8 tokens + EOF = 9
        assert len(tokens) == 9
        assert tokens[0].value == "contains"
        assert tokens[4].type == TokenType.AND


class TestParser:
    """Test cases for the DSL parser."""

    def test_parse_function_call(self):
        """Test parsing function calls."""
        lexer = Lexer('contains("test")')
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()
        assert ast.name == "contains"
        assert ast.args[0].value == "test"

    def test_parse_comparison(self):
        """Test parsing comparisons."""
        lexer = Lexer("sender_id == 123")
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()
        assert ast.left.name == "sender_id"
        assert ast.op == "=="
        assert ast.right.value == 123

    def test_parse_and_expression(self):
        """Test parsing AND expressions."""
        lexer = Lexer('contains("a") && contains("b")')
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()
        assert ast.op == "&&"
        assert ast.left.name == "contains"
        assert ast.right.name == "contains"

    def test_parse_or_expression(self):
        """Test parsing OR expressions."""
        lexer = Lexer('contains("a") || contains("b")')
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()
        assert ast.op == "||"

    def test_parse_not_expression(self):
        """Test parsing NOT expressions."""
        lexer = Lexer('!has_reaction("✅")')
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()
        assert ast.op == "!"
        assert ast.operand.name == "has_reaction"

    def test_parse_complex_expression(self):
        """Test parsing complex expressions."""
        lexer = Lexer('contains("urgent") && !has_reaction("✅")')
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()
        assert ast.op == "&&"
        assert ast.left.name == "contains"
        assert ast.right.op == "!"


class TestMessageFilter:
    """Test cases for message filtering."""

    def test_contains(self):
        """Test contains() filter."""
        filt = create_filter('contains("test")')
        msg = MockMessage(text="this is a test message")
        assert filt.matches(msg) is True

        msg2 = MockMessage(text="no match here")
        assert filt.matches(msg2) is False

    def test_sender_id_equals(self):
        """Test sender_id comparison."""
        filt = create_filter("sender_id == 123")
        msg = MockMessage(sender_id=123)
        assert filt.matches(msg) is True

        msg2 = MockMessage(sender_id=456)
        assert filt.matches(msg2) is False

    def test_and_combination(self):
        """Test AND combination."""
        filt = create_filter('contains("urgent") && sender_id == 123')
        msg = MockMessage(text="urgent message", sender_id=123)
        assert filt.matches(msg) is True

        msg2 = MockMessage(text="urgent message", sender_id=456)
        assert filt.matches(msg2) is False

    def test_or_combination(self):
        """Test OR combination."""
        filt = create_filter('contains("urgent") || contains("important")')
        msg = MockMessage(text="urgent message")
        assert filt.matches(msg) is True

        msg2 = MockMessage(text="important message")
        assert filt.matches(msg2) is True

        msg3 = MockMessage(text="normal message")
        assert filt.matches(msg3) is False

    def test_not_expression(self):
        """Test NOT expression."""
        filt = create_filter('!contains("spam")')
        msg = MockMessage(text="good message")
        assert filt.matches(msg) is True

        msg2 = MockMessage(text="spam message")
        assert filt.matches(msg2) is False

    def test_has_media(self):
        """Test has_media filter."""
        filt = create_filter("has_media")
        msg = MockMessage(media={"type": "photo"})
        assert filt.matches(msg) is True

        msg2 = MockMessage(media=None)
        assert filt.matches(msg2) is False

    def test_is_forwarded(self):
        """Test is_forwarded filter."""
        filt = create_filter("is_forwarded")
        msg = MockMessage(forward={"from_id": 789})
        assert filt.matches(msg) is True

        msg2 = MockMessage(forward=None)
        assert filt.matches(msg2) is False

    def test_complex_filter(self):
        """Test complex filter expression."""
        filt = create_filter('(contains("urgent") || contains("important")) && !has_reaction("✅")')
        # This would require has_reaction to work with mock, which needs more setup
        # For now, just test the parsing
        assert filt.expression == '(contains("urgent") || contains("important")) && !has_reaction("✅")'

    def test_message_id_comparison(self):
        """Test message_id comparisons."""
        filt = create_filter("message_id > 100")
        msg = MockMessage(id=150)
        assert filt.matches(msg) is True

        msg2 = MockMessage(id=50)
        assert filt.matches(msg2) is False

    def test_empty_text(self):
        """Test filter with empty text."""
        filt = create_filter('contains("test")')
        msg = MockMessage(text="")
        assert filt.matches(msg) is False

        msg2 = MockMessage(text=None)
        assert filt.matches(msg2) is False