import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Activity, Archive, Bell, Check, ChevronRight, CircleAlert, CircleCheck, Clock3,
  Edit3, LayoutDashboard, Link2, ListTodo, Pause, Play, Plus, RefreshCw,
  Search, Square, Users, X,
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
const eventLabels = {
  attempt: 'Intento', clicked: 'Clic en Publicar', confirmed: 'Confirmado',
  failed: 'Error', queued: 'En cola', running: 'Iniciada', paused: 'Pausada',
  pausing: 'Pausa solicitada', cancelling: 'Cancelacion solicitada',
  cancelled: 'Cancelada', completed: 'Completada', interrupted: 'Interrumpida',
  close_error: 'Error al cerrar Chrome',
  blocked_suspected: 'Posible bloqueo',
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
    throw new Error(detail)
  }
  return response.json()
}

const emptyAccount = { name: '', profile_arg: '' }
const emptyDraw = { name: '', url: '', notes: '' }
const emptyAssignment = {
  account_id: '', draw_id: '', duration_minutes: 60, comments_per_minute: 1,
  tag_count: 1, extra_text: '', tags: [],
}

function IconButton({ icon: Icon, title, onClick, disabled, tone = '' }) {
  return <button type="button" className={`icon-button ${tone}`} title={title} aria-label={title} onClick={onClick} disabled={disabled}><Icon size={17} /></button>
}

function Status({ value }) {
  return <span className={`status status-${value}`}>{statusLabels[value] || value}</span>
}

