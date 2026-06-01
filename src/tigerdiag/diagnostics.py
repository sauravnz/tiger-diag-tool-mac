"""
Diagnostic functions for Triumph Tiger bikes.

Reads ECU information, VIN, DTCs, and live data.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .connection import Connection, NoDataError


# Known Triumph DIDs (Data Identifiers)
TRIUMPH_DIDS = {
    "F190": "VIN",
    "F18C": "ECU Serial",
    "F1A7": "Calibration Build",
    "F1A0": "Tune Number",
    "F1A2": "Tune Count",
    "F199": "Tune Date",
    "F1AE": "Software Version",
}


@dataclass
class ECUInfo:
    """ECU information read from bike."""
    vin: Optional[str] = None
    ecu_serial: Optional[str] = None
    calibration_build: Optional[str] = None
    tune_number: Optional[str] = None
    tune_count: Optional[int] = None
    tune_date: Optional[str] = None
    software_version: Optional[str] = None
    voltage: Optional[str] = None


@dataclass
class DTC:
    """Diagnostic Trouble Code."""
    code: str
    description: str = ""
    status: str = ""


@dataclass
class DiagnosticReport:
    """Complete diagnostic report."""
    adapter_info: Dict[str, str] = field(default_factory=dict)
    ecu_info: Optional[ECUInfo] = None
    dtcs: List[DTC] = field(default_factory=list)
    connected: bool = False
    error: Optional[str] = None


def read_ecu_info(conn: Connection) -> ECUInfo:
    """Read all ECU information from the bike."""
    info = ECUInfo()
    info.voltage = conn.voltage

    # Read VIN (DID F190)
    info.vin = conn.read_did_ascii("F190")

    # Read ECU Serial (DID F18C)
    raw = conn.read_did("F18C")
    if raw:
        # ECU serial is hex-encoded
        info.ecu_serial = raw.hex().upper().rstrip("A")

    # Read Calibration Build (DID F1A7)
    raw = conn.read_did("F1A7")
    if raw:
        # Strip padding
        clean = bytes(b for b in raw if b != 0xAA and b != 0x00)
        info.calibration_build = clean.hex().upper() if clean else None

    # Read Tune Number (DID F1A0)
    raw = conn.read_did("F1A0")
    if raw:
        clean = bytes(b for b in raw if b != 0xAA)
        info.tune_number = clean.hex().upper()

    # Read Tune Count (DID F1A2)
    raw = conn.read_did("F1A2")
    if raw:
        clean = bytes(b for b in raw if b != 0xAA)
        if clean:
            info.tune_count = int.from_bytes(clean, byteorder="big")

    # Read Tune Date (DID F199)
    # Bytes are BCD-encoded: 0x22 0x05 0x18 = 2022-05-18
    raw = conn.read_did("F199")
    if raw:
        clean = bytes(b for b in raw if b != 0xAA)
        if len(clean) >= 3:
            # BCD decode: 0x22 -> "22" -> 2022
            year = 2000 + ((clean[0] >> 4) * 10 + (clean[0] & 0x0F))
            month = (clean[1] >> 4) * 10 + (clean[1] & 0x0F)
            day = (clean[2] >> 4) * 10 + (clean[2] & 0x0F)
            info.tune_date = f"{year:04d}-{month:02d}-{day:02d}"

    # Read Software Version (DID F1AE)
    raw = conn.read_did("F1AE")
    if raw:
        clean = bytes(b for b in raw if b != 0xAA)
        if clean:
            info.software_version = clean.hex().upper()

    return info


def read_calibration_id(conn: Connection) -> Optional[str]:
    """
    Read calibration ID from a different module.
    Uses header DB 33 F1 and command 02 09 04.
    """
    try:
        conn.set_header("DB 33 F1")
        response = conn.send("02 09 04", pause=0.5)
        # Parse the response
        payload = conn._parse_isotp_response(response)
        if payload and len(payload) > 3:
            # Skip mode response header (49 04 01)
            data = bytes(payload[3:])
            data = bytes(b for b in data if b != 0xAA and b != 0x00)
            return data.decode("ascii", errors="ignore").strip() or None
    except (NoDataError, Exception):
        pass
    finally:
        # Restore ECU read header
        try:
            conn.set_header("DA D5 F1")
        except Exception:
            pass
    return None


def run_full_diagnostic(conn: Connection) -> DiagnosticReport:
    """Run a complete diagnostic scan."""
    report = DiagnosticReport()

    try:
        # Initialize connection
        report.adapter_info = conn.initialize()
        report.connected = True

        # Read ECU info
        report.ecu_info = read_ecu_info(conn)

        # Read calibration ID
        cal_id = read_calibration_id(conn)
        if cal_id and report.ecu_info:
            report.ecu_info.calibration_build = cal_id

    except Exception as e:
        report.error = str(e)

    return report
