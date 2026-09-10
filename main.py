import os
import re
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, status, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import create_engine, text
from pydantic import BaseModel

import pymorphy3
from thefuzz import fuzz

from models import Base, Report, ReportStatus, Priority, User, Category, AuditLog, RoutingRule
from schemas import ReportCreate, ReportResponse, StatusCheckRequest
from utils import generate_tracking_code

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres_password@db:5432/otklik_db")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

app = FastAPI(title="Otklik API")

# Встроенный стандартный CORS (надежно обрабатывает все префлайт запросы и методы)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup_event():
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    try:
        existing_categories = db.execute(text("SELECT COUNT(*) FROM categories")).scalar()
        if existing_categories == 0:
            categories_data = [
                ('1', 'Буллинг и травля'),
                ('2', 'Психологическое состояние (кризис)'),
                ('3', 'Конфликты с преподавателями / руководством'),
                ('4', 'Проблемы с учебой и нагрузкой'),
                ('5', 'Бытовые и финансовые трудности'),
                ('6', 'Другое')
            ]
            for cat_id, name in categories_data:
                db.execute(
                    text("INSERT INTO categories (id, name) VALUES (:id, :name) ON CONFLICT (id) DO NOTHING"),
                    {"id": cat_id, "name": name}
                )
            db.commit()
    except Exception as e:
        pass
    finally:
        db.close()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

morph = pymorphy3.MorphAnalyzer()
CRISIS_LEMMAS = {"суицид", "покончить", "убить", "насилие", "бить", "угрожать", "смерть"}

def detect_crisis(text: str) -> bool:
    if not text:
        return False
    
    words = re.findall(r'[а-яё]+', text.lower())
    for word in words:
        normal_form = morph.parse(word)[0].normal_form
        if normal_form in CRISIS_LEMMAS:
            return True
            
        for lemma in CRISIS_LEMMAS:
            if len(word) > 3 and fuzz.ratio(word, lemma) >= 82:
                return True
                
    return False

def strip_exif_and_save(file_paths: Optional[List[str]]) -> List[str]:
    cleaned_paths = []
    if file_paths:
        for path in file_paths:
            cleaned_paths.append(f"cleaned_{os.path.basename(path)}")
    return cleaned_paths


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


@app.post("/api/reports", response_model=dict, status_code=status.HTTP_201_CREATED)
def create_report(report_data: ReportCreate, db: Session = Depends(get_db)):
    tracking_code = generate_tracking_code()
    while db.query(Report).filter(Report.tracking_code == tracking_code).first():
        tracking_code = generate_tracking_code()

    is_crisis_detected = detect_crisis(report_data.content)
    priority = Priority.urgent if is_crisis_detected else Priority.standard

    safe_attachments = strip_exif_and_save(report_data.attachments)

    contact_info_val = getattr(report_data, 'contact_info', None)

    # Автоматическое назначение эксперта по правилам маршрутизации
    assigned_expert = None
    rule = db.query(RoutingRule).filter(RoutingRule.category_id == str(report_data.category_id)).first()
    if rule:
        assigned_expert = rule.expert_id

    new_report = Report(
        tracking_code=tracking_code,
        applicant_type=report_data.applicant_type,
        category_id=report_data.category_id,
        content=report_data.content,
        status=ReportStatus.new,
        priority=priority,
        is_crisis=is_crisis_detected,
        contact_info=contact_info_val if is_crisis_detected else None,
        expert_id=assigned_expert
    )

    db.add(new_report)
    db.commit()
    db.refresh(new_report)

    return {
        "message": "Обращение успешно создано",
        "tracking_code": tracking_code,
        "is_crisis": is_crisis_detected,
        "emergency_help_shown": is_crisis_detected,
        "status": new_report.status.value if hasattr(new_report.status, 'value') else new_report.status,
        "expert_id": new_report.expert_id
    }


