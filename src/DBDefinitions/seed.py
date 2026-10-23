from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import NoInspectionAvailable
from sqlalchemy.ext.asyncio import AsyncSession

from uoishelpers.dataloaders import readJsonFile
from uoishelpers.feeders import ImportModels

from src.DBDefinitions import BaseDBModel

logger = logging.getLogger(__name__)

# systemdata.json lives in the repository root. The path is derived from this
# file's location, so it does not depend on the current working directory.
# It can be overridden with the SYSTEMDATA_PATH environment variable.
DEFAULT_SYSTEMDATA_PATH = Path(__file__).resolve().parents[2] / "systemdata.json"


def get_systemdata_path() -> Path:
    return Path(os.environ.get("SYSTEMDATA_PATH") or DEFAULT_SYSTEMDATA_PATH)


def is_demo_enabled() -> bool:
    """Demo (non-catalog) data are imported unless DEMODATA is explicitly false.

    DEMODATA unset -> demo data ON (keeps tests and local runs working),
    DEMODATA=False/0/no/off -> only *TypeModel catalogs are imported.
    """
    value = os.environ.get("DEMODATA")
    if value is None:
        return True
    return str(value).strip().lower() not in {"false", "0", "no", "off", ""}


def is_sqlalchemy_model(cls: type) -> bool:
    """Return True only for SQLAlchemy mapped model classes."""
    try:
        mapper = sa_inspect(cls, raiseerr=False)
        return mapper is not None
    except NoInspectionAvailable:
        return False


def get_demodata():
    return readJsonFile(jsonFileName=str(get_systemdata_path()))


def select_models_to_import(is_demo: bool) -> list[type]:
    """Models to seed, ordered so that referenced tables are filled first.

    ImportModels walks the models in the order it is given them. The order of
    BaseDBModel.registry.mappers is the import order, which is not the foreign
    key order (e.g. activities would be inserted before activitytypes), so the
    models are sorted by metadata.sorted_tables (parents before children).
    """
    models = [
        mapper.class_
        for mapper in BaseDBModel.registry.mappers
        if is_sqlalchemy_model(mapper.class_) and hasattr(mapper.class_, "__tablename__")
    ]
    if not is_demo:
        models = [model for model in models if model.__name__.endswith("TypeModel")]

    by_table = {model.__tablename__: model for model in models}
    return [
        by_table[table.name]
        for table in BaseDBModel.metadata.sorted_tables
        if table.name in by_table
    ]


async def init_database_data(session: AsyncSession, get_demodata=get_demodata) -> None:
    """Idempotent seed hook for application startup.

    Rows whose id already exists are skipped, so it is safe to call repeatedly.
    It is called from DatabaseRuntime.start() after metadata.create_all().
    """

    json_data = get_demodata()
    is_demo = is_demo_enabled()
    models_to_import = select_models_to_import(is_demo)

    logger.info(
        "Seeding (demo=%s): %s",
        is_demo,
        [model.__tablename__ for model in models_to_import],
    )

    @asynccontextmanager
    async def session_maker():
        # ImportModels opens several "sessions" in a row and calls
        # session.begin() on them. With one shared session that fails
        # ("A transaction is already begun") as soon as an earlier SELECT
        # autobegan a transaction, so close it before handing the session out.
        if session.in_transaction():
            await session.commit()
        try:
            yield session
        finally:
            if session.in_transaction():
                await session.commit()

    await ImportModels(session_maker, models_to_import, json_data)

    logger.info("Seed data initialized")