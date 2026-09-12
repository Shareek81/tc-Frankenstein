export function uniqueOrigins(events) {
  const origins = new Map()
  for (const event of events) {
    if (!event.origin || event.origin === '-') continue
    const existing = origins.get(event.origin)
    origins.set(event.origin, {
      ip: event.origin,
      count: (existing?.count ?? 0) + 1,
      risk: Math.max(existing?.risk ?? 0, event.risk),
    })
  }
  return [...origins.values()].sort((first, second) =>
    second.count - first.count || first.ip.localeCompare(second.ip),
  )
}

export function globePosition(latitude, longitude) {
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude) ||
      Math.abs(latitude) > 90 || Math.abs(longitude) > 180) {
    throw new Error('Invalid geographic coordinates')
  }
  const latitudeRadians = latitude * Math.PI / 180
  const longitudeRadians = longitude * Math.PI / 180
  return [
    Math.cos(latitudeRadians) * Math.cos(longitudeRadians),
    Math.sin(latitudeRadians),
    -Math.cos(latitudeRadians) * Math.sin(longitudeRadians),
  ]
}