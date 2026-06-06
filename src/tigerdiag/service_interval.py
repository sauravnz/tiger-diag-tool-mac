"""
Service interval and instruments module support for Triumph Tiger bikes.

Reads service interval data via the instruments module at CAN header DA C1 F1.
"""

from datetime import date, timedelta
from dataclasses import dataclass
from typing import Optional, Tuple

from .connection import Connection, NoDataError
from .live_data import read_odometer, setup_live_data_session


SERVICE_RESET_DISTANCE_10000KM_COMMAND = "33 64"
SERVICE_RESET_DATE_2027_06_01_COMMAND = "5C 1B 06 01 01 6E"
SERVICE_DISTANCE_MIN_KM = 1000
SERVICE_DISTANCE_MAX_KM = 10000
SERVICE_DISTANCE_STEP_KM = 1000
SERVICE_DAYS_OPTIONS = (65, 165, 265, 365)
SERVICE_DAYS_DEFAULT = 365


@dataclass
class ServiceIntervalData:
    """Service interval information."""
    current_odometer_km: Optional[int] = None
    last_service_odometer_km: Optional[int] = None
    last_service_date: Optional[str] = None
    service_due_odometer_km: Optional[int] = None
    service_due_date: Optional[str] = None
    distance_to_service_km: Optional[int] = None
    days_to_service: Optional[int] = None


def read_service_interval(conn: Connection) -> ServiceIntervalData:
    """
    Read service interval data from the instruments module.
    
    Uses CAN header DA C1 F1 (instruments module).
    Attempts to read various UDS DIDs related to service intervals.
    
    Note: The instruments module may not respond to all queries depending on
    the bike's state (ignition on/off, engine running, etc.).
    """
    data = ServiceIntervalData()
    
    try:
        # Switch to instruments module header
        conn.set_header("DA C1 F1")
        
        # Try to read various service-related DIDs
        # These are educated guesses based on the engine ECU DID patterns
        
        # F1B0 - Service interval (attempt)
        try:
            raw = conn.read_did("F1B0")
            if raw and len(raw) >= 2:
                data.distance_to_service_km = int.from_bytes(raw[:2], byteorder="big")
        except NoDataError:
            pass
        
        # F1B1 - Service due date (attempt)
        try:
            raw = conn.read_did("F1B1")
            if raw and len(raw) >= 3:
                # Try BCD decoding like tune date
                year = 2000 + ((raw[0] >> 4) * 10 + (raw[0] & 0x0F))
                month = (raw[1] >> 4) * 10 + (raw[1] & 0x0F)
                day = (raw[2] >> 4) * 10 + (raw[2] & 0x0F)
                data.service_due_date = f"{year:04d}-{month:02d}-{day:02d}"
        except NoDataError:
            pass
        
        # F1B2 - Last service odometer (attempt)
        try:
            raw = conn.read_did("F1B2")
            if raw and len(raw) >= 3:
                data.last_service_odometer_km = int.from_bytes(raw[:3], byteorder="big")
        except NoDataError:
            pass
        
    except Exception as e:
        print(f"Error reading service interval: {e}")
    
    finally:
        # Restore ECU read header
        try:
            conn.set_header("DA D5 F1")
        except Exception:
            pass

    if data.current_odometer_km is None:
        # Gen2 Tiger 900 TFT instruments expose odometer/service data on the
        # 11-bit live-data path used by TigerTool. This is read-only.
        try:
            if setup_live_data_session(conn):
                data.current_odometer_km = read_odometer(conn)
        except Exception as e:
            print(f"Error reading service odometer: {e}")
        finally:
            try:
                conn.initialize()
            except Exception:
                pass
    
    return data


def _log_command(log, direction: str, text: str):
    if log:
        log(f"{direction} {text}")


def _send_logged(conn: Connection, command: str, log=None, pause: float = 0.3) -> str:
    _log_command(log, ">>>", command)
    response = conn.send(command, pause=pause)
    _log_command(log, "<<<", response or "(empty)")
    return response


def setup_captured_service_reset_session(conn: Connection, log=None) -> None:
    """
    Configure the ELM327 exactly like TigerTool before captured service reset writes.

    This uses the 11-bit CAN path captured on a 2021 Tiger 900 GT Pro:
    transmit 701, receive 704, long timeout while waiting for reset acknowledgement.
    """
    _send_logged(conn, "AT WS", log, pause=1.0)
    _send_logged(conn, "AT TP6", log)
    _send_logged(conn, "AT E0", log)
    _send_logged(conn, "AT H1", log)
    _send_logged(conn, "AT L0", log)
    _send_logged(conn, "AT CFC0", log)
    _send_logged(conn, "AT CAF0", log)
    _send_logged(conn, "AT SH701", log)
    _send_logged(conn, "AT CRA704", log)
    _send_logged(conn, "AT ST7F", log)


def restore_captured_service_timeout(conn: Connection, log=None) -> None:
    """Restore TigerTool's normal timeout after a captured service reset write."""
    _send_logged(conn, "AT ST32", log)


