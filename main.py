"""
Presto Touch HID - Main Firmware
Features:
- Instant touch-down actuation (zero lag)
- Dirty redrawing only (zero CPU/display overhead when idle)
- Clean header: displays workspace title (virtual zones: left=prev, center=settings, right=next)
- Settings menu: Theme, Brightness, and Wi-Fi Web Config AP
- Wi-Fi Access Point with iOS Wi-Fi QR Code & browser-based config.md editor
- Colemak keycode translation & configurable brightness
"""

import time
import os
import socket
import network
import asyncio
import json
import bluetooth
import aioble
from presto import Presto
import usb.device
from usb.device.keyboard import KeyCode
import qrcode
from microdot import Microdot, Response

# ---------------------------------------------------------
# BLE GATT Service Setup (Nordic UART Service)
# ---------------------------------------------------------
UART_SERVICE_UUID = bluetooth.UUID("6E400001-B5A3-F393-E0A9-E50E24DCCA9E")
UART_RX_CHAR_UUID = bluetooth.UUID("6E400002-B5A3-F393-E0A9-E50E24DCCA9E")
UART_TX_CHAR_UUID = bluetooth.UUID("6E400003-B5A3-F393-E0A9-E50E24DCCA9E")

print("[BLE INIT] Registering Nordic UART Service...")
uart_service = aioble.Service(UART_SERVICE_UUID)
rx_char = aioble.Characteristic(uart_service, UART_RX_CHAR_UUID, write=True, write_no_response=True)
tx_char = aioble.Characteristic(uart_service, UART_TX_CHAR_UUID, read=True, notify=True)
aioble.register_services(uart_service)
print("[BLE INIT] Nordic UART Service registered successfully")

ble_connected = False
ble_connection = None
active_notification = None
current_time_str = ""
deck_needs_redraw = False
ble_enabled = True
event_accumulator = []

current_page_idx = 0
page_active = True
pages = []

def ble_send(data_str):
    global ble_connection, tx_char
    if ble_connection and tx_char:
        try:
            print("[BLE TX] Sending notification:", data_str)
            tx_char.notify(ble_connection, data_str.encode("utf-8"))
            print("[BLE TX] Notification sent successfully")
        except Exception as e:
            print("[BLE TX ERROR] Failed to send notification:", repr(e))
    else:
        print("[BLE TX WARN] Cannot send, not connected (conn={}, tx={})".format(ble_connection, tx_char))

