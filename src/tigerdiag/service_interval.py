"""
Service interval and instruments module support for Triumph Tiger bikes.

Reads service interval data via the instruments module at CAN header DA C1 F1.
"""

from dataclasses import dataclass
from typing import Optional

from .connection import Connection, NoDataError
from .live_data import read_odometer, setup_live_data_session


SERVICE_RESET_DISTANCE_10000KM_COMMAND = "33 64"
SERVICE_RESET_DATE_2027_06_01_COMMAND = "5C 1B 06 01 01 6E"


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


def reset_service_distance_10000km_captured(conn: Connection, log=None) -> bool:
    """
    Reset service distance using the exact 10,000 km TigerTool capture.

    This is intentionally not configurable. It sends only the allowlisted payload
    captured from TigerTool for this bike.
    """
    setup_captured_service_reset_session(conn, log)
    try:
        response = _send_logged(
            conn,
            SERVICE_RESET_DISTANCE_10000KM_COMMAND,
            log,
            pause=1.5,
        )
        return "B3 64" in response.upper()
    finally:
        restore_captured_service_timeout(conn, log)


def reset_service_date_2027_06_01_captured(conn: Connection, log=None) -> bool:
    """
    Reset service date using the exact TigerTool capture.

    Captured payload: 5C 1B 06 01 01 6E, acknowledged by
    704 DC 1B 06 01 01 6E 00 00.
    """
    setup_captured_service_reset_session(conn, log)
    try:
        response = _send_logged(
            conn,
            SERVICE_RESET_DATE_2027_06_01_COMMAND,
            log,
            pause=1.5,
        )
        return "DC 1B 06 01 01 6E" in response.upper()
    finally:
        restore_captured_service_timeout(conn, log)


def reset_service_interval(conn: Connection, new_interval_km: int) -> bool:
    """
    Generic service reset is intentionally disabled.

    The captured TigerTool reset helpers above send exact allowlisted payloads for
    this bike. This generic entry point remains a hard stop so callers cannot invent
    or vary write commands without a matching capture.
    """
    print("Generic service reset is disabled; use an exact captured TigerTool reset helper.")
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
