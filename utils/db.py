from contextlib import contextmanager
from database import SessionLocal


@contextmanager
def get_db():
    """
    Provide a SQLAlchemy session that is always closed.
    Usage:
        with get_db() as db:
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
