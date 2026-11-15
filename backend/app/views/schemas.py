"""
View (capa de serialización/validación) en el patrón MVC de este backend.
Son modelos Pydantic: validan lo que entra por la API y dan forma a lo que
sale, sin que los controladores tengan que tocar SQL ni los modelos tengan
que saber nada de HTTP.
"""
from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator


class VoiceIngestRequest(BaseModel):
    astronaut_id: int
    mission_id: int
    transcript: str = Field(min_length=1)
    # P02: opcionales. Cuando se manda session_id, este reporte de voz se
    # vincula al caso compartido en curso y dispara el mismo ciclo de
    # reevaluación que el monitoreo pasivo (en vez de guardarse "suelto").
    # Sin ellos el endpoint se comporta exactamente como antes (compatible).
    session_id: Optional[int] = None
    operator_id: Optional[int] = None
    context_destination: Optional[
        Literal["LEO", "LUNAR_SURFACE", "MARS_TRANSIT", "MARS_SURFACE", "DEEP_SPACE"]] = None


class ObservationCreateRequest(BaseModel):
    indicator_code: str
    mission_id: int
    data_source_code: str
    data_origin: Literal["REAL", "SIMULATED", "DERIVED"]
    recorded_at: str
    unit: str
    measurement_method: str
    astronaut_id: Optional[int] = None
    habitat_id: Optional[int] = None
    value_numeric: Optional[float] = None
    value_text: Optional[str] = None
    day_relative_to_launch: Optional[int] = None
    notes: Optional[str] = None
    # P02: opcionales, mismo criterio que en VoiceIngestRequest arriba.
    session_id: Optional[int] = None
    operator_id: Optional[int] = None
    context_destination: Optional[
        Literal["LEO", "LUNAR_SURFACE", "MARS_TRANSIT", "MARS_SURFACE", "DEEP_SPACE"]] = None

    @field_validator("unit", "measurement_method")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("no puede estar vacío (regla: cada registro necesita unidad y método)")
        return v


class EmergencyEvaluateRequest(BaseModel):
    astronaut_id: int
    # Opcional: sirve para elegir el rango de referencia según destino cuando
    # exista uno específico. Sin él se usan los rangos sin contexto.
    context_destination: Optional[
        Literal["LEO", "LUNAR_SURFACE", "MARS_TRANSIT", "MARS_SURFACE", "DEEP_SPACE"]] = None
    hazard_code: Optional[Literal["DISTANCE", "ISOLATION", "GRAVITY",
                                   "RADIATION", "ENCLOSED_ENV"]] = None


class AstronautCreateRequest(BaseModel):
    call_sign: str
    mission_id: Optional[int] = None
    display_name: Optional[str] = None
    sex: Optional[Literal["M", "F", "OTHER"]] = None


def validation_error_payload(exc) -> dict:
    return {"error": "validation_error", "details": exc.errors()}
