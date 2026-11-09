from uoishelpers.dataloaders.LoaderMapBase import LoaderMapBase
from uoishelpers.dataloaders.IDLoader import IDLoader

import src.DBDefinitions
from src.DBDefinitions import BaseDBModel, EventModel, EventInvitationModel

# Doména Social (projekt ACTIVITIES): DB modely, pro které LoaderMap vytváří dataloadery.
# Importují se z balíčku src.DBDefinitions (ne přímo ze souboru), stejně jako Event modely.
from src.DBDefinitions import ActivityModel, ActivityTypeModel


class LoaderMap(LoaderMapBase[BaseDBModel]):
    BaseModel = BaseDBModel

    EventModel: IDLoader[src.DBDefinitions.EventModel] = None
    EventInvitationModel: IDLoader[src.DBDefinitions.EventInvitationModel] = None

    # Typované atributy loaderů domény Social (dataloadery řeší problém N+1 – dotazy se dávkují).
    # Název atributu MUSÍ odpovídat názvu DB modelu, protože service vrací ctx.loaders.<NázevModelu>
    # (a později GQL vrstva přes LoaderName).
    ActivityModel: IDLoader[src.DBDefinitions.ActivityModel] = None
    ActivityTypeModel: IDLoader[src.DBDefinitions.ActivityTypeModel] = None

    def __init__(self, session):
        super().__init__(session)
        self.EventModel = self.get(EventModel)
        self.EventInvitationModel = self.get(EventInvitationModel)

        # Inicializace loaderů pro doménu Social; self.get(Model) vytvoří (a cachuje) IDLoader nad danou session.
        self.ActivityModel = self.get(ActivityModel)
        self.ActivityTypeModel = self.get(ActivityTypeModel)

    def get_by_name(self, name: str):
        return getattr(self, name)


def createLoadersContext(session):
    """Compatibility helper for places expecting a dict context."""
    return {'loaders': LoaderMap(session)}