import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {runInNewContext} from 'node:vm';

const home = readFileSync(new URL('../community_bot/web/home.js', import.meta.url), 'utf8');
const app = readFileSync(new URL('../community_bot/web/app.js', import.meta.url), 'utf8');
const start = home.indexOf('function profileWizard(index){');
const end = home.indexOf("document.addEventListener('click',e=>", start);
assert.ok(start !== -1 && end > start, 'Profile wizard function is present');
const wizardSource = home.slice(start, end);

function scenario(uploadPhoto) {
  const file = {name: 'avatar.jpeg', size: 1024};
  const button = {disabled: false, textContent: 'Завершить'};
  const form = {
    querySelector(selector) {
      if (selector === '[data-wizard-back]') return null;
      if (selector === '[type=submit]') return button;
      if (selector === 'input') return {files: [file]};
      throw Error('Unexpected form selector: ' + selector);
    },
  };
  let html = '', error = '';
  const initial = {
    revision: 'revision-123',
    has_avatar: false,
    user: {},
    profile: {fill_percent: 80, blocks: Array.from({length: 5}, (_, i) => ({filled: i < 4}))},
  };
  const context = {
    data: initial,
    AVATAR_MAX_MB: 64,
    AVATAR_ACCEPT: 'image/*,.heic,.heif',
    busy: false,
    sheet(markup) { html = markup; },
    $(selector) {
      if (selector === '#wizard-form') return form;
      if (selector === '#sheet') return {open: true};
      throw Error('Unexpected selector: ' + selector);
    },
    esc: String,
    uploadPhoto,
    async api(path) {
      assert.equal(path, 'me');
      return {...initial, profile: {...initial.profile, fill_percent: 100}};
    },
    render() {},
    toast(message) { error = message; },
  };
  runInNewContext(wizardSource, context);
  context.profileWizard(4);
  return {file, button, form, context, get html() {return html;}, get error() {return error;}};
}

test('avatar wizard uses existing authorized profile upload and completes', async () => {
  let args;
  const s = scenario(async (...values) => { args = values; });
  assert.match(s.html, /Шаг 5 из 5/);
  await s.form.onsubmit({preventDefault() {}});
  assert.equal(args[0], s.file);
  assert.equal(args[1], 'profile/avatar');
  assert.equal(args[2]['X-Profile-Revision'], 'revision-123');
  assert.match(s.html, /Профиль заполнен!/);
  assert.equal(s.context.busy, false);
  assert.match(app, /async function uploadPhoto\(file, endpoint, headers\)/);
});

test('failed avatar upload displays error and allows retry', async () => {
  const s = scenario(async () => { throw Error('Сервер отклонил фото'); });
  await s.form.onsubmit({preventDefault() {}});
  assert.equal(s.error, 'Сервер отклонил фото');
  assert.equal(s.button.disabled, false);
  assert.equal(s.button.textContent, 'Завершить');
  assert.equal(s.context.busy, false);
});
