"""
Unit testy service vrstvy domény Social (ActivityService, ActivityTypeService).

Testy nepotřebují Postgres: loader je nahrazen SqliteLoaderem (monkeypatch na getLoader), který skutečně
provádí SQL nad SQLite v paměti s reálnými modely ActivityModel a ActivityTypeModel. Ověřuje se tedy
doménová logika service včetně správnosti SQL podmínek (např. IS NULL), ne jen volání mockované metody.

SqliteLoader navíc filter_by záměrně odmítá: při ostrém běhu (CLI) skončilo volání filter_by jako první dotaz
nad loaderem chybou "No inspection system is available ...". Services domény Social proto musí používat jen
execute_select a load; test selže, pokud by některá metoda filter_by znovu použila.

Generický CRUD nad skutečnou DB řeší tests/services/test_servicedefinitions_crud.py,
který si nové services najde sám přes ServiceRegistry.

Spuštění:

    python -m pytest tests/services/test_activity_services_unit.py -q
"""

from __future__ import annotations

import types
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from src.DBDefinitions import ActivityModel, ActivityTypeModel, BaseDBModel
from src.ServiceDefinitions.BaseService import BaseService, ServiceExceptionWithCode
from src.ServiceDefinitions.Domain_Social import ActivityService, ActivityTypeService
from src.ServiceDefinitions.ServiceContext import SERVICES


class SqliteLoader:
    """
    Náhrada IDLoaderu nad SQLite v paměti.

    - execute_select provede libovolný select (jako ostrý loader),
    - load vrací řádek podle primárního klíče,
    - filter_by vždy vyhodí chybu (stejnou jako ostrý loader při ostrém běhu), service ho nesmí používat,
    - všechna volání se zaznamenávají, aby je testy mohly zkontrolovat.
    """

    def __init__(self, session: Session, model):
        self.session = session
        self.model = model
        self.filter_calls = []
        self.statements = []

    async def execute_select(self, stmt):
        self.statements.append(stmt)
        return list(self.session.scalars(stmt).all())

    async def load(self, id_):
        return self.session.get(self.model, id_)

    async def filter_by(self, **kwargs):
        self.filter_calls.append(kwargs)
        raise sa.exc.NoInspectionAvailable(
            "No inspection system is available for object of type <class 'type'>"
        )


@pytest.fixture
def session():
    # čistá SQLite databáze v paměti s tabulkami z reálných modelů, pro každý test nová
    engine = sa.create_engine("sqlite://")
    BaseDBModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _add(session: Session, *rows):
    session.add_all(rows)
    session.commit()
    return rows if len(rows) != 1 else rows[0]


def _patch_loader(monkeypatch, service_cls, loader):
    async def fake_get_loader(cls, ctx):
        return loader

    monkeypatch.setattr(service_cls, "getLoader", classmethod(fake_get_loader))
    return loader


def _activity_loader(session, monkeypatch):
    return _patch_loader(monkeypatch, ActivityService, SqliteLoader(session, ActivityModel))


def _type_loader(session, monkeypatch):
    return _patch_loader(monkeypatch, ActivityTypeService, SqliteLoader(session, ActivityTypeModel))


def _ctx():
    return types.SimpleNamespace(user=None, Services=types.SimpleNamespace())


###########################################################################################################################
# registrace a getLoader
###########################################################################################################################


def test_social_services_are_registered_in_service_registry():
    # ServiceRegistry musí vracet třídy, které dědí z BaseService (podle toho je hledá CLI i generický CRUD test).
    assert SERVICES.ActivityService is ActivityService
    assert SERVICES.ActivityTypeService is ActivityTypeService
    assert issubclass(ActivityService, BaseService)
    assert issubclass(ActivityTypeService, BaseService)


@pytest.mark.asyncio
async def test_social_services_get_loader_returns_matching_loader_from_context():
    activity_loader = object()
    type_loader = object()
    ctx = types.SimpleNamespace(loaders=types.SimpleNamespace(ActivityModel=activity_loader, ActivityTypeModel=type_loader))

    assert await ActivityService.getLoader(ctx) is activity_loader
    assert await ActivityTypeService.getLoader(ctx) is type_loader


###########################################################################################################################
# ActivityService
###########################################################################################################################


@pytest.mark.asyncio
async def test_activity_read_by_entity_converts_string_id_and_filters(session, monkeypatch):
    entity_id = uuid.uuid4()
    matching = _add(session, ActivityModel(entity_id=entity_id, title="mine"))
    _add(session, ActivityModel(entity_id=uuid.uuid4(), title="other"))
    loader = _activity_loader(session, monkeypatch)

    # id přijde jako řetězec (tak ho předává CLI), do dotazu musí dojít uuid.UUID
    result = await ActivityService.ReadByEntity(ctx=_ctx(), entity_id=str(entity_id))

    assert [row.id for row in result] == [matching.id]
    # filter_by se nesmí použít (to byla chyba z ostrého běhu)
    assert loader.filter_calls == []
    assert len(loader.statements) == 1


