from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List


SYSTEM_BITS = {
    0b00: "P",
    0b01: "C",
    0b10: "B",
    0b11: "U",
}


GENERIC_DESCRIPTIONS = {
    "P0030": "HO2S heater control circuit, bank 1 sensor 1",
    "P0031": "HO2S heater control circuit low, bank 1 sensor 1",
    "P0032": "HO2S heater control circuit high, bank 1 sensor 1",
    "P0105": "Manifold absolute pressure/barometric pressure circuit",
    "P0110": "Intake air temperature sensor circuit",
    "P0115": "Engine coolant temperature sensor circuit",
    "P0120": "Throttle/pedal position sensor A circuit",
    "P0130": "Oxygen sensor circuit, bank 1 sensor 1",
    "P0135": "Oxygen sensor heater circuit, bank 1 sensor 1",
    "P0171": "System too lean, bank 1",
    "P0172": "System too rich, bank 1",
    "P0201": "Injector circuit/open, cylinder 1",
    "P0202": "Injector circuit/open, cylinder 2",
    "P0203": "Injector circuit/open, cylinder 3",
    "P0300": "Random/multiple cylinder misfire detected",
    "P0301": "Cylinder 1 misfire detected",
    "P0302": "Cylinder 2 misfire detected",
    "P0303": "Cylinder 3 misfire detected",
    "P0335": "Crankshaft position sensor A circuit",
    "P0351": "Ignition coil A primary/secondary circuit",
    "P0352": "Ignition coil B primary/secondary circuit",
    "P0353": "Ignition coil C primary/secondary circuit",
    "P0443": "EVAP purge control valve circuit",
    "P0500": "Vehicle speed sensor",
    "P0560": "System voltage",
    "P0562": "System voltage low",
    "P0563": "System voltage high",
    "P0606": "PCM/ECM processor fault",
}


@dataclass(frozen=True)
class Dtc:
    code: str
    description: str

    @property
    def suggestion(self) -> str:
        return suggestion_for_code(self.code)


def decode_dtc_pair(first: int, second: int) -> str | None:
    if first == 0 and second == 0:
        return None

    system = SYSTEM_BITS[(first & 0xC0) >> 6]
    digit1 = (first & 0x30) >> 4
    digit2 = first & 0x0F
    return f"{system}{digit1:X}{digit2:X}{second:02X}"


def decode_dtc_bytes(data: Iterable[int]) -> List[Dtc]:
    values = list(data)
    codes: List[Dtc] = []
    for offset in range(0, len(values) - 1, 2):
        code = decode_dtc_pair(values[offset], values[offset + 1])
        if not code:
            continue
        codes.append(Dtc(code=code, description=description_for_code(code)))
    return codes


def description_for_code(code: str) -> str:
    if code in GENERIC_DESCRIPTIONS:
        return GENERIC_DESCRIPTIONS[code]
    if len(code) != 5:
        return "Unknown diagnostic trouble code"
    if code[0] == "P" and code[1] in {"0", "2", "3"}:
        return "Generic powertrain diagnostic trouble code"
    if code[0] == "P" and code[1] == "1":
        return "Manufacturer-specific powertrain diagnostic trouble code"
    if code[0] == "C":
        return "Chassis diagnostic trouble code"
    if code[0] == "B":
        return "Body/instrument diagnostic trouble code"
    if code[0] == "U":
        return "Network/communication diagnostic trouble code"
    return "Unknown diagnostic trouble code"


def suggestion_for_code(code: str) -> str:
    base = code.split("-", 1)[0]
    prefix = base[:3]
    if base in {"P0560", "P0562", "P0563"}:
        return "Check battery charge, terminals, grounds, and charging voltage before chasing sensors."
    if base.startswith("P03"):
        return "Check ignition coils, plugs, injector connectors, fuel quality, and air leaks; avoid clearing until the cause is recorded."
    if base == "P0500":
        return "Inspect wheel speed/vehicle speed signal wiring and compare against ABS or instrument module faults."
    if base == "P0606":
        return "Do not clear first. Save the report and investigate ECU power, grounds, connectors, and dealer-level ECU checks."
    if prefix in {"P01", "P02"}:
        return "Inspect the named sensor/actuator connector and wiring, then compare live data if available."
    if base.startswith("U"):
        return "Check battery voltage first, then inspect CAN/ECU connector issues if the code returns."
    if base.startswith("C"):
        return "Treat chassis/ABS faults as safety critical; inspect wheel sensors, brake switches, fuses, and wiring."
    return "Record the code, inspect the related circuit or subsystem, then re-scan after any repair."


def severity_for_code(code: str) -> str:
    base = code.split("-", 1)[0]
    if base in {"P0606"}:
        return "high"
    if base.startswith("C"):
        return "high"
    if base.startswith("U"):
        return "medium"
    if base.startswith("P03"):
        return "medium"
    if base in {"P0560", "P0562", "P0563"}:
        return "medium"
    if base.startswith("P"):
        return "medium"
    return "unknown"
