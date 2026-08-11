from __future__ import annotations

import hmac
import os
from datetime import datetime
from hashlib import sha256
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.research_protocol import content_hash

CONTRACT_VERSION = "1.0.0"
DEFAULT_DEVELOPMENT_SIGNING_KEY = b"development-factor-signing-key-32b"


class PackageValidationError(ValueError):
    pass


class CompatibilityError(PackageValidationError):
    pass


def signing_key_from_env() -> bytes:
    raw_key = os.environ.get("QH_RUNNER_SIGNING_KEY", "")
    signing_key = raw_key.encode("utf-8") if raw_key else DEFAULT_DEVELOPMENT_SIGNING_KEY
    if len(signing_key) < 32:
        raise PackageValidationError("strategy signing key must contain at least 32 bytes")
    return signing_key


class RiskLimits(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_leverage: float = Field(gt=0)
    max_symbol_exposure: float = Field(gt=0, le=1)
    max_total_exposure: float = Field(gt=0, le=1)
    max_loss: float = Field(gt=0)
    max_drawdown: float = Field(gt=0, le=1)
    kill_switch_required: bool = True


class StrategyReleasePayload(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: str = CONTRACT_VERSION
    strategy_id: str
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    target_market: Literal["okx"]
    product_type: Literal["usdt_perpetual"]
    runner_compatibility: str
    formula: str
    formula_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    parameters: dict[str, Any]
    universe: dict[str, Any]
    signal_frequency: Literal["1h", "4h"]
    rebalance_frequency: str
    data_fields: tuple[str, ...]
    data_delay_seconds: int = Field(ge=0)
    data_snapshot_id: str
    research_engine_version: str
    out_of_sample_results: dict[str, float]
    cost_assumptions: dict[str, float]
    risk_limits: RiskLimits
    simulation_results: dict[str, Any]
    allowed_environments: tuple[Literal["shadow", "demo", "live"], ...]
    approved_by: str
    approved_at: datetime
    audit_record_ids: tuple[str, ...]

    @model_validator(mode="after")
    def validate_formula_hash(self) -> StrategyReleasePayload:
        if sha256(self.formula.encode("utf-8")).hexdigest() != self.formula_hash:
            raise ValueError("formula_hash does not match formula")
        if self.approved_at.tzinfo is None:
            raise ValueError("approved_at must be timezone-aware")
        return self


class StrategyReleasePackage(BaseModel):
    model_config = ConfigDict(frozen=True)

    payload: StrategyReleasePayload
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    signature_algorithm: Literal["HMAC-SHA256"] = "HMAC-SHA256"
    signature: str = Field(pattern=r"^[0-9a-f]{64}$")


def create_release_package(
    payload: StrategyReleasePayload, signing_key: bytes
) -> StrategyReleasePackage:
    if len(signing_key) < 32:
        raise PackageValidationError("signing key must contain at least 32 bytes")
    digest = content_hash(payload)
    signature = hmac.new(signing_key, digest.encode("ascii"), sha256).hexdigest()
    return StrategyReleasePackage(
        payload=payload,
        content_sha256=digest,
        signature=signature,
    )


def _major(version: str) -> int:
    try:
        return int(version.split(".", 1)[0])
    except (ValueError, IndexError) as exc:
        raise CompatibilityError(f"invalid semantic version: {version}") from exc


def verify_release_package(
    package: StrategyReleasePackage,
    signing_key: bytes,
    *,
    runner_version: str,
    environment: str,
) -> StrategyReleasePayload:
    expected_hash = content_hash(package.payload)
    if not hmac.compare_digest(expected_hash, package.content_sha256):
        raise PackageValidationError("strategy package content hash mismatch")
    expected_signature = hmac.new(signing_key, expected_hash.encode("ascii"), sha256).hexdigest()
    if not hmac.compare_digest(expected_signature, package.signature):
        raise PackageValidationError("strategy package signature mismatch")
    if _major(package.payload.runner_compatibility) != _major(runner_version):
        raise CompatibilityError("runner major version is incompatible with strategy package")
    if environment not in package.payload.allowed_environments:
        raise CompatibilityError(f"strategy package is not approved for {environment}")
    return package.payload
