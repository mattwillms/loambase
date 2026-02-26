from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str


class UserUpdate(BaseModel):
    name: Optional[str] = None
    timezone: Optional[str] = None
    zip_code: Optional[str] = None


class UserRead(BaseModel):
    id: int
    name: str
    email: str
    role: str
    is_active: bool
    timezone: Optional[str]
    zip_code: Optional[str]
    hardiness_zone: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    created_at: datetime
    last_login: Optional[datetime]

    model_config = {"from_attributes": True}


class UserAdminRead(UserRead):
    """Extended view for admin endpoints."""
    pass


class AdminUserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: str = "user"
    is_active: bool = True
    timezone: Optional[str] = None
    zip_code: Optional[str] = None
    hardiness_zone: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class AdminUserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    password: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    timezone: Optional[str] = None
    zip_code: Optional[str] = None
    hardiness_zone: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class AdminUserRead(BaseModel):
    id: int
    name: str
    email: str
    role: str
    is_active: bool
    timezone: Optional[str]
    zip_code: Optional[str]
    hardiness_zone: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    created_at: datetime
    last_login: Optional[datetime]

    model_config = {"from_attributes": True}


class UserStats(BaseModel):
    gardens: int
    beds: int
    active_plantings: int
    tasks_due_today: int
