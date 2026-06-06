"""
Live data reading for Triumph Tiger bikes.

Reads real-time sensor data (RPM, temperature, speed, etc.) from the bike's CAN bus.
Uses 11-bit CAN protocol (ATTP6) with transmit on CAN ID 701 and receive on 704/569.
"""

from dataclasses import dataclass
from typing import Dict, Optional

from .connection import Connection, NoDataError


@dataclass
class LiveDataFrame:
    """Single live data reading."""
    odometer_km: Optional[int] = None
    rpm: Optional[int] = None
    speed_kmh: Optional[int] = None
    coolant_temp_c: Optional[int] = None
    ambient_temp_c: Optional[int] = None
    throttle_percent: Optional[int] = None
    gear: Optional[int] = None
    fuel_level_percent: Optional[int] = None
    raw_704: Optional[bytes] = None
    raw_569: Optional[bytes] = None


def setup_live_data_session(conn: Connection) -> bool:
    """
    Configure ELM327 for live data reading.
    
    Uses 11-bit CAN protocol (ATTP6) with:
    - Transmit header: CAN ID 701
    - Receive from: CAN ID 704 (query responses)
    - Receive from: CAN ID 569 (broadcast data)
    
    Returns True if setup successful.
    """
    try:
        # Warm start
        conn.send("ATWS", pause=1.0)
        
        # Configure for 11-bit CAN
        conn.send("ATE0")       # Echo off
        conn.send("ATTP6")      # Protocol 6 = ISO 15765-4 CAN 11-bit 500kbps
        conn.send("ATH1")       # Headers ON
        conn.send("ATL0")       # Linefeeds off
        conn.send("ATCAF0")     # CAN Auto Format OFF
        conn.send("ATCFC0")     # CAN Flow Control OFF (important for live data)
        conn.send("ATSH701")    # Set transmit header to CAN ID 701
        conn.send("ATCRA704")   # Set receive address to CAN ID 704
        
        return True
    except Exception as e:
        print(f"Failed to setup live data session: {e}")
        return False


def read_odometer(conn: Connection) -> Optional[int]:
    """
    Read odometer value from live data.
    
    Sends query "0D 01" to CAN ID 704.
    Response format: 704 8D 01 00 [ODO_HI] [ODO_LO] 00 00 00
    
    Returns odometer in kilometers, or None if failed.
    """
    try:
        response = conn.send("0D 01", pause=0.3)
        payload = conn._parse_isotp_response(response)
        
        if not payload or len(payload) < 5:
            return None
        
        # Response format: 8D 01 00 [ODO_HI] [ODO_LO] 00 00 00
        # Skip response header (8D 01 00)
        odo_bytes = payload[3:5]
        odo_km = int.from_bytes(bytes(odo_bytes), byteorder="big")
        
        return odo_km
    except (NoDataError, Exception):
        return None


def read_live_frame(conn: Connection) -> LiveDataFrame:
    """
    Read a single frame of live data from the bike.
    
    Queries CAN ID 704 for sensor data and reads broadcast from 569.
    """
    frame = LiveDataFrame()
    
    try:
        # Read odometer
        frame.odometer_km = read_odometer(conn)
        
        # Try to read other sensor data (0x47 01)
        try:
            response = conn.send("47 01", pause=0.3)
            payload = conn._parse_isotp_response(response)
            if payload and len(payload) >= 8:
                frame.raw_704 = bytes(payload)
        except NoDataError:
            pass
        
        # Switch to broadcast receive (CAN ID 569)
        try:
            conn.send("ATCRA569", pause=0.2)
            response = conn.send("00", pause=0.5)
            payload = conn._parse_isotp_response(response)
            if payload and len(payload) >= 7:
                frame.raw_569 = bytes(payload)
        except NoDataError:
            pass
        finally:
            # Switch back to 704
            try:
                conn.send("ATCRA704", pause=0.2)
            except Exception:
                pass
    
    except Exception as e:
        print(f"Error reading live data frame: {e}")
    
    return frame


def read_live_data(conn: Connection, duration_seconds: float = 5.0) -> list:
    """
    Read live data for a specified duration.
    
    Returns list of LiveDataFrame objects.
    """
    import time
    
    frames = []
    start_time = time.time()
    
    try:
        if not setup_live_data_session(conn):
            return frames
        
        while time.time() - start_time < duration_seconds:
            frame = read_live_frame(conn)
            frames.append(frame)
            time.sleep(0.5)
    
    except Exception as e:
        print(f"Error during live data collection: {e}")
    
    return frames


def format_live_data(frame: LiveDataFrame) -> str:
    """Format a live data frame for display."""
    lines = []
    
    if frame.odometer_km is not None:
        lines.append(f"  Odometer:        {frame.odometer_km:6d} km")
    
    if frame.rpm is not None:
        lines.append(f"  RPM:             {frame.rpm:6d}")
    
    if frame.speed_kmh is not None:
        lines.append(f"  Speed:           {frame.speed_kmh:6d} km/h")
    
    if frame.coolant_temp_c is not None:
        lines.append(f"  Coolant Temp:    {frame.coolant_temp_c:6d}°C")
    
    if frame.throttle_percent is not None:
        lines.append(f"  Throttle:        {frame.throttle_percent:6d}%")
    
    if frame.gear is not None:
        lines.append(f"  Gear:            {frame.gear:6d}")
    
    if frame.fuel_level_percent is not None:
        lines.append(f"  Fuel Level:      {frame.fuel_level_percent:6d}%")
    
    if frame.raw_704 is not None:
        lines.append(f"  Raw 704:         {frame.raw_704.hex().upper()}")
    
    if frame.raw_569 is not None:
        lines.append(f"  Raw 569:         {frame.raw_569.hex().upper()}")
    
    return "\n".join(lines) if lines else "  (no data)"
