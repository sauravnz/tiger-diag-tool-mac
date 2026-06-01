from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .dtc import decode_dtc_pair, description_for_code, suggestion_for_code
from .elm327 import Elm327, ElmError, ElmNoData, normalise_header
from .obd import hex_bytes, response_messages


UDS_DTC_STATUS_BITS = (
    (0x01, "test_failed"),
    (0x02, "test_failed_this_cycle"),
    (0x04, "pending"),
    (0x08, "confirmed"),
    (0x10, "test_not_completed_since_clear"),
    (0x20, "failed_since_clear"),
    (0x40, "test_not_completed_this_cycle"),
    (0x80, "warning_indicator_requested"),
)


@dataclass(frozen=True)
class ModuleTarget:
    name: str
    tx_header: str
    description: str = ""


@dataclass(frozen=True)
class ModuleProfile:
    name: str
    protocol: str
    description: str
    modules: List[ModuleTarget]


@dataclass(frozen=True)
class UdsDtc:
    raw: str
    code: str
    status: int
    status_flags: List[str]
    description: str
    suggestion: str


@dataclass
class ModuleScanResult:
    target: ModuleTarget
    responded: bool
    dtcs: List[UdsDtc] = field(default_factory=list)
    raw_lines: List[str] = field(default_factory=list)
    error: Optional[str] = None


@dataclass(frozen=True)
class DiscoveredModule:
    tx_header: str
    response_kind: str
    dtc_count: int
    raw_lines: List[str]


def load_module_profile(path: str) -> ModuleProfile:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    modules = [
        ModuleTarget(
            name=item["name"],
            tx_header=normalise_header(item["tx_header"]),
            description=item.get("description", ""),
        )
        for item in data.get("modules", [])
    ]
    if not modules:
        raise ElmError(f"Module profile {path} does not contain any modules")
    return ModuleProfile(
        name=data.get("name", Path(path).stem),
        protocol=data.get("protocol", "can_11_500"),
        description=data.get("description", ""),
        modules=modules,
    )


def module_profile_to_dict(profile: ModuleProfile) -> Dict[str, object]:
    return {
        "name": profile.name,
        "description": profile.description,
        "protocol": profile.protocol,
        "modules": [
            {
                "name": item.name,
                "tx_header": item.tx_header,
                "description": item.description,
            }
            for item in profile.modules
        ],
    }


