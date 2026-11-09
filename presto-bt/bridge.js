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
let monitorWaBadge = true;

let lastGmailUnread = null;
let lastWaUnread = null;
let lastSentTime = null;
let currentDeckName = 'Workspace';
let calendarScheduleText = '';
let activeCalendarKey = null;

// Load stored settings
chrome.storage.local.get(['autoSwitchDeck', 'monitorUnreadBadge', 'monitorWaBadge', 'calendarSchedule'], (res) => {
  if (res.autoSwitchDeck !== undefined) autoSwitchDeck = res.autoSwitchDeck;
  if (res.monitorUnreadBadge !== undefined) monitorUnreadBadge = res.monitorUnreadBadge;
  if (res.monitorWaBadge !== undefined) monitorWaBadge = res.monitorWaBadge;
  if (res.calendarSchedule !== undefined) calendarScheduleText = res.calendarSchedule;
});

// UI Callbacks
let uiLogCallback = null;
let uiStatusCallback = null;

export function registerCallbacks(onLog, onStatus) {
  uiLogCallback = onLog;
  uiStatusCallback = onStatus;
}

export function setOptions(autoSwitch, monitorUnread, monitorWa) {
  autoSwitchDeck = autoSwitch;
  monitorUnreadBadge = monitorUnread;
  if (monitorWa !== undefined) monitorWaBadge = monitorWa;
  chrome.storage.local.set({ autoSwitchDeck, monitorUnreadBadge, monitorWaBadge });
}

export function setCalendarSchedule(text) {
  calendarScheduleText = text || '';
  chrome.storage.local.set({ calendarSchedule: calendarScheduleText });
  inspectCalendarSchedule(true);
}

function log(type, message, tagClass = 'tag-sys') {
  if (uiLogCallback) uiLogCallback(type, message, tagClass);
}

function updateStatus(isConnected, deviceName = '') {
  if (uiStatusCallback) uiStatusCallback(isConnected, deviceName);
}

function withTimeout(promise, ms, errorMsg) {
  let timer;
  const timeoutPromise = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(errorMsg)), ms);
  });
  return Promise.race([promise, timeoutPromise]).finally(() => clearTimeout(timer));
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

    log('SYS', 'Discovering Nordic UART Service...');
    const service = await withTimeout(
      server.getPrimaryService(NUS_SERVICE_UUID),
      8000,
      'Service discovery timed out. Toggle Bluetooth off and on in macOS settings to clear stale GATT cache.'
    );

    rxCharacteristic = await service.getCharacteristic(NUS_RX_UUID);
    txCharacteristic = await service.getCharacteristic(NUS_TX_UUID);

    log('SYS', 'Subscribing to button press events...');
    await txCharacteristic.startNotifications();
    txCharacteristic.addEventListener('characteristicvaluechanged', handlePrestoEvent);

    updateStatus(true, bluetoothDevice.name || 'Presto');
    log('SYS', 'Presto connected! Two-way sync is active.', 'tag-tap');

    // Force-sync state upon fresh connection
    lastGmailUnread = null;
    lastWaUnread = null;
    lastSentTime = null;
    activeCalendarKey = null;
    currentDeckName = null;
    syncTime(true);
    inspectCalendarSchedule(true);
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
  lastSentTime = null;
  sendQueue = [];
  isSending = false;
  updateStatus(false);
}

// -------------------------------------------------------------
// 2. Sending Data / Commands to Presto
// -------------------------------------------------------------
let sendQueue = [];
let isSending = false;

export async function sendRaw(str) {
  sendQueue.push(str);
  if (isSending) return;
  isSending = true;

  while (sendQueue.length > 0) {
    const msg = sendQueue.shift();
    if (rxCharacteristic) {
      try {
        const encoder = new TextEncoder();
        const data = encoder.encode(msg);
        if (rxCharacteristic.writeValueWithoutResponse) {
          await rxCharacteristic.writeValueWithoutResponse(data);
        } else if (rxCharacteristic.writeValueWithResponse) {
          await rxCharacteristic.writeValueWithResponse(data);
        } else {
          await rxCharacteristic.writeValue(data);
        }
        log('SENT', msg, 'tag-sys');
      } catch (error) {
        console.error('[BLE Send Error]', error);
        log('ERR', `Send error: ${error.message || error}`, 'tag-ack');
      }
      // Pace writes so MicroPython event loop never drops/coalesces packets
      await new Promise(r => setTimeout(r, 45));
    }
  }
  isSending = false;
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

export function sendChunkedEvent(payload) {
  if (!payload || payload === 'clear') {
    sendRaw('event:clear');
    return;
  }
  const prefix = 'event:+';
  const maxBytes = 20 - new TextEncoder().encode(prefix).length; // 13 max payload bytes
  let cur = '';
  for (const ch of payload) {
    if (new TextEncoder().encode(cur + ch).length > maxBytes) {
      sendRaw(prefix + cur);
      cur = ch;
    } else {
      cur += ch;
    }
  }
  if (cur.length > 0) {
    sendRaw(prefix + cur);
  }
  sendRaw('event:eof');
}

export function syncTime(force = false) {
  if (!rxCharacteristic) return;
  const now = new Date();
  const hh = String(now.getHours()).padStart(2, '0');
  const mm = String(now.getMinutes()).padStart(2, '0');
  const timeStr = `${hh}:${mm}`;

  if (force || timeStr !== lastSentTime) {
    lastSentTime = timeStr;
    sendRaw(`time:${timeStr}`);
  }
}

// -------------------------------------------------------------
// 3. Handling Events Received from Presto Touchscreen
// -------------------------------------------------------------
async function handlePrestoEvent(event) {
  syncTime(false);
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
  syncTime(false);
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

    // Check WhatsApp unread badge across all tabs
    if (monitorWaBadge) {
      await inspectWhatsAppUnread();
    }

    // Check Calendar schedule
    inspectCalendarSchedule(false);
  } catch (err) {
    console.error('checkActiveTab error:', err);
  }
}

