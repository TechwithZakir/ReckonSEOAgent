from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Identifier = Annotated[
    str, StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:/-]+$")
]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
IdempotencyKey = Annotated[
    str, StringConstraints(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
]
TokenCount = Annotated[int, Field(strict=True, ge=0, le=1_000_000_000_000)]
PositiveTokenCount = Annotated[int, Field(strict=True, gt=0, le=1_000_000_000_000)]


class ModelReservationRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: UUID
    request_id: UUID
    idempotency_key: IdempotencyKey
    provider: Identifier
    model: Identifier
    request_digest: Digest
    max_input_tokens: PositiveTokenCount
    max_output_tokens: PositiveTokenCount


class ModelUsageReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    input_tokens: TokenCount
    output_tokens: TokenCount
