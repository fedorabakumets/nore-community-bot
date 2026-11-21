'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const source = fs.readFileSync(
  path.join(__dirname, '..', 'community_bot', 'web', 'staff-chat.js'), 'utf8',
);
const window = {
  visualViewport: {addEventListener() {}},
  addEventListener() {},
};
const document = {addEventListener() {}};
const deliverySource=fs.readFileSync(
  path.join(__dirname, '..', 'community_bot', 'web', 'staff-chat-delivery.js'), 'utf8',
);
vm.runInNewContext(deliverySource, {window,document,console,setTimeout,clearTimeout});
vm.runInNewContext(source, {
  window, document, esc: value => String(value),
  console, setTimeout, clearTimeout, setInterval, clearInterval,
});
assert.ok(window.NoraStaffChat, 'Chat script must initialize');
const html = window.NoraStaffChat.screen();
assert.match(html, /id="staff-chat-feed"/);
assert.match(html, /id="staff-chat-compose"/);
assert.match(html, /id="staff-chat-file"[^>]*multiple/);
assert.match(html, /data-chat-record/);
assert.match(html, /id="staff-chat-record-status"/);
assert.match(html, /id="staff-chat-compose-file"/);
assert.match(html, /data-chat-attach/);
assert.match(html, /id="staff-chat-draft"/);
assert.match(html, /id="staff-chat-submit"/);
assert.ok(source.includes('groupAlbums(items)'), 'Album grouping must be wired to feed');
assert.ok(source.includes('staff-chat-voice-progress'), 'Voice seeking control must exist');
assert.ok(source.includes('stopRecording(true)'), 'Recordings must be stopped on exit');
assert.match(html, /id="staff-chat-delivery"/);
assert.ok(source.includes("form.append('operation_id'"), 'Media operation ID included');
assert.ok(source.includes('delivery.check()'), 'Status recovery wired');

console.log('NORA stage 7 media UI smoke checks passed');
