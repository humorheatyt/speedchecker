# Bundled speedtest-cli

Source: https://github.com/sivel/speedtest-cli/tree/v2.1.3
Version: 2.1.3, Apache-2.0 (see LICENSE.speedtest-cli).

Local modification: a `transfer_observer(direction, size)` hook in download reads
and upload body reads for live transfer telemetry. Upload counters measure bytes
provided to the HTTP stack, not acknowledged payload. No Ookla binary is bundled.
This community client uses speedtest.net HTTP endpoints; results differ from the
proprietary Ookla application and availability depends on the remote service.
