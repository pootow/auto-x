"""DSL filter engine for message matching."""

import re
import operator
from datetime import datetime
from typing import Any, Callable, Optional
from dataclasses import dataclass
from enum import Enum, auto


class TokenType(Enum):
    """Token types for the DSL lexer."""
    IDENTIFIER = auto()
    STRING = auto()
    NUMBER = auto()
    LPAREN = auto()
    RPAREN = auto()
    AND = auto()
    OR = auto()
    NOT = auto()
    EQ = auto()
    NE = auto()
    LT = auto()
    LE = auto()
    GT = auto()
    GE = auto()
    EOF = auto()


@dataclass
class Token:
    """A token from the lexer."""
    type: TokenType
    value: Any
    position: int


class Lexer:
    """Tokenizer for the DSL filter language."""

    KEYWORDS = {
        'contains': TokenType.IDENTIFIER,
        'sender_id': TokenType.IDENTIFIER,
        'sender_name': TokenType.IDENTIFIER,
        'has_reaction': TokenType.IDENTIFIER,
        'is_forwarded': TokenType.IDENTIFIER,
        'has_media': TokenType.IDENTIFIER,
        'message_id': TokenType.IDENTIFIER,
        'date': TokenType.IDENTIFIER,
    }

    def __init__(self, text: str):
        """Initialize lexer with input text.

        Args:
            text: DSL expression to tokenize
        """
        self.text = text
        self.pos = 0
        self.current_char = text[0] if text else None

    def advance(self) -> None:
        """Advance position and update current_char."""
        self.pos += 1
        self.current_char = self.text[self.pos] if self.pos < len(self.text) else None

    def skip_whitespace(self) -> None:
        """Skip whitespace characters."""
        while self.current_char and self.current_char.isspace():
            self.advance()

    def read_string(self, quote_char: str) -> str:
        """Read a quoted string.

        Args:
            quote_char: The quote character (' or ")

        Returns:
            The string contents
        """
        result = []
        self.advance()  # Skip opening quote
        while self.current_char and self.current_char != quote_char:
            if self.current_char == '\\':
                self.advance()
                if self.current_char:
                    result.append(self.current_char)
                    self.advance()
            else:
                result.append(self.current_char)
                self.advance()
        self.advance()  # Skip closing quote
        return ''.join(result)

    def read_number(self) -> int | float:
        """Read a number.

        Returns:
            The parsed number
        """
        result = []
        has_dot = False
        while self.current_char and (self.current_char.isdigit() or self.current_char == '.'):
            if self.current_char == '.':
                if has_dot:
                    break
                has_dot = True
            result.append(self.current_char)
            self.advance()

        num_str = ''.join(result)
        return float(num_str) if has_dot else int(num_str)

    def read_identifier(self) -> str:
        """Read an identifier.

        Returns:
            The identifier name
        """
        result = []
        while self.current_char and (self.current_char.isalnum() or self.current_char == '_'):
            result.append(self.current_char)
            self.advance()
        return ''.join(result)

    def get_next_token(self) -> Token:
        """Get the next token from input.

        Returns:
            Next token
        """
        while self.current_char:
            # Skip whitespace
            if self.current_char.isspace():
                self.skip_whitespace()
                continue

            pos = self.pos

            # String literals
            if self.current_char in ('"', "'"):
                return Token(TokenType.STRING, self.read_string(self.current_char), pos)

            # Numbers
            if self.current_char.isdigit():
                return Token(TokenType.NUMBER, self.read_number(), pos)

            # Identifiers
            if self.current_char.isalpha() or self.current_char == '_':
                name = self.read_identifier()
                return Token(self.KEYWORDS.get(name, TokenType.IDENTIFIER), name, pos)

            # Two-character operators
            if self.current_char == '&' and self.pos + 1 < len(self.text) and self.text[self.pos + 1] == '&':
                self.advance()
                self.advance()
                return Token(TokenType.AND, '&&', pos)

            if self.current_char == '|' and self.pos + 1 < len(self.text) and self.text[self.pos + 1] == '|':
                self.advance()
                self.advance()
                return Token(TokenType.OR, '||', pos)

            if self.current_char == '=' and self.pos + 1 < len(self.text) and self.text[self.pos + 1] == '=':
                self.advance()
                self.advance()
                return Token(TokenType.EQ, '==', pos)

            if self.current_char == '!' and self.pos + 1 < len(self.text) and self.text[self.pos + 1] == '=':
                self.advance()
                self.advance()
                return Token(TokenType.NE, '!=', pos)

            if self.current_char == '<' and self.pos + 1 < len(self.text) and self.text[self.pos + 1] == '=':
                self.advance()
                self.advance()
                return Token(TokenType.LE, '<=', pos)

            if self.current_char == '>' and self.pos + 1 < len(self.text) and self.text[self.pos + 1] == '=':
                self.advance()
                self.advance()
                return Token(TokenType.GE, '>=', pos)

            # Single-character tokens
            char = self.current_char
            self.advance()

            if char == '(':
                return Token(TokenType.LPAREN, '(', pos)
            if char == ')':
                return Token(TokenType.RPAREN, ')', pos)
            if char == '!':
                return Token(TokenType.NOT, '!', pos)
            if char == '<':
                return Token(TokenType.LT, '<', pos)
            if char == '>':
                return Token(TokenType.GT, '>', pos)

            raise SyntaxError(f"Unexpected character: {char} at position {pos}")

        return Token(TokenType.EOF, None, self.pos)

    def tokenize(self) -> list[Token]:
        """Tokenize the entire input.

        Returns:
            List of all tokens
        """
        tokens = []
        while True:
            token = self.get_next_token()
            tokens.append(token)
            if token.type == TokenType.EOF:
                break
        return tokens