async def ble_rx_worker(connection):
    global active_notification, current_time_str, deck_needs_redraw, current_page_idx, page_active, pages, event_accumulator
    print("[BLE RX] Worker listening for connection:", connection)
    while True:
        try:
            conn = await rx_char.written()
            if conn != connection:
                continue
            data = rx_char.read()
            if not data:
                continue

            try:
                raw_msg = str(data, "utf-8")
            except Exception as dec_err:
                print("[BLE RX ERROR] UTF-8 decode failed:", repr(dec_err))
                continue

            msg = raw_msg.strip()
            print("[BLE RX MSG RECEIVED]: raw={!r}".format(raw_msg))

            # Compact commands (guaranteed to fit in single 20-byte BLE MTU packet)
            if msg.startswith("deck:") or msg.startswith("switch_deck:"):
                target = msg.split(":", 1)[1].strip().lower()
                print("[BLE RX ACTION] Switch deck to: {!r}".format(target))
                matched = False
                for p_idx, p in enumerate(pages):
                    if target in p.get("title", "").lower():
                        current_page_idx = p_idx
                        page_active = False  # Switch current deck immediately!
                        deck_needs_redraw = True
                        matched = True
                        print("[BLE RX ACTION] Switched to deck index {}: {!r}".format(p_idx, p.get("title")))
                        break
                if not matched:
                    print("[BLE RX ACTION WARN] No deck matching {!r} found in pages".format(target))

            elif msg.startswith("badge:"):
                parts = msg.split(":")
                if len(parts) >= 3:
                    app_name = parts[1].strip().lower()
                    count_str = parts[2].strip()
                else:
                    app_name = "gmail"
                    count_str = parts[1].strip()

                try:
                    count = int(count_str)
                except Exception:
                    count = 0

                print("[BLE RX ACTION] Set badge: app={!r}, count={}".format(app_name, count))
                for p in pages:
                    for b in p.get("buttons", []):
                        b_id = b.get("id", "").lower()
                        b_lbl = b.get("label", "").lower()

                        is_match = False
                        if app_name in ("gmail", "mail"):
                            is_match = "gmail" in b_id or "gmail" in b_lbl
                            base_label = "Gmail"
                        elif app_name in ("wa", "whatsapp"):
                            is_match = "whatsapp" in b_id or "wa" in b_id or "wa" in b_lbl or "whatsapp" in b_lbl
                            base_label = "WA"
                        else:
                            is_match = app_name in b_id or app_name in b_lbl
                            base_label = b.get("label", app_name)

                        if is_match:
                            if count > 0:
                                b["label"] = "{} ({})".format(base_label, count)
                                b["color"] = "alert"
                            else:
                                b["label"] = base_label
                                b["color"] = None
                            deck_needs_redraw = True
                            print("[BLE RX ACTION] Updated button: label={!r}, color={!r}".format(b["label"], b.get("color")))

            elif msg.startswith("btn:"):
                parts = msg.split(":")
                if len(parts) >= 3:
                    btn_id = parts[1].strip().lower()
                    new_lbl = parts[2].strip()
                    new_col = parts[3].strip() if len(parts) >= 4 else None
                    print("[BLE RX ACTION] Update button {!r} -> label={!r}, color={!r}".format(btn_id, new_lbl, new_col))
                    for p in pages:
                        for b in p.get("buttons", []):
                            if btn_id in b.get("id", "").lower() or btn_id in b.get("label", "").lower():
                                b["label"] = new_lbl
                                b["color"] = new_col if new_col and new_col != "none" else None
                                deck_needs_redraw = True

            elif msg.startswith("time:"):
                t_str = msg.split(":", 1)[1].strip()
                if len(t_str) >= 4 and t_str != current_time_str:
                    current_time_str = t_str
                    deck_needs_redraw = True
                    print("[BLE RX ACTION] Time updated:", current_time_str)

            elif raw_msg.startswith("event:+"):
                chunk = raw_msg[7:]
                event_accumulator.append(chunk)
                print("[BLE RX ACTION] Event chunk appended: {!r}, accumulated chunks={}".format(chunk, len(event_accumulator)))

            elif msg == "event:eof":
                full_evt = "".join(event_accumulator).replace("\\n", "\n").strip()
                event_accumulator = []
                print("[BLE RX ACTION] Event EOF received, full text: {!r}".format(full_evt))
                is_clear = (not full_evt) or (full_evt.lower() in ("clear", "none"))

                for p in pages:
                    for b in p.get("buttons", []):
                        b_id = b.get("id", "").lower()
                        b_lbl = b.get("label", "").lower()
                        b_def_lbl = b.get("default_label", "").lower()
                        if "cal" in b_id or "calendar" in b_id or "cal" in b_lbl or "cal" in b_def_lbl:
                            if "default_label" not in b:
                                b["default_label"] = b.get("label", "Cal")
                            if is_clear:
                                b["label"] = b["default_label"]
                                b["color"] = None
                            else:
                                b["label"] = full_evt
                                b["color"] = "event"
                            deck_needs_redraw = True
                            print("[BLE RX ACTION] Calendar button updated: label={!r}, color={!r}".format(b["label"], b.get("color")))

            elif msg == "event:clear":
                event_accumulator = []
                print("[BLE RX ACTION] Event clear received")
                for p in pages:
                    for b in p.get("buttons", []):
                        b_id = b.get("id", "").lower()
                        b_lbl = b.get("label", "").lower()
                        b_def_lbl = b.get("default_label", "").lower()
                        if "cal" in b_id or "calendar" in b_id or "cal" in b_lbl or "cal" in b_def_lbl:
                            if "default_label" not in b:
                                b["default_label"] = b.get("label", "Cal")
                            b["label"] = b["default_label"]
                            b["color"] = None
                            deck_needs_redraw = True
                            print("[BLE RX ACTION] Calendar button cleared: label={!r}".format(b["label"]))

            elif msg.startswith("event:"):
                # Single-packet backward compatibility
                event_accumulator = []
                raw_evt = msg.split(":", 1)[1].strip()
                evt_text = raw_evt.replace("\\n", "\n")
                is_clear = (not evt_text) or (evt_text.lower() in ("clear", "none"))
                print("[BLE RX ACTION] Event update: is_clear={}, text={!r}".format(is_clear, evt_text))

                for p in pages:
                    for b in p.get("buttons", []):
                        b_id = b.get("id", "").lower()
                        b_lbl = b.get("label", "").lower()
                        b_def_lbl = b.get("default_label", "").lower()
                        if "cal" in b_id or "calendar" in b_id or "cal" in b_lbl or "cal" in b_def_lbl:
                            if "default_label" not in b:
                                b["default_label"] = b.get("label", "Cal")
                            if is_clear:
                                b["label"] = b["default_label"]
                                b["color"] = None
                            else:
                                b["label"] = evt_text
                                b["color"] = "event"
                            deck_needs_redraw = True
                            print("[BLE RX ACTION] Calendar button updated: label={!r}, color={!r}".format(b["label"], b.get("color")))

            # Standard JSON commands fallback
            elif msg.startswith("{") and msg.endswith("}"):
                try:
                    payload = json.loads(msg)
                    cmd = payload.get("command")
                    print("[BLE RX JSON CMD]", cmd, payload)
                    if cmd == "switch_deck":
                        deck_name = payload.get("name", "").lower()
                        for p_idx, p in enumerate(pages):
                            if deck_name in p.get("title", "").lower():
                                current_page_idx = p_idx
                                page_active = False
                                deck_needs_redraw = True
                                break
                    elif cmd == "update_button":
                        btn_id = payload.get("id", "").lower()
                        new_lbl = payload.get("label")
                        new_col = payload.get("color")
                        for p in pages:
                            for b in p.get("buttons", []):
                                if btn_id in b.get("id", "").lower() or btn_id in b.get("label", "").lower():
                                    if new_lbl:
                                        b["label"] = new_lbl
                                    if "color" in payload:
                                        b["color"] = new_col
                                    deck_needs_redraw = True
                    elif "clear" in payload:
                        active_notification = None
                        deck_needs_redraw = True
                    elif "notify" in payload:
                        active_notification = str(payload["notify"])
                        deck_needs_redraw = True
                    elif "title" in payload:
                        active_notification = str(payload["title"])
                        deck_needs_redraw = True
                except Exception as e:
                    print("[BLE RX JSON ERROR]", repr(e))
            elif msg.lower() == "clear":
                active_notification = None
                deck_needs_redraw = True
            else:
                active_notification = msg
                deck_needs_redraw = True
        except asyncio.CancelledError:
            print("[BLE RX] Worker cancelled")
            break
        except Exception as e:
            print("[BLE RX EXCEPTION]:", repr(e))
            await asyncio.sleep_ms(100)

