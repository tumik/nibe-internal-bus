# Internal bus protocol notes

What has been worked out about the F1226's internal RS-485 bus, from passive
captures checked against the pump's own USB log export. These are observations,
not a specification: anything not listed under a confirmed meaning is a guess.

The bus runs at 9600 baud, 8N1. See the [README](../README.md) for where to tap
it.

## Frames

The base board's display unit is the bus master. It polls one command at a
time, and the addressed board replies:

```
master:  5C 00 <addr> <cmd> <len> <data …> <chk>
slave:   C0 <cmd> <len> <data …> <chk>
         06                                  ACK from the master, rarely 15 (NAK)
```

- The master's checksum is the XOR of every byte after the `5C` up to the last
  data byte. The slave's includes its `C0`.
- A checksum that works out as `5C` is sent as `C5` instead.
- A slave reply carries no address; it belongs to the master frame just before
  it.

### Byte stuffing

A `5C` inside the data would look like the start of a new frame, so it is sent
doubled, `5C 5C`. Both the length byte and the checksum count the bytes **as
sent**, doubling included. Example, a 16-byte ADC reply whose first value is
`0x015C`:

```
C0 91 11 5C 5C 01 91 01 6E 03 5D 03 86 00 41 03 8D 01 01 00 AB
      ^^ 17 bytes on the wire          16 bytes of data after unescaping
```

So a frame is cut and checksummed on the raw bytes, and only then is each
`5C 5C` in its data collapsed back into one `5C`. This held for all of the
~1 260 stuffed frames in a 5.6 hour capture; in that capture a stuffed `5C`
only ever appeared in slave replies.

The esphome-nibe gateway frames the same way, so the datagrams it forwards
contain whole frames with the doubling still in place.

## Addresses and cycle

| Address | What it is |
| --- | --- |
| `00F5` | The base board. Everything decoded so far is here. |
| `00FC` | Only ever sent command `55` with one data byte, always `FF`, in bursts of three every ~5 s. |

The master repeats a cycle of roughly one second: `A0`, `55`, then `96` or
`99` (now and then `EF` instead), `90`, `91`, `92`, `93`, `85`.

## Commands to `00F5`

### `55` — relay outputs (master, 2 bytes)

Byte 0 is exactly the **Relays PCA-Base** value (register 43514) in the USB log;
it matched on every one of 2 635 log rows compared.

| Byte.bit | Meaning | Confidence |
| --- | --- | --- |
| 0.0 | Compressor | confirmed |
| 0.1 | GP1 heating circuit pump | confirmed |
| 0.2 | GP2 brine (collector) pump | confirmed |
| 0.3 | QN10 3-way valve, 0 = heating, 1 = hot water | confirmed |
| 0.4 | Electrical addition, 2 kW (third step) | confirmed |
| 0.6 | Electrical addition, 2 kW (first step) | confirmed |
| 1.0 | Electrical addition, 2 kW (second step) | confirmed |
| 1.1 | Electrical addition, 1 kW | confirmed |
| 0.5 | AA1-K5 relay output, function not identified | firmware |
| 0.7 | AA1-K7 relay output, function not identified | firmware |
| 1.2 | Inverted alarm output, set while there is no alarm | inferred |
| 1.3 | "GP2 speed != 0", a copy of 0.2 | firmware |
| 1.4 | Hot water circulation request (register 43180) | firmware |

The pump steps its 7 kW immersion heater up through these relays:

| kW | Relays on | Example payload |
| --- | --- | --- |
| 1 | 1.1 | `0A 06` |
| 2 | 0.6 | `4A 04` |
| 3 | 0.6, 1.1 | `4A 06` |
| 4 | 0.6, 1.0 | `4A 05` |
| 5 | 0.6, 1.0, 1.1 | `4A 07` |
| 6 | 0.6, 1.0, 0.4 | `5A 05` |

That is `kW = 1·bit(1.1) + 2·bit(0.6) + 2·bit(1.0) + 2·bit(0.4)`, which equals
**Tot.Int.Add** (register 43084) on every row compared. Seven kilowatts (all
four relays) was not seen because the pump under test limits the addition to
6 kW. The figure is the relays' nominal rating; actual power varies with the
mains voltage.

Other payloads seen: `02 04` idle, `07 0C` heating on the compressor, `0F 0C`
hot water on the compressor, `0E 0C` brine pump alone just before a compressor
start or just after a stop.

### `A0` — pump PWM duty (master, 2 bytes)

