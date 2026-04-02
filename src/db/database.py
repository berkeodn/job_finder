from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from config import settings

from .models import Base

engine = create_engine(settings.db_url, echo=False)
SessionLocal = sessionmaker(bind=engine)


def init_db() -> None:
    Base.metadata.create_all(engine)


def get_session() -> Session:
    return SessionLocal()
