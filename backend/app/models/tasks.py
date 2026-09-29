from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=200)


class TaskUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    completed: StrictBool | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode='after')
    def nonempty(self):
        if not self.model_fields_set or any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError('Supply a title or completed state; null is not allowed')
        return self


class Task(BaseModel):
    id: str
    title: str
    completed: bool
    created_at: str
