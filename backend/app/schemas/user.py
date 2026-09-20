from pydantic import BaseModel, EmailStr
import uuid


class UserDetails(BaseModel):
    user_id: uuid.UUID
    email: EmailStr
