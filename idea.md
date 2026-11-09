### 1. Platform & Firmware Selection

The Pimoroni Presto is built around the Raspberry Pi RP2350 (or RP2040 depending on the model variation, my specific case is this one, I have one of the earliest models) paired with wireless connectivity, a capacitive touch display, an SD card slot, and onboard flash/RAM.

For this project, **CircuitPython** is significantly better suited than C++ or MicroPython for three reasons:

1. **Native USB HID:** `adafruit_hid` provides instant, plug-and-play USB keyboard emulation without custom descriptors.
2. **Dynamic Reloading:** Changes saved to the filesystem can automatically trigger a soft reload, letting you iterate quickly.
3. **Graphics & Touch Stack:** `displayio` makes rendering multi-page grids, caching icons, and tracking touch bounds straightforward.

---

### 2. Configuration Schema (Light Markdown)

Using basic Markdown headings and key-value bullet lists keeps parsing simple without requiring a heavy regex engine.

#### Sample `config.md`

```markdown
## Media

### Mute
- icon: /sd/icons/mute.bmp
- action: KEY_MUTE

### PlayPause
- icon: /sd/icons/play.bmp
- action: KEY_MEDIA_PLAY_PAUSE

## Dev Tools

### Run Tests
- icon: /sd/icons/test.bmp
- combo: GUI + SHIFT + T

### Terminal
- icon: /sd/icons/term.bmp
- text: npm start\n

```

#### Parsing Strategy

A lightweight line-by-line parser running on-device:

* Lines starting with `## ` define a new **Page / Deck**.
* Lines starting with `### ` define a **Button** inside the current deck.
* Lines starting with `- ` split on the first colon (`:`) to extract properties (`icon`, `action`, `combo`, `text`).
* Supports three trigger modes:
* `action`: Single HID usage code / media key (e.g., volume, play/pause).
* `combo`: Modifier-based shortcuts (e.g., `CTRL + C`, `GUI + ALT + R`).
* `text`: Raw string typing via keystroke sequence.



---

### 3. Display, Layout, and Touch Handling

1. **Grid Engine:**
* Define a fixed layout per page (e.g., a 2×3 or 3×4 grid depending on icon size and display resolution).
* Divide the screen into bounding boxes stored in memory alongside each button's assigned key sequence.


2. **Touch & Gestures:**
* **Tap:** If `touch_down` and `touch_up` occur within a button's bounding box without significant travel, fire the HID event.
* **Swipe / Horizontal Scroll:** If horizontal movement exceeds a threshold (e.g., $\Delta X > 40\text{px}$), transition pages by updating the visible `displayio.Group` rather than firing a button action.
* **Visual Feedback:** Invert or slightly dim the icon on touch press to confirm actuation before releasing.



---

### 4. Configuration Updates (Wireless & SD)

* **Direct SD Card:** Presto mounts the micro-SD card via SPI/SDIO. If present, it checks `/sd/config.md`; otherwise, it falls back to onboard flash (`/config.md`).
* **Wireless Editing:**
* Leverage the onboard Wi-Fi chip to run a lightweight local HTTP server (using `adafruit_httpserver` in CircuitPython).
* Host a minimal HTML page with a `textarea` that reads and overwrites `config.md` over your local network, enabling easy phone or browser edits without unmounting the SD card.



---

### 5. Web Bluetooth (Chrome Bridge)

Because the Presto's wireless module typically uses standard Wi-Fi/BLE co-processors, you have two options for bi-directional feedback:

* **BLE Mode:** Present a custom BLE GATT service that Chrome connects to using the Web Bluetooth API (`navigator.bluetooth`). Chrome writes state updates (e.g., microphone status, build state, unread counts) to an RX characteristic, which the display renders on top of the icons.
* **Alternative (WebHID / Serial):** If the device is already plugged in via USB for HID emulation, you can use the **WebHID API** or **Web Serial API** directly from Chrome. This avoids BLE complexity entirely, letting you stream events over the existing USB cable while running keyboard emulation concurrently.

---

### Recommended Staging

1. **Stage 1 (Core HID & Parser):** Get basic USB HID keypresses working and verify the `config.md` parser parses decks, buttons, and key chords into memory structures.
2. **Stage 2 (UI & Touch Navigation):** Render a static grid from the parsed config and implement swipe navigation across multiple pages.
3. **Stage 3 (Network Config & Two-Way Comms):** Add the local web config editor, followed by WebHID/Web Bluetooth for host-to-device feedback.