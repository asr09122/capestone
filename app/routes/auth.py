"""Auth routes — JWT token issuance and user registration."""
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, field_validator

from app.core.security import authenticate_user, create_access_token, create_user
from app.core.config import get_settings

router = APIRouter()


class SignupRequest(BaseModel):
    username: str
    password: str
    seller_id: Optional[int] = None
    role: str = "seller"

    @field_validator("username")
    @classmethod
    def username_valid(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 3:
            raise ValueError("Username must be at least 3 characters")
        if len(v) > 50:
            raise ValueError("Username must be at most 50 characters")
        if not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Username may only contain letters, numbers, hyphens, underscores")
        return v

    @field_validator("password")
    @classmethod
    def password_valid(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("Password must be at least 6 characters")
        return v

    @field_validator("role")
    @classmethod
    def role_valid(cls, v: str) -> str:
        if v not in ("seller", "admin"):
            raise ValueError("Role must be 'seller' or 'admin'")
        return v


@router.post("/signup", status_code=status.HTTP_200_OK)
async def signup(req: SignupRequest):
    """Create a new user account."""
    if req.role == "seller" and req.seller_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="seller_id is required for seller accounts",
        )
    if req.role == "admin" and req.seller_id is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="seller_id must be omitted for admin accounts",
        )
    try:
        user = create_user(req.username, req.password, req.seller_id, req.role)
        return {
            "message": "User created successfully",
            "username": user["username"],
            "seller_id": user["seller_id"],
            "role": user["role"],
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not create user: {e}",
        )


@router.post("/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """Authenticate and return a JWT bearer token."""
    try:
        user = authenticate_user(form_data.username, form_data.password)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Authentication error: {e}",
        )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    settings = get_settings()
    token = create_access_token(
        data={"sub": user["username"], "seller_id": user["seller_id"], "role": user["role"]},
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "role": user["role"],
        "seller_id": user["seller_id"],
    }