# AST Node types
@dataclass
class FunctionCall:
    """A function call expression."""
    name: str
    args: list


@dataclass
class BinaryOp:
    """A binary operation."""
    left: Any
    op: str
    right: Any


@dataclass
class UnaryOp:
    """A unary operation."""
    op: str
    operand: Any


@dataclass
class Identifier:
    """An identifier reference."""
    name: str


@dataclass
class Literal:
    """A literal value."""
    value: Any


class Parser:
    """Parser for the DSL filter language."""

    def __init__(self, tokens: list[Token]):
        """Initialize parser with tokens.

        Args:
            tokens: List of tokens from lexer
        """
        self.tokens = tokens
        self.pos = 0
        self.current_token = tokens[0] if tokens else Token(TokenType.EOF, None, 0)

    def advance(self) -> None:
        """Advance to next token."""
        self.pos += 1
        if self.pos < len(self.tokens):
            self.current_token = self.tokens[self.pos]
        else:
            self.current_token = Token(TokenType.EOF, None, self.pos)

    def parse(self) -> Any:
        """Parse the entire expression.

        Returns:
            AST root node
        """
        return self.parse_or_expression()

    def parse_or_expression(self) -> Any:
        """Parse OR expressions.

        Returns:
            AST node
        """
        left = self.parse_and_expression()

        while self.current_token.type == TokenType.OR:
            self.advance()
            right = self.parse_and_expression()
            left = BinaryOp(left, '||', right)

        return left

    def parse_and_expression(self) -> Any:
        """Parse AND expressions.

        Returns:
            AST node
        """
        left = self.parse_unary_expression()

        while self.current_token.type == TokenType.AND:
            self.advance()
            right = self.parse_unary_expression()
            left = BinaryOp(left, '&&', right)

        return left

    def parse_unary_expression(self) -> Any:
        """Parse unary expressions.

        Returns:
            AST node
        """
        if self.current_token.type == TokenType.NOT:
            self.advance()
            operand = self.parse_unary_expression()
            return UnaryOp('!', operand)

        return self.parse_comparison()

    def parse_comparison(self) -> Any:
        """Parse comparison expressions.

        Returns:
            AST node
        """
        left = self.parse_primary()

        comparison_ops = {
            TokenType.EQ: '==',
            TokenType.NE: '!=',
            TokenType.LT: '<',
            TokenType.LE: '<=',
            TokenType.GT: '>',
            TokenType.GE: '>=',
        }

        if self.current_token.type in comparison_ops:
            op = comparison_ops[self.current_token.type]
            self.advance()
            right = self.parse_primary()
            return BinaryOp(left, op, right)

        return left

    def parse_primary(self) -> Any:
        """Parse primary expressions.

        Returns:
            AST node
        """
        token = self.current_token

        if token.type == TokenType.NUMBER:
            self.advance()
            return Literal(token.value)

        if token.type == TokenType.STRING:
            self.advance()
            return Literal(token.value)

        if token.type == TokenType.IDENTIFIER:
            name = token.value
            self.advance()

            # Check for function call
            if self.current_token.type == TokenType.LPAREN:
                self.advance()  # consume '('
                args = []
                if self.current_token.type != TokenType.RPAREN:
                    args.append(self.parse_or_expression())
                    while self.current_token.type != TokenType.RPAREN:
                        # Skip commas if present
                        if self.current_token.type == TokenType.IDENTIFIER and self.current_token.value == ',':
                            self.advance()
                        args.append(self.parse_or_expression())
                self.advance()  # consume ')'
                return FunctionCall(name, args)

            return Identifier(name)

        if token.type == TokenType.LPAREN:
            self.advance()
            expr = self.parse_or_expression()
            if self.current_token.type != TokenType.RPAREN:
                raise SyntaxError(f"Expected ')' at position {self.current_token.position}")
            self.advance()
            return expr

        raise SyntaxError(f"Unexpected token: {token.type} at position {token.position}")


