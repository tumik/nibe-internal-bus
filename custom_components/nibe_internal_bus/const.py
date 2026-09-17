"""Constants for the Nibe internal-bus integration."""

from __future__ import annotations

DOMAIN = "nibe_internal_bus"

CONF_PUSH_INTERVAL = "push_interval"

DEFAULT_PORT = 9999

# The ESP32 drops a UDP target 120 s after its last request
# (NibeGwComponent.h: TARGET_TIMEOUT_MS = 120000), so re-register at half that.
KEEPALIVE_INTERVAL = 60

# A field whose frame has not been seen for this long is reported unavailable.
STALE_AFTER = 60

DEFAULT_PUSH_INTERVAL = 15
MIN_PUSH_INTERVAL = 5
MAX_PUSH_INTERVAL = 60

# How long the config flow waits for the ESP32 to start forwarding frames.
PROBE_TIMEOUT = 15

# The only bus address this integration decodes.
BUS_ADDRESS = 0x00F5

MODE_STANDBY = "standby"
MODE_HEATING = "heating"
MODE_HOT_WATER = "hot_water"

VALVE_HEATING = "heating"
VALVE_HOT_WATER = "hot_water"

# Values synthesised by the coordinator rather than decoded from a payload.
FIELD_OPERATING_MODE = "derived_operating_mode"

FIELD_RELAYS_RAW = "00F5_MASTER_55_byte0"
FIELD_COMPRESSOR = "00F5_MASTER_55_byte0bit0"
FIELD_HEATING_PUMP = "00F5_MASTER_55_byte0bit1"
FIELD_BRINE_PUMP = "00F5_MASTER_55_byte0bit2"
FIELD_THREE_WAY_VALVE = "00F5_MASTER_55_byte0bit3"

# Both 0xA0 bytes are inverted PWM duty: a bigger byte means a slower pump.
FIELD_GP1_DUTY = "00F5_MASTER_A0_byte0"
FIELD_GP2_DUTY = "00F5_MASTER_A0_byte1"

# Fields pushed to Home Assistant the instant they change, instead of waiting
# for the next timer tick -- compressor starts should not be delayed.
DISCRETE_FIELDS = frozenset(
    {
        FIELD_RELAYS_RAW,
        FIELD_COMPRESSOR,
        FIELD_HEATING_PUMP,
        FIELD_BRINE_PUMP,
        FIELD_THREE_WAY_VALVE,
        FIELD_OPERATING_MODE,
    }
)
