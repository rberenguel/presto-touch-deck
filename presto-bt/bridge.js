// Presto BT Deck Bridge - Core Two-Way Controller
const NUS_SERVICE_UUID = '6e400001-b5a3-f393-e0a9-e50e24dcca9e';
const NUS_RX_UUID = '6e400002-b5a3-f393-e0a9-e50e24dcca9e';
const NUS_TX_UUID = '6e400003-b5a3-f393-e0a9-e50e24dcca9e';

let bluetoothDevice = null;
let rxCharacteristic = null;
let txCharacteristic = null;

// User Config Options
let autoSwitchDeck = true;
let monitorUnreadBadge = true;

let lastGmailUnread = null;
let currentDeckName = 'Workspace';

// Load stored settings
chrome.storage.local.get(['autoSwitchDeck', 'monitorUnreadBadge'], (res) => {
  if (res.autoSwitchDeck !== undefined) autoSwitchDeck = res.autoSwitchDeck;
  if (res.monitorUnreadBadge !== undefined) monitorUnreadBadge = res.monitorUnreadBadge;
});

// UI Callbacks
let uiLogCallback = null;
let uiStatusCallback = null;

export function registerCallbacks(onLog, onStatus) {
  uiLogCallback = onLog;
  uiStatusCallback = onStatus;
}

export function setOptions(autoSwitch, monitorUnread) {
  autoSwitchDeck = autoSwitch;
  monitorUnreadBadge = monitorUnread;
  chrome.storage.local.set({ autoSwitchDeck, monitorUnreadBadge });
}

function log(type, message, tagClass = 'tag-sys') {
  if (uiLogCallback) uiLogCallback(type, message, tagClass);
}

function updateStatus(isConnected, deviceName = '') {
  if (uiStatusCallback) uiStatusCallback(isConnected, deviceName);
}

// -------------------------------------------------------------
// 1. Bluetooth Connection Management
// -------------------------------------------------------------
export async function connectPresto() {
  if (!navigator.bluetooth) {
    alert('Web Bluetooth is not supported or not enabled in this context.');
    return;
  }

  try {
    log('SYS', 'Requesting Bluetooth device matching Presto NUS Service...');

    bluetoothDevice = await navigator.bluetooth.requestDevice({
      filters: [
        { services: [NUS_SERVICE_UUID] }
      ],
      optionalServices: [NUS_SERVICE_UUID]
    });

    log('SYS', `Selected: ${bluetoothDevice.name || 'Presto'}. Connecting GATT...`);
    bluetoothDevice.addEventListener('gattserverdisconnected', onDisconnected);

    const server = await bluetoothDevice.gatt.connect();
    log('SYS', 'GATT connected. Stabilizing link (350ms)...');
    await new Promise(r => setTimeout(r, 350));

    log('SYS', 'Discovering Nordic UART Service...');
    const service = await server.getPrimaryService(NUS_SERVICE_UUID);
    rxCharacteristic = await service.getCharacteristic(NUS_RX_UUID);
    txCharacteristic = await service.getCharacteristic(NUS_TX_UUID);

    log('SYS', 'Subscribing to button press events...');
    await txCharacteristic.startNotifications();
    txCharacteristic.addEventListener('characteristicvaluechanged', handlePrestoEvent);

    updateStatus(true, bluetoothDevice.name || 'Presto');
    log('SYS', 'Presto connected! Two-way sync is active.', 'tag-tap');

    // Force-sync state upon fresh connection
    lastGmailUnread = null;
    currentDeckName = null;
    await checkActiveTab();
  } catch (error) {
    console.error('Connection failed:', error);
    if (error.name !== 'NotFoundError') {
      log('ERR', `Connection error: ${error.name} - ${error.message || error}`, 'tag-ack');
    } else {
      log('SYS', 'Connection prompt cancelled by user.');
    }
    updateStatus(false);
  }
}

export function disconnectPresto() {
  if (bluetoothDevice && bluetoothDevice.gatt.connected) {
    bluetoothDevice.gatt.disconnect();
    log('SYS', 'Disconnected by user.');
  }
  updateStatus(false);
}

function onDisconnected() {
  log('SYS', 'Presto disconnected.', 'tag-ack');
  rxCharacteristic = null;
  txCharacteristic = null;
  bluetoothDevice = null;
  updateStatus(false);
}

