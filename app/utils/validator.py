"""Lightweight reusable validators."""


class ValueValidator:
    """Generic validation helpers used across routers."""

    @staticmethod
    def require(value: Any, message: str = "Required value missing.") -> None:
        if value is None:
            raise ValueError(message)

    @staticmethod
    def non_empty(value: str, message: str = "Value cannot be empty.") -> None:
        if value is None or not str(value).strip():
            raise ValueError(message)
