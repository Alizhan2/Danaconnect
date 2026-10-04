"""Explicit, development-only synthetic dataset: python -m app.seed.

This command never overwrites existing records. IDs are stable UUID5 values,
timestamps are relative to a reference date. Set DEMO_MODE=true explicitly.
"""
import argparse
import hashlib
from datetime import date, datetime, time, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal, engine
from app.schema_registry import Base
from app.models import (
    Application, AuditEvent, Booking, Consent, Conversation,
    ConversationMember, Direction, Document, DocumentVersion, Feedback, Message,
    Notification, Participation, ParticipationEvent, Project, ProjectMember,
    RegistrationReview, Result, ShowcaseConsent, Slot, User,
)


def demo_id(key: str) -> str:
    return str(uuid5(NAMESPACE_URL, "https://demo.danaconnect.example.test/" + key))


def seed_demo(db: Session, reference_date: date | None = None) -> dict[str, str]:
    """Insert a repeatable sample graph without changing any existing records."""
    if settings.environment != "development" or not settings.demo_mode:
        raise RuntimeError("Synthetic seeding requires ENVIRONMENT=development and DEMO_MODE=true")
    anchor = datetime.combine(reference_date or datetime.now(timezone.utc).date(), time(12), tzinfo=timezone.utc)

    def add(model, key, **values):
        identifier = demo_id(key)
        existing = db.get(model, identifier)
        if existing is None:
            db.add(model(id=identifier, **values))
            db.flush()
        return identifier

    ai = add(Direction, "direction-ai", slug="applied-ai", name_ru="Прикладной ИИ", name_kk="Қолданбалы ЖИ", name_en="Applied AI", description_ru="Демонстрационное направление: идеи, данные и первые прототипы.", active=True)
    product = add(Direction, "direction-product", slug="product-design", name_ru="Продукт и дизайн", name_kk="Өнім және дизайн", name_en="Product & Design", description_ru="Демонстрационное направление: исследования и цифровые продукты.", active=True)
    code = add(Direction, "direction-software", slug="software-engineering", name_ru="Разработка ПО", name_kk="Бағдарламалық жасақтама", name_en="Software Engineering", description_ru="Демонстрационное направление: веб-приложения и архитектура.", active=True)

    user_specs = [
        ("admin", "Администратор · Демо", "admin", [ai, product, code], "Администратор демонстрационной среды", "", False),
        ("mentor", "Алия · Демо", "mentor", [ai, code], "Вымышленный профиль. Помогаю превратить идею в небольшой работающий прототип.", "Python, FastAPI, машинное обучение", True),
        ("mentor-design", "Дана · Демо", "mentor", [product], "Вымышленный профиль. Работаю с исследованиями пользователей и продуктовыми гипотезами.", "UX research, Figma, product discovery", True),
        ("mentee", "Аружан · Демо", "mentee", [ai], "Вымышленный профиль. Создаю учебный проект в области ИИ и хочу выстроить план разработки.", "Python, анализ данных", False),
        ("mentee-project", "Мадина · Демо", "mentee", [product], "Вымышленный профиль участницы завершённого демонстрационного проекта.", "Исследования, прототипирование", False),
        ("mentee-candidate", "Айгерим · Демо", "mentee", [ai, code], "Вымышленный профиль для демонстрации заявок на проект.", "Python, JavaScript", False),
    ]
    users = {}
    for key, name, role, directions, bio, expertise, intake in user_specs:
        users[key] = add(User, "user-" + key, email=key + "@example.test", full_name=name, role=role, account_status="active", intake_open=intake, timezone="Asia/Oral", city="Демонстрационный город", organization="Вымышленная организация · Демо" if role == "mentor" else "", phone="+7 700 000 00 00" if role == "mentor" else None, mentor_commitment=role == "mentor", mentor_commitment_accepted_at=anchor-timedelta(days=14) if role == "mentor" else None, birth_date=date(2000, 1, 1) if role == "mentee" else None, bio=bio, expertise=expertise, direction_ids=directions, evidence_urls=["https://example.test/demo-evidence"] if role == "mentor" else [], capacity=4 if role == "mentor" else 3, profile_completed=True, created_at=anchor-timedelta(days=14))

    pending = add(User, "user-pending", email="pending@example.test", full_name="Участница · Демо, на проверке", role="mentee", account_status="pending", intake_open=False, timezone="Asia/Oral", city="Демонстрационный город", birth_date=date(2000, 1, 1), bio="Вымышленная анкета для очереди модерации.", expertise="Python", direction_ids=[ai], evidence_urls=[], capacity=3, profile_completed=True, created_at=anchor-timedelta(days=1))
    versions = []
    document_specs = [
        ("participation-rules", "Правила участия — демонстрационный черновик", "registration", ["mentee", "mentor", "admin"]),
        ("privacy-draft", "Обработка данных — демонстрационный черновик", "registration", ["mentee", "mentor", "admin"]),
        ("mentor-intake", "Условия набора ментора — демонстрационный черновик", "intake", ["mentor"]),
        ("private-project-draft", "Конфиденциальность проекта — демонстрационный черновик", "private_project", ["mentee", "mentor"]),
        ("showcase-draft", "Публикация кейса — демонстрационный черновик", "showcase", ["mentee", "mentor"]),
    ]
    for slug, title, scope, roles in document_specs:
        document = add(Document, "document-"+slug, slug=slug, title=title, required_roles=roles, direction_id=None, scope=scope, active=True)
        content = ("ДЕМОНСТРАЦИОННЫЙ ЧЕРНОВИК. НЕ ЮРИДИЧЕСКИЙ ДОКУМЕНТ.\n\n"
                   "Этот текст существует только для проверки интерфейса согласий на вымышленных данных. "
                   "Он не является договором, политикой обработки персональных данных, NDA или электронной подписью. "
                   "Перед использованием платформы реальными участниками владелец должен предоставить утверждённую редакцию.\n\n"
                   f"Область демонстрации: {scope}. Версия: demo-1.")
        version = add(DocumentVersion, "version-"+slug, document_id=document, version="demo-1", content=content, content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(), published_at=anchor-timedelta(days=15))
        versions.append((version, scope, roles))
    for key, _, role, *_ in user_specs:
        for version, scope, roles in versions:
            if role in roles:
                add(Consent, f"consent-{key}-{version}", user_id=users[key], document_version_id=version, accepted_at=anchor-timedelta(days=13), method="demo_seed", ip_address=None, user_agent="Synthetic development dataset")
        if role != "admin":
            add(RegistrationReview, "review-"+key, user_id=users[key], admin_id=users["admin"], decision="approved", reason="Вымышленная анкета: автоматическое одобрение только при явном создании демоданных.", created_at=anchor-timedelta(days=13))
    for version, scope, roles in versions:
        if "mentee" in roles and scope == "registration":
            add(Consent, f"consent-pending-{version}", user_id=pending, document_version_id=version, accepted_at=anchor-timedelta(days=1), method="demo_seed", user_agent="Synthetic development dataset")

    project_ai = add(Project, "project-ai", owner_id=users["mentor"], mentor_id=users["mentor"], direction_id=ai, title="ИИ-помощник для учебных материалов · Демо", problem="Учебные заметки трудно быстро превратить в последовательный план повторения.", description="Вымышленный проект: изучаем потребности студентов и собираем небольшой прототип помощника по учебным заметкам.", private_details="Закрытый демонстрационный контекст. Все сведения вымышлены; реальных файлов и контактов здесь нет.", stage="prototype", required_skills=["Python", "UX research"], capacity=3, visibility_status="published", created_at=anchor-timedelta(days=10))
    project_design = add(Project, "project-design", owner_id=users["mentee-project"], mentor_id=users["mentor-design"], direction_id=product, title="Навигатор первого карьерного шага · Демо", problem="Начинающим специалистам сложно определить первый реалистичный карьерный шаг.", description="Вымышленный кейс: карта пользовательского пути и интерактивный прототип карьерного навигатора.", private_details="Синтетический сценарий исследования без настоящих респондентов.", stage="completed", required_skills=["Product discovery", "Figma"], capacity=3, visibility_status="published", created_at=anchor-timedelta(days=20))
    add(Project, "project-web", owner_id=users["mentee-candidate"], mentor_id=None, direction_id=code, title="Доступный планировщик встреч · Демо", problem="Нужно учитывать часовые пояса и доступность интерфейса при выборе встреч.", description="Вымышленная идея менти: сделать понятный планировщик с доступными формами и корректными часовыми поясами.", private_details="Демонстрационная идея без реальных пользовательских данных.", stage="idea", required_skills=["TypeScript", "Accessibility"], capacity=2, visibility_status="published", created_at=anchor-timedelta(days=3))
    add(Project, "project-pending", owner_id=users["mentee-candidate"], mentor_id=None, direction_id=ai, title="Помощник исследователя · Демо, на проверке", problem="Нужен простой способ структурировать заметки из открытых источников.", description="Вымышленная карточка для демонстрации проверки проектов администратором.", private_details="", stage="idea", required_skills=["Python"], capacity=2, visibility_status="pending", created_at=anchor-timedelta(days=1))

    active = add(Participation, "participation-active", project_id=project_ai, mentee_id=users["mentee"], mentor_id=users["mentor"], status="active", started_at=anchor-timedelta(days=7))
    completed = add(Participation, "participation-completed", project_id=project_design, mentee_id=users["mentee-project"], mentor_id=users["mentor-design"], status="completed_successfully", started_at=anchor-timedelta(days=20), completed_at=anchor-timedelta(days=2))
    for project, key, role in [(project_ai,"mentor","mentor"),(project_ai,"mentee","mentee"),(project_design,"mentor-design","mentor"),(project_design,"mentee-project","mentee")]:
        add(ProjectMember, f"member-{project}-{key}", project_id=project, user_id=users[key], member_role=role, joined_at=anchor-timedelta(days=7))
    for participation, when in [(active, anchor-timedelta(days=7)), (completed, anchor-timedelta(days=20))]:
        add(ParticipationEvent, "event-start-"+participation, participation_id=participation, actor_id=users["admin"], from_status=None, to_status="active", reason="Начало вымышленного демонстрационного участия", created_at=when)
    add(ParticipationEvent, "event-complete", participation_id=completed, actor_id=users["mentee-project"], from_status="active", to_status="completed_successfully", reason="Вымышленное завершение демонстрации", created_at=anchor-timedelta(days=2))
    application = add(Application, "application-pending", project_id=project_ai, mentee_id=users["mentee-candidate"], mentor_id=users["mentor"], motivation="Демонстрационная заявка: хочу потренироваться в разработке ИИ-прототипа.", status="pending", created_at=anchor-timedelta(days=1))
    add(Application, "application-accepted", project_id=project_ai, mentee_id=users["mentee"], mentor_id=users["mentor"], motivation="Вымышленная заявка для активного участия.", status="accepted", created_at=anchor-timedelta(days=8))

    conversation = add(Conversation, "conversation-active", participation_id=active, created_at=anchor-timedelta(days=7))
    pending_conversation = add(Conversation, "conversation-pending", application_id=application, created_at=anchor-timedelta(days=1))
    for conv, members in [(conversation,["mentor","mentee"]),(pending_conversation,["mentor","mentee-candidate"])]:
        for key in members:
            add(ConversationMember, f"conversation-member-{conv}-{key}", conversation_id=conv, user_id=users[key])
    add(Message, "message-hello", conversation_id=conversation, sender_id=users["mentor"], body="Демонстрационное сообщение: на первой встрече уточним цель и небольшой проверяемый результат.", created_at=anchor-timedelta(days=6))
    add(Message, "message-reply", conversation_id=conversation, sender_id=users["mentee"], body="Демонстрационное сообщение: подготовила список пользовательских задач и черновик плана.", created_at=anchor-timedelta(days=5))

    for key, mentor, days, hour in [("ai-1","mentor",1,12),("ai-2","mentor",3,12),("design-1","mentor-design",2,11),("design-2","mentor-design",4,11)]:
        start = (anchor+timedelta(days=days)).replace(hour=hour)
        add(Slot, "slot-"+key, mentor_id=users[mentor], starts_at=start, ends_at=start+timedelta(minutes=30), timezone="Asia/Oral", status="available", created_at=anchor)
    past_start = anchor-timedelta(days=4)
    old_slot = add(Slot, "slot-completed", mentor_id=users["mentor-design"], starts_at=past_start, ends_at=past_start+timedelta(minutes=30), timezone="Asia/Oral", status="booked", created_at=anchor-timedelta(days=5))
    add(Booking, "booking-completed", slot_id=old_slot, mentee_id=users["mentee-project"], mentor_id=users["mentor-design"], participation_id=completed, status="completed", meeting_url=None, created_at=anchor-timedelta(days=5))
    add(Result, "result-completed", participation_id=completed, status="completed_successfully", exit_reason="goal_achieved", initiator="mentee", artifact_url="https://example.test/demo-career-prototype", summary="Синтетический кейс: подготовлены карта пользовательского пути и демонстрационный прототип. Это не результат реальной программы.", meeting_count=1, verification_status="verified", completed_at=anchor-timedelta(days=2))
    for key, target in [("mentee-project","mentor"),("mentor-design","mentee")]:
        add(Feedback, "feedback-"+key, participation_id=completed, author_id=users[key], target_role=target, rating=5, nps=9, comment="Синтетический отзыв для проверки интерфейса, не реальная оценка программы.", created_at=anchor-timedelta(days=2))
        add(ShowcaseConsent, "showcase-"+key, project_id=project_design, user_id=users[key], accepted=True, updated_at=anchor-timedelta(days=2))
    add(Notification, "notification-mentee", user_id=users["mentee"], kind="participation", title="Ваш демонстрационный проект готов к работе", body="Выберите свободное время и подготовьте вопросы для первой встречи.", created_at=anchor-timedelta(days=1))
    add(Notification, "notification-mentor", user_id=users["mentor"], kind="application", title="Новая демонстрационная заявка", body="Вымышленная участница подала заявку на учебный проект.", created_at=anchor-timedelta(days=1))
    add(AuditEvent, "audit-seed", actor_id=users["admin"], action="demo_seed", entity_type="environment", entity_id=demo_id("environment"), detail={"synthetic": True, "reference_date": anchor.date().isoformat()}, created_at=anchor)
    db.commit()
    return {key+"@example.test": identifier for key, identifier in users.items()}


def main():
    parser = argparse.ArgumentParser(description="Insert synthetic development demo data; never use on real-user databases.")
    parser.add_argument("--create-tables", action="store_true", help="Explicitly create missing tables in this development database (prefer Alembic migrations).")
    parser.add_argument("--reference-date", type=date.fromisoformat, help="ISO date for reproducible timestamps; defaults to today's UTC date.")
    args = parser.parse_args()
    if settings.environment != "development" or not settings.demo_mode:
        parser.error("Set ENVIRONMENT=development and DEMO_MODE=true explicitly before seeding.")
    if args.create_tables:
        Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        users = seed_demo(db, args.reference_date)
    print("Synthetic demo records ready; existing records preserved. These are not real participants or legal consents.")
    for email in users:
        print(email)
    print("Sign in through the development email code flow (AUTH_DEBUG_CODE=true); no demo passwords exist.")


if __name__ == "__main__":
    main()
