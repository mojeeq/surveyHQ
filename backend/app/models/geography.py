"""Boundary layers: the areas fieldwork is organised into.

A census works to a frame of enumeration areas, and the frame lives in a GIS
file rather than in the survey data. Holding it here lets the platform answer
the question the data alone cannot: not "how many interviews were done in the
area the interviewer said", but "how many were done in the area they were
actually standing in".

The geometry is a file on disk beside the datasets, and only what a list has to
show - its name, how many areas it has, what they are described by, where it is
on Earth - is in the database. That is how a dataset is stored, for the same
reason: a national frame is megabytes of coordinates that no query filters on.
"""

from __future__ import annotations

import enum

from sqlalchemy import JSON, BigInteger, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin


class BoundaryFormat(str, enum.Enum):
    """What the layer arrived as, kept so a re-import can say where it came from."""

    geojson = "geojson"
    geopackage = "geopackage"
    shapefile = "shapefile"


class BoundaryLayer(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "boundary_layers"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    # Null is the shared area, as everywhere else: a national frame is usually
    # everybody's, and a layer drawn for one survey belongs to that survey.
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source_format: Mapped[BoundaryFormat] = mapped_column(
        String(20), default=BoundaryFormat.geojson.value
    )
    source_filename: Mapped[str] = mapped_column(String(300), default="")
    storage_path: Mapped[str] = mapped_column(String(500), default="")
    file_size: Mapped[int] = mapped_column(BigInteger, default=0)
    feature_count: Mapped[int] = mapped_column(Integer, default=0)
    # The attribute names the areas carry, so a widget can be told which one is
    # the area code and which one to write on the map.
    properties: Mapped[list] = mapped_column(JSON, default=list)
    # [min_x, min_y, max_x, max_y], for framing a map on the layer without
    # reading the coordinates back off disk.
    bbox: Mapped[list] = mapped_column(JSON, default=list)
    created_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
