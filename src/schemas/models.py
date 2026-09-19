"""
Canonical schema definitions for GraphOne / FrontierAtlas Intelligence Graph.

Every record produced by the pipeline (regardless of source or vertical)
is validated against one of these models before being written to storage.
This guarantees schema consistency across thousands of heterogeneous sources.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, HttpUrl

SCHEMA_VERSION = "1.0"


class RecordType(str, Enum):
    STARTUP = "STARTUP"
    PRODUCT = "PRODUCT"
    RESEARCH_PAPER = "RESEARCH_PAPER"
    JOB = "JOB"
    NEWS = "NEWS"


class PricingModel(str, Enum):
    FREE = "FREE"
    FREEMIUM = "FREEMIUM"
    PAID = "PAID"
    ENTERPRISE = "ENTERPRISE"
    UNKNOWN = "UNKNOWN"


class Source(BaseModel):
    name: str
    url: str  # HttpUrl is stricter but some sources return odd query strings; keep as str + validate separately


class BaseRecord(BaseModel):
    schemaVersion: str = SCHEMA_VERSION
    recordType: RecordType
    source: Source
    collectedAt: datetime = Field(default_factory=datetime.utcnow)
    # every record must carry provenance — the raw source URL used for
    # extraction. Records without this are rejected at the resolver stage.


class StartupContentData(BaseModel):
    employeeCount: Optional[int] = None
    foundedYear: Optional[int] = None
    hq: Optional[str] = None
    industry: Optional[str] = None


class StartupContent(BaseModel):
    entityName: str  # canonical name, filled by entity resolver
    rawName: Optional[str] = None  # name as it appeared at source, pre-resolution
    description: Optional[str] = None
    website: Optional[str] = None
    data: StartupContentData = Field(default_factory=StartupContentData)


class StartupRecord(BaseRecord):
    recordType: RecordType = RecordType.STARTUP
    content: StartupContent


class ProductContent(BaseModel):
    startupName: str  # canonical parent startup name
    productName: str
    rawStartupName: Optional[str] = None
    pricingModel: PricingModel = PricingModel.UNKNOWN
    description: Optional[str] = None
    website: Optional[str] = None


class ProductRecord(BaseRecord):
    recordType: RecordType = RecordType.PRODUCT
    content: ProductContent


class ResearchPaperContent(BaseModel):
    title: str
    authors: List[str] = Field(default_factory=list)
    abstract: Optional[str] = None
    paper_url: str
    github_url: Optional[str] = None
    github_stars: Optional[int] = None
    published_date: Optional[datetime] = None
    arxiv_id: Optional[str] = None
    categories: List[str] = Field(default_factory=list)


class ResearchPaperRecord(BaseRecord):
    recordType: RecordType = RecordType.RESEARCH_PAPER
    content: ResearchPaperContent


class JobContent(BaseModel):
    title: str
    company: str
    rawCompany: Optional[str] = None
    date: datetime
    is_remote: bool = False
    role_family: Optional[str] = None
    location: Optional[str] = None
    job_url: Optional[str] = None
    description: Optional[str] = None


class JobRecord(BaseRecord):
    recordType: RecordType = RecordType.JOB
    content: JobContent


class NewsContent(BaseModel):
    title: str
    summary: Optional[str] = None
    full_text: Optional[str] = None
    published_date: datetime
    article_url: str
    entities_mentioned: List[str] = Field(default_factory=list)


class NewsRecord(BaseRecord):
    recordType: RecordType = RecordType.NEWS
    content: NewsContent
