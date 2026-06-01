# Service Reset Capture Notes

Captured from TigerTool V3.7 on a 2021 Tiger 900 GT Pro using an ELM327 v1.4
interface on COM3.

## Safety Status

TigerDiag must remain read-only by default. The service reset commands below are
documented from a successful TigerTool session but are not implemented as CLI
write commands yet.

The previous speculative `2E F1 B0` reset attempt is disabled in code.

## Service Read Path

TigerTool first tries the 29-bit instruments module path:

```text
AT WS
AT E0
AT AL
AT H1
AT V0
AT L0
AT TP7
AT CAF0
AT CFC1
AT CP 18
AT SH DA C1 F1
02 10 03
NO DATA
```

For this bike it then uses the 11-bit CAN path:

```text
AT WS
AT E0
AT TP6
AT H1
AT L0
AT CAF0
AT CFC0
AT SH701
AT CRA704
0D 01
704 8D 01 00 47 B5 00 00 00
47 01
704 C7 02 00 01 00 00 01 FF
AT CRA569
00
569 49 00 40 22 01 2A 01 00
```

The odometer value is `0x47B5 = 18357 km`, matching TigerTool's displayed
current odometer.

## Distance Reset Capture

The user selected the mileage/distance checkbox and confirmed reset. TigerTool
sent:

```text
AT WS
AT TP6
AT E0
AT H1
AT L0
AT CFC0
AT CAF0
AT SH701
AT CRA704
AT ST7F
33 64
704 B3 64 00 00 00 00 00 00
AT ST32
```

Inference from the capture: `33 64` appears to be the service distance reset
command for a 10,000 km interval (`0x64 * 100 km`). This needs at least one more
interval variant before making it configurable.

## Date Reset Capture

The user selected the date checkbox and confirmed reset. TigerTool sent:

```text
AT WS
AT TP6
AT E0
AT H1
AT L0
AT CFC0
AT CAF0
AT SH701
AT CRA704
AT ST7F
5C 1B 06 01 01 6E
704 DC 1B 06 01 01 6E 00 00
AT ST32
```

The bike confirmed the updated service date after this reset. The payload appears
to include the due date and/or days value, but the exact byte layout needs more
captures before TigerDiag should generate this dynamically.

Likely fields:

- `1B 06 01`: service due date `2027-06-01` using year offset `0x1B = 27`
- `01 6E`: days value `366`

## Follow-up Captures

Useful future captures:

- Distance reset with another interval, for example 5000 km, to confirm the
  `33 xx` scale.
- Date reset on another day or with a non-default days value to confirm the date
  and days encoding.
- A single reset where both distance and date are sent together, if TigerTool
  allows that for this model.
