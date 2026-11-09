# Presto Touch HID

Presto transforms the Pimoroni Presto into a zero-latency USB macro deck with two-way Web Bluetooth connectivity. Touch a button to trigger native keyboard shortcuts, switch browser tabs, or archive email without lifting your hands from the keyboard. The device draws nothing while idle, lights up on the instant of contact, and syncs workspace state directly with your browser.

---

## Capabilities

The firmware turns the microcontroller into a composite USB device that presents both a CDC serial interface and a native USB HID keyboard.

- **Instant Touch-Down Actuation**: Buttons actuate and flash visually on the exact frame your finger touches the glass.
- **Dirty Redrawing Only**: The screen redraws only when a button state changes or a notification arrives, consuming zero CPU cycles while idle.
- **Colemak Physical Translation**: Keyboard shortcut combinations translate Colemak key positions into physical QWERTY scancodes so your operating system receives the correct keys.
- **Two-Way Web Bluetooth**: The Nordic UART Service streams touchscreen taps to host applications and receives live deck switches and unread count badges.
- **On-Device Wi-Fi AP Editor**: The device hosts its own Wi-Fi access point and Microdot web server, letting you edit `config.md` directly from your phone or laptop.
- **Header Navigation**: Tapping the top-left switches to the previous deck, the top-right switches to the next deck, and the center opens settings.

---

## Hardware Requirements

- **Pimoroni Presto**: Powered by the Raspberry Pi RP2350 (specifically the RP2350B package with dual Cortex-M33 cores, 48 GPIOs, and 8MB PSRAM), featuring a 240×240 pixel ST7701 display, FT6236 capacitive touchscreen, and CYW43439 wireless radio.
- **USB-C Cable**: High-speed data cable connected directly to your host machine.
- **Web Bluetooth Host**: Google Chrome (version 115+) or any BLE client supporting the Nordic UART Service.
- **Host Tools**: [`uv`](https://docs.astral.sh/uv/) for Python project management.

---

## Directory Structure

```text
presto/
├── pyproject.toml        # Python project configuration (managed by uv)
├── boot.py               # Early boot script initializing USB HID keyboard
├── main.py               # Core firmware (display, touch, BLE GATT server, HID)
├── config.md             # Deck definitions, button actions, and hardware options
├── lib/
│   └── microdot.py       # Lightweight Microdot HTTP server (MIT License)
└── presto-bt/            # Practical example: companion Chrome extension
    ├── manifest.json     # Chrome extension manifest (Manifest V3)
    ├── background.js     # Toolbar icon click handler
    ├── bridge.js         # Web Bluetooth connection and tab synchronization
    ├── index.html        # Extension manager dashboard
    └── styles.css        # Dashboard interface styles
```

---

## Device Installation

Use `uv` to install dependencies and flash the device firmware over USB.

1. Install project dependencies using `uv`:
   ```bash
   uv sync
   ```
2. Put the Presto board into bootloader mode by holding the BOOT button while inserting the USB cable.
3. Copy the Pimoroni Presto MicroPython firmware image (`.uf2`) to the mounted `RPI-RP2` volume.
4. Wait for the board to reboot and expose its USB serial port.
5. Copy the library dependencies to the board:
   ```bash
   uv run mpremote connect /dev/cu.usbmodem11201 cp -r lib :
   ```
6. Copy the bootloader script:
   ```bash
   uv run mpremote connect /dev/cu.usbmodem11201 cp boot.py :
   ```
7. Copy the deck configuration file:
   ```bash
   uv run mpremote connect /dev/cu.usbmodem11201 cp config.md :
   ```
8. Copy the main application script:
   ```bash
   uv run mpremote connect /dev/cu.usbmodem11201 cp main.py :
   ```
9. Reset the board:
   ```bash
   uv run mpremote connect /dev/cu.usbmodem11201 reset
   ```

---

## Example Extension (`presto-bt`)

The included Chrome extension (`presto-bt`) serves as a practical reference example showing how external applications can extend the Presto over Web Bluetooth. It connects to the Presto via the Nordic UART Service, monitors active tabs, updates button labels with live Gmail unread counts, and focuses target tabs upon button presses. Any web application, native daemon (e.g. using Python `bleak`), or browser extension can communicate with Presto using the same protocol.

To run the example Chrome extension:

1. Open Google Chrome.
2. Go to the extensions management page: `chrome://extensions`.
3. Set the **Developer mode** toggle in the top-right corner to **On**.
4. Click **Load unpacked**.
5. Select the `presto-bt` directory in this repository.
6. Click the `Presto BT Deck Bridge` icon in the Chrome toolbar to open the manager dashboard.
7. Click **Connect Presto** and pair with the device.

---

## Deck Configuration (`config.md`)

Decks and global hardware settings live in plain text within `config.md`.

### Global Settings

Place global settings as bullet points at the top of `config.md`:

```markdown
- brightness: 12%
- layout: colemak
```

### Decks and Buttons

Define decks with level-2 headings (`##`) and individual buttons with level-3 headings (`###`). Each button supports one of three action types:

```markdown
## Workspace

### Terminal
- label: Terminal
- combo: HYPER + T

### Gmail
- label: Gmail
- bt: jump_tab:mail.google.com

### Git Status
- label: Git Status
- text: git status\n
```

- **`combo`**: Sends physical key combinations with modifiers (`CTRL`, `SHIFT`, `ALT`, `GUI`, or `HYPER` for `CTRL+ALT+GUI+SHIFT`).
- **`text`**: Sends raw text strings sequentially through the USB keyboard interface.
- **`bt`**: Emits a notification payload over Web Bluetooth to any connected client.

---

## Web Bluetooth Protocol

Presto implements the standard Nordic UART Service (NUS) over Bluetooth Low Energy.

- **Service UUID**: `6e400001-b5a3-f393-e0a9-e50e24dcca9e`
- **RX Characteristic (`6e400002-...`)**: Host writes compact UTF-8 strings without response.
- **TX Characteristic (`6e400003-...`)**: Presto emits JSON touch events via GATT notifications.

### Supported RX Commands (Host → Presto)

Commands stay below 20 bytes to fit into a standard single-packet BLE ATT Maximum Transmission Unit:

| Command | Example | Description |
| :--- | :--- | :--- |
| `deck:<name>` | `deck:Gmail` | Switches the visible deck to the first matching title |
| `badge:<count>` | `badge:3` | Updates the Gmail button label to `Gmail (3)` and sets its color to amber |
| `btn:<id>:<label>[:<color>]` | `btn:mute:Unmute:alert` | Dynamically updates a specific button label and color |
| `clear` | `clear` | Clears any active alert banner from the header |

---

## On-Device Wi-Fi Config AP

To edit configuration without a USB connection:

1. Tap the center of the Presto header to enter the Settings screen.
2. Tap **Wi-Fi Config AP**.
3. Scan the displayed QR code with your phone camera to connect to the `Presto-Config` network.
4. Navigate to `http://192.168.4.1` in your browser.
5. Modify `config.md` inside the text area.
6. Tap **Save & Reboot** to write changes to flash and reload the deck.

---

## Licenses & Third-Party Code

- **Presto Firmware & Extension**: MIT License.
- **Microdot (`lib/microdot.py`)**: Copyright (c) 2022 Miguel Grinberg, licensed under the MIT License.
