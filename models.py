import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, Boolean, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.orm import declarative_base, relationship
import enum

Base = declarative_base()

class ApplicantType(str, enum.Enum):
    schoolkid = "schoolkid"
    parent = "parent"
    teacher = "teacher"

class ReportStatus(str, enum.Enum):
    new = "new"                           # Новое, ждёт оператора
    distributed = "distributed"           # Распределено оператором
    in_progress = "in_progress"           # В работе у эксперта
    need_info = "need_info"               # Нужно уточнение от заявителя
    ready = "ready"                       # Ответ готов
    returned = "returned"                 # Возвращено заявителем (не помогло)
    completed = "completed"               # Завершено (подтверждено)
    rejected = "rejected"                 # Отклонено (спам / вне компетенции)
    auto_closed = "auto_closed"           # Закрыто без ответа

class Priority(str, enum.Enum):
    low = "low"
    standard = "standard"
    urgent = "urgent"

class UserRole(str, enum.Enum):
    operator = "operator"
    expert = "expert"
    admin = "admin"

class SenderType(str, enum.Enum):
    applicant = "applicant"
    expert = "expert"
    system = "system"

class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(SQLEnum(UserRole), nullable=False)
    full_name = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)


class Category(Base):
    __tablename__ = "categories"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, unique=True, nullable=False)
    description = Column(String, nullable=True)


class Report(Base):
    __tablename__ = "reports"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tracking_code = Column(String, unique=True, index=True, nullable=False) # Формат otk-XXXX-XXXX
    applicant_type = Column(SQLEnum(ApplicantType), nullable=False)         # Школьник / Родитель / Педагог
    category_id = Column(String, ForeignKey("categories.id"), nullable=True) # Может быть NULL («не знаю, как назвать»)
    
    content = Column(Text, nullable=False)                                  # Текст обращения
    status = Column(SQLEnum(ReportStatus), default=ReportStatus.new, nullable=False)
    priority = Column(SQLEnum(Priority), default=Priority.standard, nullable=False)
    is_crisis = Column(Boolean, default=False, nullable=False)              # Детекция кризисных маркеров
    
    contact_info = Column(String, nullable=True)                            
    
    operator_id = Column(String, ForeignKey("users.id"), nullable=True)
    expert_id = Column(String, ForeignKey("users.id"), nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Связи
    messages = relationship("Message", back_populates="report", cascade="all, delete-orphan")
    internal_notes = relationship("InternalNote", back_populates="report", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    report_id = Column(String, ForeignKey("reports.id"), nullable=False)
    sender_type = Column(SQLEnum(SenderType), nullable=False)                 # Кто написал (заявитель, эксперт, система)
    text = Column(Text, nullable=False)
    attachments_json = Column(Text, nullable=True)                          # Список путей к вложениям (без EXIF)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    report = relationship("Report", back_populates="messages")


class InternalNote(Base):
    __tablename__ = "internal_notes"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    report_id = Column(String, ForeignKey("reports.id"), nullable=False)
    author_id = Column(String, ForeignKey("users.id"), nullable=False)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    report = relationship("Report", back_populates="internal_notes")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    admin_id = Column(String, ForeignKey("users.id"), nullable=False)
    action = Column(String, nullable=False)                                 # Описание действия
    target_report_id = Column(String, nullable=True)
    reason = Column(String, nullable=False)                                 # Причина вмешательства (требование ТЗ)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)