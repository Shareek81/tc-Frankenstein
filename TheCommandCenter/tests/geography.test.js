import test from 'node:test'
import assert from 'node:assert/strict'
import { globePosition, uniqueOrigins } from '../src/geography.js'

test('origin list deduplicates and aggregates count and peak risk', () => {
  assert.deepEqual(uniqueOrigins([
    { origin: '8.8.8.8', risk: 30 }, { origin: '8.8.8.8', risk: 90 },
    { origin: '10.0.0.5', risk: 10 }, { origin: '-', risk: 10 },
  ]), [{ ip: '8.8.8.8', count: 2, risk: 90 }, { ip: '10.0.0.5', count: 1, risk: 10 }])
})

test('geographic coordinates match Earth texture axes on a unit sphere', () => {
  const near = (actual, expected) => actual.forEach((value, index) => assert.ok(Math.abs(value - expected[index]) < 1e-10))
  near(globePosition(0, 0), [1, 0, 0])
  near(globePosition(0, 90), [0, 0, -1])
  near(globePosition(90, 0), [0, 1, 0])
  near(globePosition(0, -90), [0, 0, 1])
  for (const coordinates of [[91, 0], [0, 181], [NaN, 0], [0, '10']]) {
    assert.throws(() => globePosition(...coordinates))
  }
})