async def ble_peripheral_task():
    global ble_connected, ble_connection, deck_needs_redraw
    print("[BLE PERIPHERAL] Task started")
    while True:
        if not ble_enabled:
            await asyncio.sleep_ms(500)
            continue
        rx_task = None
        try:
            print("[BLE PERIPHERAL] Advertising as 'Presto' (services=[{}], interval=250ms)...".format(UART_SERVICE_UUID))
            connection = await aioble.advertise(
                250_000,
                name="Presto",
                services=[UART_SERVICE_UUID]
            )
            print("[BLE PERIPHERAL] CONNECTED from device:", connection.device)
            ble_connection = connection
            ble_connected = True
            deck_needs_redraw = True

            rx_task = asyncio.create_task(ble_rx_worker(connection))

            print("[BLE PERIPHERAL] Awaiting disconnect from central...")
            await connection.disconnected(timeout_ms=None)
            print("[BLE PERIPHERAL] Central disconnected")

        except asyncio.CancelledError:
            print("[BLE PERIPHERAL] Task cancelled")
            break
        except Exception as e:
            print("[BLE PERIPHERAL CYCLE ERROR]:", repr(e))
            await asyncio.sleep_ms(1000)
        finally:
            print("[BLE PERIPHERAL] Cleaning up connection...")
            if rx_task:
                rx_task.cancel()
            ble_connected = False
            ble_connection = None
            event_accumulator = []
            deck_needs_redraw = True
            await asyncio.sleep_ms(500)

# ---------------------------------------------------------
# 1. USB Keyboard Setup & Colemak Translation
# ---------------------------------------------------------
kbd = None
try:
    import boot
    if hasattr(boot, "kbd"):
        kbd = boot.kbd
except Exception:
    pass

if kbd is None:
    try:
        import usb.device
        from usb.device.keyboard import KeyboardInterface
        kbd = KeyboardInterface()
        usb.device.get().init(kbd, builtin_driver=True)
    except Exception:
        kbd = None

COLEMAK_TO_PHYSICAL = {
    "A": KeyCode.A,
    "B": KeyCode.B,
    "C": KeyCode.C,
    "D": KeyCode.G,
    "E": KeyCode.K,
    "F": KeyCode.E,
    "G": KeyCode.T,
    "H": KeyCode.H,
    "I": KeyCode.L,
    "J": KeyCode.Y,
    "K": KeyCode.N,
    "L": KeyCode.U,
    "M": KeyCode.M,
    "N": KeyCode.J,
    "O": KeyCode.SEMICOLON,
    "P": KeyCode.R,
    "Q": KeyCode.Q,
    "R": KeyCode.S,
    "S": KeyCode.D,
    "T": KeyCode.F,
    "U": KeyCode.I,
    "V": KeyCode.V,
    "W": KeyCode.W,
    "X": KeyCode.X,
    "Y": KeyCode.O,
    "Z": KeyCode.Z,
}

MODIFIERS = {
    "CTRL": KeyCode.LEFT_CTRL,
    "CONTROL": KeyCode.LEFT_CTRL,
    "SHIFT": KeyCode.LEFT_SHIFT,
    "ALT": KeyCode.LEFT_ALT,
    "OPT": KeyCode.LEFT_ALT,
    "OPTION": KeyCode.LEFT_ALT,
    "GUI": KeyCode.LEFT_UI,
    "CMD": KeyCode.LEFT_UI,
    "COMMAND": KeyCode.LEFT_UI,
    "WIN": KeyCode.LEFT_UI,
}

HYPER_MODS = [KeyCode.LEFT_CTRL, KeyCode.LEFT_ALT, KeyCode.LEFT_SHIFT, KeyCode.LEFT_UI]
MEH_MODS = [KeyCode.LEFT_CTRL, KeyCode.LEFT_ALT, KeyCode.LEFT_SHIFT]

SPECIAL_KEYS = {
    "ENTER": KeyCode.ENTER,
    "RETURN": KeyCode.ENTER,
    "SPACE": KeyCode.SPACE,
    "TAB": KeyCode.TAB,
    "ESC": KeyCode.ESCAPE,
    "ESCAPE": KeyCode.ESCAPE,
    "BACKSPACE": KeyCode.BACKSPACE,
    "DELETE": KeyCode.DELETE,
    "UP": KeyCode.UP,
    "DOWN": KeyCode.DOWN,
    "LEFT": KeyCode.LEFT,
    "RIGHT": KeyCode.RIGHT,
}

CHAR_TO_KEY = {
    " ": KeyCode.SPACE,
    "\n": KeyCode.ENTER,
    "\t": KeyCode.TAB,
    "!": (KeyCode.LEFT_SHIFT, KeyCode.N1),
    "@": (KeyCode.LEFT_SHIFT, KeyCode.N2),
    "#": (KeyCode.LEFT_SHIFT, KeyCode.N3),
    "$": (KeyCode.LEFT_SHIFT, KeyCode.N4),
    "%": (KeyCode.LEFT_SHIFT, KeyCode.N5),
    "^": (KeyCode.LEFT_SHIFT, KeyCode.N6),
    "&": (KeyCode.LEFT_SHIFT, KeyCode.N7),
    "*": (KeyCode.LEFT_SHIFT, KeyCode.N8),
    "(": (KeyCode.LEFT_SHIFT, KeyCode.N9),
    ")": (KeyCode.LEFT_SHIFT, KeyCode.N0),
    "-": KeyCode.MINUS,
    "_": (KeyCode.LEFT_SHIFT, KeyCode.MINUS),
    "=": KeyCode.EQUAL,
    "+": (KeyCode.LEFT_SHIFT, KeyCode.EQUAL),
    "[": KeyCode.OPEN_BRACKET,
    "{": (KeyCode.LEFT_SHIFT, KeyCode.OPEN_BRACKET),
    "]": KeyCode.CLOSE_BRACKET,
    "}": (KeyCode.LEFT_SHIFT, KeyCode.CLOSE_BRACKET),
    "\\": KeyCode.BACKSLASH,
    "|": (KeyCode.LEFT_SHIFT, KeyCode.BACKSLASH),
    ";": (KeyCode.LEFT_SHIFT, KeyCode.P),
    ":": (KeyCode.LEFT_SHIFT, KeyCode.P),
    "'": KeyCode.QUOTE,
    '"': (KeyCode.LEFT_SHIFT, KeyCode.QUOTE),
    ",": KeyCode.COMMA,
    "<": (KeyCode.LEFT_SHIFT, KeyCode.COMMA),
    ".": KeyCode.DOT,
    ">": (KeyCode.LEFT_SHIFT, KeyCode.DOT),
    "/": KeyCode.SLASH,
    "?": (KeyCode.LEFT_SHIFT, KeyCode.SLASH),
}

