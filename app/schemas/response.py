"""Standard API response envelope."""

from typing import Any
from pydantic import BaseModel


class ApiResponse(BaseModel):
    detail: list[Any]
    pagination: dict[str, Any] | None = None
