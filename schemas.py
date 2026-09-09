from pydantic import BaseModel, Field
from typing import Optional, List
from models import ApplicantType, ReportStatus, Priority

class ReportCreate(BaseModel):
    applicant_type: ApplicantType
    category_id: Optional[str] = None
    content: str = Field(..., min_length=5, description="Текст обращения")
    contact_info: Optional[str] = Field(None, description="Опциональный контакт для связи")
    attachments: Optional[List[str]] = Field(default=[], description="Список путей к файлам")

class ReportResponse(BaseModel):
    id: str
    tracking_code: str
    applicant_type: ApplicantType
    status: ReportStatus
    priority: Priority
    is_crisis: bool
    created_at: str

    class Config:
        from_attributes = True

class StatusCheckRequest(BaseModel):
    tracking_code: str