CURRENT_LAYOUT = "colemak"

def map_letter_key(letter):
    letter_upper = letter.upper()
    if CURRENT_LAYOUT == "colemak" and letter_upper in COLEMAK_TO_PHYSICAL:
        return COLEMAK_TO_PHYSICAL[letter_upper]
    return getattr(KeyCode, letter_upper, None)

def parse_combo(combo_str):
    parts = [p.strip().upper() for p in combo_str.split("+")]
    mods = []
    regular_key = None

    for p in parts:
        if p == "HYPER":
            mods.extend(HYPER_MODS)
        elif p == "MEH":
            mods.extend(MEH_MODS)
        elif p in MODIFIERS:
            mods.append(MODIFIERS[p])
        elif p in SPECIAL_KEYS:
            regular_key = SPECIAL_KEYS[p]
        elif len(p) == 1 and p.isalpha():
            regular_key = map_letter_key(p)
        elif len(p) == 1 and p.isdigit():
            regular_key = getattr(KeyCode, "N" + p, None)
        elif hasattr(KeyCode, p):
            regular_key = getattr(KeyCode, p)

    return mods, regular_key

def send_combo(mods, key):
    if not kbd or not kbd.is_open():
        return
    keys = list(mods)
    if key is not None:
        keys.append(key)
    try:
        kbd.send_keys(keys)
        time.sleep_ms(20)
        kbd.send_keys([])
        time.sleep_ms(15)
    except Exception as e:
        print("[HID] send_combo error:", e)

def send_text(text):
    if not kbd or not kbd.is_open():
        return
    text = text.replace("\\n", "\n").replace("\\t", "\t")
    for ch in text:
        keys = []
        if ch.isupper():
            keys.append(KeyCode.LEFT_SHIFT)
            k = map_letter_key(ch)
            if k:
                keys.append(k)
        elif ch.islower():
            k = map_letter_key(ch)
            if k:
                keys.append(k)
        elif ch.isdigit():
            k = getattr(KeyCode, "N" + ch, None)
            if k:
                keys.append(k)
        elif ch in CHAR_TO_KEY:
            val = CHAR_TO_KEY[ch]
            if isinstance(val, tuple):
                keys.extend(val)
            else:
                keys.append(val)

        if keys:
            try:
                kbd.send_keys(keys)
                time.sleep_ms(15)
                kbd.send_keys([])
                time.sleep_ms(15)
            except Exception as e:
                print("[HID] send_text error:", e)

# ---------------------------------------------------------
# 2. Config Parser & SD/Flash Path Resolver
# ---------------------------------------------------------
deck_settings = {}

def get_config_path():
    try:
        if "sd" in os.listdir("/"):
            if "config.md" in os.listdir("/sd"):
                return "/sd/config.md"
    except Exception:
        pass
    return "/config.md"

def load_config():
    global CURRENT_LAYOUT
    filepath = get_config_path()

    try:
        with open(filepath, "r") as f:
            lines = f.readlines()
    except Exception as e:
        print("[Config] Error:", e)
        return [], {}

    pages = []
    settings = {}
    current_page = None
    current_button = None

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("# "):
            continue

        if line.startswith("- ") and current_page is None and current_button is None:
            prop = line[2:].strip()
            if ":" in prop:
                k, v = prop.split(":", 1)
                settings[k.strip().lower()] = v.strip().lower()
            continue

        if line.startswith("## "):
            page_title = line[3:].strip()
            current_page = {"title": page_title, "buttons": []}
            pages.append(current_page)
            current_button = None

        elif line.startswith("### "):
            if current_page is None:
                current_page = {"title": "Default", "buttons": []}
                pages.append(current_page)
            btn_title = line[4:].strip()
            current_button = {"id": btn_title, "label": btn_title}
            current_page["buttons"].append(current_button)

        elif line.startswith("- ") and current_button is not None:
            prop_line = line[2:].strip()
            if ":" in prop_line:
                k, v = prop_line.split(":", 1)
                k = k.strip().lower()
                v = v.strip()
                current_button[k] = v

    global CURRENT_LAYOUT, deck_settings
    if "layout" in settings:
        CURRENT_LAYOUT = settings["layout"]
    deck_settings = settings

    return pages, settings

# ---------------------------------------------------------
# 3. Hardware, Display & Themes
# ---------------------------------------------------------
presto = Presto()
display = presto.display
touch = presto.touch
WIDTH, HEIGHT = display.get_bounds()

THEMES = [
    {
        "name": "Cyber Blue",
        "bg": (18, 22, 30),
        "header": (28, 35, 48),
        "btn": (38, 46, 62),
        "active": (12, 160, 205),
        "border": (60, 72, 95),
        "text": (245, 248, 255),
    },
    {
        "name": "OLED Neon",
        "bg": (0, 0, 0),
        "header": (16, 16, 16),
        "btn": (24, 24, 24),
        "active": (0, 230, 255),
        "border": (50, 50, 50),
        "text": (255, 255, 255),
    },
    {
        "name": "Amber Glow",
        "bg": (24, 18, 12),
        "header": (40, 28, 18),
        "btn": (52, 38, 24),
        "active": (255, 160, 20),
        "border": (90, 65, 40),
        "text": (255, 245, 230),
    },
    {
        "name": "Matrix Green",
        "bg": (10, 24, 14),
        "header": (18, 40, 24),
        "btn": (25, 55, 33),
        "active": (40, 220, 80),
        "border": (45, 90, 55),
        "text": (230, 255, 235),
    },
]

current_theme_idx = 0
BRIGHTNESS_LEVELS = [0.06, 0.12, 0.20, 0.35]
current_brightness_val = 0.12

