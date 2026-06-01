from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .elm327 import Elm327, ElmError, ElmNoData, connect_auto, list_serial_candidates, score_port
from .obd import adapter_info


@dataclass
class DoctorReport:
    ports: List[dict] = field(default_factory=list)
    selected_port: Optional[str] = None
    selected_baud: Optional[int] = None
    adapter: Dict[str, str] = field(default_factory=dict)
    adapter_ok: bool = False
    ecu_ok: bool = False
    ecu_error: Optional[str] = None
    notes: List[str] = field(default_factory=list)


def run_doctor(
    port: Optional[str],
    baudrate: Optional[int],
    protocol: str,
    timeout: float,
) -> DoctorReport:
    report = DoctorReport()
    candidates = list_serial_candidates()
    report.ports = [
        {
            "device": candidate.device,
            "description": candidate.description,
            "hwid": candidate.hwid,
            "score": score_port(candidate),
            "likely": score_port(candidate) > 0,
        }
        for candidate in candidates
    ]

    likely = [item for item in report.ports if item["likely"]]
    if not port and not likely:
        report.notes.append("No likely USB/FTDI ELM serial port found.")
        report.notes.append("Connect the BMDiag cable to the bike first; most ELM adapters need OBD socket power.")
        report.notes.append("On macOS, the port normally looks like /dev/cu.usbserial-* or similar.")
        return report

    try:
        elm = connect_auto(port, baudrate, protocol, timeout=timeout, require_ecu=False)
    except ElmError as exc:
        report.notes.append(f"ELM adapter did not answer: {exc}")
        report.notes.append("Try a different --baud value, check ignition/kill switch, and confirm the adapter LEDs are on.")
        return report

    with elm:
        report.selected_port = elm.port
        report.selected_baud = elm.baudrate
        report.adapter = adapter_info(elm)
        report.adapter_ok = bool(report.adapter)
        probe_ecu(elm, report)

    return report


def probe_ecu(elm: Elm327, report: DoctorReport) -> None:
    try:
        lines = elm.command("0100")
    except ElmNoData as exc:
        report.ecu_error = str(exc)
        report.notes.append("The adapter answered, but the ECU did not return standard OBD capability data.")
        report.notes.append("Check ignition on, kill switch run, and try --protocol can_11_500 on a Tiger 900.")
        return
    except ElmError as exc:
        report.ecu_error = str(exc)
        report.notes.append("The adapter answered, but ECU probing failed.")
        report.notes.append("Try --protocol can_11_500, then --protocol auto, and confirm the bike socket is fully seated.")
        return

    report.ecu_ok = bool(lines)
    if report.ecu_ok:
        report.notes.append("Adapter and ECU both responded. Standard scan should work from this port/baud/protocol.")
    else:
        report.ecu_error = "empty response to 0100"
        report.notes.append("The ECU probe returned an empty response; try an explicit protocol.")


def doctor_report_to_dict(report: DoctorReport) -> dict:
    return {
        "ports": report.ports,
        "selected_port": report.selected_port,
        "selected_baud": report.selected_baud,
        "adapter": report.adapter,
        "adapter_ok": report.adapter_ok,
        "ecu_ok": report.ecu_ok,
        "ecu_error": report.ecu_error,
        "notes": report.notes,
    }
