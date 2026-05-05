from datetime import datetime
from sqlalchemy import String, DateTime, Text, Integer, Enum as SqlEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
import enum


class Base(DeclarativeBase):
    pass


class MappingType(enum.Enum):
    USER = "user"
    CHANNEL = "channel"


class Mapping(Base):
    __tablename__ = "mappings"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[MappingType] = mapped_column(SqlEnum(MappingType))
    external_id: Mapped[str] = mapped_column(String(255), index=True)  # Slack ID
    internal_id: Mapped[str] = mapped_column(String(255), index=True)  # Nextcloud ID


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(50))  # 'slack' or 'nextcloud'
    event_id: Mapped[str] = mapped_column(String(255), index=True)
    content: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50))  # 'success', 'failed', 'ignored'
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
