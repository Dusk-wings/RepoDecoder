from pydantic import BaseModel
from typing import Generic, TypeVar, Optional

T = TypeVar("T")


class StandardResponse(BaseModel, Generic[T]):
    message: str
    status: int
    data: Optional[T] = None
