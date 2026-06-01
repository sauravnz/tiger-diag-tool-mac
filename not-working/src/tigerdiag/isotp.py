from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple


@dataclass
class IsoTpStream:
    expected_length: int
    data: List[int] = field(default_factory=list)
    next_sequence: int = 1

    @property
    def complete(self) -> bool:
        return len(self.data) >= self.expected_length

    def payload(self) -> List[int]:
        return self.data[: self.expected_length]


def reassemble_isotp_payloads(lines: Iterable[str]) -> List[List[int]]:
    payloads: List[List[int]] = []
    streams: Dict[str, IsoTpStream] = {}

    for line in lines:
        parsed = parse_can_line(line)
        if not parsed:
            continue
        source, data = parsed
        if not data:
            continue

        pci = data[0]
        frame_type = pci >> 4

        if frame_type == 0x0:
            length = pci & 0x0F
            if length == 0 or length > len(data) - 1:
                payloads.append(data)
            else:
                payloads.append(data[1 : 1 + length])
            continue

        if frame_type == 0x1 and len(data) >= 2:
            length = ((pci & 0x0F) << 8) | data[1]
            streams[source] = IsoTpStream(expected_length=length, data=data[2:])
            if streams[source].complete:
                payloads.append(streams.pop(source).payload())
            continue

        if frame_type == 0x2:
            stream = streams.get(source)
            if not stream:
                continue
            sequence = pci & 0x0F
            if sequence != stream.next_sequence:
                streams.pop(source, None)
                continue
            stream.data.extend(data[1:])
            stream.next_sequence = (stream.next_sequence + 1) & 0x0F
            if stream.complete:
                payloads.append(streams.pop(source).payload())
            continue

        payloads.append(data)

    return payloads


def parse_can_line(line: str) -> Optional[Tuple[str, List[int]]]:
    tokens = line.strip().upper().split()
    if not tokens:
        return None

    first = tokens[0]
    if is_can_id(first) and len(tokens) > 1:
        values = []
        for token in tokens[1:]:
            if len(token) == 2 and all(char in "0123456789ABCDEF" for char in token):
                values.append(int(token, 16))
        return first, values

    values = hex_bytes(line)
    return "", values


def is_can_id(token: str) -> bool:
    return len(token) in {3, 8} and all(char in "0123456789ABCDEF" for char in token)


def hex_bytes(line: str) -> List[int]:
    return [int(token, 16) for token in re.findall(r"\b[0-9A-F]{2}\b", line.upper())]
