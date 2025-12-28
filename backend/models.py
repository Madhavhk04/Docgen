from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List, Dict, Any
from datetime import datetime
import uuid

class User(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    email: EmailStr
    hashed_password: str
    full_name: Optional[str] = None
    profession: Optional[str] = None
    security_question: Optional[str] = None
    security_answer_hash: Optional[str] = None
    
    # Cosmos DB specific fields
    partitionKey: str = Field(default="", alias="partitionKey") # usually same as email for users

    class Config:
        populate_by_name = True

class Document(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    user_id: str
    filename: str
    file_path: str
    doc_type: str
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    input_data: Optional[Dict[str, Any]] = None
    
    # Cosmos DB specific
    partitionKey: str = Field(default="", alias="partitionKey") # usually same as user_id for documents

