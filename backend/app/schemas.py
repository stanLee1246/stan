from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator

Intent = Literal['employment', 'postgraduate', 'civil_service', 'public_institution', 'internship']
OutcomePath = Literal['employment', 'postgraduate', 'civil_service', 'public_institution', 'unresolved', 'other']
DataKind = Literal['demo', 'authorized']


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r'^[a-zA-Z0-9_-]+$')
    password: str = Field(min_length=10, max_length=128)


class Register(Credentials):
    nickname: str = Field(min_length=1, max_length=60)

    @field_validator('nickname')
    @classmethod
    def nonempty_nickname(cls, value):
        if not value.strip():
            raise ValueError('昵称不能为空')
        return value.strip()


class ProfileInput(BaseModel):
    expected_version: int = Field(ge=0)
    major: str = Field(min_length=2, max_length=100)
    graduation_year: int = Field(ge=2000, le=2100)
    stage: Literal['studying', 'internship', 'job_seeking', 'exam_preparation', 'graduated'] = 'studying'
    degree: Literal['junior_college', 'bachelor', 'master', 'doctor'] = 'bachelor'
    english: Literal['unknown', 'cet4', 'cet6', 'other'] = 'unknown'
    internship_months: int | None = Field(default=None, ge=0, le=120)
    summary: str = Field(default='', max_length=3000)
    skills: list[str] = Field(default_factory=list, max_length=30)
    cities: list[str] = Field(default_factory=list, max_length=15)
    intents: list[Intent] = Field(min_length=1, max_length=5)

    @field_validator('major')
    @classmethod
    def trim_major(cls, value):
        value = value.strip()
        if len(value) < 2:
            raise ValueError('专业至少两个字符')
        return value

    @field_validator('skills', 'cities')
    @classmethod
    def clean_tags(cls, values):
        result = list(dict.fromkeys(v.strip() for v in values if v.strip()))
        if any(len(v) > 80 for v in result):
            raise ValueError('标签过长')
        return result


class ImportInput(BaseModel):
    source_name: str = Field(min_length=2, max_length=120)
    data_kind: DataKind = 'demo'
    authorized_consent: bool = False
    csv_content: str = Field(min_length=1, max_length=500_000)


class OpportunityInput(BaseModel):
    source_record_id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=2, max_length=150)
    organization: str = Field(min_length=2, max_length=150)
    path: Intent
    organization_type: Literal['private', 'state_owned', 'government', 'public_institution', 'university', 'other'] = 'other'
    city: str | None = Field(default=None, max_length=80)
    skills: list[str] = Field(default_factory=list, max_length=30)
    majors: list[str] = Field(default_factory=list, max_length=30)
    minimum_degree: Literal['junior_college', 'bachelor', 'master', 'doctor'] | None = None
    description: str = Field(min_length=2, max_length=10000)
    deadline: date | None = None
    published_at: date | None = None
    source_url: HttpUrl
    data_kind: Literal['demo', 'public'] = 'public'
    requirements_verified: bool = False

    @field_validator('skills', 'majors')
    @classmethod
    def validate_terms(cls, values):
        result = list(dict.fromkeys(v.strip() for v in values if v.strip()))
        if any(len(v) > 100 for v in result):
            raise ValueError('条件字段过长')
        return result

    @field_validator('source_url')
    @classmethod
    def url_length(cls, value):
        if len(str(value)) > 255:
            raise ValueError('来源链接过长')
        return value


class ExperienceInput(BaseModel):
    title: str = Field(min_length=2, max_length=150)
    body: str = Field(min_length=20, max_length=10000)
    graduation_year: int = Field(ge=2000, le=2100)
    city: str = Field(min_length=2, max_length=80)
    path: OutcomePath
    public_consent: bool


class ModerationInput(BaseModel):
    status: Literal['approved', 'rejected']
    note: str = Field(default='', max_length=300)
