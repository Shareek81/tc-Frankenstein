import '@fontsource/space-grotesk/500.css'
import '@fontsource/space-grotesk/600.css'
import '@fontsource/ibm-plex-sans/400.css'
import '@fontsource/ibm-plex-sans/500.css'
import '@fontsource/ibm-plex-sans/600.css'
import '@fontsource/ibm-plex-mono/400.css'
import './app.css'
import { createOriginMap } from './origin-map.js'
import {
  createIcons,
  Shield,
  Activity,
  Radio,
  ArrowUpRight,
  ArrowDownToLine,
  Search,
  Pause,
  Play,
  X,
  ChevronLeft,
  ChevronRight,
  ShieldOff,
  Copy,
  Check,
  CircleHelp,
  RefreshCw,
  Terminal,
  Globe2,
  SlidersHorizontal,
} from 'lucide'
import * as echarts from 'echarts/core'
import { LineChart, BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import {
  appendEvent,
  replaceHistory,
  summarize,
  filterEvents,
  timeline,
  riskLevel,
  toCsv,
} from './events.js'

echarts.use([
  LineChart,
  BarChart,
  GridComponent,
  TooltipComponent,
  CanvasRenderer,
])
const icons = {
  Shield,
  Activity,
  Radio,
  ArrowUpRight,
  ArrowDownToLine,
  Search,
  Pause,
  Play,
  X,
  ChevronLeft,
  ChevronRight,
  ShieldOff,
  Copy,
  Check,
  CircleHelp,
  RefreshCw,
  Terminal,
  Globe2,
  SlidersHorizontal,
}
const icon = (name) => `<i data-lucide="${name}" aria-hidden="true"></i>`
const refreshIcons = () =>
  createIcons({ icons, attrs: { 'stroke-width': 1.65 } })
const escape = (value) =>
  String(value).replace(
    /[&<>"']/g,
    (character) =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[
        character
      ],
  )
const formatTime = (timestamp) =>
  new Date(timestamp).toLocaleTimeString('en-GB', {
    hour12: false,
    timeZone: 'UTC',
  })
const $ = (selector) => document.querySelector(selector)

$('#app').innerHTML = `
  <a class="skip-link" href="#events">Skip to events</a>
  <header class="topbar">
    <a class="brand" href="#overview"><span class="brand-mark">${icon('shield')}</span><span>FRANKENSTEIN<span class="brand-sub">COMMAND CENTER</span></span></a>
    <nav aria-label="Main navigation"><a href="#overview" class="active">Overview</a><a href="#events">Event stream</a></nav>
    <div class="header-meta"><span class="environment">LOCAL ENVIRONMENT</span><span id="clock" class="mono"></span><button class="icon-button" id="connection-info" title="Connection details" aria-label="Connection details">${icon('circle-help')}</button></div>
  </header>
  <main id="overview">
    <section class="page-heading">
      <div><div class="eyebrow"><span class="status-dot"></span> SECURITY OPERATIONS</div><h1>Threat command center<span class="heading-dot">.</span></h1><p class="subtitle">Every signal. One field of view.</p></div>
      <div class="heading-actions"><span class="connection" id="connection" role="status"><span class="status-dot"></span><span>Connecting</span></span><button class="button mitigate" id="mitigate">${icon('shield-off')}<span>Mitigate attack</span></button></div>
    </section>
    <div class="connection-banner" id="connection-banner" hidden><span id="connection-message"></span><button id="reconnect" class="text-button">${icon('refresh-cw')}Reconnect</button></div>
    <section class="metrics" aria-label="Retained event statistics">
      <div class="metric"><span class="metric-label">Events retained ${icon('activity')}</span><div><strong id="total">0</strong><span class="metric-note">processed signals</span></div><span class="mini-rule mint"></span></div>
      <div class="metric"><span class="metric-label">Critical signals ${icon('shield')}</span><div><strong id="critical" class="critical-text">0</strong><span class="metric-note">risk 80 or above</span></div><span class="mini-rule coral"></span></div>
      <div class="metric"><span class="metric-label">Observed origins ${icon('globe-2')}</span><div><strong id="origins">0</strong><span class="metric-note">unique IP addresses</span></div><span class="mini-rule blue"></span></div>
      <div class="metric"><span class="metric-label">Recent activity ${icon('radio')}</span><div><strong id="recent">0</strong><span class="metric-note">events / last 5 min</span></div><span class="mini-rule amber"></span></div>
    </section>
    <section class="origin-map" aria-labelledby="origin-map-title">
      <div class="section-heading"><h2 id="origin-map-title">Origin map <span id="origin-count" class="count-pill">0</span></h2><button id="reset-map" class="icon-button" title="Reset globe view" aria-label="Reset globe view">${icon('globe-2')}</button></div>
      <div class="origin-map-layout">
        <div class="origin-directory"><label class="search">${icon('search')}<input id="origin-search" type="search" placeholder="Find IP address" aria-label="Find origin IP" autocomplete="off"/></label><div class="origin-list" aria-label="Unique origin IP addresses">No origin IPs received</div></div>
        <div class="origin-scene"><div class="origin-globe"></div><div class="location-caption"><strong class="location-ip">No IP selected</strong><p class="location-status" role="status">Approximate network locations</p></div></div>
      </div>
      <p class="geolocation-notice">Approximate IP geolocation, not an attacker’s physical location. Selected public IPs are sent to IPWho.is. Simulated activity does not confirm real attacks.</p>
    </section>
    <section class="situation" aria-label="Threat overview">
      <div class="posture" id="posture" data-level="low">
        <div class="section-heading"><h2>Threat posture</h2><span class="overline">5-MINUTE PEAK</span></div>
        <div class="gauge" role="meter" aria-label="Global threat level" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0">
          <svg viewBox="0 0 300 180" aria-hidden="true"><path class="gauge-track" d="M 28 152 A 122 122 0 0 1 272 152" pathLength="100"/><path id="gauge-fill" d="M 28 152 A 122 122 0 0 1 272 152" pathLength="100"/><text x="22" y="177">0</text><text x="251" y="177">100</text></svg>
          <div class="gauge-value"><strong id="risk-score">0</strong><span>/ 100</span><span id="risk-label" class="risk-badge">NO RECENT SIGNALS</span></div>
        </div>
        <div class="risk-scale"><span>Low</span><span>Elevated</span><span>High</span><span>Critical</span></div>
        <div class="posture-bottom"><span id="risk-description">Awaiting processed telemetry.</span><button class="icon-button" id="risk-info" aria-label="Threat calculation details" title="Threat calculation details">${icon('circle-help')}</button></div>
        <button class="button secondary review-critical" id="review-critical">${icon('shield')}Review critical events</button>
      </div>
    </section>
    <section class="analytics" aria-label="Signal analytics">
      <div class="timeline-panel"><div class="section-heading"><h2>${icon('activity')}Signal intensity</h2><div class="chart-legend"><span><b class="mint-dot"></b>Peak risk</span><span><b class="grey-dot"></b>Events</span><span class="overline">LAST 12 MIN</span></div></div><div id="timeline" role="img" aria-label="Peak threat risk and event count by processing minute"></div></div>
      <div class="attack-panel"><div class="section-heading"><h2>Event categories</h2><span class="overline">RETAINED</span></div><div id="attack-mix"></div></div>
    </section>
    <section class="events-section" id="events">
      <div class="events-title"><div class="title-inline"><h2>Latest events</h2><span class="count-pill" id="event-count">0</span><span class="live-tag" id="feed-tag"><span class="status-dot"></span>LIVE</span></div><div class="table-actions"><button class="text-button" id="pause" aria-pressed="false">${icon('pause')}<span>Pause view</span></button><button class="text-button" id="export">${icon('arrow-down-to-line')}<span>Export CSV</span></button></div></div>
      <div class="filterbar"><label class="search">${icon('search')}<input id="search" type="search" placeholder="Search event, IP address or ID" aria-label="Search events" autocomplete="off"/></label><div class="filters"><label><span class="sr-only">Filter by severity</span><select id="severity-filter"><option value="all">All severities</option><option value="critical">Critical</option><option value="high">High</option><option value="elevated">Elevated</option><option value="low">Low</option></select></label><button class="icon-button" id="clear-filters" title="Reset filters" aria-label="Reset filters">${icon('sliders-horizontal')}</button></div></div>
      <div class="feed-position"><span class="overline">NEWEST FIRST</span><button class="text-button" id="latest-events" hidden>${icon('refresh-cw')}Latest events</button></div>
      <div class="table-scroll"><table><thead><tr><th>Processed at (UTC)</th><th>Event / activity</th><th>Origin IP</th><th>Risk level</th><th>AI score</th><th><span class="sr-only">Inspect</span></th></tr></thead><tbody id="event-rows"></tbody></table></div>
      <div class="empty-state" id="empty-state">${icon('radio')}<h3>Listening for signals</h3><p id="empty-description">No processed events received yet.</p></div>
      <div class="table-footer"><span id="pagination-label">0 events</span><div class="pagination"><button class="icon-button" id="previous" aria-label="Previous page" title="Previous page">${icon('chevron-left')}</button><span id="page-label">1 / 1</span><button class="icon-button" id="next" aria-label="Next page" title="Next page">${icon('chevron-right')}</button></div></div>
    </section>
    <footer class="footer"><span><span class="status-dot"></span>FRANKENSTEIN <span class="footer-divider">/</span> LOCAL THREAT INTELLIGENCE</span><span id="last-signal">No signals received</span></footer>
  </main>
  <dialog id="detail-dialog" class="detail-dialog" aria-labelledby="detail-title"><div class="dialog-heading"><span class="eyebrow">EVENT INSPECTOR</span><button class="icon-button close-dialog" aria-label="Close event details" title="Close">${icon('x')}</button></div><div id="detail-content"></div><button class="button secondary" id="copy-event">${icon('copy')}Copy event JSON</button></dialog>
  <dialog id="mitigate-dialog" aria-labelledby="mitigate-title"><div class="dialog-heading"><span class="dialog-symbol">${icon('shield-off')}</span><button class="icon-button close-dialog" aria-label="Close mitigation dialog" title="Close">${icon('x')}</button></div><div class="eyebrow">RESPONSE ACTION</div><h2 id="mitigate-title">Stop attack simulation?</h2><p>Request an end to the active simulation. Monitoring remains active and queued events may still arrive. This action does not block network traffic.</p><div class="action-summary"><span>Scope</span><strong>Attack simulation</strong><span>Action</span><strong>Request stop</strong></div><p id="mitigation-status" class="dialog-status" role="status"></p><div class="dialog-actions"><button class="button secondary close-dialog">Cancel</button><button class="button mitigate" id="confirm-mitigate">${icon('shield-off')}Request stop</button></div></dialog>
  <dialog id="info-dialog" aria-labelledby="info-title"><div class="dialog-heading"><span class="eyebrow">SYSTEM CONTEXT</span><button class="icon-button close-dialog" aria-label="Close information" title="Close">${icon('x')}</button></div><h2 id="info-title"></h2><div id="info-content"></div></dialog>
  <div class="toast" id="toast" role="status" hidden></div>
`

$('#overview').insertBefore($('#events'), $('.situation'))
$('.situation').append($('.analytics'))
$('#overview').insertBefore($('.origin-map'), $('.footer'))

let events = []
let frozenEvents = null
let pageNumber = 1
let selectedEvent = null
let connectionState = 'connecting'
let lastReceived = null
let source
let reconnectTimer
let renderQueued = false
let stoppedRequested = false
const pageSize = 10
const originMap = createOriginMap($('.origin-map'))
const chart = echarts.init($('#timeline'), null, { renderer: 'canvas' })
const resize = new ResizeObserver(() => chart.resize())
resize.observe($('#timeline'))
const visibleEvents = () => frozenEvents ?? events
const filters = () => ({
  query: $('#search').value,
  severity: $('#severity-filter').value,
})
const shownEvents = () => filterEvents(visibleEvents(), filters())
let toastTimeout

function toast(message) {
  $('#toast').textContent = message
  $('#toast').hidden = false
  clearTimeout(toastTimeout)
  toastTimeout = setTimeout(() => {
    $('#toast').hidden = true
  }, 4000)
}

function scheduleRender() {
  if (renderQueued) return
  renderQueued = true
  requestAnimationFrame(() => {
    renderQueued = false
    render()
  })
}

function render() {
  const current = visibleEvents()
  originMap.update(current)
  const summary = summarize(current)
  $('#total').textContent = summary.total.toLocaleString()
  $('#critical').textContent = summary.critical.toLocaleString()
  $('#origins').textContent = summary.origins.toLocaleString()
  $('#recent').textContent = summary.recent.toLocaleString()
  $('#review-critical').disabled = summary.critical === 0
  $('#posture').dataset.level = summary.level
  $('#risk-score').textContent = summary.score ?? 'N/A'
  $('.gauge').setAttribute('role', summary.score === null ? 'img' : 'meter')
  for (const [attribute, value] of Object.entries({
    'aria-valuenow': summary.score, 'aria-valuemin': 0, 'aria-valuemax': 100,
  })) {
    if (summary.score === null) $('.gauge').removeAttribute(attribute)
    else $('.gauge').setAttribute(attribute, value)
  }
  const riskLabel = summary.score === null
    ? 'Risk unavailable'
    : summary.recent === 0 ? 'No recent signals' : `${summary.level} threat`
  const riskCoverage = summary.unknownRisk > 0 && summary.score !== null
    ? ` ${summary.unknownRisk} recent ${summary.unknownRisk === 1 ? 'event has' : 'events have'} unknown risk.`
    : ''
  $('.gauge').setAttribute('aria-label', `Global threat level: ${riskLabel}.${riskCoverage}`)
  $('.gauge').setAttribute(
    'aria-valuetext',
    `${summary.score ?? 'Unavailable'}: ${riskLabel}.${riskCoverage}`,
  )
  if (summary.score === null) $('.gauge').removeAttribute('aria-valuetext')
  $('#gauge-fill').style.strokeDasharray = `${summary.score ?? 0} 100`
  $('#risk-label').textContent = riskLabel.toUpperCase()
  $('#risk-description').textContent =
    (summary.score === null
      ? 'Recent events have no available risk assessment.'
      : summary.score >= 80
      ? 'High-severity activity detected.'
      : summary.score >= 60
        ? 'Elevated activity requires review.'
        : summary.score > 0
          ? 'Monitoring incoming activity.'
          : 'No signals in the last five minutes.') + riskCoverage
  $('#last-signal').textContent = summary.latest
    ? `LAST SIGNAL ${formatTime(summary.latest.timestamp)}`
    : 'No signals received'
  const totalEvents = summary.total || 1
  $('#attack-mix').innerHTML = summary.types.length
    ? summary.types
        .slice(0, 4)
        .map(
          ([name, count], index) =>
            `<div class="mix-row"><div><span>${escape(name)}</span><span class="mono">${Math.round((count / totalEvents) * 100)}% <small>${count}</small></span></div><div class="mix-track"><span style="width:${(count / totalEvents) * 100}%;background:var(--mix-${index})"></span></div></div>`,
        )
        .join('')
    : '<div class="mix-empty">No events in retained history</div>'
  const buckets = timeline(current)
  chart.setOption({
    animationDuration: 450,
    grid: { top: 12, left: 30, right: 10, bottom: 25 },
    tooltip: {
      trigger: 'axis',
      renderMode: 'richText',
      confine: true,
      backgroundColor: '#202427',
      borderColor: '#41484b',
      textStyle: { color: '#edf1ef', fontFamily: 'IBM Plex Sans' },
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: buckets.map((bucket) =>
        new Date(bucket.time).toLocaleTimeString('en-GB', {
          hour: '2-digit',
          minute: '2-digit',
          timeZone: 'UTC',
        }),
      ),
      axisLine: { lineStyle: { color: '#303639' } },
      axisTick: { show: false },
      axisLabel: {
        color: '#87938e',
        fontSize: 10,
        fontFamily: 'IBM Plex Mono',
      },
    },
    yAxis: [
      {
        type: 'value',
        max: 100,
        interval: 50,
        axisLabel: { color: '#87938e', fontSize: 10 },
        splitLine: { lineStyle: { color: '#272d2f', type: 'dashed' } },
      },
      { type: 'value', show: false, min: 0 },
    ],
    series: [
      {
        name: 'Events',
        type: 'bar',
        yAxisIndex: 1,
        barWidth: 15,
        data: buckets.map((bucket) => bucket.count),
        itemStyle: { color: '#343e3a' },
      },
      {
        name: 'Peak risk',
        type: 'line',
        smooth: 0.22,
        symbol: 'circle',
        symbolSize: 5,
        showSymbol: current.length > 0,
        data: buckets.map((bucket) => bucket.score),
        itemStyle: { color: summary.score >= 80 ? '#ff7770' : '#a6efc1' },
        lineStyle: { width: 2 },
        areaStyle: { color: '#a6efc1', opacity: 0.045 },
      },
    ],
  })
  renderTable()
}

function renderTable() {
  const filtered = shownEvents()
  const pages = Math.max(1, Math.ceil(filtered.length / pageSize))
  pageNumber = Math.min(pageNumber, pages)
  const slice = filtered.slice(
    (pageNumber - 1) * pageSize,
    pageNumber * pageSize,
  )
  $('#event-count').textContent = filtered.length
  $('#event-rows').innerHTML = slice
    .map(
      (event) =>
        `<tr><td class="mono time-cell">${formatTime(event.timestamp)}<span>${new Date(event.timestamp).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', timeZone: 'UTC' })}</span></td><td><button class="event-title" data-event="${escape(event.event_id)}">${escape(event.title)}</button><span class="event-status">${escape(event.status)}</span></td><td class="mono origin-cell">${escape(event.origin)}</td><td><span class="severity ${riskLevel(event.risk)}"><b></b>${riskLevel(event.risk)}</span></td><td>${event.danger_score === null ? '<span class="ai-unavailable">Unavailable</span>' : `<span class="score-cell"><span class="score-track"><span style="width:${event.danger_score}%;background:var(--${riskLevel(event.danger_score)})"></span></span><strong class="mono">${event.danger_score}</strong></span>`}</td><td><button class="icon-button inspect" data-event="${escape(event.event_id)}" title="Inspect event" aria-label="Inspect ${escape(event.title)}">${icon('arrow-up-right')}</button></td></tr>`,
    )
    .join('')
  $('#empty-state').hidden = filtered.length > 0
  $('#empty-state h3').textContent = events.length
    ? 'No matching signals'
    : 'Listening for signals'
  $('#empty-description').textContent = events.length
    ? 'No events match the current filters.'
    : connectionState === 'live'
      ? 'No processed events received yet.'
      : 'Waiting for a connection to the analytics bridge.'
  $('#pagination-label').textContent = filtered.length
    ? `${(pageNumber - 1) * pageSize + 1}-${Math.min(pageNumber * pageSize, filtered.length)} of ${filtered.length} events`
    : '0 events'
  $('#page-label').textContent = `${pageNumber} / ${pages}`
  $('#previous').disabled = pageNumber <= 1
  $('#next').disabled = pageNumber >= pages
  $('#export').disabled = !filtered.length
  $('#latest-events').hidden = pageNumber === 1 && frozenEvents === null
  refreshIcons()
}

function setConnection(state) {
  connectionState = state
  $('#connection').dataset.state = state
  $('#connection span:last-child').textContent = {
    live: 'Stream connected',
    connecting: 'Connecting',
    offline: 'Reconnecting',
  }[state]
  $('#connection-banner').hidden = state !== 'offline'
  $('#connection-message').textContent =
    'Connection interrupted. Retained data may be stale; reconnecting automatically.'
  $('#feed-tag').classList.toggle(
    'is-paused',
    frozenEvents !== null || state !== 'live',
  )
  $('#feed-tag').innerHTML =
    `<span class="status-dot"></span>${frozenEvents ? 'PAUSED' : state === 'live' ? 'LIVE' : 'OFFLINE'}`
}

function reconnect() {
  source?.close()
  clearTimeout(reconnectTimer)
  setConnection('offline')
  renderTable()
  reconnectTimer = setTimeout(connect, 2000)
}

function connect() {
  clearTimeout(reconnectTimer)
  source?.close()
  setConnection('connecting')
  source = new EventSource('/api/stream')
  source.addEventListener('snapshot', (message) => {
    try {
      events = replaceHistory(JSON.parse(message.data))
      lastReceived = Date.now()
      setConnection('live')
      scheduleRender()
    } catch {
      toast('Invalid snapshot received. Reconnecting.')
      reconnect()
    }
  })
  source.addEventListener('log', (message) => {
    try {
      events = appendEvent(events, JSON.parse(message.data))
      lastReceived = Date.now()
      setConnection('live')
      if (!frozenEvents) scheduleRender()
    } catch {
      toast('An invalid event was received. Refreshing history.')
      reconnect()
    }
  })
  source.addEventListener('reset', reconnect)
  source.onerror = reconnect
}

function inspect(id) {
  selectedEvent = visibleEvents().find((event) => event.event_id === id)
  if (!selectedEvent) return
  const event = selectedEvent
  const assessment = event.insight.length === 2 && event.respondsuggested.length === 2
    ? `<h4>Observations</h4><ol class="insight-points">${event.insight.map(point => `<li>${escape(point)}</li>`).join('')}</ol><h4>Suggested response</h4><ol class="response-points">${event.respondsuggested.map(point => `<li>${escape(point)}</li>`).join('')}</ol><p class="ai-caution">AI-generated recommendations. Verify before taking action.</p>`
    : '<p class="ai-unavailable">AI insight is not available for this event.</p>'
  $('#detail-content').innerHTML =
    `<h2 id="detail-title">${escape(event.title)}</h2><span class="severity ${riskLevel(event.risk)}"><b></b>${riskLevel(event.risk)}</span><section class="ai-insight" aria-labelledby="ai-insight-title"><h3 id="ai-insight-title">AI Insight</h3>${assessment}</section><dl class="detail-list"><dt>Origin IP</dt><dd class="mono">${escape(event.origin)}</dd><dt>Status</dt><dd>${escape(event.status)}</dd><dt>AI danger score</dt><dd>${event.danger_score === null ? 'Unavailable' : `${event.danger_score} / 100`}</dd><dt>Risk score</dt><dd>${event.risk === null ? 'Unknown' : `${event.risk} / 100`}</dd><dt>Recorded at</dt><dd>${escape(event.sourceTime)}</dd><dt>Processed at</dt><dd>${escape(event.processed_at)}</dd><dt>Event ID</dt><dd class="mono">${escape(event.event_id)}</dd></dl>`
  $('#detail-dialog').showModal()
}

$('#event-rows').addEventListener('click', (event) => {
  const button = event.target.closest('[data-event]')
  if (button) inspect(button.dataset.event)
})
for (const selector of ['#search', '#severity-filter'])
  $(selector).addEventListener('input', () => {
    pageNumber = 1
    renderTable()
  })
$('#clear-filters').onclick = () => {
  $('#search').value = ''
  $('#severity-filter').value = 'all'
  pageNumber = 1
  renderTable()
}
$('#previous').onclick = () => {
  pageNumber--
  renderTable()
}
$('#next').onclick = () => {
  pageNumber++
  renderTable()
}
function togglePause() {
  frozenEvents = frozenEvents ? null : [...events]
  if (!frozenEvents) pageNumber = 1
  $('#pause').setAttribute('aria-pressed', String(frozenEvents !== null))
  $('#pause').innerHTML =
    `${icon(frozenEvents ? 'play' : 'pause')}<span>${frozenEvents ? 'Resume view' : 'Pause view'}</span>`
  setConnection(connectionState)
  render()
}
$('#pause').onclick = togglePause
$('#latest-events').onclick = () => {
  pageNumber = 1
  if (frozenEvents) togglePause()
  else renderTable()
}
$('#review-critical').onclick = () => {
  $('#search').value = ''
  $('#severity-filter').value = 'critical'
  pageNumber = 1
  renderTable()
  $('#events').scrollIntoView({ block: 'start' })
  $('#severity-filter').focus({ preventScroll: true })
}
$('#export').onclick = () => {
  const url = URL.createObjectURL(
    new Blob([toCsv(shownEvents())], { type: 'text/csv;charset=utf-8;' }),
  )
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `frankenstein-events-${new Date().toISOString().slice(0, 10)}.csv`
  anchor.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
  toast('Filtered events exported.')
}
$('#copy-event').onclick = async () => {
  if (!selectedEvent) return
  const { event_id, title, origin, status, risk, danger_score, processed_at } =
    selectedEvent
  try {
    await navigator.clipboard.writeText(
      JSON.stringify(
        {
          event_id,
          event: title,
          origin,
          status,
          risk,
          danger_score,
          processed_at,
          insight: selectedEvent.insight,
          respondsuggested: selectedEvent.respondsuggested,
        },
        null,
        2,
      ),
    )
    toast('Event JSON copied.')
  } catch {
    toast('Clipboard unavailable in this browser.')
  }
}
document.querySelectorAll('.close-dialog').forEach((button) => {
  button.onclick = () => button.closest('dialog').close()
})
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') document.querySelector('dialog[open]')?.close()
})
document.querySelectorAll('dialog').forEach((dialog) =>
  dialog.addEventListener('click', (event) => {
    if (event.target === dialog) {
      const bounds = dialog.getBoundingClientRect()
      if (
        event.clientX < bounds.left ||
        event.clientX > bounds.right ||
        event.clientY < bounds.top ||
        event.clientY > bounds.bottom
      )
        dialog.close()
    }
  }),
)
$('#mitigate').onclick = () => {
  $('#mitigation-status').textContent = stoppedRequested
    ? 'A previous stop request was accepted. You can request again if the simulator was restarted.'
    : ''
  $('#mitigate-dialog').showModal()
}
$('#confirm-mitigate').onclick = async () => {
  const button = $('#confirm-mitigate')
  button.disabled = true
  button.innerHTML = `${icon('refresh-cw')}Requesting...`
  refreshIcons()
  $('#mitigation-status').textContent = ''
  try {
    const response = await fetch('/api/simulator/stop', {
      method: 'POST',
      signal: AbortSignal.timeout(10000),
    })
    if (response.status !== 202)
      throw new Error(
        'Stop request was not accepted. Check simulator control and retry.',
      )
    const payload = await response.json()
    if (payload.status !== 'stop_requested')
      throw new Error('Unexpected response. Stop is not confirmed.')
    stoppedRequested = true
    $('#mitigation-status').textContent =
      'Stop request accepted. Simulator exit is not confirmed; queued signals may continue.'
    $('#mitigation-status').className = 'dialog-status success'
    toast('Simulation stop requested.')
  } catch (error) {
    $('#mitigation-status').textContent =
      error.name === 'TimeoutError'
        ? 'Request timed out. Stop status is unknown; you can retry.'
        : error.message
    $('#mitigation-status').className = 'dialog-status error'
  } finally {
    button.disabled = false
    button.innerHTML = `${icon('shield-off')}Request stop`
    refreshIcons()
  }
}
function showInfo(title, content) {
  $('#info-title').textContent = title
  $('#info-content').innerHTML = content
  $('#info-dialog').showModal()
}
$('#connection-info').onclick = () =>
  showInfo(
    'Monitoring status',
    `<dl class="detail-list"><dt>Connection</dt><dd>${escape(connectionState)}</dd><dt>Last update (UTC)</dt><dd>${lastReceived ? formatTime(lastReceived) : 'Not yet received'}</dd><dt>History</dt><dd>Up to 1,000 processed events</dd></dl><p>A connected stream does not guarantee complete monitoring coverage. Retained history refreshes after reconnection.</p>`,
  )
$('#risk-info').onclick = () =>
  showInfo(
    'Threat calculation',
    '<p>The gauge shows the highest event risk in the last five minutes. Risk is the higher of the AI danger score and reported severity normalized to 100.</p><dl class="detail-list"><dt>Low</dt><dd>0-29</dd><dt>Elevated</dt><dd>30-59</dd><dt>High</dt><dd>60-79</dd><dt>Critical</dt><dd>80-100</dd></dl><p>Scores are estimates, not verified compromise. A zero score means no recent signals, not proof of safety.</p>',
  )
$('#reconnect').onclick = connect
function tick() {
  $('#clock').textContent = `${new Date().toISOString().slice(11, 19)} UTC`
}
tick()
const clockTimer = setInterval(tick, 1000)
const riskTimer = setInterval(() => {
  if (!frozenEvents) render()
}, 15000)
render()
connect()
addEventListener(
  'pagehide',
  () => {
    source?.close()
    clearTimeout(reconnectTimer)
    clearTimeout(toastTimeout)
    clearInterval(clockTimer)
    clearInterval(riskTimer)
    chart.dispose()
    originMap.dispose()
    resize.disconnect()
  },
  { once: true },
)
addEventListener('pageshow', (event) => {
  if (event.persisted) location.reload()
})
