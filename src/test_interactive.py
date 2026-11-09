"""
Presto Touch HID - Step 1 Interactive Grid Test
Displays a clean 2x3 grid of touch buttons on the Presto screen.
Provides immediate visual press feedback and emits JSON events over serial.
(No buzzer)
"""

import time
import json
from presto import Presto
from touch import Button

# Initialize Presto hardware (default scaled resolution 240x240 for crisp performance)
presto = Presto()
display = presto.display
touch = presto.touch
WIDTH, HEIGHT = display.get_bounds()

# Palette / Colors
COLOR_BG = display.create_pen(20, 24, 33)        # Dark slate background
COLOR_HEADER_BG = display.create_pen(35, 41, 56) # Header banner
COLOR_TEXT = display.create_pen(240, 244, 250)   # White/light gray text
COLOR_SUBTEXT = display.create_pen(140, 150, 170)# Muted text
COLOR_BTN_NORMAL = display.create_pen(45, 53, 72)# Button base
COLOR_BTN_ACTIVE = display.create_pen(16, 149, 193)# Cyan on tap
COLOR_BTN_BORDER = display.create_pen(70, 80, 105)

# Button definition structure
BUTTON_DEFS = [
    {"id": "mute",       "col": 0, "row": 0, "label": "Mute"},
    {"id": "play_pause", "col": 1, "row": 0, "label": "Play/Pause"},
    {"id": "tests",      "col": 0, "row": 1, "label": "Run Tests"},
    {"id": "terminal",   "col": 1, "row": 1, "label": "Terminal"},
    {"id": "prev_track", "col": 0, "row": 2, "label": "Prev Track"},
    {"id": "next_track", "col": 1, "row": 2, "label": "Next Track"},
]

# Grid layout metrics for 240x240
GRID_X = 8
GRID_Y = 36
BTN_W = 108
BTN_H = 58
GAP_X = 8
GAP_Y = 8

buttons = []
for item in BUTTON_DEFS:
    bx = GRID_X + item["col"] * (BTN_W + GAP_X)
    by = GRID_Y + item["row"] * (BTN_H + GAP_Y)
    btn_obj = Button(bx, by, BTN_W, BTN_H)
    buttons.append({
        "def": item,
        "btn": btn_obj,
        "x": bx,
        "y": by,
        "w": BTN_W,
        "h": BTN_H,
        "was_pressed": False,
    })

def render(last_event_msg="Ready"):
    # Clear screen
    display.set_pen(COLOR_BG)
    display.clear()

    # Header bar
    display.set_pen(COLOR_HEADER_BG)
    display.rectangle(0, 0, WIDTH, 28)
    display.set_pen(COLOR_TEXT)
    display.text("PRESTO TOUCH HID", 8, 4, WIDTH, 2)
    display.set_pen(COLOR_SUBTEXT)
    display.text(last_event_msg, 8, 16, WIDTH, 1)

    # Render buttons
    for b in buttons:
        is_down = b["btn"].is_pressed()
        
        # Border
        display.set_pen(COLOR_BTN_BORDER)
        display.rectangle(b["x"] - 1, b["y"] - 1, b["w"] + 2, b["h"] + 2)

        # Button fill
        if is_down:
            display.set_pen(COLOR_BTN_ACTIVE)
        else:
            display.set_pen(COLOR_BTN_NORMAL)
        display.rectangle(b["x"], b["y"], b["w"], b["h"])

        # Label
        display.set_pen(COLOR_TEXT)
        label = b["def"]["label"]
        # Center-ish label inside button
        display.text(label, b["x"] + 8, b["y"] + (b["h"] // 2) - 4, b["w"] - 16, 2)

    presto.update()

def main():
    print("[Presto] Starting Touch HID grid...")
    last_status = "Ready"
    render(last_status)

    while True:
        touch.poll()
        state_changed = False

        for b in buttons:
            is_down = b["btn"].is_pressed()
            
            # Detect tap trigger (press event)
            if is_down and not b["was_pressed"]:
                b["was_pressed"] = True
                state_changed = True
                event = {
                    "event": "press",
                    "id": b["def"]["id"],
                    "label": b["def"]["label"],
                    "timestamp": time.ticks_ms()
                }
                # Emit over serial
                print(json.dumps(event))
                last_status = "Tapped: " + b["def"]["label"]

            elif not is_down and b["was_pressed"]:
                b["was_pressed"] = False
                state_changed = True
                event = {
                    "event": "release",
                    "id": b["def"]["id"],
                    "label": b["def"]["label"],
                    "timestamp": time.ticks_ms()
                }
                print(json.dumps(event))

        if state_changed:
            render(last_status)

        time.sleep(0.01)

if __name__ == "__main__":
    main()
