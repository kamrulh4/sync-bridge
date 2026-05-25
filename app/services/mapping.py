from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.db import Mapping, MappingType, MessageMapping
import csv
import io


class MappingService:
    @staticmethod
    async def get_internal_id(
        session: AsyncSession, external_id: str, m_type: MappingType
    ) -> str | None:
        """Slack ID -> Nextcloud ID"""
        result = await session.execute(
            select(Mapping.internal_id).where(
                Mapping.external_id == external_id, Mapping.type == m_type
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_external_id(
        session: AsyncSession, internal_id: str, m_type: MappingType
    ) -> str | None:
        """Nextcloud ID -> Slack ID"""
        result = await session.execute(
            select(Mapping.external_id).where(
                Mapping.internal_id == internal_id, Mapping.type == m_type
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def save_message_mapping(
        session: AsyncSession,
        slack_ts: str,
        talk_msg_id: str,
        channel_id: str,
        parent_slack_ts: str | None = None,
        parent_talk_id: str | None = None,
    ):
        """Saves a link between Slack and Nextcloud messages with parent relationship."""
        mapping = MessageMapping(
            slack_ts=slack_ts,
            talk_msg_id=str(talk_msg_id),
            channel_id=channel_id,
            parent_slack_ts=parent_slack_ts,
            parent_talk_id=parent_talk_id,
        )
        session.add(mapping)
        # Commit is handled by the caller

    @staticmethod
    async def get_talk_id_by_slack_ts(session: AsyncSession, slack_ts: str) -> str | None:
        """Finds Nextcloud message ID for a Slack timestamp."""
        result = await session.execute(
            select(MessageMapping.talk_msg_id).where(MessageMapping.slack_ts == slack_ts)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_slack_ts_by_talk_id(session: AsyncSession, talk_msg_id: str) -> str | None:
        """Finds Slack timestamp for a Nextcloud message ID."""
        result = await session.execute(
            select(MessageMapping.slack_ts).where(MessageMapping.talk_msg_id == str(talk_msg_id))
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def import_from_csv(
        session: AsyncSession, csv_content: str, m_type: MappingType
    ):
        """
        Imports mappings from CSV.
        Supported formats:
          external_id, internal_id
          external_id, name, internal_id
        """
        reader = csv.reader(io.StringIO(csv_content))
        rows = list(reader)
        if not rows:
            return 0

        first_row = rows[0]
        header_keywords = {
            "external_id",
            "internal_id",
            "slack_id",
            "talk_username",
            "channel_id",
            "room_token",
            "user",
            "channel",
            "platform",
            "channel_name",
            "slack_channel_name",
            "talk_room_name",
        }
        if any(cell.strip().lower() in header_keywords for cell in first_row):
            rows = rows[1:]

        count = 0
        for row in rows:
            if not row or len(row) < 2:
                continue

            ext_id = row[0].strip()
            if m_type == MappingType.FILE_SINK:
                int_id = row[1].strip()
            else:
                int_id = row[2].strip() if len(row) >= 3 else row[1].strip()

            if not ext_id or not int_id:
                continue

            result = await session.execute(
                select(Mapping).where(
                    Mapping.external_id == ext_id, Mapping.type == m_type
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                if existing.internal_id != int_id:
                    existing.internal_id = int_id
                    count += 1
            else:
                new_mapping = Mapping(
                    type=m_type, external_id=ext_id, internal_id=int_id
                )
                session.add(new_mapping)
                count += 1

        await session.commit()
        return count

    @staticmethod
    async def upsert_mapping(
        session: AsyncSession,
        external_id: str,
        internal_id: str,
        m_type: MappingType,
    ):
        result = await session.execute(
            select(Mapping).where(
                Mapping.external_id == external_id, Mapping.type == m_type
            )
        )
        mapping = result.scalar_one_or_none()
        if mapping:
            mapping.internal_id = internal_id
        else:
            mapping = Mapping(
                type=m_type, external_id=external_id, internal_id=internal_id
            )
            session.add(mapping)

        await session.commit()
        return mapping

    @staticmethod
    async def delete_mapping(
        session: AsyncSession, external_id: str, m_type: MappingType
    ):
        result = await session.execute(
            select(Mapping).where(
                Mapping.external_id == external_id, Mapping.type == m_type
            )
        )
        mapping = result.scalar_one_or_none()
        if mapping:
            await session.delete(mapping)
            await session.commit()
            return True
        return False