def load_discovery_profile(path: str, name: str, protocol: str = "can_11_500") -> ModuleProfile:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ElmError(f"Discovery file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ElmError(f"Discovery file is not valid JSON: {path}: {exc}") from exc
    return profile_from_discovery(data, name=name, protocol=protocol)


def profile_from_discovery(data: Dict[str, object], name: str, protocol: str = "can_11_500") -> ModuleProfile:
    modules_data = data.get("modules", [])
    if not isinstance(modules_data, list):
        raise ElmError("Discovery JSON must contain a modules list")

    modules: List[ModuleTarget] = []
    seen: set[str] = set()
    for index, item in enumerate(modules_data, start=1):
        if not isinstance(item, dict):
            continue
        response_kind = str(item.get("response_kind", ""))
        if not is_usable_discovery_response(response_kind):
            continue
        header = normalise_header(str(item.get("tx_header", "")))
        if len(header) != 3 or header in seen:
            continue
        seen.add(header)
        dtc_count = item.get("dtc_count", 0)
        modules.append(
            ModuleTarget(
                name=f"Discovered module {index} ({header})",
                tx_header=header,
                description=f"Generated from discover-modules response {response_kind}; DTC count during discovery: {dtc_count}.",
            )
        )

    if not modules:
        raise ElmError("Discovery JSON did not contain any usable responding module headers")

    return ModuleProfile(
        name=name,
        protocol=protocol,
        description="Generated from TigerDiag discover-modules output. Review names after confirming module identity on the bike.",
        modules=modules,
    )


def is_usable_discovery_response(response_kind: str) -> bool:
    return response_kind == "positive" or response_kind.startswith("negative_")


def scan_modules(
    elm: Elm327,
    targets: Iterable[ModuleTarget],
    status_mask: int = 0xFF,
) -> List[ModuleScanResult]:
    results: List[ModuleScanResult] = []
    elm.show_headers(True)
    for target in targets:
        elm.set_header(target.tx_header)
        query = f"1902{status_mask:02X}"
        try:
            lines = elm.command(query)
        except ElmNoData:
            results.append(ModuleScanResult(target=target, responded=False, error="no data"))
            continue
        except ElmError as exc:
            results.append(ModuleScanResult(target=target, responded=False, error=str(exc)))
            continue

        parsed = parse_uds_dtc_response(lines, subfunction=0x02)
        results.append(ModuleScanResult(target=target, responded=True, dtcs=parsed, raw_lines=lines))
    elm.show_headers(False)
    return results


def discover_modules(
    elm: Elm327,
    start_header: str,
    end_header: str,
    status_mask: int = 0xFF,
) -> List[DiscoveredModule]:
    start = parse_header_int(start_header)
    end = parse_header_int(end_header)
    if end < start:
        raise ElmError("--end-header must be greater than or equal to --start-header")
    if end - start > 0x1FF:
        raise ElmError("Discovery range is too large; keep scans to 512 headers or fewer")

    discovered: List[DiscoveredModule] = []
    elm.show_headers(True)
    for header in range(start, end + 1):
        tx_header = f"{header:03X}"
        elm.set_header(tx_header)
        try:
            lines = elm.command(f"1902{status_mask:02X}")
        except ElmNoData:
            continue
        except ElmError:
            continue
        if not lines:
            continue
        dtcs = parse_uds_dtc_response(lines, subfunction=0x02)
        discovered.append(
            DiscoveredModule(
                tx_header=tx_header,
                response_kind=classify_uds_response(lines),
                dtc_count=len(dtcs),
                raw_lines=lines,
            )
        )
    elm.show_headers(False)
    return discovered


def classify_uds_response(lines: Iterable[str]) -> str:
    for values in response_messages(lines):
        if find_positive_response(values, subfunction=0x02) is not None:
            return "positive"
        for index in range(0, len(values) - 2):
            if values[index] == 0x7F and values[index + 1] == 0x19:
                return f"negative_0x{values[index + 2]:02X}"
    return "other"


def parse_header_int(header: str) -> int:
    clean = normalise_header(header)
    if len(clean) != 3:
        raise ElmError("Module discovery currently supports 11-bit CAN headers only")
    return int(clean, 16)


def parse_uds_dtc_response(lines: Iterable[str], subfunction: int = 0x02) -> List[UdsDtc]:
    payload: List[int] = []
    for values in response_messages(lines):
        start = find_positive_response(values, subfunction=subfunction)
        if start is None:
            continue
        payload.extend(values[start + 2 :])

    if not payload:
        return []

    # UDS ReadDTCInformation positive responses include a status availability mask
    # before the repeated DTC/status records.
    records = payload[1:]
    dtcs: List[UdsDtc] = []
    for offset in range(0, len(records) - 3, 4):
        raw_code = records[offset : offset + 3]
        status = records[offset + 3]
        if raw_code == [0x00, 0x00, 0x00]:
            continue
        dtcs.append(decode_uds_dtc(raw_code, status))
    return dtcs


def find_positive_response(values: List[int], subfunction: int) -> Optional[int]:
    for index in range(0, len(values) - 1):
        if values[index] == 0x59 and values[index + 1] == subfunction:
            return index
    return None


def decode_uds_dtc(raw_code: List[int], status: int) -> UdsDtc:
    raw = "".join(f"{value:02X}" for value in raw_code)
    base = decode_dtc_pair(raw_code[0], raw_code[1])
    if base:
        code = f"{base}-{raw_code[2]:02X}"
        description = description_for_code(base)
        suggestion = suggestion_for_code(base)
    else:
        code = raw
        description = "Manufacturer-specific diagnostic trouble code"
        suggestion = "Record the raw UDS DTC and module name, then compare against Triumph service data."
    flags = [name for bit, name in UDS_DTC_STATUS_BITS if status & bit]
    return UdsDtc(
        raw=raw,
        code=code,
        status=status,
        status_flags=flags,
        description=description,
        suggestion=suggestion,
    )


def module_results_to_dict(results: Iterable[ModuleScanResult]) -> List[Dict[str, object]]:
    output: List[Dict[str, object]] = []
    for result in results:
        output.append(
            {
                "module": {
                    "name": result.target.name,
                    "tx_header": result.target.tx_header,
                    "description": result.target.description,
                },
                "responded": result.responded,
                "error": result.error,
                "raw_lines": result.raw_lines,
                "dtcs": [
                    {
                        "raw": item.raw,
                        "code": item.code,
                        "status": f"0x{item.status:02X}",
                        "status_flags": item.status_flags,
                        "description": item.description,
                        "suggestion": item.suggestion,
                    }
                    for item in result.dtcs
                ],
            }
        )
    return output


def discovered_modules_to_dict(results: Iterable[DiscoveredModule]) -> List[Dict[str, object]]:
    return [
        {
            "tx_header": item.tx_header,
            "response_kind": item.response_kind,
            "dtc_count": item.dtc_count,
            "raw_lines": item.raw_lines,
        }
        for item in results
    ]