@pytest.mark.asyncio
async def test_activity_read_by_entity_adds_entity_type_filter_when_given(session, monkeypatch):
    entity_id = uuid.uuid4()
    entity_type_id = uuid.uuid4()
    matching = _add(session, ActivityModel(entity_id=entity_id, entity_type_id=entity_type_id))
    _add(session, ActivityModel(entity_id=entity_id, entity_type_id=uuid.uuid4()))
    _activity_loader(session, monkeypatch)

    result = await ActivityService.ReadByEntity(ctx=_ctx(), entity_id=entity_id, entity_type_id=str(entity_type_id))

    assert [row.id for row in result] == [matching.id]


@pytest.mark.asyncio
async def test_activity_read_by_entity_returns_empty_list_when_nothing_matches(session, monkeypatch):
    _add(session, ActivityModel(entity_id=uuid.uuid4()))
    _activity_loader(session, monkeypatch)

    assert await ActivityService.ReadByEntity(ctx=_ctx(), entity_id=uuid.uuid4()) == []


@pytest.mark.asyncio
async def test_activity_read_by_entity_raises_when_entity_id_is_missing(session, monkeypatch):
    loader = _activity_loader(session, monkeypatch)

    with pytest.raises(ServiceExceptionWithCode) as exc_info:
        await ActivityService.ReadByEntity(ctx=_ctx(), entity_id=None)

    assert exc_info.value.code == "activity_entity_id_missing"
    assert exc_info.value.location == "ReadByEntity"
    assert loader.statements == []  # k dotazu do DB vůbec nedošlo


@pytest.mark.asyncio
async def test_activity_read_by_entity_raises_for_invalid_uuid(session, monkeypatch):
    loader = _activity_loader(session, monkeypatch)

    with pytest.raises(ServiceExceptionWithCode) as exc_info:
        await ActivityService.ReadByEntity(ctx=_ctx(), entity_id="not-a-uuid")

    assert exc_info.value.code == "activity_entity_id_invalid"
    assert loader.statements == []


@pytest.mark.asyncio
async def test_activity_read_by_actor_filters_by_actor_id(session, monkeypatch):
    actor_id = uuid.uuid4()
    mine = _add(session, ActivityModel(actor_id=actor_id))
    _add(session, ActivityModel(actor_id=uuid.uuid4()))
    loader = _activity_loader(session, monkeypatch)

    result = await ActivityService.ReadByActor(ctx=_ctx(), actor_id=str(actor_id))

    assert [row.id for row in result] == [mine.id]
    assert loader.filter_calls == []


@pytest.mark.asyncio
async def test_activity_read_by_actor_raises_when_actor_id_is_missing(session, monkeypatch):
    _activity_loader(session, monkeypatch)

    with pytest.raises(ServiceExceptionWithCode) as exc_info:
        await ActivityService.ReadByActor(ctx=_ctx(), actor_id=None)

    assert exc_info.value.code == "activity_actor_id_missing"


@pytest.mark.asyncio
async def test_activity_read_by_activity_type_matches_only_exact_type(session, monkeypatch):
    root = _add(session, ActivityTypeModel(name="activity"))
    child = _add(session, ActivityTypeModel(name="created", parent_id=root.id))
    matching = _add(session, ActivityModel(activity_type_id=child.id))
    _add(session, ActivityModel(activity_type_id=root.id))
    _activity_loader(session, monkeypatch)

    result = await ActivityService.ReadByActivityType(ctx=_ctx(), activity_type_id=child.id)

    assert [row.id for row in result] == [matching.id]


@pytest.mark.asyncio
async def test_activity_execute_service_method_turns_service_error_into_error_callback(session, monkeypatch):
    # Ověřuje napojení na BaseService.ExecuteServiceMethod: chyba service se převede na Error callback s kódem.
    _activity_loader(session, monkeypatch)
    captured = {}

    async def on_error(msg, code, exception=None):
        captured.update(msg=msg, code=code)
        return "error-result"

    result = await ActivityService.ExecuteServiceMethod(
        ActivityService.ReadByEntity(ctx=_ctx(), entity_id=None),
        Error=on_error,
    )

    assert result == "error-result"
    assert captured["code"] == "activity_entity_id_missing"


###########################################################################################################################
# ActivityTypeService
###########################################################################################################################


