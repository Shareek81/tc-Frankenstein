import { createGlobe } from './globe.js'
import { uniqueOrigins } from './geography.js'

export function createOriginMap(section) {
  const globe = createGlobe(section.querySelector('.origin-globe'))
  const list = section.querySelector('.origin-list')
  const search = section.querySelector('#origin-search')
  const status = section.querySelector('.location-status')
  const heading = section.querySelector('.location-ip')
  let origins = []
  let selected = null
  let request = null
  let signature = ''

  function renderList() {
    const focusedIp = list.contains(document.activeElement) ? document.activeElement.dataset.ip : null
    const filtered = origins.filter(origin => origin.ip.includes(search.value.trim()))
    list.replaceChildren()
    for (const origin of filtered) {
      const button = document.createElement('button')
      button.className = 'origin-item'
      button.setAttribute('aria-pressed', String(origin.ip === selected))
      button.dataset.ip = origin.ip
      const address = document.createElement('span')
      address.textContent = origin.ip
      const count = document.createElement('small')
      count.textContent = `${origin.count} ${origin.count === 1 ? 'event' : 'events'}`
      button.append(address, count)
      button.onclick = () => select(origin)
      list.append(button)
      if (origin.ip === focusedIp) button.focus({ preventScroll: true })
    }
    if (!filtered.length) list.textContent = origins.length ? 'No matching IP addresses' : 'No origin IPs received'
  }

  async function select(origin) {
    request?.abort()
    const controller = new AbortController()
    request = controller
    const timeout = setTimeout(() => controller.abort(), 12000)
    selected = origin.ip
    globe.clear()
    heading.textContent = selected
    status.textContent = 'Locating IP...'
    renderList()
    try {
      const response = await fetch(`/api/locations/${encodeURIComponent(selected)}`, { signal: controller.signal })
      if (!response.ok) throw new Error('Location lookup unavailable. Select the IP to retry.')
      const location = await response.json()
      if (request !== controller) return
      if (location.status === 'located') {
        globe.focus(location.latitude, location.longitude, origin.risk)
        status.textContent = `${[location.city, location.country].filter(Boolean).join(', ') || 'Approximate location'} | ${location.latitude.toFixed(2)}, ${location.longitude.toFixed(2)}`
      } else {
        status.textContent = location.status === 'non_public'
          ? 'Private or reserved IP - no public geographic location.'
          : 'No geographic location available.'
      }
    } catch (error) {
      if (request !== controller) return
      status.textContent = error.name === 'AbortError' ? 'Lookup timed out. Select the IP to retry.' : 'Location lookup unavailable. Select the IP to retry.'
    } finally {
      clearTimeout(timeout)
    }
  }

  search.oninput = renderList
  section.querySelector('#reset-map').onclick = () => globe.reset()
  return {
    update(events) {
      const next = uniqueOrigins(events)
      const nextSignature = JSON.stringify(next)
      if (nextSignature === signature) return
      signature = nextSignature
      origins = next
      section.querySelector('#origin-count').textContent = origins.length
      if (selected && !origins.some(origin => origin.ip === selected)) {
        request?.abort()
        request = null
        selected = null
        globe.clear()
        heading.textContent = 'No IP selected'
        status.textContent = 'Approximate network locations'
      }
      renderList()
    },
    dispose() {
      request?.abort()
      request = null
      globe.dispose()
    },
  }
}