"""
Apex Scout - Veritabanı Katmanı (SQLAlchemy 2.0)
SQLite ile başlar, PostgreSQL'e geçiş kolaydır.
"""

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from config.settings import settings


class Base(DeclarativeBase):
    """Base class for all models"""

    pass


# Engine oluşturma - SQLite için özel ayarlar
def create_db_engine():
    """Veritabanı motorunu oluşturur"""
    db_url = settings.db_url

    if db_url.startswith("sqlite"):
        # SQLite için: thread safety ve foreign key desteği
        engine = create_engine(
            db_url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            echo=False,  # True yaparsanız SQL logları görürsünüz
        )

        # SQLite pragmaları - WAL modu eşzamanlı erişim (bot + dashboard) için şart
        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            # WAL: eşzamanlı okuma + yazma (dashboard bot DB'sini okurken bot yazar)
            cursor.execute("PRAGMA journal_mode=WAL")
            # Busy timeout: lock çakışmasında bekle (5 saniye)
            cursor.execute("PRAGMA busy_timeout=5000")
            # Senkron: normal (NORMAL WAL ile daha hızlı, güvenli yeterli)
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()

    else:
        # PostgreSQL, MySQL vb. için
        engine = create_engine(
            db_url,
            pool_pre_ping=True,
            pool_recycle=3600,
            echo=False,
        )

    return engine


engine = create_db_engine()
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    """Veritabanı tablolarını oluşturur"""
    # Models'ları import et (metadata register olması için)
    from shared.models import Decision, Position, SystemMetrics, Token, Trade  # noqa: F401

    Base.metadata.create_all(bind=engine)


def drop_db() -> None:
    """Veritabanı tablolarını siler (test için)"""
    Base.metadata.drop_all(bind=engine)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """
    Veritabanı oturumu context manager.
    Kullanım:
        with get_session() as session:
            session.add(obj)
            session.commit()
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session_direct() -> Session:
    """
    Direkt session döner (manuel commit/close gerekir).
    Dependency injection veya uzun süreli işlemler için.
    """
    return SessionLocal()


# Alembic migration desteği için
def get_engine():
    """Alembic için engine döner"""
    return engine
