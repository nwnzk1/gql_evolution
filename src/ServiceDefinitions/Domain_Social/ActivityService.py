import typing
import uuid

from sqlalchemy import select
from uoishelpers.dataloaders.IDLoader import IDLoader

from src.DBDefinitions import ActivityModel
from src.ServiceDefinitions.BaseService import BaseService, ServiceExceptionWithCode
from src.ServiceDefinitions.ServiceContext import ServiceContext

###########################################################################################################################
#
# ActivityService – vrstva služeb (Services) pro entitu Activity (tabulka "activities", doména Social).
#
# Architektura (stejná jako ve vzoru gql_evolution, větev 2026):
#
#     GQL model / resolver  ->  Service (tato třída)  ->  DataLoader (IDLoader z LoaderMap)  ->  DB model (ActivityModel)
#
# Pravidla:
# - Service NIKDY nesahá přímo na DB session ani nepíše SQL; vždy jde přes dataloader z ctx.loaders.
#   Díky tomu se dotazy dávkují a nevzniká problém N+1.
# - Standardní CRUD (Create, ReadById, ReadPage, Update, Delete) je zděděný z BaseService, proto se zde neopakuje.
#   Update a Delete používají sloupec "lastchange" jako optimistický zámek (řeší BaseService).
# - Zde jsou jen doménové (business) metody specifické pro Activity.
# - Filtrování podle sloupců bez skutečného cizího klíče (entity_id, actor_id; UUIDFKey totiž ForeignKey ignoruje)
#   se dělá explicitním select + loader.execute_select. Metoda loader.filter_by(...) funguje přes FKeyLoader
#   a vyžaduje sloupec se skutečným cizím klíčem; pro entity_id skončila chybou
#   "No inspection system is available for object of type <class 'type'>".
# - Chyby aplikační logiky se hlásí přes ServiceExceptionWithCode; zachytává je BaseService.ExecuteServiceMethod
#   a převádí na typovanou chybu (Error callback), takže resolver nemusí řešit výjimky ručně.
#
###########################################################################################################################


class ActivityService(BaseService[IDLoader[ActivityModel]]):
    @classmethod
    async def getLoader(cls, ctx: ServiceContext) -> IDLoader[ActivityModel]:
        # Jediná povinná metoda každé service: vrací dataloader pro příslušný DB model.
        # Název atributu (ActivityModel) musí odpovídat atributu LoaderMap v src/Dataloaders/__init__.py.
        return ctx.loaders.ActivityModel

    @classmethod
    def _ToUUID(cls, value: typing.Any, *, name: str, location: str) -> uuid.UUID:
        """
        Pomocná (privátní) funkce: převede hodnotu na uuid.UUID.

        Proč je potřeba:
        - CLI (src/ServiceDefinitions/main.py) předává ID jako řetězce z JSON payloadu,
        - dataloader filtruje nad sloupcem typu UUID, proto musí dostat uuid.UUID, ne str.

        Chybí-li hodnota, nebo není validní UUID, vyhodí ServiceExceptionWithCode
        (kód např. "activity_entity_id_missing" / "activity_entity_id_invalid").
        Metody s prefixem "_" nejsou z CLI dostupné.
        """
        # Hodnota nebyla zadána -> chyba aplikační logiky.
        if value is None:
            raise ServiceExceptionWithCode(
                f'{name} is required',
                code=f'activity_{name}_missing',
                location=location,
            )
        # Už je to UUID -> nic se nepřevádí.
        if isinstance(value, uuid.UUID):
            return value
        # Řetězec (např. z CLI/GraphQL) -> pokus o převod, špatný formát je chyba aplikační logiky.
        try:
            return uuid.UUID(str(value))
        except ValueError as e:
            raise ServiceExceptionWithCode(
                f'{name} is not a valid UUID',
                code=f'activity_{name}_invalid',
                location=location,
            ) from e

    @classmethod
    async def ReadByEntity(
        cls,
        ctx: ServiceContext,
        entity_id: typing.Union[uuid.UUID, str],
        entity_type_id: typing.Union[uuid.UUID, str, None] = None,
    ) -> list[ActivityModel]:
        """
        Vrátí aktivity vztahující se k jedné entitě (např. všechny aktivity jedné skupiny).

        - entity_id je povinné (id entity, ke které se aktivita vztahuje),
        - entity_type_id je volitelný zpřesňující filtr.
        Nenalezeno = prázdný seznam (není to chyba).
        """
        loader = await cls.getLoader(ctx)

        # Validace a převod id (chyba = ServiceExceptionWithCode ještě před dotazem do DB).
        entity_id = cls._ToUUID(entity_id, name='entity_id', location='ReadByEntity')

        # Dotaz skládáme postupně, aby se nezadaný entity_type_id do podmínky vůbec nedostal.
        stmt = select(ActivityModel).where(ActivityModel.entity_id == entity_id)
        if entity_type_id is not None:
            entity_type_id = cls._ToUUID(entity_type_id, name='entity_type_id', location='ReadByEntity')
            stmt = stmt.where(ActivityModel.entity_type_id == entity_type_id)

        # execute_select je metoda dataloaderu: dotaz proběhne přes loader (ne přes vlastní session).
        return await loader.execute_select(stmt)

    @classmethod
    async def ReadByActor(cls, ctx: ServiceContext, actor_id: typing.Union[uuid.UUID, str]) -> list[ActivityModel]:
        """
        Vrátí aktivity, které vyvolal daný uživatel (actor_id).

        actor_id nemá v databázi skutečný cizí klíč (UUIDFKey argument ForeignKey ignoruje),
        uživatel se proto nijak neověřuje – vrací se jen shoda podle id.
        """
        loader = await cls.getLoader(ctx)
        actor_id = cls._ToUUID(actor_id, name='actor_id', location='ReadByActor')
        stmt = select(ActivityModel).where(ActivityModel.actor_id == actor_id)
        return await loader.execute_select(stmt)

    @classmethod
    async def ReadByActivityType(
        cls, ctx: ServiceContext, activity_type_id: typing.Union[uuid.UUID, str]
    ) -> list[ActivityModel]:
        """
        Vrátí aktivity přesně daného typu (activity_type_id).

        Pozor: hledá se pouze shoda s tímto jedním typem, potomci typu ve stromu
        (ActivityTypeModel.children) se nezahrnují. Pro procházení stromu typů slouží
        ActivityTypeService.ReadSubtree.
        """
        loader = await cls.getLoader(ctx)
        activity_type_id = cls._ToUUID(activity_type_id, name='activity_type_id', location='ReadByActivityType')
        stmt = select(ActivityModel).where(ActivityModel.activity_type_id == activity_type_id)
        return await loader.execute_select(stmt)