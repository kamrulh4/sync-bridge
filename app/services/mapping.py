from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.db import Mapping, MappingType
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
    async def import_from_csv(
        session: AsyncSession, csv_content: str, m_type: MappingType
    ):
        """
        Imports mappings from CSV.
        Format expected: external_id, display_name, internal_id
        (Falls back to 2-column format: external_id, internal_id)
        """
        reader = csv.reader(io.StringIO(csv_content))
        next(reader, None)  # Skip header row
        for row in reader:
            if len(row) < 2:
                continue
            ext_id = row[0].strip()
            # Use column 2 (talk_username / room_token) if available, else column 1
            int_id = row[2].strip() if len(row) >= 3 else row[1].strip()

            if not ext_id or not int_id:
                continue

            # Check if exists
            existing = await MappingService.get_internal_id(session, ext_id, m_type)
            if not existing:
                new_mapping = Mapping(
                    type=m_type, external_id=ext_id, internal_id=int_id
                )
                session.add(new_mapping)

        await session.commit()
