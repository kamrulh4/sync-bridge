from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from app.services.mapping import MappingService
from app.models.db import MappingType
from app.core.database import async_session

router = APIRouter()


class MappingItem(BaseModel):
    external_id: str
    internal_id: str


class CsvImportRequest(BaseModel):
    csv_content: str


@router.post("/user")
async def add_user_mapping(payload: MappingItem):
    async with async_session() as session:
        mapping = await MappingService.upsert_mapping(
            session, payload.external_id, payload.internal_id, MappingType.USER
        )
    return {
        "status": "ok",
        "mapping": {"external_id": mapping.external_id, "internal_id": mapping.internal_id},
    }


@router.post("/channel")
async def add_channel_mapping(payload: MappingItem):
    async with async_session() as session:
        mapping = await MappingService.upsert_mapping(
            session, payload.external_id, payload.internal_id, MappingType.CHANNEL
        )
    return {
        "status": "ok",
        "mapping": {"external_id": mapping.external_id, "internal_id": mapping.internal_id},
    }


@router.post("/filesink")
async def add_filesink_mapping(payload: MappingItem):
    async with async_session() as session:
        mapping = await MappingService.upsert_mapping(
            session, payload.external_id, payload.internal_id, MappingType.FILE_SINK
        )
    return {
        "status": "ok",
        "mapping": {"external_id": mapping.external_id, "internal_id": mapping.internal_id},
    }


@router.post("/import")
async def import_mappings(
    type: str = Query(..., pattern="^(user|channel|filesink)$"),
    payload: CsvImportRequest = None,
):
    if type == "user":
        m_type = MappingType.USER
    elif type == "channel":
        m_type = MappingType.CHANNEL
    else:
        m_type = MappingType.FILE_SINK

    async with async_session() as session:
        count = await MappingService.import_from_csv(session, payload.csv_content, m_type)

    return {"status": "ok", "imported": count}


@router.get("/user/{external_id}")
async def get_user_mapping(external_id: str):
    async with async_session() as session:
        internal_id = await MappingService.get_internal_id(session, external_id, MappingType.USER)
    if internal_id is None:
        raise HTTPException(status_code=404, detail="User mapping not found")
    return {"external_id": external_id, "internal_id": internal_id}


@router.get("/channel/{external_id}")
async def get_channel_mapping(external_id: str):
    async with async_session() as session:
        internal_id = await MappingService.get_internal_id(session, external_id, MappingType.CHANNEL)
    if internal_id is None:
        raise HTTPException(status_code=404, detail="Channel mapping not found")
    return {"external_id": external_id, "internal_id": internal_id}


@router.delete("/user/{external_id}")
async def delete_user_mapping(external_id: str):
    async with async_session() as session:
        deleted = await MappingService.delete_mapping(session, external_id, MappingType.USER)
    if not deleted:
        raise HTTPException(status_code=404, detail="User mapping not found")
    return {"status": "ok"}


@router.delete("/channel/{external_id}")
async def delete_channel_mapping(external_id: str):
    async with async_session() as session:
        deleted = await MappingService.delete_mapping(session, external_id, MappingType.CHANNEL)
    if not deleted:
        raise HTTPException(status_code=404, detail="Channel mapping not found")
    return {"status": "ok"}
