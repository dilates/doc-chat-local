"""Sample Python file for testing the code loader and chunker."""

MODULE_CONSTANT = 42


def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


def multiply(a: int, b: int) -> int:
    """Multiply two numbers."""
    return a * b


class Calculator:
    """Simple calculator class."""

    def __init__(self, initial: int = 0) -> None:
        self.value = initial

    def add(self, n: int) -> "Calculator":
        self.value += n
        return self

    def reset(self) -> "Calculator":
        self.value = 0
        return self

    def result(self) -> int:
        return self.value
