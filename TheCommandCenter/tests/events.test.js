import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  appendEvent,
  replaceHistory,
  summarize,
  filterEvents,
  timeline,
  toCsv,
  riskLevel,
} from '../src/events.js'

const now = Date.parse('2026-09-12T10:00:00Z')
const event = (id, score = 40, severity = 4) => ({
  event_id: id,
  danger_score: score,
  processed_at: new Date(now).toISOString(),
  scoring_method: 'llm',
  log: { time: '10:00:00', type: 'Port Scan', origin: '192.0.2.1', severity },
})

test('failed AI assessments retain logs without inventing scores or insights', () => {
  const failed = { ...event('failed', null, 9), insight: ['stale', 'insight'], respondsuggested: ['stale', 'response'] }
  const records = replaceHistory([failed, { ...event('unscored', null), log: { event: 'Login', source: '10.0.0.5', status: 'Failed' } }])
  assert.equal(records.length, 2)
  assert.equal(records[0].danger_score, null)
  assert.deepEqual(records[0].insight, [])
  assert.deepEqual(records[0].respondsuggested, [])
  assert.equal(records[0].risk, 90)
  assert.equal(records[1].risk, null)
  assert.equal(riskLevel(records[1].risk), 'unknown')
  assert.equal(filterEvents(records, { severity: 'low' }).length, 0)
  assert.equal(summarize(records, now).score, 90)
  assert.equal(timeline(records, now).at(-1).count, 2)
  assert.equal(appendEvent([], failed).length, 1)
  assert.doesNotMatch(toCsv(records), /null|undefined/)
})

test('reconnect snapshots replace and deduplicate retained history', () => {
  assert.equal(replaceHistory([event('one'), event('one')]).length, 1)
  assert.deepEqual(replaceHistory([]), [])
  assert.equal(
    appendEvent(replaceHistory([event('one')]), event('one')).length,
    1,
  )
})
test('gauge distinguishes unknown risk, mixed coverage and no recent events', () => {
  const unscored = { ...event('unscored', null), log: { event: 'Login', source: '10.0.0.5', status: 'Failed' } }
  const records = replaceHistory([unscored])
  const unknown = summarize(records, now)
  assert.equal(unknown.score, null)
  assert.equal(unknown.level, 'unknown')
  assert.equal(unknown.recent, 1)
  assert.equal(unknown.unknownRisk, 1)
  const mixed = summarize(replaceHistory([unscored, event('attack', null, 9)]), now)
  assert.equal(mixed.score, 90)
  assert.equal(mixed.level, 'critical')
  assert.equal(mixed.unknownRisk, 1)
  for (const summary of [summarize([], now), summarize(records, now + 300001), summarize(records, now - 1)]) {
    assert.equal(summary.score, 0)
    assert.equal(summary.recent, 0)
    assert.equal(summary.unknownRisk, 0)
  }
  assert.equal(summarize(replaceHistory([event('known')]), now).unknownRisk, 0)
})
test('high source severity triggers critical gauge even with a lower LLM estimate', () => {
  assert.equal(
    summarize(replaceHistory([event('one', 40, 9)]), now).level,
    'critical',
  )
  assert.equal(summarize(replaceHistory([event('one', 40, 9)]), now).score, 90)
})
test('threat gauge ages out and excludes future records', () => {
  const events = replaceHistory([event('one', 90)])
  assert.equal(summarize(events, now + 300001).score, 0)
  assert.equal(summarize(events, now - 1).score, 0)
})
test('history stays bounded and invalid payloads are rejected', () => {
  assert.equal(
    replaceHistory(
      Array.from({ length: 1100 }, (_, index) => event(String(index))),
    ).length,
    1000,
  )
  assert.equal(
    replaceHistory([{ ...event('bad'), danger_score: '90' }]).length,
    0,
  )
  assert.throws(() => appendEvent([], {}))
  assert.throws(() => replaceHistory({}))
})
test('malformed source severity cannot corrupt the gauge or event inspector', () => {
  for (const severity of [
    0,
    10,
    100,
    1.5,
    '9',
    '<img src=x onerror=alert(1)>',
    null,
  ]) {
    assert.equal(replaceHistory([event('invalid', 40, severity)]).length, 0)
  }
})
test('filters preserve source distinction and search matches IPs', () => {
  const legacy = {
    ...event('legacy'),
    log: { event: 'File Access', source: '10.0.0.5', status: 'Denied' },
  }
  const events = replaceHistory([event('attack', 90, 9), legacy])
  assert.equal(
    filterEvents(events, { source: 'legacy' })[0].title,
    'File Access',
  )
  assert.equal(
    filterEvents(events, { severity: 'critical', query: '192.0' }).length,
    1,
  )
})
test('timeline uses processing timestamps and CSV escapes formulas and quotes', () => {
  const events = replaceHistory([
    { ...event('one'), log: { ...event('one').log, type: '=SUM("x")' } },
  ])
  assert.equal(timeline(events, now).at(-1).count, 1)
  assert.match(toCsv(events), /'=SUM\(""x""\)/)
})

test('new events appear first even when delivery is out of order', () => {
  const older = {
    ...event('older'),
    processed_at: new Date(now - 1000).toISOString(),
  }
  const newest = {
    ...event('newest'),
    processed_at: new Date(now + 1000).toISOString(),
  }
  let history = replaceHistory([event('current'), older])
  history = appendEvent(history, newest)
  history = appendEvent(history, older)
  assert.deepEqual(
    filterEvents(history, {}).map((record) => record.event_id),
    ['newest', 'current', 'older'],
  )
})

test('customer summaries and exports combine ingestion sources', () => {
  const legacy = {
    ...event('event-2'),
    log: { event: 'File Access', source: '10.0.0.5', status: 'Denied' },
  }
  const history = replaceHistory([event('attack'), legacy])
  const summary = summarize(history, now)
  assert.equal(summary.recent, 2)
  assert.deepEqual(summary.types, [
    ['Port Scan', 1],
    ['File Access', 1],
  ])
  assert.equal(history[0].status, 'Detected')
  assert.doesNotMatch(
    toCsv(history),
    /Source|simulator|legacy|Simulated attack/,
  )
})

test('AI assessment survives snapshot and live event normalization', () => {
  const assessed = {
    ...event('assessed'),
    insight: [' Observed activity ', '<img src=x onerror=alert(1)>'],
    respondsuggested: ['Review related logs', 'Verify account activity'],
  }
  const snapshot = replaceHistory([assessed])
  assert.deepEqual(snapshot[0].insight, ['Observed activity', '<img src=x onerror=alert(1)>'])
  const live = appendEvent([], assessed)
  assert.deepEqual(live[0].respondsuggested, assessed.respondsuggested)
})

test('old or malformed AI assessments do not hide otherwise valid events', () => {
  for (const points of [undefined, null, 'text', [], ['one'], ['one', 'two', 'three'], [1, 'two'], [' ', 'two'], ['x'.repeat(401), 'two']]) {
    for (const field of ['insight', 'respondsuggested']) {
      const payload = { ...event('old'), insight: ['one', 'two'], respondsuggested: ['one', 'two'], [field]: points }
      const [record] = replaceHistory([payload])
      assert.equal(record.event_id, 'old')
      assert.deepEqual(record.insight, [])
      assert.deepEqual(record.respondsuggested, [])
    }
  }
})
