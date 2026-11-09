import typing
import uuid

from sqlalchemy import select
from uoishelpers.dataloaders.IDLoader import IDLoader

from src.DBDefinitions import ActivityTypeModel
from src.ServiceDefinitions.BaseService import BaseService, ServiceExceptionWithCode
from src.ServiceDefinitions.ServiceContext import ServiceContext

###########################################################################################################################
#
# ActivityTypeService – vrstva služeb (Services) pro číselník typů aktivit (tabulka "activitytypes", doména Social).
#
# Typy aktivit tvoří strom (ActivityTypeModel.parent_id), např. kořen "activity" a pod ním "created", "changed", ...
#
# Architektura: GQL model / resolver -> Service (tato třída) -> DataLoader (IDLoader z LoaderMap) -> ActivityTypeModel.
# - Service nesahá přímo na DB session; vždy jde přes dataloader z ctx.loaders (dávkování dotazů, bez problému N+1).
# - Standardní CRUD (Create, ReadById, ReadPage, Update, Delete) je zděděný z BaseService.
# - Zde jsou doménové metody pro práci se stromem a pro vyhledání typu podle interního názvu.
# - Chyby aplikační logiky se hlásí přes ServiceExceptionWithCode (zpracuje BaseService.ExecuteServiceMethod).
# - Dotazy podle sloupců se dělají explicitním select + loader.execute_select. Metoda loader.filter_by(...)
#   se zde NEPOUŽÍVÁ: při ostrém běhu (CLI) skončila jako první dotaz nad loaderem chybou
#   "No inspection system is available for object of type <class 'type'>" (u entity_id i parent_id).
#   Vzorové services ji volají až po loader.load(...), execute_select funguje v každém případě.
#
###########################################################################################################################


class ActivityTypeService(BaseService[IDLoader[ActivityTypeModel]]):
    @classmethod
    async def getLoader(cls, ctx: ServiceContext) -> IDLoader[ActivityTypeModel]:
        # Jediná povinná metoda každé service: vrací dataloader pro příslušný DB model.
        # Název atributu (ActivityTypeModel) musí odpovídat atributu LoaderMap v src/Dataloaders/__init__.py.
        return ctx.loaders.ActivityTypeModel

    @classmethod
    def _ToUUID(cls, value: typing.Any, *, name: str, location: str) -> uuid.UUID:
        """
        Pomocná (privátní) funkce: převede hodnotu na uuid.UUID (CLI předává ID jako řetězce).
        Chybí-li hodnota, nebo není validní UUID, vyhodí ServiceExceptionWithCode
        (kód např. "activity_type_parent_id_missing" / "activity_type_parent_id_invalid").
        """
        # Hodnota nebyla zadána -> chyba aplikační logiky.
        if value is None:
            raise ServiceExceptionWithCode(
                f'{name} is required',
                code=f'activity_type_{name}_missing',
                location=location,
            )
        # Už je to UUID -> nic se nepřevádí.
        if isinstance(value, uuid.UUID):
            return value
        # Řetězec -> pokus o převod, špatný formát je chyba aplikační logiky.
        try:
            return uuid.UUID(str(value))
        except ValueError as e:
            raise ServiceExceptionWithCode(
                f'{name} is not a valid UUID',
                code=f'activity_type_{name}_invalid',
                location=location,
            ) from e

    @classmethod
    async def ReadByName(cls, ctx: ServiceContext, name: str) -> typing.Optional[ActivityTypeModel]:
        """
        Vrátí typ aktivity podle interního názvu (sloupec name, např. "created").

        Sloupec name není v DB unikátní; pokud by jich bylo více, vrátí se první nalezený.
        Nenalezeno = None (není to chyba, o dalším postupu rozhoduje volající).
        """
        # Prázdný název nemá smysl hledat -> chyba aplikační logiky (bez dotazu do DB).
        if not name:
            raise ServiceExceptionWithCode('name is required', code='activity_type_name_missing', location='ReadByName')

        loader = await cls.getLoader(ctx)
        # Explicitní select (filter_by se nepoužívá, viz hlavička souboru).
        stmt = select(ActivityTypeModel).where(ActivityTypeModel.name == name)
        rows = await loader.execute_select(stmt)
        return rows[0] if rows else None

    @classmethod
    async def ReadRoots(cls, ctx: ServiceContext) -> list[ActivityTypeModel]:
        """
        Vrátí kořenové typy stromu (typy bez rodiče, parent_id IS NULL).

        Používá se execute_select, protože test na NULL je v SQLAlchemy "is_(None)", ne rovnost.
        """
        loader = await cls.getLoader(ctx)
        stmt = select(ActivityTypeModel).where(ActivityTypeModel.parent_id.is_(None))
        return await loader.execute_select(stmt)

    @classmethod
    async def ReadChildren(
        cls, ctx: ServiceContext, parent_id: typing.Union[uuid.UUID, str]
    ) -> list[ActivityTypeModel]:
        """
        Vrátí přímé potomky typu (jednu úroveň stromu pod parent_id).
        """
        loader = await cls.getLoader(ctx)
        parent_id = cls._ToUUID(parent_id, name='parent_id', location='ReadChildren')
        # Explicitní select (filter_by se nepoužívá, viz hlavička souboru).
        stmt = select(ActivityTypeModel).where(ActivityTypeModel.parent_id == parent_id)
        return await loader.execute_select(stmt)

    @classmethod
    async def ReadSubtree(
        cls, ctx: ServiceContext, type_id: typing.Union[uuid.UUID, str]
    ) -> list[ActivityTypeModel]:
        """
        Vrátí zadaný typ a všechny jeho potomky (celý podstrom); zadaný typ je v seznamu první.

        Strom se prochází po úrovních přes parent_id (skutečný cizí klíč). Záměrně se nepoužívá sloupec path
        (materialized path), protože ten je v modelu označen jako "not implemented" a u nově vytvořených typů
        nemusí být vyplněný. Množina navštívených id chrání před nekonečnou smyčkou, kdyby data obsahovala cyklus.

        Neexistuje-li typ, vyhodí ServiceExceptionWithCode (code "activity_type_not_found").
        """
        type_id = cls._ToUUID(type_id, name='type_id', location='ReadSubtree')

        # Načtení výchozího typu; neexistuje-li, je to chyba aplikační logiky.
        loader = await cls.getLoader(ctx)
        root = await loader.load(type_id)
        if root is None:
            raise ServiceExceptionWithCode('Activity type not found', code='activity_type_not_found', location='ReadSubtree')

        result = [root]          # výsledný seznam (pořadí: kořen, pak úroveň po úrovni)
        visited = {root.id}      # už zařazená id – ochrana proti cyklu v datech
        current_level = [root]   # typy, jejichž potomky teď hledáme

        # Průchod do šířky: dokud existuje úroveň s potomky, načítáme další úroveň.
        while current_level:
            next_level = []
            for parent in current_level:
                for child in await cls.ReadChildren(ctx=ctx, parent_id=parent.id):
                    if child.id in visited:
                        continue
                    visited.add(child.id)
                    result.append(child)
                    next_level.append(child)
            current_level = next_level

        return result