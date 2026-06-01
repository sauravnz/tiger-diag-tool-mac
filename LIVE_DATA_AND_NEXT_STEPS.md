# Triumph Tiger Live Data & Next Steps

## What We Achieved Today

1. **Complete Architecture Rewrite:** We built a fresh, robust foundation (`tigerdiag v0.2.0`) that properly handles persistent serial connections, which is required for Triumph's specific CAN bus implementation.
2. **VIN & ECU Info Retrieval:** Successfully read the VIN (`SMTTRE64D8MAE4305`), ECU Serial, Calibration Build, and Tune Date by correctly implementing UDS Service 22 over ISO-TP.
3. **Live Data Discovery:** We successfully tapped into the bike's active CAN bus and discovered 10 unique CAN IDs broadcasting data while the engine was running.

## Live Data Findings (CAN Bus Scan)

The bike broadcasts continuous data on the following CAN IDs:

*   **Static/Slow Changing Data:** 208, 209, 210, 275, 276, 277, 500, 760
*   **Actively Changing Data:** 274 (Likely contains real-time sensors like RPM, Speed, or Throttle Position)

## Next Steps: Live Data Decoding

To build live data monitoring into the `tigerdiag scan` command, we need to map the raw bytes from CAN ID 274 (and others) to actual sensor values.

1.  **Capture Changing Data:** Run a scan while blipping the throttle to see which specific bytes in CAN ID 274 change with RPM.
2.  **Map Bytes to Sensors:** Once we identify the RPM bytes, we can apply standard automotive scaling (e.g., `(A * 256 + B) / 4`) to decode the value.
3.  **Implement Live Monitor:** Build a continuous listening mode in `tigerdiag` that parses these CAN frames in real-time.

## Next Steps: Windows Capture (Service Reset & Fault Codes)

To achieve the ultimate goal of replicating TigerTool's functionality (service resets and reading the TES fault), we need to capture the exact command sequences used by TigerTool on Windows.

### Instructions for Windows Capture

1.  **Setup:** Start Eltima Serial Port Monitor on the correct COM port *before* opening TigerTool.
2.  **Initialization:** Open TigerTool and let it connect and read the initial ECU data.
3.  **Fault Codes:** Navigate to the DTC/Fault Codes section (to capture how it reads your TES fault).
4.  **Service Info:** Navigate to the Service/Maintenance section and read the current service interval.
5.  **Service Reset:** Perform a service light reset (if you are comfortable doing so).
6.  **Export:** Stop the Eltima monitor and export the session (as `.spm` or `.csv`).

Once we have this capture, we can extract the specific UDS commands and CAN addresses used for these advanced features and implement them in our new Mac tool.
