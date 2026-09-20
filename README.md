# ESP32 433 MHz RF Bridge

A Home Assistant custom integration for controlling and monitoring 433.92 MHz
RF outlets through an ESPHome and CC1101 bridge.

The integration was built and tested with Nexa learning-code outlets and Harju
outdoor outlets. It provides:

- one Home Assistant switch and device per RF-controlled outlet
- generated Nexa or Harju transmit codes
- one searchable ESPHome V2 transmit-action selector
- learning of multiple incoming Nexa ON and OFF codes per switch
- Nexa all-off learning
- inferred switch state updates when a physical remote is used
- deletion of switches and learned-code lists from the device page

The displayed state is inferred from transmitted and received RF commands. The
outlet itself does not send state feedback.

## Requirements

- Home Assistant 2026.8.0 or newer
- HACS for the recommended installation method
- an ESPHome device with a compatible 433.92 MHz receiver/transmitter
- the tested setup uses an ESP32-C3, CC1101, ASK/OOK modulation and the pinout
  in [`examples/esphome-esp32-433mhz-rf-bridge.yaml`](examples/esphome-esp32-433mhz-rf-bridge.yaml)

The included ESPHome configuration is hardware-specific. Verify the board,
pins, radio module and secrets before flashing it to another device.
[`examples/secrets.example.yaml`](examples/secrets.example.yaml) lists the
required secret names. Reuse the existing ESPHome API encryption key when
renaming an installed device.

## Install with HACS

1. Open HACS in Home Assistant.
2. Open the menu and choose **Custom repositories**.
3. Add `https://github.com/KakeW/ha-esp32-433mhz-rf-bridge` as an
   **Integration** repository.
4. Install **ESP32 433 MHz RF Bridge**.
5. Restart Home Assistant.
6. Open **Settings > Devices & services > Add integration** and select
   **ESP32 433 MHz RF Bridge**.

HACS manages future integration updates after this installation.

## Upgrade from integration V1 to V2

V2 keeps the existing Home Assistant storage key, switch record IDs, generated
transmit codes, learned Nexa codes, inferred states and Harju polarity setting.
No outlet pairing or remote learning is required again.

The upgrade can be installed in either order:

1. Update the Home Assistant integration. Until the firmware is updated, it
   automatically falls back to the two V1 protocol-specific ESPHome actions.
2. Replace the ESPHome configuration with the current file in `examples/` and
   install it. The firmware exposes the unified `transmit_rf` V2 action and
   retains the two V1 actions as compatibility aliases.
3. Restart Home Assistant or reload both ESPHome and ESP32 433 MHz RF Bridge.
4. Open the integration options and confirm that **ESPHome transmit action** is
   `esphome.esp32_433mhz_rf_bridge_transmit_rf`.
5. Test one existing Nexa outlet, one existing Harju outlet and a Nexa remote
   command before creating new outlets.

The V2 firmware sends received Nexa codes directly to Home Assistant. It no
longer exposes the old `Last RF code` entity as a second receive path. Harju
remote reception is intentionally disabled because Harju outlets are managed as
Home Assistant-only controls.

## Migrate from ESP32 valo-ohjaus

Version 1.0.0 changes the integration domain from `esp32_valo_ohjaus` to
`esp32_433mhz_rf_bridge`. The new integration includes a one-time guided
migration.

Before starting, create a Home Assistant backup and leave the old integration
installed and configured.

1. Install the new repository through HACS and restart Home Assistant.
2. Add **ESP32 433 MHz RF Bridge** from **Settings > Devices & services**.
3. Home Assistant detects the old config entry and shows **Migrate legacy
   installation**.
4. Confirm the migration and wait for the new integration to load.
5. Verify that the existing switches still work and retain their entity IDs.
6. Follow **Rename an existing ESPHome node** below, then install the current
   example YAML.
7. Remove `/config/custom_components/esp32_valo_ohjaus` only after the new
   integration works and Home Assistant has been restarted successfully.

The migration copies the RF switch storage and moves the existing Home
Assistant entity and device registry entries to the new config entry. Existing
entity IDs, device IDs, areas, names and registry customizations are preserved.
The old storage file is deliberately retained as a rollback backup.

Automations that directly call an integration action must use the new domain:

```text
esp32_valo_ohjaus.*          -> esp32_433mhz_rf_bridge.*
esp32_valo_ohjaus_received   -> esp32_433mhz_rf_bridge_received
```

## Manual installation

Copy the integration directory to:

```text
/config/custom_components/esp32_433mhz_rf_bridge
```

Restart Home Assistant and add the integration from **Settings > Devices &
services**.

## Configure the bridge

The setup and options flow contains:

- **ESPHome transmit action**: the unified V2 action used for Nexa and Harju
  transmissions
- **Transmitter ID**: the six-hex-digit Nexa transmitter identifier
- **First virtual channel**: the first generated logical channel