def build_service_distance_reset_command(distance_km: int) -> str:
    """Build a TigerTool-style distance reset command."""
    if distance_km % SERVICE_DISTANCE_STEP_KM != 0:
        raise ValueError(f"Distance must be a multiple of {SERVICE_DISTANCE_STEP_KM} km")
    if not SERVICE_DISTANCE_MIN_KM <= distance_km <= SERVICE_DISTANCE_MAX_KM:
        raise ValueError(f"Distance must be between {SERVICE_DISTANCE_MIN_KM} and {SERVICE_DISTANCE_MAX_KM} km")
    return f"33 {distance_km // 100:02X}"


def build_service_date_reset_command(days_to_service: int, today: Optional[date] = None) -> Tuple[str, date]:
    """
    Build a TigerTool-style date reset command.

    Captures show TigerTool sends:
    5C [YY] [MM] [DD] [days_hi] [days_lo]

    The displayed TigerTool value is days to service. The wire day counter is
    displayed days + 1, while the due date is today + displayed days.
    """
    if days_to_service not in SERVICE_DAYS_OPTIONS:
        raise ValueError(f"Days must be one of: {', '.join(str(d) for d in SERVICE_DAYS_OPTIONS)}")
    base_date = today or date.today()
    due_date = base_date + timedelta(days=days_to_service)
    wire_days = days_to_service + 1
    return (
        f"5C {due_date.year % 100:02X} {due_date.month:02X} {due_date.day:02X} "
        f"{(wire_days >> 8) & 0xFF:02X} {wire_days & 0xFF:02X}",
        due_date,
    )


def reset_service_distance(conn: Connection, distance_km: int, log=None) -> bool:
    """
    Reset service distance using the TigerTool 11-bit reset command.

    Confirmed by known TigerTool-compatible workflows:
    - 9000 km  -> 33 5A, acknowledged by 704 B3 5A ...
    - 10000 km -> 33 64, acknowledged by 704 B3 64 ...
    """
    command = build_service_distance_reset_command(distance_km)
    expected = command.replace("33", "B3", 1)
    setup_captured_service_reset_session(conn, log)
    try:
        response = _send_logged(conn, command, log, pause=1.5)
        return expected in response.upper()
    finally:
        restore_captured_service_timeout(conn, log)


def reset_service_date(conn: Connection, days_to_service: int, log=None, today: Optional[date] = None) -> bool:
    """
    Reset service date using the TigerTool 11-bit reset command.

    Confirmed by capture:
    - 265 displayed days, due 26/02/27 -> 5C 1B 02 1A 01 0A
    - previous 365 displayed days capture -> day counter 0x016E
    """
    command, _ = build_service_date_reset_command(days_to_service, today=today)
    expected = command.replace("5C", "DC", 1)
    setup_captured_service_reset_session(conn, log)
    try:
        response = _send_logged(conn, command, log, pause=1.5)
        return expected in response.upper()
    finally:
        restore_captured_service_timeout(conn, log)


def reset_service_distance_10000km_captured(conn: Connection, log=None) -> bool:
    """Backward-compatible helper for the captured 10,000 km reset."""
    return reset_service_distance(conn, 10000, log=log)


def reset_service_date_2027_06_01_captured(conn: Connection, log=None) -> bool:
    """Backward-compatible helper for the earlier captured date reset."""
    setup_captured_service_reset_session(conn, log)
    try:
        response = _send_logged(conn, SERVICE_RESET_DATE_2027_06_01_COMMAND, log, pause=1.5)
        return "DC 1B 06 01 01 6E" in response.upper()
    finally:
        restore_captured_service_timeout(conn, log)


def reset_service_interval(conn: Connection, new_interval_km: int) -> bool:
    """
    Generic service reset is intentionally disabled.

    The TigerTool-compatible reset helpers above send exact allowlisted payloads for
    this bike. This generic entry point remains a hard stop so callers cannot invent
    or vary write commands without a matching capture.
    """
    print("Generic service reset is disabled; use an allowlisted TigerTool-compatible reset helper.")
    return False


def format_service_interval(data: ServiceIntervalData) -> str:
    """Format service interval data for display."""
    lines = []
    
    if data.current_odometer_km is not None:
        lines.append(f"  Current ODO:           {data.current_odometer_km:6d} km")
    
    if data.last_service_odometer_km is not None:
        lines.append(f"  Last Service ODO:      {data.last_service_odometer_km:6d} km")
    
    if data.last_service_date is not None:
        lines.append(f"  Last Service Date:     {data.last_service_date}")
    
    if data.service_due_odometer_km is not None:
        lines.append(f"  Service Due ODO:       {data.service_due_odometer_km:6d} km")
    
    if data.service_due_date is not None:
        lines.append(f"  Service Due Date:      {data.service_due_date}")
    
    if data.distance_to_service_km is not None:
        lines.append(f"  Distance to Service:   {data.distance_to_service_km:6d} km")
    
    if data.days_to_service is not None:
        lines.append(f"  Days to Service:       {data.days_to_service:6d} days")
    
    return "\n".join(lines) if lines else "  (no data available)"
