import datetime
from typing import Optional, List
from sqlalchemy import (
    Column,
    String,
    DateTime,
    ForeignKey,
)
from sqlalchemy.orm import Mapped, mapped_column

from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship

from src.DBDefinitions.BaseModel import BaseDBModel, UUIDColumn, UUIDFKey, IDType
###########################################################################################################################
#
# zde definujte sve SQLAlchemy modely
# je-li treba, muzete definovat modely obsahujici jen id polozku, na ktere se budete odkazovat
#
###########################################################################################################################

class ActivityTypeModel(BaseDBModel):
    __tablename__ = "activitytypes"

    path_attribute_name = "path"
    parent_attribute_name = "parent"
    parent_id_attribute_name = "parent_id"
    children_attribute_name = "children"

    # Materialized path technique
    path: Mapped[str] = mapped_column(
        index=True,
        nullable=True,
        default=None,
        comment="Materialized path technique, not implemented"
    )

    name: Mapped[str] = mapped_column(default=None, nullable=True, comment="internal name, aka created, changed, state_changed, ...")
    label: Mapped[str] = mapped_column(default=None, nullable=True, comment="display name")
    description: Mapped[str] = mapped_column(default=None, nullable=True, comment="meaning of the activity type")

    parent_id: Mapped[IDType] = mapped_column(
        ForeignKey("activitytypes.id"),
        index=True,
        nullable=True,
        default=None,
        comment="parent type, types form a tree"
    )

    parent = relationship(
        "ActivityTypeModel",
        viewonly=True,
        remote_side="ActivityTypeModel.id",
        uselist=False,
    ) # https://docs.sqlalchemy.org/en/20/orm/self_referential.html

    children = relationship(
        "ActivityTypeModel",
        back_populates="parent",
        uselist=True,
        init=True,
        cascade="save-update"
    ) # https://docs.sqlalchemy.org/en/20/orm/self_referential.html

    activities = relationship(
        "ActivityModel",
        viewonly=True
    )