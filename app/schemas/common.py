from typing import Any, Optional
from pydantic import BaseModel

class ApiResponse(BaseModel):
    success: bool = True
    data: Any = None
    message: Optional[str] = None