class MessageFilter:
    """Filter for evaluating DSL expressions against messages."""

    def __init__(self, expression: str):
        """Initialize filter with DSL expression.

        Args:
            expression: DSL filter expression
        """
        self.expression = expression
        self.ast = self._parse(expression)

    def _parse(self, expression: str) -> Any:
        """Parse expression to AST.

        Args:
            expression: DSL filter expression

        Returns:
            AST root node
        """
        lexer = Lexer(expression)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        return parser.parse()

    def matches(self, message: Any) -> bool:
        """Check if a message matches the filter.

        Args:
            message: Telethon Message object

        Returns:
            True if message matches filter
        """
        return self._evaluate(self.ast, message)

    def _evaluate(self, node: Any, message: Any) -> Any:
        """Evaluate an AST node against a message.

        Args:
            node: AST node
            message: Telethon Message object

        Returns:
            Evaluation result
        """
        if isinstance(node, Literal):
            return node.value

        if isinstance(node, Identifier):
            return self._get_field(node.name, message)

        if isinstance(node, FunctionCall):
            return self._call_function(node.name, node.args, message)

        if isinstance(node, UnaryOp):
            if node.op == '!':
                return not self._evaluate(node.operand, message)
            raise ValueError(f"Unknown unary operator: {node.op}")

        if isinstance(node, BinaryOp):
            left = self._evaluate(node.left, message)
            right = self._evaluate(node.right, message)

            if node.op == '&&':
                return bool(left) and bool(self._evaluate(node.right, message))
            if node.op == '||':
                return bool(left) or bool(self._evaluate(node.right, message))

            ops = {
                '==': operator.eq,
                '!=': operator.ne,
                '<': operator.lt,
                '<=': operator.le,
                '>': operator.gt,
                '>=': operator.ge,
            }

            if node.op in ops:
                return ops[node.op](left, right)

            raise ValueError(f"Unknown operator: {node.op}")

        raise ValueError(f"Unknown node type: {type(node)}")

    def _get_field(self, name: str, message: Any) -> Any:
        """Get a field value from a message.

        Args:
            name: Field name
            message: Telethon Message object

        Returns:
            Field value
        """
        field_map = {
            'message_id': 'id',
            'sender_id': 'sender_id',
            'sender_name': None,  # Need to compute
            'date': 'date',
            'text': 'text',
            'is_forwarded': 'forward',
            'has_media': 'media',
        }

        if name in ('sender_id', 'message_id', 'date', 'text'):
            return getattr(message, field_map[name], None)

        if name == 'sender_name':
            # sender_id is resolved by the client separately
            # For now, return the sender_id; this can be enhanced
            return getattr(message, 'sender_id', None)

        if name == 'is_forwarded':
            return getattr(message, 'forward', None) is not None

        if name == 'has_media':
            return getattr(message, 'media', None) is not None

        return getattr(message, name, None)

    def _call_function(self, name: str, args: list, message: Any) -> Any:
        """Call a filter function.

        Args:
            name: Function name
            args: Function arguments
            message: Telethon Message object

        Returns:
            Function result
        """
        if name == 'contains':
            if len(args) != 1:
                raise ValueError("contains() requires exactly 1 argument")
            keyword = self._evaluate(args[0], message)
            text = getattr(message, 'text', '') or ''
            return keyword in text

        if name == 'has_reaction':
            if len(args) != 1:
                raise ValueError("has_reaction() requires exactly 1 argument")
            emoji = self._evaluate(args[0], message)
            reactions = getattr(message, 'reactions', None)
            if not reactions:
                return False
            # reactions is a MessageReactions object
            for reaction in reactions.results:
                if reaction.reaction.emoticon == emoji:
                    return True
            return False

        if name == 'sender_id':
            if len(args) != 0:
                raise ValueError("sender_id does not take arguments")
            return getattr(message, 'sender_id', None)

        if name == 'sender_name':
            if len(args) != 0:
                raise ValueError("sender_name does not take arguments")
            return getattr(message, 'sender_id', None)  # Placeholder

        if name == 'is_forwarded':
            if len(args) != 0:
                raise ValueError("is_forwarded does not take arguments")
            return getattr(message, 'forward', None) is not None

        if name == 'has_media':
            if len(args) != 0:
                raise ValueError("has_media does not take arguments")
            return getattr(message, 'media', None) is not None

        raise ValueError(f"Unknown function: {name}")


def create_filter(expression: str) -> MessageFilter:
    """Create a message filter from a DSL expression.

    Args:
        expression: DSL filter expression

    Returns:
        MessageFilter instance
    """
    return MessageFilter(expression)