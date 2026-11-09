"""
Presto boot.py
Initializes the USB HID keyboard driver alongside the standard CDC serial port.
"""

import usb.device
from usb.device.keyboard import KeyboardInterface

# Create the keyboard interface and register it with the USB stack
kbd = KeyboardInterface()
usb.device.get().init(kbd, builtin_driver=True)
