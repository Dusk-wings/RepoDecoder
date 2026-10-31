from pydantic import BaseModel, EmailStr
import uuid


class UserDetails(BaseModel):
    user_id: uuid.UUID
    is_anonymous: bool
    email: EmailStr
