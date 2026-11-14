import { useCallback, useEffect, useRef, useState } from 'react'
import { deadlineFor, drawState, reminderDue, sortDraws, timeLeft } from './draws.mjs'
import Diagnostics from './Diagnostics.jsx'
import VisualAccount from './VisualAccount.jsx'
import {
  Activity, Archive, Bell, Check, ChevronRight, CircleAlert, CircleCheck, Clock3,
  Edit3, LayoutDashboard, Link2, ListTodo, Menu, Pause, Play, Plus, RefreshCw,
  ScrollText, Search, Settings2, Square, Tags, Trash2, Users, X,
} from 'lucide-react'

const nav = [
  ['inicio', LayoutDashboard, 'Inicio'],
  ['cuentas', Users, 'Cuentas'],
  ['sorteos', Link2, 'Sorteos'],
  ['asignaciones', ListTodo, 'Asignaciones'],
  ['actividad', Activity, 'Actividad'],
]
const statusLabels = {
  queued: 'En cola', running: 'En curso', pausing: 'Pausando', paused: 'Pausada',
  cancelling: 'Cancelando', cancelled: 'Cancelada', completed: 'Completada',
  failed: 'Error', interrupted: 'Interrumpida',
}
const sessionLabels = {
  connected: 'Sesión conectada', not_signed_in: 'Sin iniciar sesión',
  verification_required: 'Requiere verificación', session_expired: 'Sesión caducada',
  verification_error: 'No se pudo verificar', unknown: 'No verificada', wrong_account: 'Cuenta incorrecta',
  verification_in_progress: 'Verificación en curso', in_use_by_task: 'En uso por una tarea',
}
const eventLabels = {
  attempt: 'Intento', clicked: 'Clic en Publicar', confirmed: 'Confirmado',
  failed: 'Error', queued: 'En cola', running: 'Iniciada', paused: 'Pausada',
  pausing: 'Pausa solicitada', cancelling: 'Cancelacion solicitada',
  cancelled: 'Cancelada', completed: 'Completada', interrupted: 'Interrumpida',
  close_error: 'Error al cerrar Chrome',
  comment_count_observed: 'Comentarios de Instagram',
  comment_count_unavailable: 'Contador no disponible',
  blocked_suspected: 'Posible bloqueo',
  history_corrected: 'Historial corregido',
  selenium_retry: 'Reintento de Selenium', selenium_error: 'Error de Selenium',
}

async function request(path, options = {}) {
  const response = await fetch(`/api${path}`, {
    headers: { 'Content-Type': 'application/json' }, ...options,
  })
  if (!response.ok) {
    let detail = `Error ${response.status}`
    try {
      const data = await response.json()
      detail = typeof data.detail === 'string' ? data.detail : data.detail?.map(x => x.msg).join(', ') || detail
    } catch { /* Keep HTTP status. */ }
    const error = new Error(detail)
    error.status = response.status
    throw error
  }
  return response.json()
}

async function optionalRequest(path, fallback) {
  try { return await request(path) }
  catch (error) {
    if (error.status === 404) return fallback
    throw error
  }
}

function confirmAction(message, action) {
  if (window.confirm(message)) action()
}

const emptyAccount = { name: '', profile_arg: '' }
const emptyDraw = { name: '', url: '', notes: '', end_date: '', end_time: '', tag_count: 1 }
const emptyAssignment = {
  account_id: '', draw_id: '', duration_minutes: 60, comments_per_minute: 1,
  extra_text: '', tags: [],
}

