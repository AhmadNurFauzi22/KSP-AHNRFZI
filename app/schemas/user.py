from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, EmailStr


class RoleOut(BaseModel):
    id: int
    name: str
    code: str
    description: Optional[str] = None

    class Config:
        from_attributes = True


class UserBase(BaseModel):
    username: str
    email: EmailStr
    full_name: str
    phone_number: Optional[str] = None
    is_active: bool = True


class UserCreate(UserBase):
    password: str
    role_codes: List[str]


class UserOut(UserBase):
    id: int
    roles: List[RoleOut]
    created_at: datetime

    class Config:
        from_attributes = True
