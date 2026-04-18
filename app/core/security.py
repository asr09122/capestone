from datetime import datetime, timedelta, timezone
from typing import Optional
import sqlite3

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings

settings = get_settings()

# Use pbkdf2_sha256 — works with all passlib/bcrypt versions, no C backend issues
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


def get_db_connection():
    """Get database connection."""
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    return conn


def get_user_from_db(username: str) -> Optional[dict]:
    """Retrieve user from database by username."""
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT user_id, username, hashed_password, seller_id, role FROM users WHERE username = ?",
            (username,)
        ).fetchone()
        if row:
            return dict(row)
        return None
    finally:
        conn.close()


def create_user(username: str, password: str, seller_id: Optional[int] = None, role: str = "user") -> dict:
    """Create a new user in the database."""
    conn = get_db_connection()
    try:
        hashed_password = pwd_context.hash(password)
        cursor = conn.execute(
            "INSERT INTO users (username, hashed_password, seller_id, role) VALUES (?, ?, ?, ?)",
            (username, hashed_password, seller_id, role)
        )
        conn.commit()
        user_id = cursor.lastrowid
        return {
            "user_id": user_id,
            "username": username,
            "seller_id": seller_id,
            "role": role
        }
    except sqlite3.IntegrityError:
        raise ValueError("Username already exists")
    finally:
        conn.close()


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def authenticate_user(username: str, password: str) -> Optional[dict]:
    user = get_user_from_db(username)
    if not user:
        return None
    if not verify_password(password, user["hashed_password"]):
        return None
    return user


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode["exp"] = expire
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = get_user_from_db(username)
    if user is None:
        raise credentials_exception
    return user


def ensure_actor_can_access_seller(current_user: dict, seller_id: int) -> None:
    """Check if the current user can access the given seller_id.
    Admins can access any seller. Sellers can only access their own store.
    """
    if current_user.get("role") == "admin":
        return
    if current_user.get("seller_id") != seller_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only access your own store.",
        )


def require_seller(current_user: dict = Depends(get_current_user)) -> dict:
    """Dependency that ensures the current user is a seller (not an admin without a store)."""
    if not current_user.get("seller_id"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint requires a seller account.",
        )
    return current_user


def bootstrap_role_compatibility() -> None:
    """Normalize any legacy roles in the database to the capstone role model."""
    from app.services.workflow_service import normalize_existing_roles
    from app.db.database import session_scope
    with session_scope() as session:
        normalize_existing_roles(session)