function dateKey(date = new Date()) {
  const year = date.getFullYear()
  return `${year}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

function formatDate(value) {
  if (!value) return 'Sin fecha'
  const [year, month, day] = value.split('-')
  return `${day}/${month}/${year}`
}

function formatDeadline(draw) {
  return `${formatDate(draw.end_date)}${draw.end_time ? ` ${draw.end_time}` : ''}`
}

function parseTaskIds(input) {
  const ids = new Set()
  for (const part of input.split(/[\s,]+/).filter(Boolean)) {
    const match = part.match(/^(\d+)(?:-(\d+))?$/)
    if (!match || Number(match[2] || match[1]) < Number(match[1])) throw new Error('IDs invalidos; usa por ejemplo 20-24, 9')
    for (let id = Number(match[1]); id <= Number(match[2] || match[1]); id++) {
      ids.add(id)
      if (ids.size > 200) throw new Error('Selecciona hasta 200 tareas por correccion')
    }
  }
  if (!ids.size || ids.has(0)) throw new Error('Indica al menos un ID de tarea valido')
  return [...ids]
}

function IconButton({ icon: Icon, title, onClick, disabled, tone = '' }) {
  return <button type="button" className={`icon-button ${tone}`} title={title} aria-label={title} onClick={onClick} disabled={disabled}><Icon size={17} /></button>
}

function Status({ value }) {
  return <span className={`status status-${value}`}>{statusLabels[value] || value}</span>
}

function errorSummary(value) {
  if (!value) return ''
  const first = value.split(/\r?\n/).find(line => line.trim())?.trim() || ''
  return first === 'Message:' ? 'Selenium no devolvio un mensaje; ver detalle' : first
}

function App() {
  const [view, setView] = useState('inicio')
  const [menuOpen, setMenuOpen] = useState(false)
  const [data, setData] = useState({ overview: {}, dashboard: { draws: [], trend: [] }, settings: { reminder_hours_before: 24, browser_limit: '1' }, scheduler: {}, tags: [], accounts: [], draws: [], assignments: [], tasks: [], events: [] })
  const [modal, setModal] = useState(null)
  const [visualAccount, setVisualAccount] = useState(null)
  const [form, setForm] = useState({})
  const [filter, setFilter] = useState('')
  const [drawStatusFilter, setDrawStatusFilter] = useState('active')
  const [drawOrder, setDrawOrder] = useState('date_desc')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [selectedTask, setSelectedTask] = useState(null)
  const [taskEvents, setTaskEvents] = useState([])
  const [eventsTaskId, setEventsTaskId] = useState(null)
  const [tagSearch, setTagSearch] = useState('')
  const [notificationsEnabled, setNotificationsEnabled] = useState(
    () => typeof Notification !== 'undefined' && Notification.permission === 'granted'
  )
  const lastEventId = useRef(null)

  const refresh = useCallback(async () => {
    try {
      const keys = ['overview', 'dashboard', 'settings', 'scheduler', 'tags', 'accounts', 'draws', 'assignments', 'tasks', 'events']
      const optional = { dashboard: { draws: [], trend: [] }, settings: { reminder_hours_before: 24, browser_limit: '1' }, scheduler: {}, tags: [] }
      const values = await Promise.all(keys.map(key => key in optional ? optionalRequest(`/${key}`, optional[key]) : request(`/${key}`)))
      const [overview, dashboard, settings, scheduler, tags, accounts, draws, assignments, tasks, events] = values
      const latestId = events[0]?.id || 0
      if (lastEventId.current !== null && typeof Notification !== 'undefined' && Notification.permission === 'granted') {
        for (const event of events.filter(x => x.id > lastEventId.current && x.kind === 'blocked_suspected')) {
          const task = tasks.find(x => x.id === event.task_id)
          try {
            new Notification('Posible bloqueo de Instagram', {
              body: `${task?.account_name || 'Cuenta'}: ${event.message}`,
            })
          } catch { /* El aviso persistente sigue visible en el panel. */ }
        }
      }
      if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
        for (const draw of draws) {
          const hours = settings.reminder_hours_before ?? (settings.reminder_days_before === 0 ? 6 : 24)
          if (!reminderDue(draw, hours)) continue
          const key = `draw-reminder:${draw.id}:${draw.end_date}:${draw.end_time || 'day'}:${hours}`
          if (localStorage.getItem(key)) continue
          try {
            new Notification('Sorteo por finalizar', { body: `${draw.name}: ${formatDeadline(draw)}${draw.end_time ? '' : ' (sin hora)'}` })
            localStorage.setItem(key, '1')
          } catch { /* El aviso permanece visible en Inicio. */ }
        }
      }
      lastEventId.current = Math.max(lastEventId.current || 0, latestId)
      setData(Object.fromEntries(keys.map((key, index) => [key, values[index]])))
    } catch (err) { setError(err.message) }
  }, [])

  useEffect(() => {
    refresh()
    const timer = setInterval(refresh, 2500)
    return () => clearInterval(timer)
  }, [refresh])

  async function enableNotifications() {
    if (typeof Notification === 'undefined') {
      setError('Este navegador no admite notificaciones')
      return
    }
    const permission = await Notification.requestPermission()
    setNotificationsEnabled(permission === 'granted')
    if (permission !== 'granted') setError('Las notificaciones del navegador no estan habilitadas')
  }

  function openModal(type, item = null) {
    const base = type === 'accounts' ? emptyAccount : type === 'draws' ? emptyDraw : type === 'assignments' ? emptyAssignment : {}
    setModal({ type, id: item?.id || null })
    const value = item ? { ...item } : { ...base }
    setForm(type === 'assignments' ? { ...value, unlimited: value.duration_minutes === 0 } : type === 'tags' ? { tags_text: '' } : value)
    setTagSearch('')
    setError('')
  }

  async function perform(fn) {
    setBusy(true)
    setError('')
    try { await fn(); await refresh() }
    catch (err) { setError(err.message) }
    finally { setBusy(false) }
  }

  function save(event) {
    event.preventDefault()
    perform(async () => {
      if (modal.type === 'history') {
        await request('/tasks/correct-history', { method: 'POST', body: JSON.stringify({
          task_ids: parseTaskIds(form.task_ids_text || ''), draw_id: Number(form.draw_id),
        }) })
        setModal(null)
        return
      }
      if (modal.type === 'tags') {
        const tags = [...new Set(form.tags_text.split(/\s+/).filter(Boolean))]
        if (tags.length) await request('/tags', { method: 'POST', body: JSON.stringify({ tags }) })
        setModal(null)
        return
      }
      const body = modal.type === 'assignments'
        ? { ...form, account_id: Number(form.account_id), draw_id: Number(form.draw_id),
            duration_minutes: form.unlimited ? 0 : Number(form.duration_minutes),
            comments_per_minute: Number(form.comments_per_minute), tags: form.tags }
        : modal.type === 'draws' ? { ...form, end_date: form.end_date || null, end_time: form.end_date ? form.end_time || null : null, tag_count: Number(form.tag_count) } : form
      await request(`/${modal.type}${modal.id ? `/${modal.id}` : ''}`, {
        method: modal.id ? 'PUT' : 'POST', body: JSON.stringify(body),
      })
      setModal(null)
    })
  }

  const activeAccounts = data.accounts.filter(x => !x.archived)
  const activeDraws = data.draws.filter(x => !x.archived)
  const activeAssignments = data.assignments.filter(x => !x.archived && activeAccounts.some(a => a.id === x.account_id && !a.attention_required) && activeDraws.some(d => d.id === x.draw_id))
  const attentionAccounts = activeAccounts.filter(x => x.attention_required)
  const drawStats = data.dashboard.draws.filter(x => !x.archived)
  const now = new Date()
  const reminderHours = data.settings.reminder_hours_before ?? (data.settings.reminder_days_before === 0 ? 6 : 24)
  const upcoming = sortDraws(drawStats.filter(x => x.end_date && drawState(x, now) === 'active'), 'date_asc')
  const finished = drawStats.filter(x => drawState(x, now) === 'finished')
  const currentDraws = drawStats.filter(x => drawState(x, now) === 'active')
  const reminders = upcoming.filter(x => reminderDue(x, reminderHours, now))
  const trend = Array.from({ length: 7 }, (_, index) => {
    const date = new Date(); date.setDate(date.getDate() - (6 - index))
    const day = dateKey(date)
    return { day, clicked: data.dashboard.trend.find(x => x.day === day)?.clicked || 0 }
  })
  const maxTrend = Math.max(1, ...trend.map(x => x.clicked))
  const match = text => String(text).toLowerCase().includes(filter.toLowerCase())
  const visibleDraws = sortDraws(data.draws.filter(x =>
    match(`${x.name} ${x.url} ${x.notes}`) && (drawStatusFilter === 'all' || drawState(x, now) === drawStatusFilter)
  ), drawOrder)
  const task = data.tasks.find(x => x.id === selectedTask) || data.tasks[0]

  useEffect(() => {
    if (view !== 'actividad' || !task?.id) return
    let active = true
    setTaskEvents([])
    setEventsTaskId(null)
    const load = async () => {
      try {
        const events = await request(`/events?task_id=${task.id}&limit=200`)
        if (active) { setTaskEvents(events); setEventsTaskId(task.id) }
      } catch (err) { if (active) setError(err.message) }
    }
    load()
    const timer = setInterval(load, 2500)
    return () => { active = false; clearInterval(timer) }
  }, [view, task?.id])

  return <div className="app-shell">
    {menuOpen && <button className="menu-scrim" aria-label="Cerrar menu" onClick={() => setMenuOpen(false)} />}
    <aside className={`sidebar ${menuOpen ? 'sidebar-open' : ''}`}>
      <div className="brand"><span className="brand-mark">I</span><span><strong>INSTAGRAM-BOT</strong><small>Panel local</small></span></div>
      <div className="nav-label">ESPACIO DE TRABAJO</div>
      <nav aria-label="Navegacion principal">
        {nav.map(([id, Icon, label]) => <button key={id} className={`nav-item ${view === id ? 'active' : ''}`} onClick={() => { setView(id); setFilter(''); setMenuOpen(false) }}><Icon size={18} />{label}{view === id && <ChevronRight size={15} className="nav-chevron" />}</button>)}
      </nav>
      <div className="sidebar-foot"><span className="online-dot" />Servidor Linux</div>
    </aside>

    <main className="content">
      <header className="topbar"><div className="breadcrumb"><button className="menu-toggle" aria-label="Abrir menu" aria-expanded={menuOpen} onClick={() => setMenuOpen(!menuOpen)}><Menu size={22} /></button>Panel <ChevronRight size={14} /> <strong>{nav.find(x => x[0] === view)?.[2]}</strong></div><div className="top-actions"><IconButton icon={Bell} title={notificationsEnabled ? 'Notificaciones activas' : 'Activar notificaciones'} onClick={enableNotifications} tone={notificationsEnabled ? 'accent-icon' : ''} /><IconButton icon={RefreshCw} title="Actualizar datos" onClick={refresh} /></div></header>
      <div className="page">
        {error && <div className="error-banner"><CircleAlert size={17} />{error}<IconButton icon={X} title="Cerrar mensaje" onClick={() => setError('')} /></div>}
        {attentionAccounts.map(account => <div className="attention-banner" role="alert" key={account.id}><CircleAlert size={19} /><div><strong>{account.name}: posible bloqueo o comentario pendiente</strong><p>{account.attention_reason}</p></div><button className="button secondary" disabled={busy} onClick={() => perform(() => request(`/accounts/${account.id}/clear-attention`, { method: 'POST' }))}><Check size={16} />Marcar revisada</button></div>)}
        {view === 'inicio' && <>
          <div className="page-heading"><div><div className="eyebrow">RESUMEN</div><h1>Inicio</h1><p>Actividad de sorteos y ejecuciones locales.</p></div></div>
          {reminders.map(draw => <div className="reminder-banner" role="status" key={draw.id}><Bell size={17} /><strong>{draw.name}</strong><span>Finaliza {formatDeadline(draw)}{draw.end_time ? '' : ' (sin hora)'}</span><a href={draw.url} target="_blank" rel="noreferrer">Ver sorteo</a></div>)}
          <div className="metrics">
            {[
              ['Sorteos activos', currentDraws.length, Link2], ['Por finalizar', upcoming.filter(x => deadlineFor(x) - now <= 7 * 86400000).length, Clock3],
              ['Finalizados', finished.length, CircleCheck], ['Tareas activas', data.overview.active_tasks, Activity],
              ['Clics', data.overview.clicked, Check], ['Intentos', data.overview.attempts, ListTodo],
            ].map(([label, value, Icon]) => <div className="metric" key={label}><div className="metric-top"><span>{label}</span><Icon size={18} /></div><strong>{value ?? 0}</strong></div>)}
          </div>
          <div className="dashboard-grid">
            <section className="dashboard-section"><div className="section-heading"><h2>Por finalizar</h2><label className="reminder-setting"><Settings2 size={15} />Avisar<select aria-label="Anticipacion del aviso" value={reminderHours} onChange={e => perform(() => request('/settings', { method: 'PUT', body: JSON.stringify({ reminder_hours_before: Number(e.target.value) }) }))}><option value="1">1 h antes</option><option value="3">3 h antes</option><option value="6">6 h antes</option><option value="12">12 h antes</option><option value="24">24 h antes</option><option value="48">48 h antes</option><option value="72">72 h antes</option></select></label></div><div className="compact-list">{upcoming.slice(0, 6).map(draw => <div className="compact-row" key={draw.id}><span className="compact-name">{draw.name}</span><span>{formatDeadline(draw)}</span><strong>{timeLeft(draw, now)}</strong></div>)}{!upcoming.length && <Empty text="No hay sorteos con fecha proxima." />}</div></section>
            <section className="dashboard-section"><div className="section-heading"><h2>Mas comentados</h2><span className="subtle">Clics en Publicar</span></div><div className="compact-list">{drawStats.filter(x => x.clicked).sort((a, b) => b.clicked - a.clicked).slice(0, 6).map(draw => <div className="compact-row" key={draw.id}><span className="compact-name">{draw.name}</span><strong>{draw.clicked}</strong></div>)}{!drawStats.some(x => x.clicked) && <Empty text="Todavia no hay clics registrados." />}</div></section>
          </div>
          <section className="dashboard-section trend-section"><div className="section-heading"><h2>Clics por dia</h2><span className="subtle">Ultimos 7 dias</span></div><div className="trend-chart" role="img" aria-label="Clics en Publicar de los ultimos 7 dias">{trend.map(item => <div className="trend-column" key={item.day} title={`${formatDate(item.day)}: ${item.clicked} clics`}><span>{item.clicked}</span><div className="trend-track"><div style={{ height: `${Math.max(3, item.clicked / maxTrend * 100)}%` }} /></div><small>{item.day.slice(5)}</small></div>)}</div></section>
          <div className="dashboard-grid"><section className="dashboard-section"><div className="section-heading"><h2>Sorteos activos</h2><button className="text-action" onClick={() => setView('sorteos')}>Ver todos <ChevronRight size={16} /></button></div><div className="compact-list">{currentDraws.slice(0, 6).map(draw => <div className="compact-row" key={draw.id}><span className="compact-name">{draw.name}</span><span>{draw.clicked} clics</span></div>)}{!currentDraws.length && <Empty text="No hay sorteos activos." />}</div></section><section className="dashboard-section"><div className="section-heading"><h2>Finalizados</h2></div><div className="compact-list">{sortDraws(finished, 'date_desc').slice(0, 6).map(draw => <div className="compact-row" key={draw.id}><span className="compact-name">{draw.name}</span><span>{formatDeadline(draw)}</span><strong>{draw.clicked} clics</strong></div>)}{!finished.length && <Empty text="No hay sorteos finalizados." />}</div></section></div>
          <div className="section-heading"><h2>Tareas recientes</h2><button className="text-action" onClick={() => setView('actividad')}>Ver actividad <ChevronRight size={16} /></button></div>
          <SchedulerSummary scheduler={data.scheduler} settings={data.settings} perform={perform} />
          <TaskTable tasks={data.tasks} reasons={data.scheduler.reasons || {}} limit={6} perform={perform} busy={busy} onSelect={id => { setSelectedTask(id); setView('actividad') }} />
        </>}
        {view === 'cuentas' && <>
          <PageHeading title="Cuentas" subtitle="Perfiles Chrome y acceso manual a Instagram." action="Agregar cuenta" onAction={() => openModal('accounts')} />
          <div className="account-note"><strong>Acceso visual privado</strong><span>Agrega una cuenta con un perfil, por ejemplo cuenta2. Abre su navegador desde la tarjeta de abajo, inicia sesion manualmente y cierralo al terminar.</span></div>
          <SearchBox value={filter} onChange={setFilter} />
          <div className="table-wrap accounts-table"><table><thead><tr><th>Cuenta</th><th>Argumento de perfil</th><th>Ruta efectiva</th><th>Estado</th><th className="actions-col">Acciones</th></tr></thead><tbody>
            {data.accounts.filter(x => match(`${x.name} ${x.profile_arg}`)).map(item => <tr key={item.id}><td className="primary-cell">{item.name}</td><td><code>{item.profile_arg}</code></td><td className="path-cell" title={item.profile_path}>{item.profile_path}</td><td>{item.archived ? <span className="status">Archivada</span> : item.attention_required ? <span className="status status-interrupted">Revisar</span> : <span className="status status-running">Activa</span>}</td><td className="row-actions"><IconButton icon={Edit3} title="Editar cuenta" onClick={() => openModal('accounts', item)} /><IconButton icon={Archive} title="Archivar cuenta" disabled={!!item.archived || busy} onClick={() => confirmAction(`¿Archivar la cuenta ${item.name}?`, () => perform(() => request(`/accounts/${item.id}/archive`, { method: 'POST' })))} /></td></tr>)}
          </tbody></table>{data.accounts.length === 0 && <Empty text="Todavia no hay cuentas." />}</div>
          <div className="account-session-grid">{data.accounts.filter(x => !x.archived && match(`${x.name} ${x.profile_arg}`)).map(item => <article className="account-session-card" key={item.id}>
            <div><strong>{item.name}</strong><code>{item.profile_arg}</code></div>
            <span className="status">{sessionLabels[item.session_status] || 'No verificada'}</span>
            <small>Última verificación: {item.session_checked_at ? new Date(item.session_checked_at).toLocaleString() : 'Nunca'}</small>
            <small>{data.tasks.some(task => task.account_id === item.id && ['running', 'pausing', 'cancelling'].includes(task.status)) ? 'En uso por una tarea' : 'Sin tarea activa'}</small>
            <button className="button primary" onClick={() => setVisualAccount(item)}>Iniciar sesión / verificar</button>
            <div className="account-card-actions"><button className="button secondary" onClick={() => openModal('accounts', item)}>Editar</button><button className="button secondary" disabled={busy} onClick={() => confirmAction(`¿Archivar la cuenta ${item.name}?`, () => perform(() => request(`/accounts/${item.id}/archive`, { method: 'POST' })))}>Archivar</button></div>
          </article>)}</div>
        </>}
        {view === 'sorteos' && <>
          <PageHeading title="Sorteos" subtitle="Publicaciones guardadas y disponibles para vincular." action="Nuevo sorteo" onAction={() => openModal('draws')} />
          <div className="draw-tools"><SearchBox value={filter} onChange={setFilter} /><label className="draw-select">Estado<select aria-label="Filtrar sorteos por estado" value={drawStatusFilter} onChange={e => setDrawStatusFilter(e.target.value)}><option value="active">Activo</option><option value="finished">Finalizado</option><option value="archived">Archivado</option><option value="all">Todos</option></select></label><label className="draw-select">Ordenar<select aria-label="Ordenar sorteos" value={drawOrder} onChange={e => setDrawOrder(e.target.value)}><option value="date_desc">Fecha: mas reciente</option><option value="date_asc">Fecha: mas antigua</option><option value="comments_desc">Comentarios IG: mayor cantidad</option></select></label></div>
          <div className="table-wrap"><table><thead><tr><th>Nombre</th><th>Publicacion</th><th>Finaliza</th><th>Menciones</th><th>Comentarios IG</th><th>Estado</th><th className="actions-col">Acciones</th></tr></thead><tbody>
            {visibleDraws.map(item => <tr key={item.id}><td className="primary-cell">{item.name}</td><td><a href={item.url} target="_blank" rel="noreferrer" className="url-cell">{item.url}</a></td><td>{formatDeadline(item)}</td><td>{item.tag_count}</td><td className="count-cell">{item.comment_count == null ? <span className="subtle">Sin medir</span> : <><strong>{new Intl.NumberFormat('es-AR').format(item.comment_count)}</strong><small title={new Date(item.comment_count_checked_at).toLocaleString('es-AR')}>{new Date(item.comment_count_checked_at).toLocaleString('es-AR')}</small></>}</td><td>{item.archived ? <span className="status">Archivado</span> : drawState(item, now) === 'finished' ? <span className="status status-cancelled">Finalizado</span> : <span className="status status-running">Activo</span>}</td><td className="row-actions"><IconButton icon={Edit3} title="Editar sorteo" onClick={() => openModal('draws', item)} /><IconButton icon={Archive} title="Archivar sorteo" disabled={!!item.archived || busy} onClick={() => confirmAction(`¿Archivar el sorteo ${item.name}?`, () => perform(() => request(`/draws/${item.id}/archive`, { method: 'POST' })))} /></td></tr>)}
          </tbody></table>{!visibleDraws.length && <Empty text={data.draws.length ? 'No hay sorteos con estos filtros.' : 'Todavia no hay sorteos.'} />}</div>
        </>}
        {view === 'asignaciones' && <>
          <PageHeading title="Asignaciones" subtitle="Vincula una cuenta con un sorteo y define su ejecucion." action="Nueva asignacion" onAction={() => openModal('assignments')} />
          <div className="assignment-tools"><button className="button secondary" onClick={() => openModal('tags')}><Tags size={16} />Etiquetas disponibles ({data.tags.length})</button></div>
          <SearchBox value={filter} onChange={setFilter} />
          <div className="table-wrap"><table><thead><tr><th>Cuenta</th><th>Sorteo</th><th>Duracion</th><th>Frecuencia</th><th>Etiquetas</th><th>Estado</th><th className="actions-col">Acciones</th></tr></thead><tbody>
            {data.assignments.filter(x => match(`${x.account_name} ${x.draw_name}`)).map(item => <tr key={item.id}><td className="primary-cell">{item.account_name}</td><td>{item.draw_name}</td><td>{item.duration_minutes === 0 ? 'Indefinida' : `${item.duration_minutes} min`}</td><td>{item.comments_per_minute}/min</td><td>{item.draw_tag_count}</td><td>{item.archived ? <span className="status">Archivada</span> : <span className="status status-running">Activa</span>}</td><td className="row-actions"><IconButton icon={Play} title="Iniciar tarea" disabled={!!item.archived || busy || !activeAssignments.some(a => a.id === item.id)} tone="accent-icon" onClick={() => confirmAction(`¿Iniciar la tarea de ${item.account_name} en ${item.draw_name}?`, () => perform(() => request(`/assignments/${item.id}/start`, { method: 'POST' })))} /><IconButton icon={Edit3} title="Editar asignacion" onClick={() => openModal('assignments', item)} /><IconButton icon={Archive} title="Archivar asignacion" disabled={!!item.archived || busy} onClick={() => confirmAction('¿Archivar esta asignación?', () => perform(() => request(`/assignments/${item.id}/archive`, { method: 'POST' })))} /></td></tr>)}
          </tbody></table>{data.assignments.length === 0 && <Empty text="Todavia no hay asignaciones." />}</div>
        </>}
        {view === 'actividad' && <>
          <PageHeading title="Actividad" subtitle="Seguimiento de ejecuciones e historial de eventos." />
          <div className="assignment-tools"><button className="button secondary" onClick={() => openModal('history')}><Edit3 size={16} />Corregir historial</button></div>
          <SchedulerSummary scheduler={data.scheduler} settings={data.settings} perform={perform} />
          <TaskTable tasks={data.tasks} reasons={data.scheduler.reasons || {}} perform={perform} busy={busy} onSelect={setSelectedTask} selected={task?.id} />
          {task?.last_error && <section className="task-error-detail" role="alert"><div><CircleAlert size={17} /><strong>Detalle de la tarea #{task.id}</strong></div><pre>{task.last_error}</pre></section>}
          <Diagnostics task={task} />
          <div className="section-heading activity-heading"><h2>Eventos {task ? `· Tarea #${task.id}` : ''}</h2><span className="subtle">Actualizacion automatica</span></div>
          <div className="event-list">{(eventsTaskId === task?.id ? taskEvents : []).map(event => <div className="event" key={event.id}><span className={`event-dot event-${event.kind}`} /><div><strong>{eventLabels[event.kind] || event.kind}</strong><p>{event.kind === 'failed' ? errorSummary(event.message) : event.message}</p></div><time>{new Date(event.created_at).toLocaleString('es-AR')}</time></div>)}{eventsTaskId === task?.id && !taskEvents.length && <Empty text="No hay eventos registrados para esta tarea." />}</div>
        </>}
      </div>
    </main>

    {visualAccount && <VisualAccount account={visualAccount} onClose={() => setVisualAccount(null)} onChanged={refresh} />}
    {modal && <div className="modal-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) setModal(null) }}><form className="modal" onSubmit={save}><div className="modal-head"><div><div className="eyebrow">{modal.id ? 'EDITAR' : 'CREAR'}</div><h2>{modal.type === 'accounts' ? 'Cuenta' : modal.type === 'draws' ? 'Sorteo' : modal.type === 'tags' ? 'Etiquetas disponibles' : modal.type === 'history' ? 'Corregir historial' : 'Asignacion'}</h2></div><IconButton icon={X} title="Cerrar" onClick={() => setModal(null)} /></div>{error && <div className="modal-error"><CircleAlert size={15} />{error}</div>}<div className="modal-body">
      {modal.type === 'accounts' && <><Field label="Nombre" value={form.name} onChange={value => setForm({ ...form, name: value, profile_arg: modal.id || form.profile_arg ? form.profile_arg : value })} required /><Field label="Perfil Chrome" value={form.profile_arg} onChange={value => setForm({ ...form, profile_arg: value })} placeholder="cuenta2" required /><p className="field-hint">Se crea el directorio privado si falta. Podés reutilizar un perfil existente que aún no esté registrado.</p></>}
      {modal.type === 'draws' && <><Field label="Nombre" value={form.name} onChange={value => setForm({ ...form, name: value })} required /><Field label="URL de Instagram" value={form.url} onChange={value => setForm({ ...form, url: value })} placeholder="https://www.instagram.com/p/.../" required /><div className="field-row"><Field label="Fecha de finalizacion" type="date" value={form.end_date || ''} onChange={value => setForm({ ...form, end_date: value, end_time: value ? form.end_time : '' })} /><Field label="Hora de finalizacion" type="time" value={form.end_time || ''} onChange={value => setForm({ ...form, end_time: value })} disabled={!form.end_date} /></div><p className="field-hint">Sin hora, se considera el final de ese dia.</p><Field label="N menciones" type="number" min="0" max="100" value={form.tag_count} onChange={value => setForm({ ...form, tag_count: value })} required /><label className="field">Notas<textarea value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} rows={3} /></label></>}
      {modal.type === 'tags' && <><label className="field">Agregar etiquetas<textarea rows={4} value={form.tags_text || ''} onChange={e => setForm({ ...form, tags_text: e.target.value })} placeholder="@usuario1 @usuario2" /></label><div className="tag-library">{data.tags.map(tag => <div className="tag-library-row" key={tag}><span>{tag}</span><IconButton icon={Trash2} title={`Quitar ${tag}`} disabled={busy} onClick={() => perform(() => request(`/tags/${encodeURIComponent(tag)}`, { method: 'DELETE' }))} /></div>)}</div></>}
      {modal.type === 'history' && <><Field label="IDs de tareas terminadas" value={form.task_ids_text || ''} onChange={value => setForm({ ...form, task_ids_text: value })} placeholder="20-24, 9" required /><label className="field">Sorteo real<select value={form.draw_id || ''} onChange={e => setForm({ ...form, draw_id: e.target.value })} required><option value="">Seleccionar</option>{data.draws.map(draw => <option key={draw.id} value={draw.id}>{draw.name}</option>)}</select></label></>}
      {modal.type === 'assignments' && <><div className="field-row"><label className="field">Cuenta<select value={form.account_id} onChange={e => setForm({ ...form, account_id: e.target.value })} required><option value="">Seleccionar</option>{activeAccounts.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}</select></label><label className="field">Sorteo<select value={form.draw_id} onChange={e => setForm({ ...form, draw_id: e.target.value })} required><option value="">Seleccionar</option>{activeDraws.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}</select></label></div><div className="field-row"><label className="field">Duracion<select value={form.unlimited ? 'unlimited' : 'fixed'} onChange={e => setForm({ ...form, unlimited: e.target.value === 'unlimited', duration_minutes: form.duration_minutes || 60 })}><option value="fixed">Por tiempo</option><option value="unlimited">Indefinida, hasta pausar o bloquearse</option></select></label><Field label="Comentarios/min" type="number" min="0.01" max="60" step="0.01" value={form.comments_per_minute} onChange={value => setForm({ ...form, comments_per_minute: value })} required /></div>{!form.unlimited && <Field label="Duracion (min)" type="number" min="1" max="10080" value={form.duration_minutes} onChange={value => setForm({ ...form, duration_minutes: value })} required />}<p className="field-hint">Menciones requeridas por el sorteo: {activeDraws.find(d => d.id === Number(form.draw_id))?.tag_count ?? 'Selecciona un sorteo'}</p><label className="field">Seleccionar etiquetas ({form.tags?.length || 0})<input type="search" value={tagSearch} onChange={e => setTagSearch(e.target.value)} placeholder="Buscar etiquetas" /></label><div className="tag-picker">{data.tags.filter(tag => tag.toLowerCase().includes(tagSearch.toLowerCase())).map(tag => <label key={tag} className="tag-choice"><input type="checkbox" checked={form.tags?.includes(tag) || false} onChange={e => setForm({ ...form, tags: e.target.checked ? [...(form.tags || []), tag] : form.tags.filter(x => x !== tag) })} />{tag}</label>)}{!data.tags.length && <span className="subtle">Carga etiquetas desde la lista de Asignaciones.</span>}</div><label className="field">Texto adicional<textarea rows={2} value={form.extra_text} onChange={e => setForm({ ...form, extra_text: e.target.value })} /></label></>}
    </div><div className="modal-foot"><button type="button" className="button secondary" onClick={() => setModal(null)}>Cancelar</button><button type="submit" className="button primary" disabled={busy}><Check size={16} />Guardar</button></div></form></div>}
  </div>
}