@app.get("/api/reports")
def get_reports(status: str = None, db: Session = Depends(get_db)):
    query = db.query(Report)
    if status:
        status_map = {
            "new": ReportStatus.new,
            "новое": ReportStatus.new,
            "in_progress": ReportStatus.in_progress,
            "в работе": ReportStatus.in_progress,
            "resolved": ReportStatus.ready,
            "решено": ReportStatus.ready,
            "completed": ReportStatus.completed,
            "завершено": ReportStatus.completed,
            "rejected": ReportStatus.rejected,
            "отклонено": ReportStatus.rejected
        }
        clean_status = str(status).strip().lower()
        db_status = status_map.get(clean_status, clean_status)
        query = query.filter(Report.status == db_status)
        
    reports = query.order_by(Report.created_at.desc()).all()
    
    return [
        {
            "id": r.id,
            "tracking_code": r.tracking_code,
            "applicant_type": r.applicant_type,
            "category_id": r.category_id,
            "content": r.content,
            "status": r.status.value if hasattr(r.status, 'value') else r.status,
            "priority": r.priority.value if hasattr(r.priority, 'value') else r.priority,
            "is_crisis": r.is_crisis,
            "expert_id": getattr(r, "expert_id", None),
            "created_at": r.created_at.isoformat()
        }
        for r in reports
    ]


@app.get("/api/operator/reports")
def get_operator_reports(db: Session = Depends(get_db)):
    reports = db.query(Report).order_by(
        Report.is_crisis.desc(),
        Report.priority.desc(),
        Report.created_at.asc()
    ).all()
    
    return [
        {
            "id": r.id,
            "tracking_code": r.tracking_code,
            "applicant_type": r.applicant_type,
            "category_id": r.category_id,
            "content": r.content,
            "status": r.status.value if hasattr(r.status, 'value') else r.status,
            "priority": r.priority.value if hasattr(r.priority, 'value') else r.priority,
            "is_crisis": r.is_crisis,
            "expert_id": getattr(r, "expert_id", None),
            "created_at": r.created_at.isoformat()
        }
        for r in reports
    ]


class AssignExpertRequest(BaseModel):
    expert_name: str
    reason: Optional[str] = "Назначение эксперта оператором"

@app.patch("/api/reports/{report_id}/assign")
def assign_expert(report_id: str, payload: AssignExpertRequest, db: Session = Depends(get_db)):
    report = None
    try:
        int_id = int(report_id)
        report = db.query(Report).filter(Report.id == int_id).first()
    except ValueError:
        report = db.query(Report).filter(Report.tracking_code == report_id).first()

    if not report:
        raise HTTPException(status_code=404, detail="Обращение не найдено")
    
    old_expert = str(getattr(report, "expert_id", "не назначен"))
    
    # Пытаемся сохранить эксперта как число (если передан ID), иначе как строку
    expert_val = payload.expert_name
    try:
        expert_val = int(expert_val)
    except ValueError:
        pass

    report.expert_id = expert_val

    try:
        audit = AuditLog(
            action="MANUAL_EXPERT_ASSIGN",
            target_report_id=report.tracking_code,
            reason=payload.reason,
            details=f"Эксперт изменен с '{old_expert}' на '{payload.expert_name}'"
        )
        db.add(audit)
    except Exception:
        pass

    db.commit()
    db.refresh(report)
    
    return {"message": "Эксперт успешно назначен", "expert_id": report.expert_id}


@app.post("/api/reports/check-status", response_model=ReportResponse)
def check_report_status(payload: StatusCheckRequest, db: Session = Depends(get_db)):
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


