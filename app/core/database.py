from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import settings

# Determine connection arguments based on database dialect
connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

# Create SQLAlchemy Engine
engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    echo=settings.APP_DEBUG
)

# Enable Foreign Key support and WAL mode for SQLite
if settings.DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

# Session Factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base Declarative Class
Base = declarative_base()


def get_db():
    """Dependency injection for database session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
