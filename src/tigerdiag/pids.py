from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Union

from .dtc import decode_dtc_bytes
from .elm327 import Elm327, ElmError, ElmNoData


PidValue = Union[float, int, str]
Decoder = Callable[[List[int]], Optional[PidValue]]


@dataclass(frozen=True)
class PidDefinition:
    pid: str
    name: str
    unit: str
    decoder: Decoder


@dataclass(frozen=True)
class PidReading:
    pid: str
    name: str
    value: PidValue
    unit: str
    raw: List[int]


@dataclass(frozen=True)
class FreezeFrameReport:
    frame: int
    dtc: Optional[str]
    readings: List[PidReading]


def one_byte_minus_40(data: List[int]) -> Optional[int]:
    return data[0] - 40 if len(data) >= 1 else None


def one_byte_percent(data: List[int]) -> Optional[float]:
    return round(data[0] * 100.0 / 255.0, 1) if len(data) >= 1 else None


def fuel_trim(data: List[int]) -> Optional[float]:
    return round((data[0] - 128) * 100.0 / 128.0, 1) if len(data) >= 1 else None


def rpm(data: List[int]) -> Optional[float]:
    return round(((data[0] * 256) + data[1]) / 4.0, 1) if len(data) >= 2 else None


def speed(data: List[int]) -> Optional[int]:
    return data[0] if len(data) >= 1 else None


def pressure(data: List[int]) -> Optional[int]:
    return data[0] if len(data) >= 1 else None


def voltage(data: List[int]) -> Optional[float]:
    return round(((data[0] * 256) + data[1]) / 1000.0, 3) if len(data) >= 2 else None


def equivalence_ratio(data: List[int]) -> Optional[float]:
    return round(((data[0] * 256) + data[1]) / 32768.0, 3) if len(data) >= 2 else None


COMMON_PID_DEFINITIONS: Dict[str, PidDefinition] = {
    "04": PidDefinition("04", "calculated engine load", "%", one_byte_percent),
    "05": PidDefinition("05", "coolant temperature", "deg C", one_byte_minus_40),
    "06": PidDefinition("06", "short term fuel trim bank 1", "%", fuel_trim),
    "07": PidDefinition("07", "long term fuel trim bank 1", "%", fuel_trim),
    "0B": PidDefinition("0B", "intake manifold pressure", "kPa", pressure),
    "0C": PidDefinition("0C", "engine RPM", "rpm", rpm),
    "0D": PidDefinition("0D", "vehicle speed", "km/h", speed),
    "0E": PidDefinition("0E", "timing advance", "deg before TDC", lambda data: round(data[0] / 2.0 - 64.0, 1) if data else None),
    "0F": PidDefinition("0F", "intake air temperature", "deg C", one_byte_minus_40),
    "11": PidDefinition("11", "throttle position", "%", one_byte_percent),
    "2F": PidDefinition("2F", "fuel tank level", "%", one_byte_percent),
    "42": PidDefinition("42", "control module voltage", "V", voltage),
    "43": PidDefinition("43", "absolute load value", "%", lambda data: round(((data[0] * 256) + data[1]) * 100.0 / 255.0, 1) if len(data) >= 2 else None),
    "44": PidDefinition("44", "commanded equivalence ratio", "lambda", equivalence_ratio),
    "46": PidDefinition("46", "ambient air temperature", "deg C", one_byte_minus_40),
    "5C": PidDefinition("5C", "engine oil temperature", "deg C", one_byte_minus_40),
}


def read_snapshot(elm: Elm327, pids: Optional[Iterable[str]] = None) -> List[PidReading]:
    requested = [normalise_pid(pid) for pid in (pids or COMMON_PID_DEFINITIONS.keys())]
    supported = read_supported_pids(elm)
    readings: List[PidReading] = []

    for pid in requested:
        definition = COMMON_PID_DEFINITIONS.get(pid)
        if not definition:
            continue
        if supported and pid not in supported:
            continue
        try:
            payload = read_pid_payload(elm, pid)
        except ElmNoData:
            continue
        value = definition.decoder(payload)
        if value is None:
            continue
        readings.append(PidReading(pid=pid, name=definition.name, value=value, unit=definition.unit, raw=payload))
    return readings