function Field({ label, value, onChange, type = 'text', ...props }) {
  return <label className="field">{label}<input type={type} value={value ?? ''} onChange={e => onChange(e.target.value)} {...props} /></label>
}

function PageHeading({ title, subtitle, action, onAction }) {
  return <div className="page-heading"><div><div className="eyebrow">GESTION</div><h1>{title}</h1><p>{subtitle}</p></div>{action && <button className="button primary" onClick={onAction}><Plus size={17} />{action}</button>}</div>
}

function SchedulerSummary({ scheduler, settings, perform }) {
  const admission = scheduler.admission || {}
  const mb = value => value == null ? 'No disponible' : `${value} MB`
  const source = { pss: 'PSS', rss_fallback: 'RSS (PSS inaccesible en un proceso activo)', rss_transient: 'RSS (procesos transitorios)', none: 'Sin Chrome activo', unknown: 'No disponible' }[admission.memory_source] || 'No disponible'
  return <div className="scheduler-summary">
    <strong>Navegadores activos: {scheduler.active_browsers ?? 0}/{scheduler.limit ?? 1}</strong>
    <span>Tareas en ejecución: {scheduler.running_tasks ?? 0}</span>
    <span>En cola: {scheduler.queued_tasks ?? 0}</span>
    <span>RAM disponible: {mb(admission.available_mb)}</span>
    <span>Chrome gestionado: {mb(admission.chrome_mb)} ({source})</span>
    <span>Intentos de medición: {admission.sampling_attempts ?? 'No disponible'}</span>
    <span>RSS sin ajustar: {mb(admission.chrome_rss_mb)}</span>
    <span>Próximo navegador: {mb(admission.estimated_next_mb)}</span>
    <span>Reserva del sistema: {mb(admission.system_reserve_mb)}</span>
    <span>RAM requerida: {mb(admission.required_mb)}</span>
    <span>Chrome iniciando: {admission.starting_browsers ?? 0}</span>
    <span>Carga CPU: {admission.cpu_load ?? 'No disponible'} / {admission.cpu_threshold ?? 'No disponible'}</span>
    <span className="scheduler-reason">Admisión: {admission.reason || 'No disponible'}</span>
    <label>Máximo de navegadores <select aria-label="Máximo de navegadores simultáneos" value={settings.browser_limit || '1'} onChange={e => perform(() => request('/settings', { method: 'PUT', body: JSON.stringify({ browser_limit: e.target.value }) }))}>{['1', '2', '3', '4', 'auto'].map(value => <option key={value} value={value}>{value === 'auto' ? 'Automático' : value}</option>)}</select></label>
  </div>
}

