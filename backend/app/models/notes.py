from pydantic import BaseModel, ConfigDict, Field


class Notes(BaseModel):
    model_config = ConfigDict(extra='forbid')
    content: str = Field(default='', max_length=5000)
    updated_at: str | None = None


class NotesUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=False)
    content: str = Field(max_length=5000)
