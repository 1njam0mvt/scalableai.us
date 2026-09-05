from pydantic import BaseModel, Field
from typing import List, Optional

class ChatMessage(BaseModel):
    role: str
    content: str 

class Personalization(BaseModel):
    nickname: Optional[str] = Field(default=None, max_length=60)
    length: Optional[str] = None  # 'concise' | 'balanced' | 'detailed'
    custom_instructions: Optional[str] = Field(default=None, max_length=1500)
    language: Optional[str] = Field(default=None, max_length=40)
    voice: Optional[str] = Field(default=None, max_length=60)

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=32_000)
    session_id: Optional[str] = None
    tts: bool = False
    imgbase64: Optional[str] = None
    personalization: Optional[Personalization] = None
    project_id: Optional[str] = None

class ChatResponse(BaseModel):
    response: str
    session_id: str

class ChatHistory(BaseModel):
    session_id: str
    messages: List[ChatMessage]

class ScalableActions(BaseModel):
    wopens: List[str] = []
    plays: List[str] = []
    images: List[str] = [] 
    contents: List[str] = [] 
    googlesearches: List[str] = [] 
    youtubesearches: List[str] = []
    cam: Optional[dict] = None
    reminder: Optional[dict] = None

class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)

class SignupRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=30)
    email: str = Field(..., min_length=5, max_length=254)
    password: str = Field(..., min_length=8, max_length=200)
    display_name: Optional[str] = Field(default=None, max_length=60)

class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=254)
    password: str = Field(..., min_length=1, max_length=200)

class AuthResponse(BaseModel):
    token: str
    username: str
    email: str
    display_name: str
    created_at: Optional[float] = None

class BugReportRequest(BaseModel):
    description: str = Field(..., min_length=1, max_length=2000)
    page_url: Optional[str] = Field(default=None, max_length=500)
    user_agent: Optional[str] = Field(default=None, max_length=500)

class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=200)
    new_password: str = Field(..., min_length=8, max_length=200)

class ChatSessionSummary(BaseModel):
    session_id: str
    title: str
    updated_at: float

class DeleteAccountRequest(BaseModel):
    password: str = Field(..., min_length=1, max_length=200)

class ProjectFile(BaseModel):
    file_id: str
    filename: str
    size_bytes: int
    uploaded_at: float
    extracted_chars: int = 0
    extraction_error: Optional[str] = None

class CreateProjectRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(default="", max_length=2000)

class UpdateProjectRequest(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=100)
    description: Optional[str] = Field(default=None, max_length=2000)

class UpdateProjectInstructionsRequest(BaseModel):
    instructions: str = Field(default="", max_length=10_000)

class AddProjectTextContentRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=150)
    content: str = Field(..., min_length=1, max_length=200_000)

class Project(BaseModel):
    project_id: str
    title: str
    description: str = ""
    instructions: str = ""
    created_at: float
    updated_at: float
    pinned: bool = False
    archived: bool = False
    files: List[ProjectFile] = []
    chat_count: int = 0