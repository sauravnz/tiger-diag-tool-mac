"""
Serial port detection for macOS.

Finds ELM327/FTDI USB serial adapters.
"""

from typing import Dict, List, Optional

import serial.tools.list_ports


# Keywords that indicate an ELM327/FTDI adapter
LIKELY_KEYWORDS = ["usbserial", "FTDI", "FT232", "USB", "ELM"]

# Keywords that indicate NOT an ELM327 adapter
UNLIKELY_KEYWORDS = ["Bluetooth", "debug", "wlan", "Jabra"]


def list_ports() -> List[Dict[str, str]]:
    """List all available serial ports with descriptions."""
    ports = []
    for port in serial.tools.list_ports.comports():
        description = port.description or "n/a"
        if port.manufacturer:
            description += f" ({port.manufacturer})"
        if port.hwid and port.hwid != "n/a":
            description += f" [{port.hwid}]"
        ports.append({
            "device": port.device,
            "description": description,
        })
    return ports


def find_likely_port() -> Optional[str]:
    """
    Auto-detect the most likely ELM327 serial port.
    
    Looks for ports matching patterns like /dev/cu.usbserial-*
    """
    for port in serial.tools.list_ports.comports():
        device = port.device.lower()
        desc = (port.description or "").lower()
        hwid = (port.hwid or "").lower()
        combined = f"{device} {desc} {hwid}"

        # Skip unlikely ports
        if any(kw.lower() in combined for kw in UNLIKELY_KEYWORDS):
            continue

        # Match likely ports
        if any(kw.lower() in combined for kw in LIKELY_KEYWORDS):
            return port.device

    return None