// Evaluate daily calendar schedule against current time
export function inspectCalendarSchedule(force = false) {
  if (!rxCharacteristic) return;
  if (!calendarScheduleText || !calendarScheduleText.trim()) {
    if (activeCalendarKey !== null) {
      activeCalendarKey = null;
      sendRaw('event:clear');
      log('CAL', 'Schedule cleared. Reverting Calendar button.', 'tag-sys');
    }
    return;
  }

  const now = new Date();
  const curMins = now.getHours() * 60 + now.getMinutes();
  const lines = calendarScheduleText.split('\n');
  let currentActive = null;

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) continue;

    // Matches: - 1430@5 1:1 with Alex  OR  0930@10 Daily Standup
    const match = line.match(/^(?:-\s*)?(\d{2})(\d{2})@(\d+)\s+(.+)$/);
    if (!match) continue;

    const hh = parseInt(match[1], 10);
    const mm = parseInt(match[2], 10);
    const minBefore = parseInt(match[3], 10);
    const label = match[4].trim();

    const eventMins = hh * 60 + mm;
    const startMins = eventMins - minBefore;
    const endMins = eventMins; // clears when meeting begins

    if (curMins >= startMins && curMins < endMins) {
      const timeStr = `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`;
      currentActive = {
        time: timeStr,
        label: label
      };
      break;
    }
  }

  const newKey = currentActive ? `${currentActive.time}:${currentActive.label}` : null;
  if (newKey !== activeCalendarKey || force) {
    activeCalendarKey = newKey;
    if (currentActive) {
      // Chunked streaming allows long meeting titles without BLE 20-byte truncation
      const fullPayload = `${currentActive.time}\\n${currentActive.label}`;
      sendChunkedEvent(fullPayload);
      log('CAL', `Upcoming event: "${currentActive.label}" at ${currentActive.time}`, 'tag-tap');
    } else {
      sendRaw('event:clear');
      log('CAL', 'Event window passed. Reverting Calendar button.', 'tag-sys');
    }
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
          sendRaw(`badge:gmail:${count}`);
        } else {
          log('SYNC', 'Gmail has 0 unread emails. Restoring button.', 'tag-sys');
          sendRaw('badge:gmail:0');
        }
      }
      break;
    }
  } catch (err) {
    console.error('inspectGmailUnread error:', err);
  }
}

// Find WhatsApp Web tabs and parse unread count from title: e.g. "(3) WhatsApp" or "(*) WhatsApp"
async function inspectWhatsAppUnread() {
  try {
    const allTabs = await chrome.tabs.query({});
    const waTabs = allTabs.filter(t =>
      (t.url && (t.url.includes('web.whatsapp.com') || t.url.includes('whatsapp.com'))) ||
      (t.title && t.title.toLowerCase().includes('whatsapp'))
    );

    if (waTabs.length === 0) return;

    for (const tab of waTabs) {
      if (!tab.title) continue;
      const match = tab.title.match(/\(([^)]+)\)/);
      let count = 0;
      if (match) {
        const raw = match[1].trim();
        if (raw === '*') count = 1;
        else if (raw.endsWith('+')) count = parseInt(raw, 10) || 99;
        else count = parseInt(raw, 10) || 0;
      }

      if (count !== lastWaUnread) {
        lastWaUnread = count;
        if (count > 0) {
          log('SYNC', `WhatsApp has ${count} unread chat(s)! Setting WA button to alert.`, 'tag-tap');
          sendRaw(`badge:wa:${count}`);
        } else {
          log('SYNC', 'WhatsApp has 0 unread chats. Restoring WA button.', 'tag-sys');
          sendRaw('badge:wa:0');
        }
      }
      break;
    }
  } catch (err) {
    console.error('inspectWhatsAppUnread error:', err);
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