// -------------------------------------------------------------
// 2. Sending Data / Commands to Presto
// -------------------------------------------------------------
export async function sendRaw(str) {
  if (!rxCharacteristic) {
    console.warn('[BLE] sendRaw called but rxCharacteristic is null');
    return;
  }
  try {
    const encoder = new TextEncoder();
    const data = encoder.encode(str);
    if (rxCharacteristic.writeValueWithoutResponse) {
      await rxCharacteristic.writeValueWithoutResponse(data);
    } else if (rxCharacteristic.writeValueWithResponse) {
      await rxCharacteristic.writeValueWithResponse(data);
    } else {
      await rxCharacteristic.writeValue(data);
    }
    log('SENT', str, 'tag-sys');
  } catch (error) {
    console.error('[BLE Send Error]', error);
    log('ERR', `Send error: ${error.message || error}`, 'tag-ack');
  }
}

export function switchDeck(deckName) {
  if (currentDeckName === deckName) return;
  currentDeckName = deckName;
  log('DECK', `Switching Presto to deck: "${deckName}"`, 'tag-sys');
  sendRaw(`deck:${deckName}`);
}

export function updateButtonLabel(buttonId, newLabel) {
  log('BTN', `Updating button "${buttonId}" -> "${newLabel}"`, 'tag-sys');
  sendRaw(`btn:${buttonId}:${newLabel}`);
}

export function sendAlertNotification(text) {
  log('ALERT', `Sending alert: "${text}"`, 'tag-ack');
  sendRaw(`notify:${text}`);
}

// -------------------------------------------------------------
// 3. Handling Events Received from Presto Touchscreen
// -------------------------------------------------------------
async function handlePrestoEvent(event) {
  const value = event.target.value;
  const rawString = new TextDecoder('utf-8').decode(value);

  try {
    const data = JSON.parse(rawString);

    if (data.event === 'button_tap') {
      log('TAP', `Button tapped: "${data.label || data.id}" (action: ${data.action})`, 'tag-tap');
      await executePrestoAction(data.action || data.bt, data);
    } else if (data.event === 'notification_tap') {
      log('ACK', `Alert acknowledged on Presto: "${data.text}"`, 'tag-ack');
    } else {
      log('DATA', rawString, 'tag-sys');
    }
  } catch (e) {
    log('DATA', rawString, 'tag-sys');
  }
}

// Execute browser action triggered by Presto button
async function executePrestoAction(action, data) {
  if (!action) return;

  // 1. Jump to Tab or Open URL: "jump_tab:mail.google.com"
  if (action.startsWith('jump_tab:')) {
    const query = action.replace('jump_tab:', '').trim();
    await jumpOrOpenTab(query);
  }
  // 2. Open URL directly: "open_url:https://github.com"
  else if (action.startsWith('open_url:')) {
    const url = action.replace('open_url:', '').trim();
    chrome.tabs.create({ url });
  }
  // 3. Gmail Action: Select All
  else if (action === 'gmail_select_all') {
    await runInGmailTab(() => {
      const chk = document.querySelector('div[aria-label="Select"] input') ||
                  document.querySelector('span[role="checkbox"]') ||
                  document.querySelector('div[aria-label*="Select"]');
      if (chk) chk.click();
      else {
        document.dispatchEvent(new KeyboardEvent('keydown', { key: '*', keyCode: 56, bubbles: true }));
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'a', keyCode: 65, bubbles: true }));
      }
    });
    log('ACT', 'Executed: Gmail Select All', 'tag-tap');
  }
  // 4. Gmail Action: Archive
  else if (action === 'gmail_archive') {
    await runInGmailTab(() => {
      const btn = document.querySelector('div[aria-label="Archive"]') ||
                  document.querySelector('div[data-tooltip*="Archive"]');
      if (btn) btn.click();
      else {
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'e', keyCode: 69, bubbles: true }));
      }
    });
    log('ACT', 'Executed: Gmail Archive', 'tag-tap');
  }
  // 5. Gmail Action: Mark as Read
  else if (action === 'gmail_mark_read') {
    await runInGmailTab(() => {
      const btn = document.querySelector('div[aria-label="Mark as read"]') ||
                  document.querySelector('div[data-tooltip*="Mark as read"]');
      if (btn) btn.click();
      else {
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'I', keyCode: 73, shiftKey: true, bubbles: true }));
      }
    });
    log('ACT', 'Executed: Gmail Mark Read', 'tag-tap');
  }
  // 6. Gmail Action: Compose
  else if (action === 'gmail_compose') {
    await runInGmailTab(() => {
      const btn = document.querySelector('div[aria-label="Compose"]') ||
                  document.querySelector('div[gh="cm"]') ||
                  document.querySelector('.T-I.T-I-KE.L3');
      if (btn) btn.click();
      else {
        document.dispatchEvent(new KeyboardEvent('keydown', { key: 'c', keyCode: 67, bubbles: true }));
      }
    });
    log('ACT', 'Executed: Gmail Compose', 'tag-tap');
  }
  // 7. Switch Deck: "switch_deck:Workspace"
  else if (action.startsWith('switch_deck:')) {
    const name = action.replace('switch_deck:', '').trim();
    switchDeck(name);
  }
}

