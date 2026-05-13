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
        session: AsyncSession, slack_ts: str, talk_msg_id: str, channel_id: str
    ):
        """Saves a link between Slack and Nextcloud messages."""
        mapping = MessageMapping(
            slack_ts=slack_ts, talk_msg_id=str(talk_msg_id), channel_id=channel_id
        )
        session.add(mapping)
        await session.commit()

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
        Format expected: external_id, (name/ignore), internal_id, ...
        """
        reader = csv.reader(io.StringIO(csv_content))
        header = next(reader, None)  # Skip header row
        
        count = 0
        for row in reader:
            if not row or len(row) < 2:
                continue
            
            ext_id = row[0].strip()
            # If 3+ columns, assume 3rd column is internal_id (index 2)
            # If 2 columns, assume 2nd column is internal_id (index 1)
            int_id = row[2].strip() if len(row) >= 3 else row[1].strip()

            if not ext_id or not int_id:
                continue

            # Check if mapping already exists
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