function App() {
  const [view, setView] = useState('inicio')
  const [data, setData] = useState({ overview: {}, accounts: [], draws: [], assignments: [], tasks: [], events: [] })
  const [modal, setModal] = useState(null)
  const [form, setForm] = useState({})
  const [filter, setFilter] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [selectedTask, setSelectedTask] = useState(null)
  const [notificationsEnabled, setNotificationsEnabled] = useState(
    () => typeof Notification !== 'undefined' && Notification.permission === 'granted'
  )
  const lastEventId = useRef(null)

  const refresh = useCallback(async () => {
    try {
      const keys = ['overview', 'accounts', 'draws', 'assignments', 'tasks', 'events']
      const values = await Promise.all(keys.map(key => request(`/${key}`)))
      const latestId = values[5][0]?.id || 0
      if (lastEventId.current !== null && typeof Notification !== 'undefined' && Notification.permission === 'granted') {
        for (const event of values[5].filter(x => x.id > lastEventId.current && x.kind === 'blocked_suspected')) {
          const task = values[4].find(x => x.id === event.task_id)
          try {
            new Notification('Posible bloqueo de Instagram', {
              body: `${task?.account_name || 'Cuenta'}: ${event.message}`,
            })
          } catch { /* El aviso persistente sigue visible en el panel. */ }
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
    const base = type === 'accounts' ? emptyAccount : type === 'draws' ? emptyDraw : emptyAssignment
    setModal({ type, id: item?.id || null })
    const value = item ? { ...item } : { ...base }
    setForm(type === 'assignments' ? { ...value, tags_text: (value.tags || []).join('\n') } : value)
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
      const body = modal.type === 'assignments'
        ? { ...form, account_id: Number(form.account_id), draw_id: Number(form.draw_id),
            duration_minutes: Number(form.duration_minutes), comments_per_minute: Number(form.comments_per_minute),
            tag_count: Number(form.tag_count), tags: form.tags_text.split(/\s+/).filter(Boolean) }
        : form
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
  const match = text => String(text).toLowerCase().includes(filter.toLowerCase())
  const task = data.tasks.find(x => x.id === selectedTask) || data.tasks[0]

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><span className="brand-mark">I</span><span><strong>INSTAGRAM-BOT</strong><small>Panel local</small></span></div>
      <div className="nav-label">ESPACIO DE TRABAJO</div>
      <nav aria-label="Navegacion principal">
        {nav.map(([id, Icon, label]) => <button key={id} className={`nav-item ${view === id ? 'active' : ''}`} onClick={() => { setView(id); setFilter('') }}><Icon size={18} />{label}{view === id && <ChevronRight size={15} className="nav-chevron" />}</button>)}
      </nav>
      <div className="sidebar-foot"><span className="online-dot" />Servidor local <span className="muted">Windows</span></div>
    </aside>

    <main className="content">
      <header className="topbar"><div className="breadcrumb">Panel <ChevronRight size={14} /> <strong>{nav.find(x => x[0] === view)?.[2]}</strong></div><div className="top-actions"><span className="local-badge">127.0.0.1</span><IconButton icon={Bell} title={notificationsEnabled ? 'Notificaciones activas' : 'Activar notificaciones'} onClick={enableNotifications} tone={notificationsEnabled ? 'accent-icon' : ''} /><IconButton icon={RefreshCw} title="Actualizar datos" onClick={refresh} /></div></header>
      <div className="page">
        {error && <div className="error-banner"><CircleAlert size={17} />{error}<IconButton icon={X} title="Cerrar mensaje" onClick={() => setError('')} /></div>}
        {attentionAccounts.map(account => <div className="attention-banner" role="alert" key={account.id}><CircleAlert size={19} /><div><strong>{account.name}: posible bloqueo o comentario pendiente</strong><p>{account.attention_reason}</p></div><button className="button secondary" disabled={busy} onClick={() => perform(() => request(`/accounts/${account.id}/clear-attention`, { method: 'POST' }))}><Check size={16} />Marcar revisada</button></div>)}
        {view === 'inicio' && <>
          <div className="page-heading"><div><div className="eyebrow">RESUMEN</div><h1>Vista general</h1><p>Estado de cuentas, sorteos y ejecuciones locales.</p></div></div>
          <div className="metrics">
            {[
              ['Cuentas', data.overview.accounts, Users], ['Sorteos', data.overview.draws, Link2],
              ['Tareas activas', data.overview.active_tasks, Activity], ['Intentos', data.overview.attempts, ListTodo],
              ['Clics', data.overview.clicked, Check], ['Confirmados', data.overview.confirmed, CircleCheck],
            ].map(([label, value, Icon]) => <div className="metric" key={label}><div className="metric-top"><span>{label}</span><Icon size={18} /></div><strong>{value ?? 0}</strong></div>)}
          </div>
          <div className="section-heading"><h2>Tareas recientes</h2><button className="text-action" onClick={() => setView('actividad')}>Ver actividad <ChevronRight size={16} /></button></div>
          <TaskTable tasks={data.tasks.slice(0, 6)} perform={perform} busy={busy} onSelect={id => { setSelectedTask(id); setView('actividad') }} />
        </>}
        {view === 'cuentas' && <>
          <PageHeading title="Cuentas" subtitle="Perfiles de Chrome disponibles para las asignaciones." action="Nueva cuenta" onAction={() => openModal('accounts')} />
          <SearchBox value={filter} onChange={setFilter} />
          <div className="table-wrap"><table><thead><tr><th>Cuenta</th><th>Argumento de perfil</th><th>Ruta efectiva</th><th>Estado</th><th className="actions-col">Acciones</th></tr></thead><tbody>
            {data.accounts.filter(x => match(`${x.name} ${x.profile_arg}`)).map(item => <tr key={item.id}><td className="primary-cell">{item.name}</td><td><code>{item.profile_arg}</code></td><td className="path-cell" title={item.profile_path}>{item.profile_path}</td><td>{item.archived ? <span className="status">Archivada</span> : item.attention_required ? <span className="status status-interrupted">Revisar</span> : <span className="status status-running">Activa</span>}</td><td className="row-actions"><IconButton icon={Edit3} title="Editar cuenta" onClick={() => openModal('accounts', item)} /><IconButton icon={Archive} title="Archivar cuenta" disabled={!!item.archived || busy} onClick={() => perform(() => request(`/accounts/${item.id}/archive`, { method: 'POST' }))} /></td></tr>)}
          </tbody></table>{data.accounts.length === 0 && <Empty text="Todavia no hay cuentas." />}</div>
        </>}
        {view === 'sorteos' && <>
          <PageHeading title="Sorteos" subtitle="Publicaciones guardadas y disponibles para vincular." action="Nuevo sorteo" onAction={() => openModal('draws')} />
          <SearchBox value={filter} onChange={setFilter} />
          <div className="table-wrap"><table><thead><tr><th>Nombre</th><th>Publicacion</th><th>Notas</th><th>Estado</th><th className="actions-col">Acciones</th></tr></thead><tbody>
            {data.draws.filter(x => match(`${x.name} ${x.url} ${x.notes}`)).map(item => <tr key={item.id}><td className="primary-cell">{item.name}</td><td><a href={item.url} target="_blank" rel="noreferrer" className="url-cell">{item.url}</a></td><td className="notes-cell">{item.notes || '—'}</td><td>{item.archived ? <span className="status">Archivado</span> : <span className="status status-running">Activo</span>}</td><td className="row-actions"><IconButton icon={Edit3} title="Editar sorteo" onClick={() => openModal('draws', item)} /><IconButton icon={Archive} title="Archivar sorteo" disabled={!!item.archived || busy} onClick={() => perform(() => request(`/draws/${item.id}/archive`, { method: 'POST' }))} /></td></tr>)}
          </tbody></table>{data.draws.length === 0 && <Empty text="Todavia no hay sorteos." />}</div>
        </>}
        {view === 'asignaciones' && <>
          <PageHeading title="Asignaciones" subtitle="Vincula una cuenta con un sorteo y define su ejecucion." action="Nueva asignacion" onAction={() => openModal('assignments')} />
          <SearchBox value={filter} onChange={setFilter} />
          <div className="table-wrap"><table><thead><tr><th>Cuenta</th><th>Sorteo</th><th>Duracion</th><th>Frecuencia</th><th>Etiquetas</th><th>Estado</th><th className="actions-col">Acciones</th></tr></thead><tbody>
            {data.assignments.filter(x => match(`${x.account_name} ${x.draw_name}`)).map(item => <tr key={item.id}><td className="primary-cell">{item.account_name}</td><td>{item.draw_name}</td><td>{item.duration_minutes} min</td><td>{item.comments_per_minute}/min</td><td>{item.tag_count}</td><td>{item.archived ? <span className="status">Archivada</span> : <span className="status status-running">Activa</span>}</td><td className="row-actions"><IconButton icon={Play} title="Iniciar tarea" disabled={!!item.archived || busy || !activeAssignments.some(a => a.id === item.id)} tone="accent-icon" onClick={() => perform(() => request(`/assignments/${item.id}/start`, { method: 'POST' }))} /><IconButton icon={Edit3} title="Editar asignacion" onClick={() => openModal('assignments', item)} /><IconButton icon={Archive} title="Archivar asignacion" disabled={!!item.archived || busy} onClick={() => perform(() => request(`/assignments/${item.id}/archive`, { method: 'POST' }))} /></td></tr>)}
          </tbody></table>{data.assignments.length === 0 && <Empty text="Todavia no hay asignaciones." />}</div>
        </>}
        {view === 'actividad' && <>
          <PageHeading title="Actividad" subtitle="Seguimiento de ejecuciones e historial de eventos." />
          <TaskTable tasks={data.tasks} perform={perform} busy={busy} onSelect={setSelectedTask} selected={task?.id} />
          <div className="section-heading activity-heading"><h2>Eventos {task ? `· Tarea #${task.id}` : ''}</h2><span className="subtle">Actualizacion automatica</span></div>
          <div className="event-list">{data.events.filter(e => !task || e.task_id === task.id).slice(0, 100).map(event => <div className="event" key={event.id}><span className={`event-dot event-${event.kind}`} /><div><strong>{eventLabels[event.kind] || event.kind}</strong><p>{event.message}</p></div><time>{new Date(event.created_at).toLocaleString('es-AR')}</time></div>)}{!data.events.length && <Empty text="No hay eventos registrados." />}</div>
        </>}
      </div>
    </main>

    {modal && <div className="modal-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) setModal(null) }}><form className="modal" onSubmit={save}><div className="modal-head"><div><div className="eyebrow">{modal.id ? 'EDITAR' : 'CREAR'}</div><h2>{modal.type === 'accounts' ? 'Cuenta' : modal.type === 'draws' ? 'Sorteo' : 'Asignacion'}</h2></div><IconButton icon={X} title="Cerrar" onClick={() => setModal(null)} /></div>{error && <div className="modal-error"><CircleAlert size={15} />{error}</div>}<div className="modal-body">
      {modal.type === 'accounts' && <><Field label="Nombre" value={form.name} onChange={value => setForm({ ...form, name: value })} required /><Field label="Argumento de perfil" value={form.profile_arg} onChange={value => setForm({ ...form, profile_arg: value })} placeholder="accounts/cuenta1" required /><p className="field-hint">Se anexa al directorio de perfiles del runner actual.</p></>}
      {modal.type === 'draws' && <><Field label="Nombre" value={form.name} onChange={value => setForm({ ...form, name: value })} required /><Field label="URL de Instagram" value={form.url} onChange={value => setForm({ ...form, url: value })} placeholder="https://www.instagram.com/p/.../" required /><label className="field">Notas<textarea value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} rows={3} /></label></>}
      {modal.type === 'assignments' && <><div className="field-row"><label className="field">Cuenta<select value={form.account_id} onChange={e => setForm({ ...form, account_id: e.target.value })} required><option value="">Seleccionar</option>{activeAccounts.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}</select></label><label className="field">Sorteo<select value={form.draw_id} onChange={e => setForm({ ...form, draw_id: e.target.value })} required><option value="">Seleccionar</option>{activeDraws.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}</select></label></div><div className="field-row"><Field label="Duracion (min)" type="number" min="1" max="10080" value={form.duration_minutes} onChange={value => setForm({ ...form, duration_minutes: value })} required /><Field label="Comentarios/min" type="number" min="0.01" max="60" step="0.01" value={form.comments_per_minute} onChange={value => setForm({ ...form, comments_per_minute: value })} required /></div><Field label="Cantidad de etiquetas" type="number" min="0" max="100" value={form.tag_count} onChange={value => setForm({ ...form, tag_count: value })} required /><label className="field">Etiquetas disponibles<textarea rows={3} value={form.tags_text || ''} onChange={e => setForm({ ...form, tags_text: e.target.value })} placeholder="@usuario1 @usuario2" required /></label><label className="field">Texto adicional<textarea rows={2} value={form.extra_text} onChange={e => setForm({ ...form, extra_text: e.target.value })} /></label></>}
    </div><div className="modal-foot"><button type="button" className="button secondary" onClick={() => setModal(null)}>Cancelar</button><button type="submit" className="button primary" disabled={busy}><Check size={16} />Guardar</button></div></form></div>}
  </div>
}

function Field({ label, value, onChange, type = 'text', ...props }) {
  return <label className="field">{label}<input type={type} value={value ?? ''} onChange={e => onChange(e.target.value)} {...props} /></label>
}

function PageHeading({ title, subtitle, action, onAction }) {
  return <div className="page-heading"><div><div className="eyebrow">GESTION</div><h1>{title}</h1><p>{subtitle}</p></div>{action && <button className="button primary" onClick={onAction}><Plus size={17} />{action}</button>}</div>
}

function SearchBox({ value, onChange }) {
  return <div className="toolbar"><div className="search"><Search size={17} /><input aria-label="Buscar" placeholder="Buscar..." value={value} onChange={e => onChange(e.target.value)} /></div></div>
}

function Empty({ text }) { return <div className="empty">{text}</div> }

function TaskTable({ tasks, perform, busy, onSelect, selected }) {
  return <div className="table-wrap"><table><thead><tr><th>Tarea</th><th>Cuenta</th><th>Sorteo</th><th>Estado</th><th>Intentos</th><th>Clics</th><th>Tiempo</th><th className="actions-col">Controles</th></tr></thead><tbody>{tasks.map(item => <tr key={item.id} className={selected === item.id ? 'selected-row' : ''} onClick={() => onSelect(item.id)}><td className="primary-cell">#{item.id}</td><td>{item.account_name}</td><td>{item.draw_name}</td><td><Status value={item.status} /></td><td>{item.attempts}</td><td>{item.clicked}</td><td><span className="time-cell"><Clock3 size={14} />{Math.floor(item.elapsed_seconds / 60)} min</span></td><td className="row-actions" onClick={e => e.stopPropagation()}>{['queued', 'running'].includes(item.status) && <IconButton icon={Pause} title="Pausar" disabled={busy} onClick={() => perform(() => request(`/tasks/${item.id}/pause`, { method: 'POST' }))} />}{['paused', 'interrupted'].includes(item.status) && <IconButton icon={Play} title="Reanudar" disabled={busy} onClick={() => perform(() => request(`/tasks/${item.id}/resume`, { method: 'POST' }))} />}{['queued', 'running', 'paused', 'interrupted'].includes(item.status) && <IconButton icon={Square} title="Cancelar" disabled={busy} onClick={() => perform(() => request(`/tasks/${item.id}/cancel`, { method: 'POST' }))} />}</td></tr>)}</tbody></table>{tasks.length === 0 && <Empty text="No hay tareas todavia." />}</div>
}

export default App
