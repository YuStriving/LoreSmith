from __future__ import annotations


from typing import Optional


class ApiError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400, details: Optional[dict] = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
