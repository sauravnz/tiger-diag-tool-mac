"""
Serial connection to ELM327 adapter for Triumph bikes.

This module handles:
- Opening/closing the serial port
- Sending AT commands and OBD/UDS commands
- Reading responses (including multi-frame ISO-TP)
- Triumph-specific CAN initialization

The key insight: ALL commands must be sent in ONE persistent connection.
The ELM327 loses its configuration if the connection is closed and reopened.
"""

import time
from typing import List, Optional

import serial


class ConnectionError(Exception):
    """Raised when connection to adapter fails."""
    pass


class NoDataError(Exception):
    """Raised when ECU returns NO DATA."""
    pass


class Connection:
    """
    Persistent serial connection to ELM327 adapter.
    
    Usage:
        with Connection("/dev/cu.usbserial-XXXX") as conn:
            conn.initialize()
            vin = conn.read_did("F190")
    """

    def __init__(self, port: str, baudrate: int = 38400, timeout: float = 2.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self._ser: Optional[serial.Serial] = None
        self._identity: Optional[str] = None
        self._voltage: Optional[str] = None
        self._protocol: Optional[str] = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *args):
        self.close()

    def open(self):
        """Open serial connection."""
        try:
            self._ser = serial.Serial(
                self.port,
                baudrate=self.baudrate,
                timeout=self.timeout,
            )
        except serial.SerialException as e:
            raise ConnectionError(f"Cannot open {self.port}: {e}")

    def close(self):
        """Close serial connection."""
        if self._ser and self._ser.is_open:
            self._ser.close()
        self._ser = None

    @property
    def is_open(self) -> bool:
        return self._ser is not None and self._ser.is_open

    @property
    def identity(self) -> Optional[str]:
        return self._identity

    @property
    def voltage(self) -> Optional[str]:
        return self._voltage

    @property
    def protocol(self) -> Optional[str]:
        return self._protocol

    def send(self, command: str, pause: float = 0.1) -> str:
        """
        Send a command and read the full response.
        
        Returns the cleaned response string (without the command echo or prompt).
        Raises NoDataError if the response contains "NO DATA".
        """
        if not self.is_open:
            raise ConnectionError("Connection not open")

        # Flush input buffer
        self._ser.reset_input_buffer()

        # Send command with carriage return
        self._ser.write((command + "\r").encode("ascii"))
        time.sleep(pause)

        # Read until we get the '>' prompt
        response = ""
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            chunk = self._ser.read(self._ser.in_waiting or 1)
            if not chunk:
                continue
            response += chunk.decode("ascii", errors="replace")
            if ">" in response:
                break

        # Clean up: remove prompt, carriage returns, and extra whitespace
        response = response.replace(">", "").replace("\r", "\n").strip()

        # Remove echo if present
        lines = response.split("\n")
        lines = [l.strip() for l in lines if l.strip()]
        if lines and lines[0].upper().replace(" ", "") == command.upper().replace(" ", ""):
            lines = lines[1:]

        response = "\n".join(lines)

        if "NO DATA" in response.upper():
            raise NoDataError(f"{command}: no data")

        if "?" in response and len(response.strip()) <= 2:
            raise ConnectionError(f"Unknown command: {command}")

        return response

    def initialize(self) -> dict:
        """
        Initialize ELM327 for Triumph bike communication.
        
        This sends the EXACT sequence that TigerTool uses.
        Returns adapter info dict.
        """
        # Reset adapter
        resp = self.send("ATZ", pause=1.0)
        self._identity = resp.strip()

        # Configure adapter
        self.send("ATE0")       # Echo off
        self.send("ATH1")       # Headers ON (needed for multi-frame)
        self.send("ATV0")       # Voltage display format
        self.send("ATL0")       # Linefeeds off
        self.send("ATCAF0")     # CAN Auto Format OFF
        self.send("ATCFC1")     # CAN Flow Control ON (CRITICAL!)
        self.send("ATCP18")     # CAN Protocol 18
        self.send("ATSH DA D5 F1")  # Set header for ECU read
        self.send("ATTP7")      # Timeout Parameter 7

        # Read voltage
        self._voltage = self.send("ATRV").strip()

        return {
            "identity": self._identity,
            "voltage": self._voltage,
            "port": self.port,
            "baudrate": self.baudrate,
        }

    def set_header(self, header: str):
        """Set CAN header for subsequent commands."""
        self.send(f"ATSH {header}")

    def read_did(self, did: str) -> Optional[bytes]:
        """
        Read a UDS Data Identifier using Service 22.
        
        Args:
            did: 4-character hex DID (e.g., "F190" for VIN)
        
        Returns:
            Raw data bytes (without UDS/ISO-TP headers), or None if failed.
        """
        if len(did) != 4:
            raise ValueError(f"DID must be 4 hex chars, got: {did}")

        # Build ISO-TP single frame: 03 22 XX XX
        # 03 = 3 data bytes follow
        # 22 = UDS Service 22 (Read Data By Identifier)
        # XX XX = DID
        command = f"03 22 {did[:2]} {did[2:]}"

        try:
            response = self.send(command, pause=0.5)
        except NoDataError:
            return None

        # Parse multi-frame ISO-TP response
        payload = self._parse_isotp_response(response)

        if not payload:
            return None

        # Validate UDS response header: 62 [DID_HI] [DID_LO] [DATA...]
        if len(payload) < 3:
            return None
        if payload[0] != 0x62:
            return None
        if payload[1] != int(did[:2], 16) or payload[2] != int(did[2:], 16):
            return None

        # Return just the data portion
        return bytes(payload[3:])

    def read_did_ascii(self, did: str) -> Optional[str]:
        """Read a DID and return as ASCII string (stripping padding)."""
        data = self.read_did(did)
        if data is None:
            return None
        # Strip AA padding bytes and null bytes
        data = bytes(b for b in data if b != 0xAA and b != 0x00)
        return data.decode("ascii", errors="ignore").strip() or None

    def send_obd(self, command: str) -> Optional[str]:
        """Send a standard OBD command and return raw response."""
        try:
            return self.send(command, pause=0.3)
        except NoDataError:
            return None

    def _parse_isotp_response(self, response: str) -> Optional[List[int]]:
        """
        Parse ISO-TP response from ELM327.
        
        Handles both single-frame and multi-frame responses.
        
        Example multi-frame (VIN):
            18 DA F1 D5 10 14 62 F1 90 53 4D 54   <- First frame
            18 DA F1 D5 21 54 52 45 36 34 44 38   <- Continuation 1
            18 DA F1 D5 22 4D 41 45 34 33 30 35   <- Continuation 2
        
        Example single-frame (TUNE_COUNT):
            18 DA F1 D5 06 62 F1 A2 00 00 05      <- Single frame
        """
        payload = []
        lines = [l.strip() for l in response.split("\n") if l.strip()]

        for line in lines:
            # Parse hex tokens
            tokens = line.split()
            frame_bytes = []
            for token in tokens:
                try:
                    frame_bytes.append(int(token, 16))
                except ValueError:
                    continue

            if not frame_bytes:
                continue

            # 11-bit CAN frames are reported as: 704 8D 01 00 ...
            # The first token is the CAN ID, not an ISO-TP PCI byte. TigerTool's
            # live/service data responses use these raw eight-byte frames.
            if frame_bytes[0] > 0xFF:
                payload.extend(frame_bytes[1:])
                continue

            # Skip CAN frame header: 18 DA F1 D5
            if (len(frame_bytes) >= 4 and
                frame_bytes[0] == 0x18 and frame_bytes[1] == 0xDA and
                frame_bytes[2] == 0xF1):
                frame_bytes = frame_bytes[4:]

            if not frame_bytes:
                continue

            # Parse ISO-TP Protocol Control Information (PCI)
            pci = frame_bytes[0]
            frame_type = (pci >> 4) & 0x0F

            if frame_type == 0x0:
                # Single frame: PCI low nibble = data length
                length = pci & 0x0F
                payload.extend(frame_bytes[1:1 + length])

            elif frame_type == 0x1:
                # First frame: PCI + next byte = total length
                # Data starts at byte index 2
                payload.extend(frame_bytes[2:])

            elif frame_type == 0x2:
                # Continuation frame: PCI low nibble = sequence number
                # Data starts at byte index 1
                payload.extend(frame_bytes[1:])

        # Strip AA padding bytes from end
        while payload and payload[-1] == 0xAA:
            payload.pop()

        return payload if payload else None
