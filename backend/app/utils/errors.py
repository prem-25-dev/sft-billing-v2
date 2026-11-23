"""Errors and helpers for translating them into HTTP responses."""
from __future__ import annotations


class NotFoundError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class ValidationFailedError(Exception):
    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__(str(errors))


class ConflictError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)
