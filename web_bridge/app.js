// Presto Deck — Web Bluetooth Client Implementation
const NUS_SERVICE_UUID = '6e400001-b5a3-f393-e0a9-e50e24dcca9e';
const NUS_RX_UUID = '6e400002-b5a3-f393-e0a9-e50e24dcca9e';
const NUS_TX_UUID = '6e400003-b5a3-f393-e0a9-e50e24dcca9e';

let bluetoothDevice = null;
let rxCharacteristic = null;
let txCharacteristic = null;

// UI Elements
const statusPill = document.getElementById('status-pill');
const statusText = document.getElementById('status-text');
const btnConnect = document.getElementById('btn-connect');
const btnDisconnect = document.getElementById('btn-disconnect');
const btnSendNotify = document.getElementById('btn-send-notify');
const notifyInput = document.getElementById('notify-input');
const eventLog = document.getElementById('event-log');

// Format timestamp HH:MM:SS
function getTimestamp() {
  const d = new Date();
  return d.toTimeString().split(' ')[0];
}

// Append event to live stream UI
function logEvent(type, message, tagClass = 'tag-sys') {
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

function clearLog() {
  eventLog.innerHTML = '';
  logEvent('SYS', 'Event log cleared.');
}

// Update UI Connection State
function setConnectedState(isConnected, deviceName = '') {
  if (isConnected) {
    statusPill.className = 'status-pill connected';
    statusText.textContent = `Connected: ${deviceName || 'Presto-Deck'}`;
    btnConnect.disabled = true;
    btnDisconnect.disabled = false;
    btnSendNotify.disabled = false;
  } else {
    statusPill.className = 'status-pill';
    statusText.textContent = 'Disconnected';
    btnConnect.disabled = false;
    btnDisconnect.disabled = true;
    btnSendNotify.disabled = true;
  }
}

// Connect to Presto via Web Bluetooth
async function connectPresto() {
  if (!navigator.bluetooth) {
    alert('Web Bluetooth is not supported in this browser. Please open this page in Google Chrome or Microsoft Edge.');
    return;
  }

  try {
    logEvent('SYS', 'Requesting Bluetooth device matching "Presto"...');

    bluetoothDevice = await navigator.bluetooth.requestDevice({
      filters: [
        { name: 'Presto-Deck' },
        { namePrefix: 'Presto' }
      ],
      optionalServices: [NUS_SERVICE_UUID]
    });

    logEvent('SYS', `Selected device: ${bluetoothDevice.name}. Connecting GATT...`);
    bluetoothDevice.addEventListener('gattserverdisconnected', onDisconnected);

    const server = await bluetoothDevice.gatt.connect();
    logEvent('SYS', 'GATT connected. Discovering Nordic UART Service...');

    const service = await server.getPrimaryService(NUS_SERVICE_UUID);
    rxCharacteristic = await service.getCharacteristic(NUS_RX_UUID);
    txCharacteristic = await service.getCharacteristic(NUS_TX_UUID);

    logEvent('SYS', 'Subscribing to Presto TX notifications...');
    await txCharacteristic.startNotifications();
    txCharacteristic.addEventListener('characteristicvaluechanged', handleIncomingNotification);

    setConnectedState(true, bluetoothDevice.name);
    logEvent('SYS', 'Bridge ready! Bidirectional communication established.', 'tag-tap');
  } catch (error) {
    console.error('Bluetooth connection failed:', error);
    if (error.name !== 'NotFoundError') {
      logEvent('ERR', `Connection failed: ${error.message || error}`, 'tag-ack');
    } else {
      logEvent('SYS', 'Connection prompt cancelled by user.');
    }
    setConnectedState(false);
  }
}

// Handle disconnection
function onDisconnected() {
  logEvent('SYS', 'Device disconnected.', 'tag-ack');
  rxCharacteristic = null;
  txCharacteristic = null;
  bluetoothDevice = null;
  setConnectedState(false);
}

// Disconnect manually
function disconnectPresto() {
  if (bluetoothDevice && bluetoothDevice.gatt.connected) {
    bluetoothDevice.gatt.disconnect();
    logEvent('SYS', 'Disconnected by user.');
  }
  setConnectedState(false);
}

// Handle incoming notifications from Presto Deck
function handleIncomingNotification(event) {
  const value = event.target.value;
  const decoder = new TextDecoder('utf-8');
  const rawString = decoder.decode(value);

  try {
    const data = JSON.parse(rawString);

    if (data.event === 'button_tap') {
      logEvent(
        'TAP',
        `Button: "${data.label || data.id}" (id: ${data.id}, action: ${data.action || 'none'})`,
        'tag-tap'
      );
    } else if (data.event === 'notification_tap') {
      logEvent('ACK', `User acknowledged alert on Presto: "${data.text}"`, 'tag-ack');
    } else {
      logEvent('DATA', rawString, 'tag-sys');
    }
  } catch (e) {
    // Plain string notification
    logEvent('DATA', rawString, 'tag-sys');
  }
}

// Send notification payload to Presto
async function sendPayload(payload) {
  if (!rxCharacteristic) {
    alert('Please connect to Presto Deck first.');
    return;
  }

  try {
    const encoder = new TextEncoder();
    const data = encoder.encode(typeof payload === 'string' ? payload : JSON.stringify(payload));
    await rxCharacteristic.writeValue(data);
  } catch (error) {
    console.error('Send error:', error);
    logEvent('ERR', `Failed to send data: ${error.message}`, 'tag-ack');
  }
}

// Send custom notification from input
async function sendCustomNotification() {
  const text = notifyInput.value.trim();
  if (!text) return;
  await sendPayload({ notify: text });
  logEvent('SENT', `Sent alert to deck: "${text}"`, 'tag-sys');
  notifyInput.value = '';
}

// Quick presets
async function quickSend(text) {
  await sendPayload({ notify: text });
  logEvent('SENT', `Sent alert to deck: "${text}"`, 'tag-sys');
}

async function quickClear() {
  await sendPayload({ clear: true });
  logEvent('SENT', 'Sent clear notification request', 'tag-ack');
}

// Enter key in input sends notification
notifyInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    sendCustomNotification();
  }
});
