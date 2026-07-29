"""故障操作请求。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from apps.api.domains.market_data.schemas import DataSourceCheckRequest


class DataSourceIncidentCheck(DataSourceCheckRequest):
    incident_id: str = Field(..., min_length=1)


class DataSourceRecoveryAcknowledge(BaseModel):
    resolution: str = Field(..., min_length=1)
