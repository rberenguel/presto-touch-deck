import {
  connectPresto,
  disconnectPresto,
  switchDeck,
  sendRaw,
  sendChunkedEvent,
  syncTime,
  setCalendarSchedule,
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
const chkMonitorWa = document.getElementById('chk-monitor-wa');
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

function syncSettings() {
  const autoSwitch = chkAutoSwitch ? chkAutoSwitch.checked : true;
  const monGmail = chkMonitorUnread ? chkMonitorUnread.checked : true;
  const monWa = chkMonitorWa ? chkMonitorWa.checked : true;
  setOptions(autoSwitch, monGmail, monWa);
}

chkAutoSwitch.addEventListener('change', syncSettings);
chkMonitorUnread.addEventListener('change', syncSettings);
if (chkMonitorWa) chkMonitorWa.addEventListener('change', syncSettings);

btnClearLog.addEventListener('click', () => {
  eventLog.innerHTML = '';
  appendLog('SYS', 'Event log cleared.');
});

// Quick Deck Switching buttons
btnDeckWorkspace.addEventListener('click', () => switchDeck('Workspace'));
btnDeckGmail.addEventListener('click', () => switchDeck('Gmail'));
if (btnDeckDev) btnDeckDev.addEventListener('click', () => switchDeck('Dev Deck'));

const btnTestBadge2 = document.getElementById('btn-test-badge-2');
if (btnTestBadge2) btnTestBadge2.addEventListener('click', () => sendRaw('badge:gmail:2'));

const btnTestBadge0 = document.getElementById('btn-test-badge-0');
if (btnTestBadge0) btnTestBadge0.addEventListener('click', () => sendRaw('badge:gmail:0'));

const btnTestWa1 = document.getElementById('btn-test-wa-1');
if (btnTestWa1) btnTestWa1.addEventListener('click', () => sendRaw('badge:wa:1'));

const btnTestWa0 = document.getElementById('btn-test-wa-0');
if (btnTestWa0) btnTestWa0.addEventListener('click', () => sendRaw('badge:wa:0'));

const btnSyncTime = document.getElementById('btn-sync-time');
if (btnSyncTime) btnSyncTime.addEventListener('click', () => syncTime(true));

// Calendar Schedule UI
const txtCalendar = document.getElementById('txt-calendar');
const btnSaveCal = document.getElementById('btn-save-cal');
const btnTestCalEvent = document.getElementById('btn-test-cal-event');
const btnTestCalClear = document.getElementById('btn-test-cal-clear');

// Load stored calendar schedule into textarea
chrome.storage.local.get(['calendarSchedule'], (res) => {
  if (res.calendarSchedule && txtCalendar) {
    txtCalendar.value = res.calendarSchedule;
  }
});

if (txtCalendar) {
  txtCalendar.addEventListener('input', () => {
    setCalendarSchedule(txtCalendar.value);
  });
}

if (btnSaveCal) {
  btnSaveCal.addEventListener('click', () => {
    setCalendarSchedule(txtCalendar ? txtCalendar.value : '');
    appendLog('CAL', 'Schedule saved and synchronized.', 'tag-tap');
  });
}

if (btnTestCalEvent) {
  btnTestCalEvent.addEventListener('click', () => {
    sendChunkedEvent('21:25\\nSprint Retrospective & Team Sync');
    appendLog('TEST', 'Sent test chunked calendar event: "21:25\\nSprint Retrospective & Team Sync"', 'tag-tap');
  });
}

if (btnTestCalClear) {
  btnTestCalClear.addEventListener('click', () => {
    sendRaw('event:clear');
    appendLog('TEST', 'Sent calendar clear', 'tag-sys');
  });
}

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