function SearchBox({ value, onChange }) {
  return <div className="toolbar"><div className="search"><Search size={17} /><input aria-label="Buscar" placeholder="Buscar..." value={value} onChange={e => onChange(e.target.value)} /></div></div>
}

function Empty({ text }) { return <div className="empty">{text}</div> }

function TaskTable({ tasks, limit, perform, busy, onSelect, selected, reasons = {} }) {
  const priority = status => status === 'running' ? 0 : ['queued', 'pausing', 'cancelling'].includes(status) ? 1 : 2
  const ordered = [...tasks].sort((a, b) => priority(a.status) - priority(b.status) || b.id - a.id)
  const visible = limit ? ordered.slice(0, limit) : ordered
  return <div className="table-wrap"><table><thead><tr><th>Tarea</th><th>Cuenta</th><th>Sorteo</th><th>Estado</th><th>Detalle</th><th>Intentos</th><th>Clics</th><th>Tiempo</th><th className="actions-col">Controles</th></tr></thead><tbody>
    {visible.map(item => <tr key={item.id} className={[selected === item.id ? 'selected-row' : '', item.status === 'running' ? 'active-task-row' : ''].filter(Boolean).join(' ')} onClick={() => onSelect(item.id)}>
      <td className="primary-cell">#{item.id}</td><td>{item.account_name}</td><td>{item.draw_name}</td><td><Status value={item.status} /></td>
      <td className="task-error-cell">{item.status === 'queued' && <span>{reasons[item.id] || 'En cola'}</span>}{item.last_error && <span title={errorSummary(item.last_error)}><CircleAlert size={14} /><span className="task-error-text">{errorSummary(item.last_error)}</span></span>}</td>
      <td>{item.attempts}</td><td>{item.clicked}</td><td><span className="time-cell"><Clock3 size={14} />{Math.floor(item.elapsed_seconds / 60)} min</span></td>
      <td className="row-actions" onClick={e => e.stopPropagation()}><IconButton icon={ScrollText} title="Ver logs y error" onClick={() => onSelect(item.id)} />{['queued', 'running'].includes(item.status) && <IconButton icon={Pause} title="Pausar" disabled={busy} onClick={() => perform(() => request(`/tasks/${item.id}/pause`, { method: 'POST' }))} />}{['paused', 'interrupted'].includes(item.status) && <IconButton icon={Play} title="Reanudar" disabled={busy} onClick={() => confirmAction(`¿Reanudar la tarea ${item.id}?`, () => perform(() => request(`/tasks/${item.id}/resume`, { method: 'POST' })))} />}{['queued', 'running', 'paused', 'interrupted'].includes(item.status) && <IconButton icon={Square} title="Cancelar" disabled={busy} onClick={() => confirmAction(`¿Cancelar la tarea ${item.id}?`, () => perform(() => request(`/tasks/${item.id}/cancel`, { method: 'POST' })))} />}</td>
    </tr>)}
  </tbody></table>{tasks.length === 0 && <Empty text="No hay tareas todavia." />}</div>
}

export default App
