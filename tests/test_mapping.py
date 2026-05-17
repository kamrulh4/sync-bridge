import pytest
from app.services.mapping import MappingService
from app.models.db import MappingType


@pytest.mark.asyncio
async def test_mapping_import_and_lookup(db_session):
    csv_content = "U123,john.doe\nU456,jane.smith"
    await MappingService.import_from_csv(db_session, csv_content, MappingType.USER)

    # Test Lookup Slack -> Nextcloud
    int_id = await MappingService.get_internal_id(db_session, "U123", MappingType.USER)
    assert int_id == "john.doe"

    # Test Lookup Nextcloud -> Slack
    ext_id = await MappingService.get_external_id(
        db_session, "jane.smith", MappingType.USER
    )
    assert ext_id == "U456"


@pytest.mark.asyncio
async def test_filesink_import_and_lookup(db_session):
    csv_content = "platform,channel_id,channel_name\nslack,C0B18DWU309,bridge-files\ntalk,8n9pggb8,bridge-files"
    count = await MappingService.import_from_csv(db_session, csv_content, MappingType.FILE_SINK)
    assert count == 2

    slack_sink = await MappingService.get_internal_id(db_session, "slack", MappingType.FILE_SINK)
    talk_sink = await MappingService.get_internal_id(db_session, "talk", MappingType.FILE_SINK)
    assert slack_sink == "C0B18DWU309"
    assert talk_sink == "8n9pggb8"


@pytest.mark.asyncio
async def test_mapping_duplicate_import(db_session):
    csv_content = "U123,john.doe"
    await MappingService.import_from_csv(db_session, csv_content, MappingType.USER)
    await MappingService.import_from_csv(db_session, csv_content, MappingType.USER)

    # Should only have one record (implicit check by lookup still working)
    int_id = await MappingService.get_internal_id(db_session, "U123", MappingType.USER)
    assert int_id == "john.doe"