def read_freeze_frame(elm: Elm327, frame: int = 0, pids: Optional[Iterable[str]] = None) -> FreezeFrameReport:
    requested = [normalise_pid(pid) for pid in (pids or COMMON_PID_DEFINITIONS.keys())]
    supported = read_supported_freeze_pids(elm, frame=frame)
    readings: List[PidReading] = []

    for pid in requested:
        definition = COMMON_PID_DEFINITIONS.get(pid)
        if not definition:
            continue
        if supported and pid not in supported:
            continue
        try:
            payload = read_freeze_pid_payload(elm, pid, frame=frame)
        except ElmNoData:
            continue
        value = definition.decoder(payload)
        if value is None:
            continue
        readings.append(PidReading(pid=pid, name=definition.name, value=value, unit=definition.unit, raw=payload))

    return FreezeFrameReport(frame=frame, dtc=read_freeze_frame_dtc(elm, frame=frame), readings=readings)


def read_pid_payload(elm: Elm327, pid: str) -> List[int]:
    from .obd import response_payload

    clean = normalise_pid(pid)
    return response_payload(elm.command(f"01{clean}"), expected_mode="41", pid=clean)


def read_freeze_pid_payload(elm: Elm327, pid: str, frame: int = 0) -> List[int]:
    from .obd import response_payload

    clean = normalise_pid(pid)
    payload = response_payload(elm.command(f"02{clean}{frame:02X}"), expected_mode="42", pid=clean)
    if payload and payload[0] == frame:
        return payload[1:]
    return payload


def read_freeze_frame_dtc(elm: Elm327, frame: int = 0) -> Optional[str]:
    try:
        payload = read_freeze_pid_payload(elm, "02", frame=frame)
    except ElmNoData:
        return None
    codes = decode_dtc_bytes(payload[:2])
    return codes[0].code if codes else None


def read_supported_pids(elm: Elm327) -> set[str]:
    supported: set[str] = set()
    for base in ("00", "20", "40"):
        try:
            payload = read_pid_payload(elm, base)
        except ElmNoData:
            continue
        if len(payload) < 4:
            continue
        supported.update(decode_supported_pid_block(int(base, 16), payload[:4]))
    return supported


def read_supported_freeze_pids(elm: Elm327, frame: int = 0) -> set[str]:
    supported: set[str] = set()
    for base in ("00", "20", "40"):
        try:
            payload = read_freeze_pid_payload(elm, base, frame=frame)
        except ElmNoData:
            continue
        if len(payload) < 4:
            continue
        supported.update(decode_supported_pid_block(int(base, 16), payload[:4]))
    return supported


def decode_supported_pid_block(base: int, payload: List[int]) -> set[str]:
    if len(payload) != 4:
        raise ElmError("Supported PID payload must contain exactly four bytes")

    value = (payload[0] << 24) | (payload[1] << 16) | (payload[2] << 8) | payload[3]
    output: set[str] = set()
    for bit in range(32):
        if value & (1 << (31 - bit)):
            output.add(f"{base + bit + 1:02X}")
    return output


def normalise_pid(pid: str) -> str:
    clean = pid.strip().upper()
    if len(clean) == 1:
        clean = f"0{clean}"
    if len(clean) != 2 or any(char not in "0123456789ABCDEF" for char in clean):
        raise ElmError(f"PID must be one byte of hex, got {pid!r}")
    return clean


def snapshot_to_dict(readings: Iterable[PidReading]) -> List[dict]:
    return [
        {
            "pid": item.pid,
            "name": item.name,
            "value": item.value,
            "unit": item.unit,
            "raw": [f"0x{value:02X}" for value in item.raw],
        }
        for item in readings
    ]


def freeze_frame_to_dict(report: Optional[FreezeFrameReport]) -> Optional[dict]:
    if report is None:
        return None
    return {
        "frame": report.frame,
        "dtc": report.dtc,
        "readings": snapshot_to_dict(report.readings),
    }
