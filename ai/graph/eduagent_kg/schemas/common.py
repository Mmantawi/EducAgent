from pydantic import BaseModel, ConfigDict, Field


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class CurriculumMetadata(ContractModel):
    grade: int = Field(ge=1, le=12)
    subject: str = Field(min_length=1)
    original_language: str = Field(min_length=2, description="BCP 47 language tag")