pens = {}
PEN_WHITE = display.create_pen(255, 255, 255)
PEN_BLACK = display.create_pen(0, 0, 0)
PEN_ALERT = display.create_pen(255, 160, 20)
PEN_EVENT = display.create_pen(170, 70, 240)

def apply_theme(idx):
    global current_theme_idx, pens
    current_theme_idx = idx % len(THEMES)
    t = THEMES[current_theme_idx]
    pens = {
        "bg": display.create_pen(*t["bg"]),
        "header": display.create_pen(*t["header"]),
        "btn": display.create_pen(*t["btn"]),
        "active": display.create_pen(*t["active"]),
        "border": display.create_pen(*t["border"]),
        "text": display.create_pen(*t["text"]),
        "accent": display.create_pen(0, 210, 160),
    }

apply_theme(0)

HEADER_H = 40
GRID_X = 8
GRID_Y = 46
BTN_W = 108
BTN_H = 56
GAP_X = 8
GAP_Y = 6

def hit_test(x, y, bx, by, bw, bh):
    return (bx <= x < bx + bw) and (by <= y < by + bh)

def text_width(txt, scale):
    try:
        return display.measure_text(txt, scale)
    except Exception:
        return len(txt) * (6 if scale == 1 else 12)

# ---------------------------------------------------------
# 4. Wi-Fi Access Point & Web Config Server
# ---------------------------------------------------------
def url_unquote(s):
    s = s.replace("+", " ")
    parts = s.split("%")
    res = parts[0]
    for p in parts[1:]:
        if len(p) >= 2:
            try:
                res += chr(int(p[:2], 16)) + p[2:]
            except Exception:
                res += "%" + p
        else:
            res += "%" + p
    return res

