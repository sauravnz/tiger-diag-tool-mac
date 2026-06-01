from __future__ import annotations

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
        if protocol not in PROTOCOLS:
            names = ", ".join(sorted(PROTOCOLS))
            raise ElmError(f"Unknown protocol '{protocol}'. Choose one of: {names}")

        self.command("ATZ", pause=1.0, tolerate_no_data=True)
        for cmd in (
            "ATD",
            "ATE0",
            "ATL0",
            "ATS0",
            "ATH0",
            "ATCAF1",
            "ATAT1",
            f"ATSP{PROTOCOLS[protocol]}",
        ):
            self.command(cmd, tolerate_no_data=True)

    def command(self, command: str, pause: float = 0.05, tolerate_no_data: bool = False) -> List[str]:
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
        clean = normalise_header(header)
        self.command(f"ATSH{clean}", tolerate_no_data=True)

    def show_headers(self, enabled: bool) -> None:
        self.command("ATH1" if enabled else "ATH0", tolerate_no_data=True)

    def _read_until_prompt(self) -> str:
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
    text = raw.replace("\r", "\n").replace(">", "\n")
    lines = []
    for line in text.splitlines():
        item = line.strip()
        if not item:
            continue
        if echo and item.upper() == echo.upper():
            continue
        lines.append(re.sub(r"\s+", " ", item).upper())
    return lines


def normalise_header(header: str) -> str:
    clean = re.sub(r"[^0-9A-Fa-f]", "", header).upper()
    if len(clean) not in {3, 6, 8}:
        raise ElmError("CAN/K-line header must be 3, 6, or 8 hex characters")
    return clean


def is_status_or_error(line: str) -> bool:
    if line in {"OK", "NO DATA", "?", "STOPPED", "UNABLE TO CONNECT", "BUS INIT: ERROR"}:
        return True
    if line.startswith("SEARCHING"):
        return True
    return False


def first_error_line(lines: Iterable[str]) -> Optional[str]:
    for line in lines:
        if line in {"NO DATA", "?", "STOPPED", "UNABLE TO CONNECT", "BUS INIT: ERROR"}:
            return line
    return None
