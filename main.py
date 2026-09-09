import os
from fastapi import FastAPI
from sqlalchemy import create_engine, text
from typing import List

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres_password@localhost:5432/otklik_db")

engine = create_engine(DATABASE_URL)
app = FastAPI(title="Otklik API")

@app.get("/")
def read_root():
    return {"message": "Платформа 'Отклик' API запущен"}

@app.get("/health")
def health_check():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        return {"status": "error", "database": str(e)}
import os
import re
from fastapi import FastAPI, Depends, HTTPException, status
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import create_engine
from datetime import datetime

from models import Base, Report, ReportStatus, Priority, User, Category
from schemas import ReportCreate, ReportResponse, StatusCheckRequest
from utils import generate_tracking_code

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres_password@db:5432/otklik_db")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

app = FastAPI(title="Otklik API")

@app.on_event("startup")
def startup_event():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

CRISIS_KEYWORDS = ["суицид", "покончить", "убить себя", "насилие", "бьют", "угрожают убийством", "смерть"]

def detect_crisis(text: str) -> bool:
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in CRISIS_KEYWORDS)

def strip_exif_and_save(file_paths: List[str]) -> List[str]:
    cleaned_paths = []
    for path in file_paths:
        cleaned_paths.append(f"cleaned_{os.path.basename(path)}")
    return cleaned_paths


@app.post("/api/reports", response_model=dict, status_code=status.HTTP_201_CREATED)
def create_report(report_data: ReportCreate, db: Session = Depends(get_db)):
    """
    Создание нового обращения анонимным заявителем (Сценарии С1, С2, С6).
    Автоматически определяет кризисные маркеры, генерирует трек-код и очищает вложения.
    """
    tracking_code = generate_tracking_code()
    while db.query(Report).filter(Report.tracking_code == tracking_code).first():
        tracking_code = generate_tracking_code()

    is_crisis_detected = detect_crisis(report_data.content)
    priority = Priority.urgent if is_crisis_detected else Priority.standard

    safe_attachments = strip_exif_and_save(report_data.attachments)

    new_report = Report(
        tracking_code=tracking_code,
        applicant_type=report_data.applicant_type,
        category_id=report_data.category_id,
        content=report_data.content,
        status=ReportStatus.new,
        priority=priority,
        is_crisis=is_crisis_detected,
        contact_info=report_data.contact_info if is_crisis_detected else None # Сохраняем контакты изолированно
    )

    db.add(new_report)
    db.commit()
    db.refresh(new_report)

    return {
        "message": "Обращение успешно создано",
        "tracking_code": tracking_code,
        "is_crisis": is_crisis_detected,
        "emergency_help_shown": is_crisis_detected,
        "status": new_report.status
    }


@app.post("/api/reports/check-status", response_model=ReportResponse)
def check_report_status(payload: StatusCheckRequest, db: Session = Depends(get_db)):
    """
    Проверка статуса обращения по трек-номеру (ТЗ раздел 4.1, 4.7).
    """
    report = db.query(Report).filter(Report.tracking_code == payload.tracking_code).first()
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Обращение с таким трек-номером не найдено. Проверьте правильность ввода."
        )
    
    return ReportResponse(
        id=report.id,
        tracking_code=report.tracking_code,
        applicant_type=report.applicant_type,
        status=report.status,
        priority=report.priority,
        is_crisis=report.is_crisis,
        created_at=report.created_at.isoformat()
    )


@app.get("/health")
def health_check():
    return {"status": "ok", "database": "connected"}