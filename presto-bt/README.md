# Presto BT Deck Bridge — Chrome Extension

A two-way Web Bluetooth companion for your Pimoroni Presto Macro Deck.

## Features
- **Dynamic Tab Monitoring**:
  - Automatically reads unread count `(N)` from Gmail tabs and updates the `Gmail` button label on Presto to `Gmail (N)` in real time.
- **Context-Aware Workspace Switching**:
  - Focusing a Gmail tab in Chrome automatically flips Presto to the dedicated **Gmail Workspace** (`Open Inbox`, `Select All`, `Archive`, `Mark Read`, `Compose`).
  - Switching back to another tab flips Presto back to the default **Workspace**.
- **Two-Way Action Execution**:
  - Pressing **Gmail** on Presto focuses your open Gmail tab (or opens one if not already open).
  - Pressing **Select All**, **Archive**, **Mark Read**, or **Compose** on Presto directly controls Gmail in Chrome.
- **Side Panel Support**:
  - Can run inside the Chrome Side Panel (`chrome.sidePanel`) so the bridge stays connected and monitors tabs continuously while you browse.

---

## Installation (Unpacked Extension)

1. Open **Google Chrome** and navigate to:
   ```
   chrome://extensions
   ```
2. In the top-right corner, toggle **Developer mode** to **ON**.
3. Click **Load unpacked** in the top-left corner.
4. Select the folder:
   ```
   /Users/ruben/code/presto/presto-bt
   ```
5. Pin **Presto BT Deck** to your Chrome toolbar by clicking the puzzle icon.

---

## How to Use

1. Click the **Presto BT Deck** extension icon in your Chrome toolbar (or open the Side Panel).
2. Click **Connect Presto**.
3. In the Chrome Bluetooth pairing prompt, select **`Presto-Deck`** and click **Pair**.
4. Test the two-way automations:
   - **Tab Jumping**: Tap the **Gmail** button on your Presto. Chrome will immediately bring your Gmail tab to the front.
   - **Unread Sync**: Look at the Presto screen—if your Gmail tab has unread emails, the button will dynamically update to show `Gmail (N)`.
   - **Contextual Deck Switching**: When you click into your Gmail tab, Presto automatically displays the **Gmail** deck buttons (`Select All`, `Archive`, `Mark Read`, `Compose`, `Workspace`).
   - **Gmail Actions**: Tapping **Archive** or **Select All** on Presto performs that action directly in Gmail!
