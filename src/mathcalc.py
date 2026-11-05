"""Safe calculator for the math mode (F7). No eval: only numbers and + - * / ^ ( ) %."""

from __future__ import annotations

import ast
import math
import operator
import re

# Characters that can be part of a math expression while typing.
MATH_CHARS = set("0123456789+-*/×xX÷:^().,=% ")

_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
}


def _normalise(expression: str) -> str:
    text = expression.strip().rstrip("=").strip()
    text = text.replace("×", "*").replace("x", "*").replace("X", "*")
    text = text.replace("÷", "/").replace(":", "/").replace("^", "**")
    # Norwegian decimal comma: 2,5 -> 2.5
    text = re.sub(r"(\d),(\d)", r"\1.\2", text)
    # 20% -> (20/100)
    text = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"(\1/100)", text)
    return text


def _evaluate(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _evaluate(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _evaluate(node.operand)
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
        left, right = _evaluate(node.left), _evaluate(node.right)
        if isinstance(node.op, ast.Pow) and (abs(right) > 100 or abs(left) > 1e6):
            raise ValueError("for stort tall")
        return _OPERATORS[type(node.op)](left, right)
    raise ValueError("ikke et mattestykke")


def format_number(value: float, language: str = "nb") -> str:
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        value = int(value)
    if isinstance(value, int):
        text = f"{value}"
    else:
        text = f"{value:.10g}"
    if language == "nb":
        text = text.replace(".", ",")
    return text


def calculate(expression: str, language: str = "nb") -> tuple[str, str] | None:
    """Return (what to show, what to type) or None if this is not a calculation.

    "9*9"  -> ("9*9 = 81", "9*9 = 81")
    "9*9=" -> ("9*9 = 81", "9*9=81")
    """
    typed = expression.strip()
    if not typed:
        return None
    text = _normalise(typed)
    # Needs at least one operator between two numbers.
    if not re.search(r"\d\s*(\*\*|[-+*/])\s*[-+(]*\d", text):
        return None
    try:
        value = _evaluate(ast.parse(text, mode="eval"))
    except ZeroDivisionError:
        return (f"{typed.rstrip('=').strip()} = kan ikke dele på 0", "")
    except (SyntaxError, ValueError, TypeError, OverflowError, RecursionError):
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    result = format_number(value, language)
    shown = f"{typed.rstrip('=').strip()} = {result}"
    if expression.rstrip().endswith("="):
        insert = expression + result
    else:
        insert = expression.rstrip() + " = " + result
    return shown, insert
