# Nibe Internal Bus for Home Assistant

A local-push custom integration that reads the **internal RS-485 bus** of a Nibe
heat pump — the link the pump's own components use to talk to each other — and
exposes what it carries as Home Assistant entities.

## Why this exists

There are plenty of projects and tools for reading the **external**
Modbus/RS-485 port that many Nibe devices have. I own an **F1226**, which has no
external Modbus/RS-485 port, and which officially has no support at all for
reading sensor data out of the device.

I still wanted its sensor data in Home Assistant. So instead I tapped into the
**internal** RS-485 bus that the heat pump's internal components use to
communicate with each other, decoded it, and built this.

The protocol is broadly similar to what the other Nibe heat pumps expose on
their external interface, but these are **not** processed temperature /
percentage / etc. values — they are **raw ADC and PWM values**, which this
integration converts (see [How the values are
interpreted](#how-the-values-are-interpreted)).

I suspect this could work with other Nibe heat pumps as well. Contributions are
welcome if you are able to test on another Nibe.

## Compatibility

| Model | Status |
| --- | --- |
| F1226 | Tested, all entities verified against the pump's own USB log export |

Nothing else has been tested. If you try another model, please open an issue
with a capture — see [Development](#development).

## ⚠️ Disclaimer

**This worked for me. It might not work for you.** Do your own research. Do not
trust my pinout — there may be different board revisions, different cable
colours, different models. You may break your heat pump if you do not know what
you are doing. There are no warranties of any kind, express or implied.

---

## Hardware installation

The mainboard sits behind the front panel:

![F1226 mainboard](f1226_main_board.jpg)

It has two similar connectors at the top, labelled **X5** and **X6**. They are
wired identically: one of them goes to the display module, and the other is free
and can be used for this.

![X5 and X6, one free and one going to the display](f1226_connectors_x5_and_x6.jpg)

| Pin | Signal | Colour on the display cable |
| --- | --- | --- |
| 1 | RS-485 D+ (A) | Black |
| 2 | RS-485 D− (B) | Brown |
| 5 | +12 V | Yellow |
| 6 | GND | Green |

The connector is similar to a PCI-Express GPU 6-pin power connector. I had a
spare cable from a modular PSU, which was a good fit:

![PSU cable plugged into the free connector](f1226_connected_gpu_power_cable.jpg)

I used pins **5 and 6** to power a [LilyGo
T-CAN485](https://github.com/Xinyuan-LilyGO/T-CAN485) board, and connected pins
**1 and 2** to the T-CAN485's RS-485 A/B terminals.

## Software installation

**1. Flash the ESP32.** Install ESPHome on the T-CAN485 with
[`esphome/lilygo-t-can485-passive.yaml`](esphome/lilygo-t-can485-passive.yaml),
which is included in this repository — edited from
[esphome-nibe](https://github.com/elupus/esphome-nibe) for a completely passive
setup. You will need a `secrets.yaml` alongside it with `wifi_ssid`,
`wifi_password`, `api_encryption_key` and `ota_password`, and the ESP32 should
have a static IP.

In this setup `esphome-nibe` must not transmit anything on the bus: the
`acknowledge:` list **must stay empty**, and there are no `constants:` or
`climate:` sections. That is what keeps everything — including this integration
— from ever putting a byte on the RS-485 bus.

**2. Install this integration.** HACS → Custom repositories → add this
repository as an **Integration**, install, restart, then **Settings → Devices &
services → Add integration → Nibe Internal Bus**.

**3. Connect.** Setup asks for the IP and port of your T-CAN485 (the `nibegw`
read port, 9999 by default). It then sends one trigger packet and waits up to 15
seconds for frames from bus address `00F5`; if none arrive, setup fails with a
specific reason rather than creating a device full of unavailable entities.

Once connected it decodes every signal I have been able to decode so far.

> This is not the same thing as the official
> [`nibe_heatpump`](https://www.home-assistant.io/integrations/nibe_heatpump/)
> integration. That one speaks the MODBUS40 accessory protocol over the external
> port. This one is a passive tap on an internal bus that is already there.

## How it stays connected

`nibegw` only forwards captured telegrams to hosts that have sent it a validly
framed request — that is how it learns where to send data. It then forgets a
target 120 seconds after that host's last request
(`NibeGwComponent.h: TARGET_TIMEOUT_MS = 120000`).

So this integration:

1. opens one UDP socket on an OS-assigned local port and **keeps it for the
   lifetime of the config entry** — the device registers the `(ip, port)` tuple,
   so a new source port would create a duplicate target;
2. sends the 4-byte trigger packet `C0 00 00 C0` immediately and then **every
   60 seconds**, i.e. at half the timeout.

That packet is a zero-length slave frame. It is tagged MODBUS40/READ\_TOKEN by
*which port it arrives on*, not by its content, and with `acknowledge:` empty it
is never dequeued onto the RS-485 bus. It is inert.

---

## Entities

### Temperatures

Eleven NTC sensors. The mainboard's own set comes in the `SLAVE 0x90` reply, the
EP14 cooling module's set in `SLAVE 0x91`.

| Entity | Frame / slot | Nibe register |
| --- | --- | --- |
| Outdoor temperature (BT1) | `90` slot 0 | 40004 |
| Hot water top (BT7) | `90` slot 1 | 40013 |
| Hot water bottom (BT6) | `90` slot 2 | 40014 |
| Supply line (BT2) | `90` slot 3 | 40008 |
| Condenser out (BT12) | `91` slot 0 | 40017 |
| Return line (BT3) | `91` slot 1 | 40012 |
| Brine out (BT11) | `91` slot 2 | 40016 |
| Brine in (BT10) | `91` slot 3 | 40015 |
| Hot gas (BT14) | `91` slot 4 | 40018 |
| Suction gas (BT17) | `91` slot 5 | 40022 |
| Liquid line (BT15) | `91` slot 6 | *not exported* |

These have been compared against the pump's own USB log export and agree with it
to within the ADC quantisation floor. They are not approximations.

### Pumps

| Entity | Source |
| --- | --- |
| Heating pump speed (GP1) | `MASTER 0xA0` byte 0 |
| Brine pump speed (GP2) | `MASTER 0xA0` byte 1 |
| GP1 raw duty byte | `MASTER 0xA0` byte 0, undecoded — diagnostic, disabled by default |

### States

| Entity | Source |
| --- | --- |
| Compressor | `MASTER 0x55` byte 0 bit 0 |
| Heating circulation pump | `MASTER 0x55` byte 0 bit 1 |
| Brine pump | `MASTER 0x55` byte 0 bit 2 |
| Three-way valve | `MASTER 0x55` byte 0 bit 3 |
| Operating mode | derived from the compressor, electrical addition and valve bits |
| Relay bitmask (PCA-Base) | `MASTER 0x55` byte 0 — diagnostic, disabled by default |
| Relay bitmask byte 1 | `MASTER 0x55` byte 1 — diagnostic, disabled by default |
| Relay byte 1 bit 2 / bit 3 | `MASTER 0x55` byte 1 bits 2 and 3, meaning unknown — diagnostic, disabled by default |
| Status reply 0x96 / 0x99 | `SLAVE 0x96` / `0x99` byte 0, meaning unknown — diagnostic, disabled by default |

### Electrical addition

| Entity | Source |
| --- | --- |
| Electrical addition | on when any addition relay is |
| Electrical addition power | sum of the switched-in relays' ratings, kW |
| Electrical addition energy | the power integrated over time, kWh |
| Electrical addition relay 1 kW, 2 kW A / B / C | `MASTER 0x55` byte 1 bit 1, byte 0 bit 6, byte 1 bit 0, byte 0 bit 4 — diagnostic, disabled by default |

The power is the relays' **nominal** rating, not a measurement, but it equals
the pump's own *Tot.Int.Add* (43084) on every row of its USB log export.

The energy sensor is meant for the Energy dashboard and needs no helper. It is
integrated here rather than left to a Riemann sum helper because the power is
a step function known exactly at every relay change, so the integral is exact.
The total survives restarts; time while Home Assistant is down, or while the
bus has been silent for over 60 seconds, is not counted.

There is deliberately no "last frame received" entity. Its value changes on
every bus cycle, which would write a database row every few seconds for
something that has no useful history. Liveness is already visible in the
entities themselves — they go unavailable once the bus goes quiet — and the
exact timestamp, frame counts and checksum error count are in the integration's
diagnostics download.

---

## How the values are interpreted

Framing, byte stuffing and everything known per command are written up in
[docs/protocol.md](docs/protocol.md). The one framing detail that affects
values: a `0x5C` byte inside a payload is sent doubled, and must be collapsed
back before the payload is read, or every ADC slot after it shifts by a byte.

### Temperatures are raw 10-bit ADC counts, not scaled numbers

This is the single thing that matters, and it is what makes every naive attempt
at reading this bus fail.

Each two-byte slot in the `0x90`/`0x91` replies is a **little-endian unsigned
10-bit thermistor ADC count**. The pump samples each sensor as a resistive
divider, so the count is proportional to the thermistor's *resistance*, not to
temperature. Temperature is a logarithmic function of it:

```
adc / 1023 = R / (R + R_fixed)
x          = ln(adc / (1023 - adc))        # = ln(R / R_fixed)
1/T[K]     = c0 + c1·x + c2·x² + c3·x³     # Steinhart-Hart style
°C         = 1/T[K] − 273.15

c = [0.003162333411, 0.000251402068, 1.485144801e-06, 1.11796736e-07]
```

Rough shape of the curve:

| adc | 20 | 120 | 250 | 400 | 550 | 700 | 850 | 950 | 1000 | 1023 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| °C | 182.6 | 102.8 | 74.0 | 54.6 | 39.3 | 24.7 | 7.2 | −11.3 | −31.5 | open |

The coefficients are physics, not curve-fitting: fitting each slot independently
against *different* reference registers yields Beta = 3998, 3984, 3991, 4004,
3908, 3920 K with T(x=0) = 43.09, 43.06, 43.00, 42.95, 43.32, 43.21 °C. Beta
≈ 3980 K is an ordinary NTC specification.

### Out-of-band raw values

| Raw | Meaning | What this integration does |
| --- | --- | --- |
| `1023` (`0x03FF`) | Full scale = **open circuit**, sensor not fitted or disconnected | entity goes `unavailable` |
| `1` | A digital flag sharing the slot layout, not a temperature | ignored |
| `0` | Short circuit | ignored |

`1023` is where the bogus **102.3** came from in earlier `s16/10` decodings. It
is not a sentinel constant the pump chose; it is the literal reading of an open
input. Slots 4–7 of the `0x90` reply and slot 7 of `0x91` are in this category.

### Pump speeds are inverted PWM duty

Both bytes of the `MASTER 0xA0` payload are **duty commands, inverted** — a
bigger byte means a *slower* pump, and `0x64` (100 %) stops it. This is the
normal Grundfos/Wilo "profile A" convention.

```
GP2 % = 100 − byte1
GP1 %: interpolated between the known settings below; 0 at 0x64 (stopped)
```

| GP1 byte | `0x20` | `0x2D` | `0x34` | `0x3B` | `0x64` |
| --- | --- | --- | --- | --- | --- |
| GP1 % | 70 | 50 | 40 | 30 | stopped |

GP2 is exact. GP1's settings do not lie on one straight line — the earlier
single-line fit read 70 % as 68.6 % and a stopped pump as −28.6 % — so speeds
between the known settings are interpolated. All the known settings match the
pump's own *GP1-speed* (43437). The raw byte is also available as the
disabled-by-default **GP1 raw duty byte** diagnostic entity, so further settings
can be added from recorder history.

### Relay bits

`MASTER 0x55`, LSB first. Byte 0 is the pump's own *Relays PCA-Base* (43514).

| Byte | Bit | Meaning |
| --- | --- | --- |
| 0 | 0 | Compressor |
| 0 | 1 | Heating circuit pump |
| 0 | 2 | Brine (collector) pump |
| 0 | 3 | Three-way valve — 0 = heating, 1 = hot water |
| 0 | 4 | Electrical addition 2 kW (C) |
| 0 | 6 | Electrical addition 2 kW (A) |
| 1 | 0 | Electrical addition 2 kW (B) |
| 1 | 1 | Electrical addition 1 kW |
| 1 | 2 | Unknown, always set |
| 1 | 3 | Unknown, set exactly when the brine pump runs |

Common values are `02 04` (idle: circulation only), `07 0C` (heating:
compressor and brine pump on, valve undiverted) and `0F 0C` (hot water:
everything on, valve diverted).

The pump steps the electrical addition up as 1, 2 (A), 2+1, 2+2 (A+B), 2+2+1
and 2+2+2 (A+B+C) kW, so

```
kW = 1·bit(1.1) + 2·bit(0.6) + 2·bit(1.0) + 2·bit(0.4)
```

### Operating mode is derived from the relay bits

`Prio` is **not transmitted as a value anywhere on this bus**, so the mode is
reconstructed from the bits that say whether the pump is producing anything
and where that production is going. The electrical addition sits before the
three-way valve, so it heats whichever side the valve feeds, with or without
the compressor:

| Compressor (0.0) or electrical addition on | Valve (0.3) | Mode |
| --- | --- | --- |
| no | either | Standby |
| yes | 0 | Heating |
| yes | 1 | Hot water |

The command the master polls — `0x96` or `0x99` — looks like it encodes this,
but it does not. It tracks the *compressor*, not the demand: across a 29 hour
capture the master polled `0x99` continuously through two half-hour runs with
byte 0 = `7`, i.e. compressor on with the valve set to heating, which is the
same command it polls during hot water production. `0x55` byte 1 bit 3 behaves
similarly: it follows the brine pump, which runs with the compressor.

A shorter earlier capture contained only idle and hot-water periods, which made
the `0x96`/`0x99` split look like a heating/hot-water distinction.

### Confidence

One value is marked **candidate** rather than confirmed, and is enabled anyway:

- **Liquid line (BT15)** — `0x91` slot 6 behaves exactly like a real sensor, and
  BT15 is the one EP14 sensor missing from the list, but it is absent from the
  pump's USB log export so it can never be checked against ground truth.

GP1 speed is exact only at the settings in the table above; in between it is an
interpolation.

### Update rate and availability

The bus cycles about once per second, which is far too fast to write into the
recorder. Temperatures and pump speeds are published on a timer (15 s by
default, 5–60 s in the integration's options). Relay bits, the valve, the
operating mode, the electrical addition and the `0x96`/`0x99` status replies
are published **the instant they change**, so compressor starts are not delayed
and short-lived states are not missed.

An entity becomes `unavailable` when the frame carrying it has not been seen for
60 seconds, or when its sensor reads open-circuit. Registration is maintained
independently of this, so recovery after a network blip needs no restart.

---

## Not decoded

Still unidentified on this bus, and deliberately left out:

- **`cmd 0x92`** — only slots 0 and 3 are populated and both are frozen
  (raw 178 ≈ 58 °C, raw 515 ≈ 42.7 °C); the rest read open. Probably setpoints.
- **`cmd 0x93`** — raw ~915–936 and ~11–16; the second is far outside any
  sensible NTC range, so these are probably not thermistors at all.
- **`cmd 0x85`, `cmd 0xEF`** — `0xEF` replies `0x0E` about every 40 s.
- **Address `00FC` cmd `0x55`** — payload is a constant `0xFF`, in bursts of
  three every ~5 s.
- **`0x55` byte 1 bits 2 and 3** — bit 2 is always set, bit 3 follows the brine
  pump. Exposed raw as diagnostics.
- **`cmd 0x96` / `0x99` replies** — normally `05` / `06`, flipping for a few
  seconds around compressor stops and starts. Exposed raw as diagnostics.

## Where the decoding rules live

[`custom_components/nibe_internal_bus/fields.py`](custom_components/nibe_internal_bus/fields.py)
says where each value sits on the bus; [docs/protocol.md](docs/protocol.md)
says why. Entity metadata — translation keys,
device classes, units — lives in `sensor.py` and `binary_sensor.py` and is joined
to those rules by a field identifier derived from each rule's position on the
bus, for example `00F5_SLAVE_91_ntc4`.

## Development

```
pip install -r requirements_test.txt
pytest
```

To capture raw bus traffic, for example to decode something new or to report
another model, uncomment the `packages:` include of
[`esphome/uart-debug.yaml`](esphome/uart-debug.yaml) in the ESPHome config and
reflash. Every received byte then appears in the device log as hex. Remove the
include again afterwards: it logs about ten lines a second. Capturing alongside
the pump's own USB log (menu 7.2) gives ground truth to compare against.

## License

MIT.

[`esphome/lilygo-t-can485-passive.yaml`](esphome/lilygo-t-can485-passive.yaml)
is adapted from [esphome-nibe](https://github.com/elupus/esphome-nibe), MIT,
Copyright (c) 2022 Joakim Plate.