Both bytes are inverted PWM duty: a bigger byte is a slower pump, `64` (100)
stops it and `00` is full speed. The display derives the byte from the pump
type with a piecewise linear curve:

```
0 %   -> 100;  100 % -> 0;  else  A + trunc((p - 1) * (B - A) / 98)
```

| Byte | Pump | Type | A, B | Known values |
| --- | --- | --- | --- | --- |
| 0 | GP1 heating circuit | `0F` Grundfos UPM2 25-75 | 77, 13 | `20` = 70 %, `2D` = 50 %, `34` = 40 %, `3B` = 30 %, `64` = stopped |
| 1 | GP2 brine | `0E` Grundfos UPM Geo 25-85 | 77, 10 | `64` = stopped |

The pump types above are those of the F1226 used here; other serial ranges use
other types (curves in `pump.py`). A byte of `FF` marks a pump type with no PWM
curve, i.e. unknown speed. The inverse is exact to ±1 %, since adjacent
percentages can share a duty byte. The four GP1 values match **GP1-speed**
(43437) in the USB log.

### `90`–`93` — analogue inputs (slave replies)

Little-endian 16-bit words holding raw 10-bit ADC counts: eight per reply for
`90`–`92`, three for `93`. `03FF` is an open (unconnected) input. Temperatures
are NTC thermistors; the conversion (the display firmware's lookup table) is in the README.

| Reply | Word | Sensor | Register |
| --- | --- | --- | --- |
| `90` | 0 | BT1 outdoor | 40004 |
| `90` | 1 | BT7 hot water top | 40013 |
| `90` | 2 | BT6 hot water bottom | 40014 |
| `90` | 3 | BT2 supply | 40008 |
| `91` | 0 | BT12 condenser out | 40017 |
| `91` | 1 | BT3 return | 40012 |
| `91` | 2 | BT11 brine out | 40016 |
| `91` | 3 | BT10 brine in | 40015 |
| `91` | 4 | BT14 hot gas | 40018 |
| `91` | 5 | BT17 suction gas | 40022 |
| `91` | 6 | BT15 liquid line (probably) | not logged |
| `91` | 7 | always `0001`, a flag rather than a reading | — |

Words that are not thermistors:

| Reply | Word | Meaning | Register |
| --- | --- | --- | --- |
| `93` | 0 | HP (high pressure) input, alarm when raw < 300 | 40052 |
| `91` | 7 | LP (low pressure) input, alarm when raw > 300 | 40053 |
| `92` | 0 | TB (temperature limiter) input, alarm when raw > 300 | 40054 |
| `92` | 3 | spare, nothing in the firmware reads it | — |
| `93` | 1 | spare, nothing in the firmware reads it | — |

Idle values: HP about 932, LP 1, TB 181. `90` and `91` are both input blocks of
the PCA Base (node `F5`), not of a separate cooling module.

### `96` / `99` — status (slave replies, 1 byte)

The master polls `96` while the compressor is off and `99` while it runs,
without exception in the capture.

| Reply | Normally | Transient |
| --- | --- | --- |
| `96` | `05` | `06` for ~7 s when the compressor stops |
| `99` | `06` | `05` for ~7–15 s when the compressor starts |

Both carry the soft-starter / compressor-protection status (register 43443):

| Code | Meaning | Display alarm |
| --- | --- | --- |
| 5 | stopped | — |
| 6 | running | — |
| 7 | soft start in progress | 175 |
| 1 / 2 / 3 | phase 1 / 2 / 3 missing | 40 / 41 / 42 |
| 4 | wrong phase sequence | 43 |
| 8 | motor protection | 54 |
| 9 | soft starter overheated | 44 |
| `FE` | phase fault | 45 |

Codes 5 and 6 are the only ones seen on the bus; the others come from the
display firmware. 7F is the display's internal "no reply" marker.

### Handshake bytes

After a frame the receiver sends `06` (ACK) or `15` (NAK). The ACK following a
master request comes from the PCA Base, the one following a PCA Base reply from
the display. The integration ignores frames that were NAKed (the receiver did
not accept them) and resynchronises when a corrupt length byte would otherwise
swallow the next good frame. Frames never answered at all, like the `55` sent to
the absent node `FC`, carry no handshake byte.

### `85`, `EF`

Not decoded. `EF` replies `0E`.

## Not on the bus

Everything the display computes for itself never appears in a frame: degree
minutes, the priority / operating mode, the calculated supply temperature,
setpoints, comfort mode and alarms. An alarm such as 163 (high condenser in)
only shows up indirectly, as the relays switching off.
