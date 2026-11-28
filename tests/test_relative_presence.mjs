import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';

const source = readFileSync(new URL('../community_bot/web/people.js', import.meta.url), 'utf8');
const start = source.indexOf('function presenceLine(p) {');
const end = source.indexOf('function beat(active)', start);
assert.ok(start >= 0 && end > start, 'Presence formatter exists');
const snippet = source.slice(start, end);

const now = Date.parse('2026-11-22T12:49:00Z');
class TestDate extends Date {
  constructor(...args) { super(...(args.length ? args : [now])); }
  static now() { return now; }
  toLocaleTimeString(locale, options) {
    return new Date(this.valueOf()).toLocaleTimeString(locale, {...options, timeZone: 'UTC'});
  }
  toDateString() {
    return new Date(this.valueOf()).toUTCString().slice(0, 16);
  }
}
const plural = (n, one, few, many) =>
  n % 100 >= 11 && n % 100 <= 14 ? many : n % 10 === 1 ? one :
  n % 10 >= 2 && n % 10 <= 4 ? few : many;
const presence = new Function('Date', 'plural', 'p', snippet + 'return presenceLine(p);');
const stamp = value => Date.parse(value) / 1000;

test('consistent Telegram-style online and relative timestamps', () => {
  const cases = [
    [{visible:true,online:true,last_seen:stamp('2026-11-22T12:48:00Z')}, 'В сети'],
    [{visible:true,online:false,last_seen:stamp('2026-11-22T12:48:00Z')}, 'Был 1 минуту назад'],
    [{visible:true,online:false,last_seen:stamp('2026-11-22T11:50:00Z')}, 'Был 59 минут назад'],
    [{visible:true,online:false,last_seen:stamp('2026-11-22T10:30:00Z')}, 'Был в 10:30'],
    [{visible:true,online:false,last_seen:stamp('2026-11-21T10:30:00Z')}, 'Был в сети вчера'],
    [{visible:true,online:false,last_seen:stamp('2026-11-15T10:30:00Z')}, 'Был в сети 7 дней назад'],
    [{visible:true,online:false,last_seen:stamp('2026-11-14T10:30:00Z')}, 'Был в сети давно'],
    [{visible:false,online:true,last_seen:stamp('2026-11-22T12:48:00Z')}, 'Активность скрыта'],
  ];
  for (const [input, expected] of cases) assert.equal(presence(TestDate, plural, input), expected);
});

test('unknown activity is not invented', () => {
  assert.equal(presence(TestDate, plural, {visible:true,online:false,last_seen:null}),
               'Ещё не был в сети');
});
