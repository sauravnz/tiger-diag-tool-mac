"""
ELM327 adapter communication module.

Handles serial communication with ELM327 OBD adapters, with specific
support for Triumph bikes using CAN protocol.
"""

import glob
import re
import time
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence

try:
    import serial
    from serial.tools import list_ports
except ImportError:  # pragma: no cover - exercised only before dependency install
    serial = None
    list_ports = None


COMMON_BAUDRATES = (38400, 115200, 9600, 57600)

PROTOCOLS = {
    "auto": "0",
    "iso9141": "3",
    "kwp_fast": "5",
    "can_11_500": "6",
    "can_29_500": "7",
    "can_11_250": "8",
    "can_29_250": "9",
}


class ElmError(RuntimeError):
    pass


class ElmNoData(ElmError):
    pass


@dataclass(frozen=True)
class SerialCandidate:
    device: str
    description: str = ""
    hwid: str = ""


def require_pyserial() -> None:
    if serial is None:
        raise ElmError("pyserial is not installed. Run: python -m pip install -e .")


def list_serial_candidates() -> List[SerialCandidate]:
    require_pyserial()
    candidates = {}

    for port in list_ports.comports():
        candidates[port.device] = SerialCandidate(
            device=port.device,
            description=port.description or "",
            hwid=port.hwid or "",
        )

    for pattern in (
        "/dev/cu.usbserial*",
        "/dev/cu.usbmodem*",
        "/dev/cu.SLAB_USBtoUART*",
        "/dev/cu.wchusbserial*",
    ):
        for device in glob.glob(pattern):
            candidates.setdefault(device, SerialCandidate(device=device))

    return sorted(candidates.values(), key=lambda item: score_port(item), reverse=True)


def score_port(port: SerialCandidate) -> int:
    text = f"{port.device} {port.description} {port.hwid}".lower()
    score = 0
    for token in ("usbserial", "ftdi", "ft232", "elm", "obd", "bmdiag"):
        if token in text:
            score += 10
    if "bluetooth-incoming" in text:
        score -= 50
    if "debug-console" in text:
        score -= 50
    return score


class Elm327:
    """ELM327 OBD adapter communication."""

    def __init__(self, port: str, baudrate: int = 38400, timeout: float = 2.0):
        require_pyserial()
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.serial = serial.Serial(
            port=port,
            baudrate=baudrate,
            timeout=timeout,
            write_timeout=timeout,
        )

    def close(self) -> None:
        if self.serial and self.serial.is_open:
            self.serial.close()

    def __enter__(self) -> "Elm327":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def initialize(self, protocol: str = "auto") -> None:
        """Initialize ELM327 adapter with Triumph bike settings."""
        if protocol not in PROTOCOLS:
            names = ", ".join(sorted(PROTOCOLS))
            raise ElmError(f"Unknown protocol '{protocol}'. Choose one of: {names}")

        # Reset adapter
        self.command("ATZ", pause=1.0, tolerate_no_data=True)
        
        # Basic settings
        for cmd in (
            "ATE0",      # Echo off
            "ATL0",      # Linefeeds off
            "ATS0",      # Spaces off
            "ATH0",      # Headers off (will enable later for CAN)
        ):
            self.command(cmd, tolerate_no_data=True)
        
        # CAN-specific settings for Triumph bikes
        for cmd in (
            "ATCAF0",    # CAN Auto Format OFF (required for Triumph)
            "ATCFC1",    # CAN Flow Control ON (CRITICAL for multi-frame responses)
            f"ATSP{PROTOCOLS[protocol]}",  # Set protocol
            "ATAT1",     # Adaptive timing on
        ):
            self.command(cmd, tolerate_no_data=True)

    def command(self, command: str, pause: float = 0.05, tolerate_no_data: bool = False) -> List[str]:
        """Send a command to the ELM327 and get response."""
        clean = command.strip()
        if not clean:
            return []

        self.serial.reset_input_buffer()
        self.serial.write((clean + "\r").encode("ascii"))
        self.serial.flush()
        time.sleep(pause)

        raw = self._read_until_prompt()
        lines = normalise_elm_lines(raw, echo=clean)
        error = first_error_line(lines)
        if error and not tolerate_no_data:
            if error == "NO DATA":
                raise ElmNoData(f"{clean}: no data")
            raise ElmError(f"{clean}: {error}")
        return [line for line in lines if not is_status_or_error(line)]

    def set_header(self, header: str) -> None:
        """Set CAN message header."""
        clean = normalise_header(header)
        self.command(f"ATSH{clean}", tolerate_no_data=True)

    def show_headers(self, enabled: bool) -> None:
        """Enable/disable CAN header display."""
        self.command("ATH1" if enabled else "ATH0", tolerate_no_data=True)

    def _read_until_prompt(self) -> str:
        """Read from serial until we get the ELM327 prompt (>)."""
        deadline = time.monotonic() + self.timeout
        data = bytearray()
        while time.monotonic() < deadline:
            chunk = self.serial.read(1)
            if not chunk:
                continue
            data.extend(chunk)
            if chunk == b">":
                break
        if not data:
            raise ElmError("No response from ELM327 adapter")
        return data.decode("ascii", errors="replace")


def connect_auto(
    port: Optional[str],
    baudrate: Optional[int],
    protocol: str,
    timeout: float = 2.0,
    require_ecu: bool = True,
) -> Elm327:
    """Auto-detect and connect to ELM327 adapter."""
    candidates = list_serial_candidates()
    ports = [port] if port else [candidate.device for candidate in candidates if score_port(candidate) > 0]
    if not ports:
        raise ElmError(
            "No likely ELM/USB serial ports found. Is the BMDiag cable plugged in, connected to the bike, "
            "and powered with ignition on? Use list-ports to inspect all serial devices."
        )

    bauds: Sequence[int] = [baudrate] if baudrate else COMMON_BAUDRATES
    attempts = []
    for candidate_port in ports:
        for candidate_baud in bauds:
            try:
                elm = Elm327(candidate_port, candidate_baud, timeout=timeout)
                elm.initialize(protocol=protocol)
                if require_ecu:
                    elm.command("0100")
                else:
                    elm.command("ATI", tolerate_no_data=True)
                return elm
            except Exception as exc:
                attempts.append(f"{candidate_port}@{candidate_baud}: {exc}")
                try:
                    elm.close()  # type: ignore[name-defined]
                except Exception:
                    pass

    detail = "\n".join(f"  - {attempt}" for attempt in attempts[-8:])
    raise ElmError(f"Could not connect to an ECU through an ELM327 adapter. Recent attempts:\n{detail}")


def normalise_elm_lines(raw: str, echo: str = "") -> List[str]:
    """Normalize ELM327 response into clean lines."""
    text = raw.replace("\r", "\n").replace(">", "\n")
    lines = []
    for line in text.splitlines():
        item = line.strip()
        if item and item != echo:
            lines.append(item)
    return lines


def normalise_header(header: str) -> str:
    """Normalize CAN header format."""
    return header.replace(" ", "").upper()


def is_status_or_error(line: str) -> bool:
    """Check if line is a status message or error."""
    return line.upper() in ("OK", "?") or line.startswith("UNABLE")


def first_error_line(lines: Iterable[str]) -> Optional[str]:
    """Find first error line in response."""
    for line in lines:
        upper = line.upper()
        if upper in ("NO DATA", "ERROR", "?"):
            return upper
        if upper.startswith("ERROR"):
            return upper
    return None
