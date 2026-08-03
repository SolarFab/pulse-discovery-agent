"""Typed recipes and raw events (publisher-discovery spec: Recipes are typed).

A recipe is the ONLY artifact the scout may produce: a strict, validated form that
the generic harvest executor knows how to run. No generated code, no free text.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, HttpUrl, field_validator

BERLIN = ZoneInfo("Europe/Berlin")

RecipeType = Literal[
    "ics_feed", "jsonld", "rss", "html_selector",
    "aggregator_covered", "instagram_lead", "none",
]


class SelectorParams(BaseModel):
    """Parameters for html_selector recipes — the only type with free-ish params."""

    item_selector: str = Field(min_length=1, max_length=200)
    title_selector: str | None = Field(default=None, max_length=200)
    date_selector: str | None = Field(default=None, max_length=200)
    date_attr: str | None = Field(default=None, max_length=50)   # e.g. "datetime"
    url_selector: str | None = Field(default=None, max_length=200)


class Recipe(BaseModel):
    recipe_type: RecipeType
    url: HttpUrl | None = None
    params: SelectorParams | None = None
    scope: str | None = Field(default=None, max_length=200)      # facet coverage note
    confidence: float = Field(ge=0.0, le=1.0)
    instagram_handle: str | None = Field(default=None, max_length=100)

    @field_validator("url")
    @classmethod
    def _https_only(cls, v):
        if v is not None and v.scheme != "https":
            raise ValueError("recipe URLs must be https")
        return v

    def needs_url(self) -> bool:
        return self.recipe_type in ("ics_feed", "jsonld", "rss", "html_selector")


class RawEvent(BaseModel):
    """What the harvester stages — deliberately minimal; enrichment is Pulse's job."""

    title: str = Field(min_length=2, max_length=300)
    start_time: datetime
    end_time: datetime | None = None
    url: str | None = None
    description: str | None = Field(default=None, max_length=2000)
    price: str | None = Field(default=None, max_length=100)
    venue_name: str | None = Field(default=None, max_length=200)
    address: str | None = Field(default=None, max_length=300)

    @field_validator("start_time", "end_time")
    @classmethod
    def _tz_aware(cls, v):
        if v is not None and v.tzinfo is None:
            return v.replace(tzinfo=BERLIN)  # naive source times are local Berlin times
        return v


def future_events(events: list[RawEvent], now: datetime) -> list[RawEvent]:
    """The verification gate's core question: does the recipe yield dated FUTURE events?"""
    return [e for e in events if e.start_time > now]
