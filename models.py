import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, Boolean, DateTime, ForeignKey, Enum as SQLEnum, Integer
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy import Column, String, Text, Boolean, DateTime, ForeignKey, Enum as SQLEnum, JSON
import enum


Base = declarative_base()

class ApplicantType(str, enum.Enum):
    schoolkid = "schoolkid"
    parent = "parent"
    teacher = "teacher"

class ReportStatus(str, enum.Enum):
    new = "new"                               # Новое
    distributed = "distributed"               # Распределено оператором
    in_progress = "in_progress"               # В работе
    clarification = "clarification"           # Уточнение
    answer_ready = "answer_ready"             # Ответ готов
    returned = "returned"                     # Возвращено
    closed_no_answer = "closed_no_answer"     # Закрыто без ответа
    completed = "completed"                   # Завершено
    rejected = "rejected"                     # Отклонено

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
    
    content = Column(Text, nullable=False)                                   # Текст обращения
    status = Column(SQLEnum(ReportStatus), default=ReportStatus.new, nullable=False)
    priority = Column(SQLEnum(Priority), default=Priority.standard, nullable=False)
    is_crisis = Column(Boolean, default=False, nullable=False)               # Детекция кризисных маркеров
    
    contact_info = Column(String, nullable=True) 
    
    # Добавляем поле для хранения списка прикрепленных файлов:
    attachments = Column(JSON, nullable=True) # или Column(ARRAY(String), nullable=True)
    
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
    admin_id = Column(String, ForeignKey("users.id"), nullable=True)
    action = Column(String, nullable=False)                                 # Описание действия
    target_report_id = Column(String, nullable=True)
    reason = Column(String, nullable=True)                                  # Причина вмешательства (требование ТЗ)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class RoutingRule(Base):
    __tablename__ = "routing_rules"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    category_id = Column(String, ForeignKey("categories.id"), nullable=False)
    expert_id = Column(String, ForeignKey("users.id"), nullable=False)
    priority_threshold = Column(String, nullable=True, default="standard")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)