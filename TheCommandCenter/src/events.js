export const HISTORY_LIMIT = 1000
export const THREAT_WINDOW_MS = 5 * 60 * 1000

function validPoints(points) {
  return Array.isArray(points) && points.length === 2 && points.every(
    point => typeof point === 'string' && point.trim().length > 0 && [...point].length <= 400,
  )
}

export function normalizeEvent(event) {
  if (
    !event ||
    typeof event.event_id !== 'string' ||
    !event.event_id ||
    (event.danger_score !== null &&
      (!Number.isInteger(event.danger_score) || event.danger_score < 1 || event.danger_score > 100)) ||
    !event.log ||
    !Number.isFinite(Date.parse(event.processed_at))
  )
    return null
  const attack = typeof event.log.type === 'string'
  const severity = event.log.severity
  if (
    (attack || severity !== undefined) &&
    (!Number.isInteger(severity) || severity < 1 || severity > 9)
  )
    return null
  const hasAssessment = event.danger_score !== null && validPoints(event.insight) && validPoints(event.respondsuggested)
  return {
    ...event,
    insight: hasAssessment ? event.insight.map(point => point.trim()) : [],
    respondsuggested: hasAssessment ? event.respondsuggested.map(point => point.trim()) : [],
    source: attack ? 'simulator' : 'legacy',
    title: String(
      attack ? event.log.type : (event.log.event ?? 'Unknown event'),
    ),
    origin: String(
      attack
        ? (event.log.origin ?? 'Unknown')
        : (event.log.source ?? 'Unknown'),
    ),
    sourceTime: String(
      attack ? (event.log.time ?? '') : (event.log.timestamp ?? ''),
    ),
    status: String(attack ? 'Detected' : (event.log.status ?? 'Unknown')),
    timestamp: Date.parse(event.processed_at),
    risk: event.danger_score === null && !attack ? null : Math.max(
      event.danger_score,
      attack && Number.isInteger(event.log.severity)
        ? event.log.severity * 10
        : 0,
    ),
  }
}

export function replaceHistory(payload) {
  if (!Array.isArray(payload)) throw new Error('Invalid snapshot')
  const events = new Map()
  for (const record of payload) {
    const event = normalizeEvent(record)
    if (event) events.set(event.event_id, event)
  }
  return [...events.values()]
    .sort((first, second) => first.timestamp - second.timestamp)
    .slice(-HISTORY_LIMIT)
}

export function appendEvent(events, payload) {
  const event = normalizeEvent(payload)
  if (!event) throw new Error('Invalid event')
  return replaceHistory([
    ...events.filter((record) => record.event_id !== event.event_id),
    event,
  ])
}

export function riskLevel(score) {
  if (score === null) return 'unknown'
  return score >= 80
    ? 'critical'
    : score >= 60
      ? 'high'
      : score >= 30
        ? 'elevated'
        : 'low'
}

export function summarize(events, now = Date.now()) {
  const recent = events.filter(
    (event) =>
      event.timestamp <= now && now - event.timestamp <= THREAT_WINDOW_MS,
  )
  const unknownRisk = recent.filter((event) => event.risk === null).length
  const score = recent.length > 0 && unknownRisk === recent.length
    ? null
    : recent.reduce((peak, event) => Math.max(peak, event.risk ?? 0), 0)
  const attacks = events.filter((event) => event.source === 'simulator')
  const types = new Map()
  for (const event of events)
    types.set(event.title, (types.get(event.title) ?? 0) + 1)
  return {
    score,
    level: riskLevel(score),
    total: events.length,
    recent: recent.length,
    unknownRisk,
    critical: events.filter((event) => event.risk >= 80).length,
    origins: new Set(events.map((event) => event.origin)).size,
    attacks: attacks.length,
    legacy: events.length - attacks.length,
    latest: events.at(-1),
    types: [...types.entries()].sort((first, second) => second[1] - first[1]),
  }
}

export function filterEvents(
  events,
  { query = '', source = 'all', severity = 'all' },
) {
  const term = query.trim().toLowerCase()
  return events
    .filter(
      (event) =>
        (source === 'all' || event.source === source) &&
        (severity === 'all' || riskLevel(event.risk) === severity) &&
        `${event.title} ${event.origin} ${event.status} ${event.event_id}`
          .toLowerCase()
          .includes(term),
    )
    .toReversed()
}

export function timeline(events, now = Date.now()) {
  const minute = Math.floor(now / 60000) * 60000
  return Array.from({ length: 12 }, (_, index) => {
    const start = minute - (11 - index) * 60000
    const bucket = events.filter(
      (event) => event.timestamp >= start && event.timestamp < start + 60000,
    )
    return {
      time: start,
      score: Math.max(0, ...bucket.map((event) => event.risk)),
      count: bucket.length,
    }
  })
}

export function toCsv(events) {
  const cell = (value) => {
    const text = value === null ? '' : String(value)
    const safe = /^[=+@\-\t\r\n]/.test(text) ? `'${text}` : text
    return `"${safe.replaceAll('"', '""')}"`
  }
  return [
    [
      'Event ID',
      'Processed at',
      'Event',
      'Origin',
      'Danger score',
      'Risk score',
      'Status',
    ],
    ...events.map((event) => [
      event.event_id,
      event.processed_at,
      event.title,
      event.origin,
      event.danger_score,
      event.risk,
      event.status,
    ]),
  ]
    .map((row) => row.map(cell).join(','))
    .join('\r\n')
}