def draw_qr(ox, oy, target_size, text):
    qr = qrcode.QRCode()
    qr.set_text(text)
    w, h = qr.get_size()
    mod = max(1, target_size // w)
    total_w = w * mod
    quiet = mod * 3  # Standard quiet zone margin

    # Generous white background box so camera finder patterns contrast cleanly
    display.set_pen(PEN_WHITE)
    display.rectangle(ox - quiet, oy - quiet, total_w + (quiet * 2), total_w + (quiet * 2))

    # Black modules
    display.set_pen(PEN_BLACK)
    for x in range(w):
        for y in range(h):
            if qr.get_module(x, y):
                display.rectangle(ox + x * mod, oy + y * mod, mod, mod)

async def run_wifi_server():
    global ble_enabled
    ble_enabled = False  # Pause BLE advertising during Wi-Fi AP

    # 1. Render Wi-Fi Screen FIRST so user immediately sees the QR code and Cancel button
    display.set_pen(pens["bg"])
    display.clear()

    display.set_pen(pens["header"])
    display.rectangle(0, 0, WIDTH, HEADER_H)
    display.set_pen(pens["text"])
    display.text("Wi-Fi Config AP", 16, 12, WIDTH - 32, 2)
    display.set_pen(pens["border"])
    display.line(0, HEADER_H, WIDTH, HEADER_H)

    try:
        draw_qr(18, 54, 84, "WIFI:S:Presto-Deck;T:WPA;P:presto123;;")
    except Exception as e:
        print("[QR] Render error:", e)

    display.set_pen(pens["text"])
    display.text("SSID:", 124, 48, 110, 1)
    display.set_pen(pens["accent"])
    display.text("Presto-Deck", 124, 60, 110, 2)

    display.set_pen(pens["text"])
    display.text("Pass:", 124, 82, 110, 1)
    display.set_pen(pens["accent"])
    display.text("presto123", 124, 94, 110, 2)

    display.set_pen(pens["text"])
    display.text("URL: 192.168.4.1", 124, 120, 110, 1)

    exit_x, exit_y, exit_w, exit_h = 14, 172, 212, 48
    display.set_pen(pens["border"])
    display.rectangle(exit_x - 1, exit_y - 1, exit_w + 2, exit_h + 2)
    display.set_pen(pens["btn"])
    display.rectangle(exit_x, exit_y, exit_w, exit_h)
    display.set_pen(pens["text"])
    display.text("Stop & Return to Deck", exit_x + 16, exit_y + 16, exit_w - 32, 2)

    presto.update()

    # 2. Configure and start Access Point (RP2 CYW43 requires config BEFORE active)
    ap = network.WLAN(network.AP_IF)
    try:
        ap.active(False)
    except Exception:
        pass

    try:
        ap.config(ssid="Presto-Deck", key="presto123")
    except Exception:
        try:
            ap.config(essid="Presto-Deck", password="presto123")
        except Exception as e:
            print("[Wi-Fi] config error:", e)

    try:
        ap.active(True)
    except Exception as e:
        print("[Wi-Fi] active error:", e)

    time.sleep_ms(200)

    # 3. Setup Microdot web server
    app = Microdot()
    Response.default_content_type = "text/html"
    config_saved = False

    def get_editor_html():
        current_config = ""
        try:
            with open(get_config_path(), "r") as f:
                current_config = f.read()
        except Exception:
            pass
        escaped = current_config.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return (
            '<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>Presto Config Editor</title>'
            '<style>'
            'body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #12161E; color: #fff; padding: 16px; margin: 0; }'
            'h2 { color: #00D2A0; margin-top: 0; font-size: 20px; }'
            'p { color: #8A99AD; font-size: 13px; margin: 0 0 12px 0; }'
            'textarea { width: 100%; height: 55vh; background: #1C2330; color: #F5F8FF; font-family: monospace; font-size: 14px; border: 1px solid #3A465C; border-radius: 8px; padding: 10px; box-sizing: border-box; }'
            'button { width: 100%; background: #0CA0CD; color: #fff; font-size: 16px; font-weight: bold; padding: 14px; border: none; border-radius: 8px; margin-top: 12px; cursor: pointer; }'
            'button:active { background: #087a9e; }'
            '</style></head><body>'
            '<h2>Presto Deck Editor</h2>'
            '<p>Connected to Presto-Deck. Edit config.md and tap Save:</p>'
            '<form method="POST" action="/save">'
            '<textarea name="content">' + escaped + '</textarea>'
            '<button type="submit">Save & Restart Deck</button>'
            '</form></body></html>'
        )

    @app.route("/")
    @app.route("/hotspot-detect.html")
    @app.route("/generate_204")
    def index(req):
        return Response(get_editor_html(), headers={"Content-Type": "text/html"})

    @app.route("/save", methods=["POST"])
    def save(req):
        nonlocal config_saved
        new_text = None
        if req.form:
            new_text = req.form.get("content")
        if not new_text and req.body:
            body_str = str(req.body, "utf-8")
            if "content=" in body_str:
                new_text = url_unquote(body_str.split("content=", 1)[1])

        if new_text is not None:
            try:
                with open(get_config_path(), "w") as f:
                    f.write(new_text)
                config_saved = True
            except Exception as e:
                print("[Save] Write error:", e)

        async def shutdown_after_response():
            await asyncio.sleep(1.0)
            app.shutdown()
        asyncio.create_task(shutdown_after_response())

        resp = (
            '<!DOCTYPE html><html><body style="background:#12161E;color:#00D2A0;font-family:sans-serif;padding:30px;text-align:center;">'
            '<h2>Config Saved!</h2><p>Presto is rebooting deck...</p></body></html>'
        )
        return Response(resp, headers={"Content-Type": "text/html"})

    srv_task = asyncio.create_task(app.start_server(host="0.0.0.0", port=80))

    running = True
    was_touch = True
    while running:
        touch.poll()
        is_touch = (touch.state in (touch.STATE_DOWN, touch.STATE_CONTACT))
        if is_touch and not was_touch:
            was_touch = True
            if hit_test(touch.x, touch.y, exit_x, exit_y, exit_w, exit_h):
                running = False
                break
        elif not is_touch:
            was_touch = False

        if config_saved:
            await asyncio.sleep(1.2)
            running = False
            break

        await asyncio.sleep_ms(25)

    try:
        app.shutdown()
        await srv_task
    except Exception:
        pass

    try:
        ap.active(False)
    except Exception:
        pass

    ble_enabled = True
    return config_saved

# ---------------------------------------------------------
# 5. Settings Screen
# ---------------------------------------------------------
async def run_settings():
    global current_brightness_val, current_theme_idx

    active_row = None
    was_touching = True
    needs_redraw = True
    in_settings = True
    config_changed = False

    actions = ["theme", "brightness", "wifi", "back"]

    while in_settings:
        touch.poll()
        is_touching = (touch.state in (touch.STATE_DOWN, touch.STATE_CONTACT))
        tx = touch.x
        ty = touch.y

        if is_touching:
            if not was_touching:
                was_touching = True
                for idx in range(4):
                    by = 48 + idx * 46
                    if hit_test(tx, ty, 14, by, 212, 40):
                        active_row = idx
                        needs_redraw = True

                        act = actions[idx]
                        if act == "theme":
                            apply_theme(current_theme_idx + 1)
                        elif act == "brightness":
                            closest = 0
                            for i, b in enumerate(BRIGHTNESS_LEVELS):
                                if abs(b - current_brightness_val) < 0.04:
                                    closest = i
                                    break
                            next_idx = (closest + 1) % len(BRIGHTNESS_LEVELS)
                            current_brightness_val = BRIGHTNESS_LEVELS[next_idx]
                            presto.set_backlight(current_brightness_val)
                        elif act == "wifi":
                            saved = await run_wifi_server()
                            if saved:
                                config_changed = True
                                in_settings = False
                            needs_redraw = True
                        elif act == "back":
                            in_settings = False
                        break
        else:
            if was_touching:
                was_touching = False
                if active_row is not None:
                    active_row = None
                    needs_redraw = True

        if needs_redraw and in_settings:
            display.set_pen(pens["bg"])
            display.clear()

            display.set_pen(pens["header"])
            display.rectangle(0, 0, WIDTH, HEADER_H)
            display.set_pen(pens["text"])
            display.text("Settings", 16, 12, WIDTH - 32, 2)
            display.set_pen(pens["border"])
            display.line(0, HEADER_H, WIDTH, HEADER_H)

            s_rows = [
                {"label": f"Theme: {THEMES[current_theme_idx]['name']}"},
                {"label": f"Brightness: {int(current_brightness_val * 100)}%"},
                {"label": "Wi-Fi Config AP"},
                {"label": "Back to Deck"},
            ]

            for idx, row in enumerate(s_rows):
                by = 48 + idx * 46
                is_active = (active_row == idx)

                display.set_pen(pens["border"])
                display.rectangle(13, by - 1, 214, 42)
                display.set_pen(pens["active"] if is_active else pens["btn"])
                display.rectangle(14, by, 212, 40)
                display.set_pen(pens["text"])
                display.text(row["label"], 22, by + 12, 192, 2)

            presto.update()
            needs_redraw = False

        await asyncio.sleep_ms(5)

    return config_changed

# ---------------------------------------------------------
# 6. Main Deck Loop
# ---------------------------------------------------------
def render_deck(page, active_btn_idx, buttons):
    display.set_pen(pens["bg"])
    display.clear()

    # Header
    display.set_pen(pens["header"])
    display.rectangle(0, 0, WIDTH, HEADER_H)

    # Bluetooth Indicator in Header (top right)
    display.set_pen(pens["accent"] if ble_connected else pens["border"])
    display.text("BT", WIDTH - 26, 12, 24, 2)

    # Clock in Header (next to BT indicator)
    if current_time_str:
        display.set_pen(pens["text"])
        display.text(current_time_str, WIDTH - 82, 12, 54, 2)

    # Title & Notification Pill
    title = page.get("title", "Workspace")
    right_margin = 86 if current_time_str else 32
    if active_notification:
        # Title on left
        display.set_pen(pens["text"])
        display.text(title, 12, 12, 56, 2)

        # Alert pill in center
        ax, ay, aw, ah = 72, 6, 80, 28
        display.set_pen(PEN_ALERT)
        display.rectangle(ax, ay, aw, ah)
        display.set_pen(PEN_BLACK)
        display.text("! " + active_notification[:8], ax + 6, ay + 6, aw - 12, 2)
    else:
        display.set_pen(pens["text"])
        display.text(title, 16, 12, WIDTH - right_margin, 2)

    display.set_pen(pens["border"])
    display.line(0, HEADER_H, WIDTH, HEADER_H)

    # Buttons
    for idx, b in enumerate(buttons):
        is_pressed = (active_btn_idx == idx)
        b_color = b["def"].get("color")

        display.set_pen(pens["border"])
        display.rectangle(b["x"] - 1, b["y"] - 1, b["w"] + 2, b["h"] + 2)

        if is_pressed:
            display.set_pen(pens["active"])
        elif b_color == "alert":
            display.set_pen(PEN_ALERT)
        elif b_color == "event":
            display.set_pen(PEN_EVENT)
        else:
            display.set_pen(pens["btn"])
        display.rectangle(b["x"], b["y"], b["w"], b["h"])

        if b_color == "alert" and not is_pressed:
            display.set_pen(PEN_BLACK)
        elif b_color == "event" and not is_pressed:
            display.set_pen(PEN_WHITE)
        else:
            display.set_pen(pens["text"])

        # Smart Multiline Centered Text Placement
        lbl = b["def"].get("label", b["def"]["id"]).replace("\\n", "\n")

        if b_color == "event":
            # Event button: Time on top (scale 2), Title below in smaller font (scale 1)
            if "\n" in lbl:
                parts = [p.strip() for p in lbl.split("\n", 1) if p.strip()]
                time_str = parts[0]
                desc_str = parts[1] if len(parts) > 1 else ""
            else:
                parts = lbl.split(" ", 1)
                time_str = parts[0]
                desc_str = parts[1] if len(parts) > 1 else ""

            # Word wrap title at ~16 characters per line
            desc_lines = []
            cur_line = ""
            for word in desc_str.split():
                if len(cur_line) + len(word) + (1 if cur_line else 0) <= 16:
                    cur_line = (cur_line + " " + word).strip()
                else:
                    if cur_line:
                        desc_lines.append(cur_line)
                    while len(word) > 16:
                        desc_lines.append(word[:16])
                        word = word[16:]
                    cur_line = word
            if cur_line:
                desc_lines.append(cur_line)

            if len(desc_lines) <= 1:
                display.text(time_str, b["x"] + 6, b["y"] + 11, b["w"] - 12, 2)
                if desc_lines:
                    display.text(desc_lines[0], b["x"] + 6, b["y"] + 32, b["w"] - 12, 1)
            elif len(desc_lines) == 2:
                display.text(time_str, b["x"] + 6, b["y"] + 8, b["w"] - 12, 2)
                display.text(desc_lines[0], b["x"] + 6, b["y"] + 27, b["w"] - 12, 1)
                display.text(desc_lines[1], b["x"] + 6, b["y"] + 39, b["w"] - 12, 1)
            else:
                display.text(time_str, b["x"] + 6, b["y"] + 4, b["w"] - 12, 2)
                display.text(desc_lines[0], b["x"] + 6, b["y"] + 20, b["w"] - 12, 1)
                display.text(desc_lines[1], b["x"] + 6, b["y"] + 31, b["w"] - 12, 1)
                display.text(desc_lines[2], b["x"] + 6, b["y"] + 42, b["w"] - 12, 1)
        else:
            if "\n" in lbl:
                raw_lines = [l.strip() for l in lbl.split("\n") if l.strip()]
            elif len(lbl) > 10 and " " in lbl and lbl.count(" ") == 1:
                raw_lines = lbl.split(" ", 1)
            else:
                raw_lines = [lbl]

            # Determine button font scale:
            # 1. Per-button property: "font_size", "scale", or "size"
            # 2. Global deck setting: "font_size" or "scale"
            # 3. Auto-fit: if any line > 8 characters, scale down to 1
            btn_cfg_scale = b["def"].get("font_size") or b["def"].get("scale") or b["def"].get("size")
            global_cfg_scale = deck_settings.get("font_size") or deck_settings.get("scale")
            chosen_scale_raw = btn_cfg_scale or global_cfg_scale

            if chosen_scale_raw:
                s_str = str(chosen_scale_raw).strip().lower()
                if s_str in ("1", "small", "sm", "tiny", "min"):
                    scale = 1
                elif s_str in ("2", "normal", "medium", "default", "large", "lg"):
                    scale = 2
                else:
                    try:
                        scale = max(1, min(3, int(s_str)))
                    except Exception:
                        scale = 2
            else:
                # Auto-fit: scale 2 overflows 96px usable width if a line exceeds 8 characters
                max_line_len = max(len(l) for l in raw_lines) if raw_lines else 0
                if max_line_len > 8:
                    scale = 1
                else:
                    scale = 2

            num_lines = len(raw_lines)
            if scale == 1:
                if num_lines == 1:
                    line_y = b["y"] + (b["h"] - 8) // 2
                    w = text_width(raw_lines[0], 1)
                    line_x = b["x"] + max(6, (b["w"] - w) // 2)
                    display.text(raw_lines[0], line_x, line_y, b["w"] - 12, 1)
                elif num_lines == 2:
                    start_y = b["y"] + (b["h"] - 20) // 2
                    for li, line_txt in enumerate(raw_lines):
                        w = text_width(line_txt, 1)
                        line_x = b["x"] + max(6, (b["w"] - w) // 2)
                        display.text(line_txt, line_x, start_y + (li * 11), b["w"] - 12, 1)
                else:
                    line_h = 10
                    total_h = num_lines * line_h
                    start_y = b["y"] + max(4, (b["h"] - total_h) // 2)
                    for li, line_txt in enumerate(raw_lines[:4]):
                        w = text_width(line_txt, 1)
                        line_x = b["x"] + max(6, (b["w"] - w) // 2)
                        display.text(line_txt, line_x, start_y + (li * line_h), b["w"] - 12, 1)
            else:
                if num_lines == 1:
                    line_y = b["y"] + (b["h"] - 14) // 2
                    w = text_width(raw_lines[0], 2)
                    line_x = b["x"] + max(6, (b["w"] - w) // 2)
                    display.text(raw_lines[0], line_x, line_y, b["w"] - 12, 2)
                elif num_lines == 2:
                    start_y = b["y"] + (b["h"] - 30) // 2
                    for li, line_txt in enumerate(raw_lines[:2]):
                        w = text_width(line_txt, 2)
                        line_x = b["x"] + max(6, (b["w"] - w) // 2)
                        display.text(line_txt, line_x, start_y + (li * 16), b["w"] - 12, 2)
                else:
                    line_h = 10
                    total_h = num_lines * line_h
                    start_y = b["y"] + max(4, (b["h"] - total_h) // 2)
                    for li, line_txt in enumerate(raw_lines[:4]):
                        w = text_width(line_txt, 1)
                        line_x = b["x"] + max(6, (b["w"] - w) // 2)
                        display.text(line_txt, line_x, start_y + (li * line_h), b["w"] - 12, 1)

    presto.update()

async def run_deck():
    global current_brightness_val, deck_needs_redraw, active_notification, current_page_idx, page_active, pages
    loaded_pages, settings = load_config()
    pages = loaded_pages

    if "brightness" in settings:
        try:
            b_str = settings["brightness"].replace("%", "").strip()
            val = float(b_str)
            if val > 1.0:
                val = val / 100.0
            current_brightness_val = max(0.02, min(1.0, val))
        except Exception:
            pass
    presto.set_backlight(current_brightness_val)

    if not pages:
        display.set_pen(pens["bg"])
        display.clear()
        display.set_pen(pens["text"])
        display.text("No config.md found!", 20, 80, WIDTH, 2)
        presto.update()
        return

    current_page_idx = 0
    was_touching = False

    while True:
        page = pages[current_page_idx]
        btn_defs = page.get("buttons", [])[:6]

        buttons = []
        for i, b_def in enumerate(btn_defs):
            col = i % 2
            row = i // 2
            bx = GRID_X + col * (BTN_W + GAP_X)
            by = GRID_Y + row * (BTN_H + GAP_Y)
            buttons.append({
                "def": b_def,
                "x": bx,
                "y": by,
                "w": BTN_W,
                "h": BTN_H,
            })

        render_deck(page, None, buttons)
        deck_needs_redraw = False
        page_active = True

        while page_active:
            # Check if background BLE task requested redraw (notification arrived, connection changed)
            if deck_needs_redraw:
                render_deck(page, None, buttons)
                deck_needs_redraw = False

            touch.poll()
            is_touching = (touch.state in (touch.STATE_DOWN, touch.STATE_CONTACT))
            tx = touch.x
            ty = touch.y

            if is_touching:
                if not was_touching:
                    was_touching = True

                    # 1. Tapped Notification Pill
                    if active_notification and hit_test(tx, ty, 84, 6, 122, 28):
                        if ble_connected:
                            ble_send(json.dumps({"event": "notification_tap", "text": active_notification}))
                        active_notification = None
                        render_deck(page, None, buttons)
                        continue

                    # 2. Touch-down on Header
                    if ty <= HEADER_H:
                        if tx < 70:
                            current_page_idx = (current_page_idx - 1) % len(pages)
                            page_active = False
                            break
                        elif tx > (WIDTH - 40):
                            current_page_idx = (current_page_idx + 1) % len(pages)
                            page_active = False
                            break
                        else:
                            reloaded = await run_settings()
                            if reloaded:
                                pages, settings = load_config()
                                current_page_idx = 0
                            page_active = False
                            break

                    # 3. Touch-down on Button Grid
                    else:
                        for idx, b in enumerate(buttons):
                            if hit_test(tx, ty, b["x"], b["y"], b["w"], b["h"]):
                                b_def = b["def"]

                                # 1. Flash button active
                                render_deck(page, idx, buttons)

                                # 2. Send BLE event to Chrome if connected
                                if ble_connected:
                                    evt = {
                                        "event": "button_tap",
                                        "id": b_def.get("id", ""),
                                        "label": b_def.get("label", ""),
                                        "bt": b_def.get("bt", ""),
                                        "action": b_def.get("bt") or b_def.get("combo") or b_def.get("text") or ""
                                    }
                                    ble_send(json.dumps(evt))

                                # 3. Fire local action
                                if "bt" in b_def:
                                    bt_act = b_def["bt"].strip()
                                    if bt_act.startswith("switch_deck:"):
                                        target_name = bt_act.split("switch_deck:", 1)[1].strip().lower()
                                        for p_idx, p in enumerate(pages):
                                            if target_name in p.get("title", "").lower():
                                                current_page_idx = p_idx
                                                page_active = False
                                                break
                                elif "combo" in b_def:
                                    mods, key = parse_combo(b_def["combo"])
                                    send_combo(mods, key)
                                elif "text" in b_def:
                                    send_text(b_def["text"])

                                # 4. Snap back to normal (if page didn't change)
                                if page_active:
                                    render_deck(page, None, buttons)
                                break
            else:
                if was_touching:
                    was_touching = False

            await asyncio.sleep_ms(5)

async def main_async():
    print("[MAIN] Spawning ble_peripheral_task...")
    asyncio.create_task(ble_peripheral_task())
    print("[MAIN] Entering run_deck loop...")
    await run_deck()

def run():
    asyncio.run(main_async())

if __name__ == "__main__":
    run()
