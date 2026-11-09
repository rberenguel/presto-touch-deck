# Presto Deck — Web Bluetooth Bridge

Bidirectional Web Bluetooth integration connecting Google Chrome directly to your Pimoroni Presto Macro Deck.

## Features
- **Zero-Install Web Bridge**: Open `web_bridge/index.html` directly in Google Chrome / Chromium / Edge (via `file://` or local dev server).
- **Push Tab Notifications to Presto**: Send real-time alert banners (CI failures, PR reviews, unread chat messages) directly to the Presto screen.
- **Deck Event Stream**: Live stream of touch events received from Presto in Chrome whenever buttons are tapped.
- **Notification Acknowledgments**: Tapping the notification alert on the Presto screen immediately fires an acknowledgment event back to Chrome over Bluetooth.
- **Custom Chrome Extension Ready**: Architecture and code snippets to pipe background tab notifications directly to the deck.

## Quick Start
1. Ensure your Presto Deck is running. You'll see a dim `BT` indicator in the top right header indicating it is advertising as `Presto-Deck`.
2. Open `web_bridge/index.html` in Google Chrome (or run `npx serve .` or `python -m http.server` and open `http://localhost:8000/web_bridge`).
3. Click **"Connect to Presto Deck"**.
4. In the browser Bluetooth pairing prompt, select **`Presto-Deck`** and click **Pair**.
5. Once connected:
   - The `BT` indicator on Presto turns bright cyan.
   - You can push notifications using the quick presets or the text box.
   - Tapping any button on Presto will log its event in the Live Event Stream.