@pytest.mark.asyncio
async def test_activity_type_read_by_name_returns_matching_type(session, monkeypatch):
    created = _add(session, ActivityTypeModel(name="created"))
    _add(session, ActivityTypeModel(name="changed"))
    loader = _type_loader(session, monkeypatch)

    result = await ActivityTypeService.ReadByName(ctx=_ctx(), name="created")

    assert result.id == created.id
    assert loader.filter_calls == []


@pytest.mark.asyncio
async def test_activity_type_read_by_name_returns_none_when_not_found(session, monkeypatch):
    _add(session, ActivityTypeModel(name="created"))
    _type_loader(session, monkeypatch)

    assert await ActivityTypeService.ReadByName(ctx=_ctx(), name="missing") is None


@pytest.mark.asyncio
async def test_activity_type_read_by_name_raises_for_empty_name(session, monkeypatch):
    loader = _type_loader(session, monkeypatch)

    with pytest.raises(ServiceExceptionWithCode) as exc_info:
        await ActivityTypeService.ReadByName(ctx=_ctx(), name="")

    assert exc_info.value.code == "activity_type_name_missing"
    assert loader.statements == []


@pytest.mark.asyncio
async def test_activity_type_read_roots_returns_only_types_without_parent(session, monkeypatch):
    root = _add(session, ActivityTypeModel(name="activity"))
    other_root = _add(session, ActivityTypeModel(name="other_root"))
    _add(session, ActivityTypeModel(name="created", parent_id=root.id))
    _type_loader(session, monkeypatch)

    result = await ActivityTypeService.ReadRoots(ctx=_ctx())

    # skutečné SQL "parent_id IS NULL": potomek se nesmí vrátit, oba kořeny ano
    assert {row.id for row in result} == {root.id, other_root.id}


@pytest.mark.asyncio
async def test_activity_type_read_children_returns_direct_children_only(session, monkeypatch):
    root = _add(session, ActivityTypeModel(name="activity"))
    child = _add(session, ActivityTypeModel(name="created", parent_id=root.id))
    _add(session, ActivityTypeModel(name="created_by_import", parent_id=child.id))
    loader = _type_loader(session, monkeypatch)

    result = await ActivityTypeService.ReadChildren(ctx=_ctx(), parent_id=str(root.id))

    assert [row.id for row in result] == [child.id]
    assert loader.filter_calls == []  # filter_by jako první dotaz nad loaderem selhával, používá se select


@pytest.mark.asyncio
async def test_activity_type_read_subtree_returns_type_and_all_descendants(session, monkeypatch):
    root = _add(session, ActivityTypeModel(name="activity"))
    created = _add(session, ActivityTypeModel(name="created", parent_id=root.id))
    changed = _add(session, ActivityTypeModel(name="changed", parent_id=root.id))
    changed_state = _add(session, ActivityTypeModel(name="state_changed", parent_id=changed.id))
    unrelated = _add(session, ActivityTypeModel(name="other_root"))
    _type_loader(session, monkeypatch)

    result = await ActivityTypeService.ReadSubtree(ctx=_ctx(), type_id=root.id)

    assert result[0].id == root.id  # zadaný typ je vždy první
    assert {row.id for row in result} == {root.id, created.id, changed.id, changed_state.id}
    assert unrelated.id not in {row.id for row in result}


@pytest.mark.asyncio
async def test_activity_type_read_subtree_of_leaf_returns_only_itself(session, monkeypatch):
    root = _add(session, ActivityTypeModel(name="activity"))
    leaf = _add(session, ActivityTypeModel(name="created", parent_id=root.id))
    _type_loader(session, monkeypatch)

    result = await ActivityTypeService.ReadSubtree(ctx=_ctx(), type_id=leaf.id)

    assert [row.id for row in result] == [leaf.id]


@pytest.mark.asyncio
async def test_activity_type_read_subtree_survives_cycle_in_data(session, monkeypatch):
    # Poškozená data: a -> b -> a. Procházení se nesmí zacyklit a každý typ se vrátí jen jednou.
    id_a, id_b = uuid.uuid4(), uuid.uuid4()
    _add(session, ActivityTypeModel(id=id_a, name="a", parent_id=id_b), ActivityTypeModel(id=id_b, name="b", parent_id=id_a))
    _type_loader(session, monkeypatch)

    result = await ActivityTypeService.ReadSubtree(ctx=_ctx(), type_id=id_a)

    assert sorted(row.name for row in result) == ["a", "b"]


@pytest.mark.asyncio
async def test_activity_type_read_subtree_raises_when_type_does_not_exist(session, monkeypatch):
    _type_loader(session, monkeypatch)

    with pytest.raises(ServiceExceptionWithCode) as exc_info:
        await ActivityTypeService.ReadSubtree(ctx=_ctx(), type_id=uuid.uuid4())

    assert exc_info.value.code == "activity_type_not_found"
    assert exc_info.value.location == "ReadSubtree"