The transmit-action field searches Home Assistant's action registry. The
integration passes the correct protocol and code automatically for each outlet.
Nexa receive codes are delivered directly from ESPHome to the integration, so
there is no separate receive-entity setting in V2.

The current example uses English identifiers throughout:

```text
ESPHome node:      esp32-433mhz-rf-bridge
Transmit action:  esphome.esp32_433mhz_rf_bridge_transmit_rf
```

Select the actual entities and actions shown by your ESPHome device. Their IDs
can differ depending on the ESPHome node name and Home Assistant entity naming.

Some Harju outlet revisions interpret generated ON/OFF command pairs with the
opposite polarity. Each Harju switch device therefore includes a **Swap
transmitted ON/OFF codes** button. It changes only commands sent to the outlet;
learned remote-control codes are left unchanged.

Harju outlets are exposed as Home Assistant-only controls. Remote-learning
buttons and learned-code sensors are only created for Nexa switches. The bridge
creation controls are presented as outlet type, outlet name, and create outlet.

### Rename an existing ESPHome node

Do not replace `name: valojen-ohjaus` and immediately run a normal OTA install:
the new hostname does not exist until that first upload succeeds.

In ESPHome Device Builder, open the existing device menu and choose **Rename
device**. Rename it from `valojen-ohjaus` to `esp32-433mhz-rf-bridge`. The online
rename flow compiles the new configuration and uploads it to the old address.
After the rename finishes, replace the configuration with
`examples/esphome-esp32-433mhz-rf-bridge.yaml` and run a normal wireless install.
Rename the existing API-key entry in `secrets.yaml` to
`esp32_433mhz_rf_bridge_api_key`, but keep its value unchanged.

The integration recognizes the two V1 ESPHome transmit actions during the V2
transition. The example firmware also keeps those actions as aliases. Existing
outlets, generated transmit codes, learned Nexa codes, entity IDs and device
IDs remain unchanged when upgrading from integration V1 to V2.

## Create an RF switch

Open the main integration device:

1. Set **New RF switch protocol** to `Nexa` or `Harju`.
2. Enter a value in **New RF switch name**.
3. Press **Create RF switch**.

The switch is created as a separate Home Assistant device with its own toggle,
learning controls, learned-code sensors and delete button.

You can also use the action directly:

```yaml
action: esp32_433mhz_rf_bridge.create_switch
data:
  name: Star light
  protocol: nexa
```

To pair an outlet, put the outlet in pairing mode and toggle the new Home
Assistant switch. The tested Harju channel B reference pair is:

```text
ON  = 111111011011110100000101
OFF = 111111110101011111010101
```

New Harju switches use the next free virtual channel and do not reuse this pair.

## Learn physical remote codes

Open the target switch device and press **Add incoming ON code**, then press the
wanted ON button on the physical remote. Repeat with **Add incoming OFF code**.

Several physical remote codes can be attached to one logical switch. Use
**Clear incoming ON codes** or **Clear incoming OFF codes** if a code was learned
in the wrong direction.

The main bridge device provides **Learn Nexa all off**. Harju outlets are
Home Assistant-only controls and do not expose remote-learning actions.

For Nexa, learning finishes after the first valid pair-coded command. Learning
an ON code removes the same code from the switch's learned OFF list, and vice
versa.

## Receive RF codes

The V2 firmware decodes Nexa 16-character hexadecimal codes, removes duplicate
RF repeats from one button press, and calls the integration action directly:

```yaml
action: esp32_433mhz_rf_bridge.receive_code
data:
  code: "66695AA6A5559655"
```

For that method, enable **Allow the device to perform Home Assistant actions**
in the ESPHome device settings.

The integration also accepts the event `esp32_433mhz_rf_bridge_received` with a
`code` field.

## Protocol notes

Confirmed Nexa examples from the tested remote:

```text
1 ON     = 66695AA6A5559655 -> decoded 0x563DC090
1 OFF    = 66695AA6A5559555 -> decoded 0x563DC080
4 ON     = 66695AA6A555965A -> decoded 0x563DC093
4 OFF    = 66695AA6A555955A -> decoded 0x563DC083
ALL OFF  = 66695AA6A5559955 -> decoded 0x563DC0A0
```

The Nexa generator uses the observed suffixes `0x8F + channel` for ON and
`0x7F + channel` for OFF, then pair-codes each bit as `0 -> 01` and `1 -> 10`.

The Harju implementation is based on a codebook of observed A, B, C and ALL
command families. It does not claim a general rolling-code algorithm or support
for every Harju-branded remote.

## Development

Run the lightweight test suite without a Home Assistant development checkout:

```bash
python3 tests/test_protocol.py
python3 tests/test_harju_runtime.py
python3 tests/test_migration.py
```

## License

MIT