// Jump to existing tab matching query or open new one
async function jumpOrOpenTab(query) {
  const tabs = await chrome.tabs.query({});
  const matched = tabs.find(t => (t.url && t.url.includes(query)) || (t.title && t.title.toLowerCase().includes(query.toLowerCase())));

  if (matched) {
    await chrome.tabs.update(matched.id, { active: true });
    await chrome.windows.update(matched.windowId, { focused: true });
    log('TAB', `Focused tab: "${matched.title.slice(0, 30)}..."`, 'tag-sys');
  } else {
    const url = query.startsWith('http') ? query : `https://${query}`;
    chrome.tabs.create({ url });
    log('TAB', `Opened new tab: ${url}`, 'tag-sys');
  }
}

// Injects helper script into open Gmail tab
async function runInGmailTab(func) {
  const tabs = await chrome.tabs.query({ url: '*://mail.google.com/*' });
  if (tabs.length === 0) {
    log('WARN', 'No Gmail tab open.', 'tag-ack');
    return;
  }
  const targetTab = tabs.find(t => t.active) || tabs[0];
  try {
    await chrome.scripting.executeScript({
      target: { tabId: targetTab.id },
      func: func
    });
  } catch (err) {
    console.error('Script injection error:', err);
  }
}

// -------------------------------------------------------------
// 4. Tab Monitoring & State Sync
// -------------------------------------------------------------
// Check active tab and sync deck/button state
async function checkActiveTab() {
  try {
    const tabs = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    const activeTab = tabs && tabs.length > 0 ? tabs[0] : null;

    if (activeTab) {
      const isGmail = (activeTab.url && activeTab.url.includes('mail.google.com')) ||
                      (activeTab.title && activeTab.title.toLowerCase().includes('gmail'));

      // Auto switch deck based on focused tab
      if (autoSwitchDeck) {
        if (isGmail && currentDeckName !== 'Gmail') {
          switchDeck('Gmail');
        } else if (!isGmail && currentDeckName === 'Gmail') {
          switchDeck('Workspace');
        }
      }
    }

    // Check Gmail unread badge across all tabs
    if (monitorUnreadBadge) {
      await inspectGmailUnread();
    }
  } catch (err) {
    console.error('checkActiveTab error:', err);
  }
}

// Find Gmail tabs and parse unread count from title: e.g. "Inbox (1) - user@gmail.com"
async function inspectGmailUnread() {
  try {
    const allTabs = await chrome.tabs.query({});
    const gmailTabs = allTabs.filter(t =>
      (t.url && t.url.includes('mail.google.com')) ||
      (t.title && t.title.toLowerCase().includes('gmail'))
    );

    if (gmailTabs.length === 0) return;

    for (const tab of gmailTabs) {
      if (!tab.title) continue;
      const match = tab.title.match(/\((\d+)\)/);
      const count = match ? parseInt(match[1], 10) : 0;

      if (count !== lastGmailUnread) {
        lastGmailUnread = count;
        if (count > 0) {
          log('SYNC', `Gmail has ${count} unread email(s)! Setting button color to alert.`, 'tag-tap');
          sendRaw(`badge:${count}`);
        } else {
          log('SYNC', 'Gmail has 0 unread emails. Restoring button.', 'tag-sys');
          sendRaw('badge:0');
        }
      }
      break;
    }
  } catch (err) {
    console.error('inspectGmailUnread error:', err);
  }
}

// Listen to tab activation (switching tabs)
chrome.tabs.onActivated.addListener(() => {
  checkActiveTab();
});

// Listen to tab updates (page load, title changes like unread emails)
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  checkActiveTab();
});

// Poll every 1.5 seconds while connected to keep in sync
setInterval(() => {
  if (rxCharacteristic) {
    checkActiveTab();
  }
}, 1500);
