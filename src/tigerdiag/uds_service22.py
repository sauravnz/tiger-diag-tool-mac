"""
UDS Service 22 (Read Data By Identifier) implementation for Triumph bikes.

This module handles reading ECU data using the UDS Service 22 protocol
with proper ISO-TP framing and multi-frame response reassembly.
"""

from typing import Optional, List, Dict
from .elm327 import Elm327, ElmError, ElmNoData
from .isotp import reassemble_isotp_payloads


# Known DIDs for Triumph Tiger bikes
TRIUMPH_DIDS: Dict[str, tuple] = {
    "F190": ("VIN", 17),  # Vehicle Identification Number
    "F186": ("ECU_TYPE", 4),  # ECU Type
    "F18C": ("ECU_SERIAL", 4),  # ECU Serial Number
    "F1A0": ("TUNE_NUMBER", 6),  # Tune Number
    "F1A2": ("TUNE_COUNT", 2),  # Tune Count
    "F1A7": ("CAL_BUILD", 6),  # Calibration/Build Number
    "F199": ("TUNE_DATE", 6),  # Tune Date
    "F1AE": ("UNKNOWN_AE", 2),  # Unknown DID
}


def read_uds_did(
    elm: Elm327,
    did: str,
    header: str = "DA D5 F1",
    expected_length: Optional[int] = None,
) -> Optional[str]:
    """
    Read a UDS Data Identifier using Service 22.

    Args:
        elm: ELM327 adapter instance
        did: Data Identifier in hex format (e.g., "F190" for VIN)
        header: CAN header to use (default: "DA D5 F1" for reading)
        expected_length: Expected response length (optional)

    Returns:
        Raw response data as hex string, or None if failed

    Raises:
        ElmError: If communication fails
        ElmNoData: If ECU doesn't respond
    """
    try:
        # Set CAN header for reading
        elm.set_header(header)

        # Parse DID (should be 2 bytes in hex)
        if len(did) != 4:
            raise ElmError(f"Invalid DID format: {did}. Expected 4 hex digits.")

        did_high = did[:2]
        did_low = did[2:]

        # Build UDS Service 22 request with ISO-TP framing
        # Format: [ISO-TP PCI] [Service] [DID High] [DID Low]
        # ISO-TP PCI for single frame: 0x0N where N = number of data bytes
        # Data bytes: Service (1) + DID (2) = 3 bytes total
        iso_tp_pci = "03"  # Single frame with 3 data bytes
        service = "22"  # UDS Service 22

        command = f"{iso_tp_pci} {service} {did_high} {did_low}"

        # Send command and get response
        lines = elm.command(command)

        if not lines:
            return None

        # Reassemble ISO-TP multi-frame responses
        payloads = reassemble_isotp_payloads(lines)

        if not payloads:
            return None

        # Extract the response data
        response_data = payloads[0]

        # Validate response format
        # Expected: [Service+0x40] [DID High] [DID Low] [Data...]
        if len(response_data) < 3:
            return None

        if response_data[0] != 0x62:  # 0x62 = positive response to 0x22
            return None

        if response_data[1] != int(did_high, 16) or response_data[2] != int(did_low, 16):
            return None

        # Extract data payload (skip service and DID bytes)
        data_payload = response_data[3:]

        # Convert to hex string
        hex_string = " ".join(f"{b:02X}" for b in data_payload)

        return hex_string

    except ElmNoData:
        return None
    except ElmError as e:
        raise ElmError(f"Failed to read DID {did}: {e}")


def read_uds_did_ascii(
    elm: Elm327,
    did: str,
    header: str = "DA D5 F1",
) -> Optional[str]:
    """
    Read a UDS Data Identifier and return as ASCII string.

    Args:
        elm: ELM327 adapter instance
        did: Data Identifier in hex format
        header: CAN header to use

    Returns:
        Response data as ASCII string, or None if failed
    """
    hex_data = read_uds_did(elm, did, header)

    if not hex_data:
        return None

    try:
        # Convert hex string to bytes
        bytes_list = bytes.fromhex(hex_data.replace(" ", ""))
        # Decode as ASCII, ignoring errors
        return bytes_list.decode("ascii", errors="ignore").strip()
    except Exception:
        return None


def read_vin_uds(elm: Elm327) -> Optional[str]:
    """
    Read VIN using UDS Service 22 DID F190.

    Args:
        elm: ELM327 adapter instance

    Returns:
        VIN as string, or None if failed
    """
    return read_uds_did_ascii(elm, "F190")


def read_ecu_info(elm: Elm327) -> Dict[str, Optional[str]]:
    """
    Read complete ECU information.

    Args:
        elm: ELM327 adapter instance

    Returns:
        Dictionary with ECU information
    """
    info = {}

    for did, (name, length) in TRIUMPH_DIDS.items():
        try:
            data = read_uds_did_ascii(elm, did)
            info[name] = data
        except Exception:
            info[name] = None

    return info
