import {
  connectPresto,
  disconnectPresto,
  switchDeck,
  sendRaw,
  registerCallbacks,
  setOptions
} from './bridge.js';

// DOM Elements
const statusPill = document.getElementById('status-pill');
const statusText = document.getElementById('status-text');
const btnConnect = document.getElementById('btn-connect');
const btnDisconnect = document.getElementById('btn-disconnect');
const chkAutoSwitch = document.getElementById('chk-auto-switch');
const chkMonitorUnread = document.getElementById('chk-monitor-unread');
const eventLog = document.getElementById('event-log');
const btnClearLog = document.getElementById('btn-clear-log');
const linkSidepanel = document.getElementById('link-sidepanel');

const btnDeckWorkspace = document.getElementById('btn-deck-workspace');
const btnDeckGmail = document.getElementById('btn-deck-gmail');
const btnDeckDev = document.getElementById('btn-deck-dev');

function getTimestamp() {
  const d = new Date();
  return d.toTimeString().split(' ')[0];
}

function appendLog(type, message, tagClass = 'tag-sys') {
  const entry = document.createElement('div');
  entry.className = 'event-entry';

  const timeSpan = document.createElement('span');
  timeSpan.className = 'event-time';
  timeSpan.textContent = getTimestamp();

  const tagSpan = document.createElement('span');
  tagSpan.className = `event-tag ${tagClass}`;
  tagSpan.textContent = type;

  const msgSpan = document.createElement('span');
  msgSpan.className = 'event-msg';
  msgSpan.textContent = message;

  entry.appendChild(timeSpan);
  entry.appendChild(tagSpan);
  entry.appendChild(msgSpan);

  eventLog.appendChild(entry);
  eventLog.scrollTop = eventLog.scrollHeight;
}

function updateStatusUI(isConnected, deviceName = '') {
  if (isConnected) {
    statusPill.className = 'status-pill connected';
    statusText.textContent = `Connected: ${deviceName || 'Presto-Deck'}`;
    btnConnect.disabled = true;
    btnDisconnect.disabled = false;
  } else {
    statusPill.className = 'status-pill';
    statusText.textContent = 'Disconnected';
    btnConnect.disabled = false;
    btnDisconnect.disabled = true;
  }
}

// Register bridge callbacks
registerCallbacks(appendLog, updateStatusUI);

// Event Listeners
btnConnect.addEventListener('click', connectPresto);
btnDisconnect.addEventListener('click', disconnectPresto);

chkAutoSwitch.addEventListener('change', () => {
  setOptions(chkAutoSwitch.checked, chkMonitorUnread.checked);
});

chkMonitorUnread.addEventListener('change', () => {
  setOptions(chkAutoSwitch.checked, chkMonitorUnread.checked);
});

btnClearLog.addEventListener('click', () => {
  eventLog.innerHTML = '';
  appendLog('SYS', 'Event log cleared.');
});

// Quick Deck Switching buttons
btnDeckWorkspace.addEventListener('click', () => switchDeck('Workspace'));
btnDeckGmail.addEventListener('click', () => switchDeck('Gmail'));
btnDeckDev.addEventListener('click', () => switchDeck('Dev Deck'));

const btnTestBadge2 = document.getElementById('btn-test-badge-2');
if (btnTestBadge2) btnTestBadge2.addEventListener('click', () => sendRaw('badge:2'));

const btnTestBadge0 = document.getElementById('btn-test-badge-0');
if (btnTestBadge0) btnTestBadge0.addEventListener('click', () => sendRaw('badge:0'));

// Side panel link
if (linkSidepanel) {
  linkSidepanel.addEventListener('click', async () => {
    if (chrome.sidePanel && chrome.sidePanel.open) {
      const window = await chrome.windows.getCurrent();
      await chrome.sidePanel.open({ windowId: window.id });
      window.close(); // close popup
    } else {
      chrome.tabs.create({ url: chrome.runtime.getURL('sidepanel.html') });
    }
  });
}