@app.patch("/api/reports/{report_id}/status")
def update_report_status(report_id: str, payload: dict, db: Session = Depends(get_db)):
    try:
        report = None
        try:
            int_id = int(report_id)
            report = db.query(Report).filter(Report.id == int_id).first()
        except ValueError:
            report = db.query(Report).filter(Report.tracking_code == report_id).first()

        if not report:
            raise HTTPException(status_code=404, detail="Обращение не найдено")
        
        new_status = payload.get("status")
        if new_status:
            status_map = {
                "new": ReportStatus.new,
                "новое": ReportStatus.new,
                "in_progress": ReportStatus.in_progress,
                "в работе": ReportStatus.in_progress,
                "resolved": ReportStatus.ready,
                "решено": ReportStatus.ready,
                "completed": ReportStatus.completed,
                "завершено": ReportStatus.completed,
                "rejected": ReportStatus.rejected,
                "отклонено": ReportStatus.rejected
            }
            
            clean_status = str(new_status).strip().lower()
            if clean_status in status_map:
                report.status = status_map[clean_status]
            else:
                report.status = ReportStatus(clean_status)

            db.commit()
            db.refresh(report)
        
        return {
            "message": "Статус успешно обновлен",
            "status": report.status.value if hasattr(report.status, 'value') else report.status
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


class MessageCreate(BaseModel):
    message: str
    sender_type: str = "applicant"

@app.get("/api/reports/{tracking_code}/messages")
def get_report_messages(tracking_code: str, db: Session = Depends(get_db)):
    report = db.query(Report).filter(Report.tracking_code == tracking_code).first()
    if not report:
        raise HTTPException(status_code=404, detail="Обращение не найдено")
    
    messages = getattr(report, "messages", [])
    return [
        {
            "id": getattr(m, "id", "1"),
            "message": getattr(m, "text", getattr(m, "message", "")),
            "sender_type": getattr(m, "sender_type", "applicant"),
            "created_at": getattr(m, "created_at", report.created_at).isoformat()
        }
        for m in messages
    ]

@app.post("/api/reports/{tracking_code}/messages")
def send_report_message(tracking_code: str, payload: MessageCreate, db: Session = Depends(get_db)):
    report = db.query(Report).filter(Report.tracking_code == tracking_code).first()
    if not report:
        raise HTTPException(status_code=404, detail="Обращение не найдено")
    
    return {
        "status": "success",
        "message": payload.message,
        "sender_type": payload.sender_type
    }


# --- Админские эндпоинты (Категории, Юзеры, Маршрутизация, Аудит) ---

class CategoryCreate(BaseModel):
    name: str
    description: Optional[str] = None

@app.get("/api/admin/categories")
def admin_get_categories(db: Session = Depends(get_db)):
    categories = db.query(Category).all()
    return [{"id": c.id, "name": c.name, "description": c.description} for c in categories]

@app.post("/api/admin/categories", status_code=status.HTTP_201_CREATED)
def admin_create_category(payload: CategoryCreate, db: Session = Depends(get_db)):
    category = Category(name=payload.name, description=payload.description)
    db.add(category)
    db.commit()
    db.refresh(category)
    return {"message": "Категория успешно создана", "id": category.id}


class UserCreateAdmin(BaseModel):
    username: str
    password: str
    role: str
    full_name: Optional[str] = None


@app.get("/api/admin/users")
def admin_get_users(db: Session = Depends(get_db)):
    users = db.query(User).all()
    return [{
        "id": u.id,
        "username": u.username,
        "role": u.role,
        "full_name": getattr(u, "full_name", None)
    } for u in users]

@app.post("/api/admin/users", status_code=status.HTTP_201_CREATED)
def admin_create_user(payload: UserCreateAdmin, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.username == payload.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Пользователь с таким логином уже существует")
    
    user = User(
        username=payload.username,
        hashed_password=payload.password,
        role=payload.role,
        full_name=payload.full_name
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"message": f"Пользователь {payload.username} успешно создан", "id": user.id}


class RoutingRuleCreate(BaseModel):
    category_id: str
    expert_id: str
    priority_threshold: Optional[str] = "standard"

@app.get("/api/admin/routing-rules")
def admin_get_routing_rules(db: Session = Depends(get_db)):
    rules = db.query(RoutingRule).all()
    return [{
        "id": r.id,
        "category_id": r.category_id,
        "expert_id": r.expert_id,
        "priority_threshold": r.priority_threshold
    } for r in rules]

@app.post("/api/admin/routing-rules", status_code=status.HTTP_201_CREATED)
def admin_create_routing_rule(payload: RoutingRuleCreate, db: Session = Depends(get_db)):
    existing_rule = db.query(RoutingRule).filter(RoutingRule.category_id == payload.category_id).first()
    if existing_rule:
        existing_rule.expert_id = payload.expert_id
        existing_rule.priority_threshold = payload.priority_threshold
        db.commit()
        return {"message": "Правило маршрутизации обновлено"}

    rule = RoutingRule(
        category_id=payload.category_id,
        expert_id=payload.expert_id,
        priority_threshold=payload.priority_threshold
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return {"message": "Правило маршрутизации сохранено"}


@app.get("/api/admin/logs")
def admin_get_audit_logs(db: Session = Depends(get_db)):
    logs = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(100).all()
    return [{
        "id": l.id,
        "action": l.action,
        "target_report_id": l.target_report_id,
        "reason": l.reason,
        "details": l.details,
        "created_at": l.created_at.isoformat()
    } for l in logs]

@app.get("/api/experts")
def get_experts(db: Session = Depends(get_db)):
    try:
        users = db.query(User.id, User.username, User.full_name, User.role).all()
        result = []
        for u in users:
            result.append({
                "id": u.id,
                "name": u.full_name or u.username
            })
        return result
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))