"""Password hashing and verification using bcrypt via passlib."""

from passlib.context import CryptContext


class PasswordManager:
    """Handles password hashing and verification using bcrypt."""

    _context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    _MAX_BYTES = 72

    @classmethod
    def _check_length(cls, password: str) -> None:
        if len(password.encode("utf-8")) > cls._MAX_BYTES:
            raise ValueError("Password must be 72 bytes or fewer.")

    @classmethod
    def hash(cls, password: str) -> str:
        """Return a bcrypt hash for the provided plaintext password."""
        cls._check_length(password)
        return cls._context.hash(password)

    @classmethod
    def verify(cls, password: str, password_hash: str) -> bool:
        """Return True when the plaintext password matches the stored hash."""
        try:
            cls._check_length(password)
        except ValueError:
            return False
        return cls._context.verify(password, password_hash)
