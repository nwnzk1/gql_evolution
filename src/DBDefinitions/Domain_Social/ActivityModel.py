import typing
import datetime
import dataclasses
import sqlalchemy
from sqlalchemy import (
    Column,
    String,
    DateTime,
    ForeignKey,
)
from sqlalchemy.orm import Mapped, mapped_column, synonym

from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship, column_property

from src.DBDefinitions.BaseModel import BaseDBModel, UUIDColumn, UUIDFKey, IDType

###########################################################################################################################
#
# zde definujte sve SQLAlchemy modely
# je-li treba, muzete definovat modely obsahujici jen id polozku, na ktere se budete odkazovat
#
###########################################################################################################################
class ActivityModel(BaseDBModel):
    __tablename__ = "activities"

    # entita, ke ktere se aktivita vztahuje
    entity_id: Mapped[IDType] = UUIDFKey(nullable=True, comment="id of the entity the activity relates to")
    entity_type_id: Mapped[IDType] = UUIDFKey(nullable=True, comment="type of the entity the activity relates to")

    # typ aktivity (ciselnik, strom)
    activity_type_id: Mapped[IDType] = mapped_column(ForeignKey("activitytypes.id"), index=True, nullable=True, default=None)
    activity_type = relationship("ActivityTypeModel", viewonly=True)

    # uzivatel, ktery aktivitu vyvolal
    actor_id: Mapped[IDType] = UUIDFKey(ForeignKey("users.id"), nullable=True, comment="user who caused the activity")

    title: Mapped[str] = mapped_column(default=None, nullable=True, comment="short title of the activity")
    content: Mapped[str] = mapped_column(default=None, nullable=True, comment="additional description of the activity")