"""
OBD-II and UDS diagnostic functions for Triumph bikes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

from .dtc import Dtc, decode_dtc_bytes
from .elm327 import Elm327, ElmError, ElmNoData
from .isotp import reassemble_isotp_payloads
from .pids import FreezeFrameReport, PidReading, freeze_frame_to_dict, read_freeze_frame, read_snapshot, snapshot_to_dict
from .uds_service22 import read_vin_uds

HEX_PAIR = re.compile(r"\b[0-9A-F]{2}\b")


@dataclass
class MilStatus:
    mil_on: bool
    dtc_count: int
    raw: List[int] = field(default_factory=list)


@dataclass
class ScanReport:
    adapter: Dict[str, str]
    vin: Optional[str]
    mil: Optional[MilStatus]
    dtcs: Dict[str, List[Dtc]]
    snapshot: List[PidReading] = field(default_factory=list)
    freeze_frame: Optional[FreezeFrameReport] = None

    @property
    def has_dtcs(self) -> bool:
        return any(self.dtcs[group] for group in self.dtcs)


def adapter_info(elm: Elm327) -> Dict[str, str]:
    info: Dict[str, str] = {}
    for label, command in (
        ("identity", "ATI"),
        ("voltage", "ATRV"),
        ("protocol", "ATDP"),
    ):
        try:
            lines = elm.command(command, tolerate_no_data=True)
            if lines:
                info[label] = " ".join(lines)
        except ElmError as exc:
            info[label] = f"unavailable: {exc}"
    return info


def scan(elm: Elm327, include_snapshot: bool = False, include_freeze_frame: bool = False) -> ScanReport:
    """Perform a complete diagnostic scan."""
    # Setup CAN for Triumph bikes (do this ONCE at the start)
    _setup_can_for_triumph(elm)
    
    return ScanReport(
        adapter=adapter_info(elm),
        vin=read_vin(elm),
        mil=read_mil_status(elm),
        dtcs={
            "stored": read_dtcs(elm, "03"),
            "pending": read_dtcs(elm, "07"),
            "permanent": read_dtcs(elm, "0A"),
        },
        snapshot=read_snapshot(elm) if include_snapshot else [],
        freeze_frame=read_freeze_frame(elm) if include_freeze_frame else None,
    )


def _setup_can_for_triumph(elm: Elm327) -> None:
    """Setup CAN protocol for Triumph bikes."""
    elm.command("ATCAF0", tolerate_no_data=True)    # CAN Auto Format OFF
    elm.command("ATCFC1", tolerate_no_data=True)    # CAN Flow Control ON
    elm.command("ATCP18", tolerate_no_data=True)    # CAN Protocol 18
    elm.command("ATTP7", tolerate_no_data=True)     # Timeout Parameter 7
    elm.command("ATH1", tolerate_no_data=True)      # Headers ON


def read_mil_status(elm: Elm327) -> Optional[MilStatus]:
    try:
        payload = response_payload(elm.command("0101"), expected_mode="41", pid="01")
    except ElmNoData:
        return None
    if not payload:
        return None
    first = payload[0]
    return MilStatus(mil_on=bool(first & 0x80), dtc_count=first & 0x7F, raw=payload)


def read_dtcs(elm: Elm327, mode: str) -> List[Dtc]:
    response_mode = f"{int(mode, 16) + 0x40:02X}"
    try:
        payload = response_payload(elm.command(mode), expected_mode=response_mode)
    except ElmNoData:
        return []
    return decode_dtc_bytes(payload)


def clear_dtcs(elm: Elm327) -> List[str]:
    return elm.command("04")


def scan_report_to_dict(report: ScanReport) -> dict:
    return {
        "adapter": report.adapter,
        "vin": report.vin,
        "mil": None
        if report.mil is None
        else {
            "on": report.mil.mil_on,
            "reported_dtc_count": report.mil.dtc_count,
            "raw": [f"0x{item:02X}" for item in report.mil.raw],
        },
        "dtcs": {
            group: [
                {
                    "code": item.code,
                    "description": item.description,
                    "suggestion": item.suggestion,
                }
                for item in codes
            ]
            for group, codes in report.dtcs.items()
        },
        "snapshot": snapshot_to_dict(report.snapshot),
        "freeze_frame": freeze_frame_to_dict(report.freeze_frame),
    }


def read_vin(elm: Elm327) -> Optional[str]:
    """Read VIN from bike ECU."""
    # Try UDS Service 22 first (works for Triumph bikes)
    try:
        vin = read_vin_uds(elm)
        if vin:
            return vin
    except Exception:
        pass
    
    # Fallback to standard OBD Mode 09 PID 02
    try:
        lines = elm.command("0902")
    except ElmNoData:
        return None

    frames = []
    for payload in response_messages(lines):
        if len(payload) < 3:
            continue
        if payload[0] == 0x49 and payload[1] == 0x02:
            frames.append(payload[3:] if len(payload) > 3 else [])

    if not frames:
        payload = response_payload(lines, expected_mode="49", pid="02")
        frames = [payload[1:]] if payload else []

    raw = bytes(value for frame in frames for value in frame if value != 0x00)
    text = raw.decode("ascii", errors="ignore").strip()
    return text or None


def response_payload(lines: Iterable[str], expected_mode: str, pid: Optional[str] = None) -> List[int]:
    payload: List[int] = []
    expected_mode_int = int(expected_mode, 16)
    pid_int = int(pid, 16) if pid else None

    for values in response_messages(lines):
        if not values:
            continue

        # Headerless or ISO-TP-reassembled response, e.g. "41 01 80 07 ..."
        if values[0] == expected_mode_int:
            if pid_int is not None and (len(values) < 2 or values[1] != pid_int):
                continue
            payload.extend(values[2:] if pid_int is not None else values[1:])
            continue

        # Headered response, e.g. "7E8 06 41 01 ..."
        for index, value in enumerate(values):
            if value != expected_mode_int:
                continue
            if pid_int is not None and (index + 1 >= len(values) or values[index + 1] != pid_int):
                continue
            payload.extend(values[index + 2 :] if pid_int is not None else values[index + 1 :])
            break

    return payload


def response_messages(lines: Iterable[str]) -> List[List[int]]:
    materialized = list(lines)
    reassembled = reassemble_isotp_payloads(materialized)
    if reassembled:
        return reassembled
    return [hex_bytes(line) for line in materialized]


def hex_bytes(line: str) -> List[int]:
    values = []
    for token in HEX_PAIR.findall(line.upper()):
        values.append(int(token, 16))
    return values
