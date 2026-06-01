"""
Service interval and instruments module support for Triumph Tiger bikes.

Reads and resets service interval data via the instruments module at CAN header DA C1 F1.
"""

from dataclasses import dataclass
from typing import Optional

from .connection import Connection, NoDataError


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
    
    return data


def reset_service_interval(conn: Connection, new_interval_km: int) -> bool:
    """
    Reset service interval on the instruments module.
    
    Uses CAN header DA C1 F1 and UDS Service 2E (Write Data By Identifier).
    
    Args:
        conn: Connection to bike
        new_interval_km: New service interval in kilometers (must be multiple of 100)
    
    Returns:
        True if reset successful, False otherwise.
    
    Note: This is a destructive operation. The actual command sequence from TigerTool
    is not yet fully reverse-engineered from the capture. This is a placeholder
    implementation that attempts the most likely approach.
    """
    if new_interval_km % 100 != 0:
        print("Error: Service interval must be a multiple of 100 km")
        return False
    
    try:
        # Switch to instruments module header
        conn.set_header("DA C1 F1")
        
        # Try to enter extended diagnostic session (may be required)
        try:
            response = conn.send("02 10 03", pause=0.5)
            print(f"Diagnostic session response: {response}")
        except NoDataError:
            print("Warning: Instruments module did not respond to session control")
            # Continue anyway - the module may not require this
        
        # Attempt to write service interval using UDS Service 2E
        # Format: 2E [DID_HI] [DID_LO] [DATA...]
        # This is speculative - the actual DID and data format are unknown
        
        interval_bytes = new_interval_km.to_bytes(2, byteorder="big")
        command = f"04 2E F1 B0 {interval_bytes[0]:02X} {interval_bytes[1]:02X}"
        
        try:
            response = conn.send(command, pause=0.5)
            print(f"Service interval write response: {response}")
            
            # Check if response indicates success (6E = positive response to 2E)
            if "6E" in response.upper():
                print("Service interval reset successful")
                return True
            else:
                print("Service interval reset may have failed - check response")
                return False
        
        except NoDataError:
            print("Error: Instruments module did not respond to write command")
            return False
    
    except Exception as e:
        print(f"Error resetting service interval: {e}")
        return False
    
    finally:
        # Restore ECU read header
        try:
            conn.set_header("DA D5 F1")
        except Exception:
            pass


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
