"""Pydantic models for the backend service."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ItemCreate(BaseModel):
    """Request model for creating an item."""

    name: str = Field(..., min_length=1, max_length=255, description="Item name")
    description: Optional[str] = Field(None, max_length=1000, description="Item description")


class Item(BaseModel):
    """Response model for an item."""

    id: int
    name: str
    description: Optional[str] = None
    created_at: str

    model_config = {"from_attributes": True}


class StatsResponse(BaseModel):
    """Response model for application statistics."""

    total_items: int
    redis_connected: bool
    service: str
    version: str
