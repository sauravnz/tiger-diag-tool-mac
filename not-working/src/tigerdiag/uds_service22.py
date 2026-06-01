"""
UDS Service 22 (Read Data By Identifier) for Triumph bikes.

Implements reading ECU data using UDS Service 22 with proper
ISO-TP multi-frame response handling.
"""

from typing import Optional, Dict, List
from .elm327 import Elm327, ElmError, ElmNoData


# Triumph Tiger bike DIDs
TRIUMPH_DIDS: Dict[str, tuple] = {
    "F190": ("VIN", 17),
    "F186": ("ECU_TYPE", 4),
    "F18C": ("ECU_SERIAL", 4),
    "F1A0": ("TUNE_NUMBER", 6),
    "F1A2": ("TUNE_COUNT", 2),
    "F1A7": ("CAL_BUILD", 6),
    "F199": ("TUNE_DATE", 6),
    "F1AE": ("UNKNOWN_AE", 2),
}


def read_uds_did(elm: Elm327, did: str, header: str = "DA D5 F1") -> Optional[str]:
    """
    Read a UDS Data Identifier using Service 22.
    
    Assumes CAN is already configured by caller.
    
    Args:
        elm: ELM327 adapter
        did: Data Identifier (e.g., "F190" for VIN)
        header: CAN header for reading
    
    Returns:
        Hex string of response data, or None if failed
    """
    if len(did) != 4:
        raise ElmError(f"Invalid DID: {did}")
    
    try:
        # Set CAN header (assume CAN is already configured)
        elm.set_header(header)
        
        # Send UDS Service 22 command with ISO-TP framing
        # Format: [ISO-TP PCI] [Service] [DID High] [DID Low]
        command = f"03 22 {did[:2]} {did[2:]}"
        lines = elm.command(command, tolerate_no_data=False)
        
        if not lines:
            return None
        
        # Parse multi-frame ISO-TP response
        payload = _parse_isotp_response(lines)
        
        if not payload or len(payload) < 3:
            return None
        
        # Validate UDS response: [0x62] [DID High] [DID Low] [Data...]
        if payload[0] != 0x62:
            return None
        
        if payload[1] != int(did[:2], 16) or payload[2] != int(did[2:], 16):
            return None
        
        # Return data portion as hex string
        data = payload[3:]
        return " ".join(f"{b:02X}" for b in data)
    
    except ElmNoData:
        return None


def _parse_isotp_response(lines: List[str]) -> Optional[List[int]]:
    """
    Parse ISO-TP multi-frame response from ELM327.
    
    Expected format:
    18 DA F1 D5 10 14 62 F1 90 53 4D 54  <- First frame
    18 DA F1 D5 21 54 52 45 36 34 44 38  <- Continuation frame 1
    18 DA F1 D5 22 4D 41 45 34 33 30 35  <- Continuation frame 2
    """
    payload = []
    
    for line in lines:
        # Parse hex tokens
        tokens = line.split()
        bytes_in_line = []
        
        for token in tokens:
            try:
                bytes_in_line.append(int(token, 16))
            except ValueError:
                continue
        
        if not bytes_in_line:
            continue
        
        # Skip CAN frame header (18 DA F1 D5)
        if len(bytes_in_line) >= 4 and bytes_in_line[0] == 0x18 and \
           bytes_in_line[1] == 0xDA and bytes_in_line[2] == 0xF1 and \
           bytes_in_line[3] == 0xD5:
            bytes_in_line = bytes_in_line[4:]
        
        if not bytes_in_line:
            continue
        
        # Parse ISO-TP PCI
        pci = bytes_in_line[0]
        frame_type = (pci >> 4) & 0x0F
        
        if frame_type == 0x1:  # First frame
            # Skip length byte and add data (7 bytes in first frame)
            if len(bytes_in_line) > 2:
                payload.extend(bytes_in_line[2:9])
        
        elif frame_type == 0x2:  # Continuation frame
            # Add all data bytes (up to 7 bytes)
            if len(bytes_in_line) > 1:
                payload.extend(bytes_in_line[1:8])
        
        elif frame_type == 0x0:  # Single frame
            # Add data bytes (length in lower nibble)
            length = pci & 0x0F
            if len(bytes_in_line) > 1:
                payload.extend(bytes_in_line[1:1+length])
    
    return payload if payload else None


def read_uds_did_ascii(elm: Elm327, did: str, header: str = "DA D5 F1") -> Optional[str]:
    """Read UDS DID and return as ASCII string."""
    hex_data = read_uds_did(elm, did, header)
    
    if not hex_data:
        return None
    
    try:
        bytes_data = bytes.fromhex(hex_data.replace(" ", ""))
        return bytes_data.decode("ascii", errors="ignore").strip()
    except Exception:
        return None


def read_vin_uds(elm: Elm327) -> Optional[str]:
    """Read VIN using UDS Service 22 DID F190."""
    return read_uds_did_ascii(elm, "F190")


def read_ecu_info(elm: Elm327) -> Dict[str, Optional[str]]:
    """Read complete ECU information."""
    info = {}
    
    for did, (name, _) in TRIUMPH_DIDS.items():
        try:
            info[name] = read_uds_did_ascii(elm, did)
        except Exception:
            info[name] = None
    
    return info
