import { useEffect, useState } from 'react'

const stageLabels = {
  chrome_start: 'Iniciando Chrome', navigation: 'Abriendo publicación',
  page_ready: 'Preparando página', comment_box_lookup: 'Buscando caja de comentarios',
  comment_box_ready: 'Caja de comentarios disponible', comment_count: 'Leyendo contador',
  comment_typing: 'Escribiendo comentario', publish_button_lookup: 'Buscando Publicar',
  publish_click: 'Clic en Publicar', failed: 'Error', completed: 'Finalizada',
  interrupted: 'Interrumpida', paused: 'Pausada', cancelled: 'Cancelada',
}
const categoryLabels = {
  browser_unresponsive: 'Navegador sin respuesta', session: 'Sesión vencida',
  verification: 'Verificación manual', navigation: 'Navegación',
  page_loading: 'Carga incompleta', selector_missing: 'Selector no encontrado',
  post_unavailable: 'Publicación inaccesible',
  not_interactable: 'Elemento no interactuable', overlay: 'Ventana superpuesta',
  element_lookup: 'Búsqueda de elemento', visibility: 'Visibilidad del elemento',
  browser_state: 'Estado del navegador', interaction: 'Interacción',
  browser_start_failed: 'Chrome no inició',
  profile_preferences_oversized: 'Preferencias del perfil demasiado grandes',
  stale_reference: 'Referencia obsoleta', editor_changed: 'Editor reemplazado',
  ambiguous_control: 'Control ambiguo', not_visible: 'Control no visible',
  pending_comment: 'Comentario pendiente',
}
const dateTime = value => value ? new Date(value).toLocaleString('es-AR') : 'Sin registrar'
const requestedPostUrl = item => {
  try { return JSON.parse(item.control_state || '{}').requested_post_url || '' }
  catch { return '' }
}

export default function Diagnostics({ task, openInitially = false }) {
  const [password, setPassword] = useState('')
  const [authenticated, setAuthenticated] = useState(false)
  const [authChecked, setAuthChecked] = useState(false)
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [image, setImage] = useState(null)
  const [expanded, setExpanded] = useState(false)

  useEffect(() => { setExpanded(!!openInitially) }, [task?.id, openInitially])

  useEffect(() => {
    if (!expanded || !task?.id) return
    setAuthChecked(false)
    fetch('/api/visual/auth', { cache: 'no-store' }).then(r => r.json())
      .then(value => setAuthenticated(!!value.authenticated))
      .catch(() => setAuthenticated(false))
      .finally(() => setAuthChecked(true))
  }, [task?.id, expanded])

  async function login(event) {
    event.preventDefault()
    setError('')
    try {
      const response = await fetch('/api/visual/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password }) })
      setPassword('')
      if (!response.ok) { setError('No se pudo iniciar la sesión administrativa'); return }
      setAuthenticated(true)
    } catch { setError('No se pudo conectar con el servidor') }
  }

  useEffect(() => {
    setData(null)
    setError('')
    setImage(null)
    if (!expanded || !task?.id || !authenticated) return
    let active = true
    const load = async () => {
      try {
        const response = await fetch(`/api/tasks/${task.id}/diagnostics`, {
          credentials: 'same-origin', cache: 'no-store',
        })
        if (response.status === 401 || response.status === 403) { setAuthenticated(false); throw new Error('La sesión administrativa terminó. Iniciá sesión nuevamente.') }
        if (!response.ok) throw new Error(`Diagnóstico no disponible (${response.status})`)
        const result = await response.json()
        if (active) { setData(result); setError('') }
      } catch (err) { if (active) setError(err.message) }
    }
    load()
    const timer = setInterval(load, 5000)
    return () => { active = false; clearInterval(timer) }
  }, [task?.id, authenticated, expanded])

  useEffect(() => () => { if (image?.url) URL.revokeObjectURL(image.url) }, [image])

  async function showScreenshot(item) {
    setError('')
    try {
      const response = await fetch(`/api/tasks/${task.id}/diagnostics/${item.id}/screenshot`, {
        credentials: 'same-origin', cache: 'no-store',
      })
      if (response.status === 401 || response.status === 403) setAuthenticated(false)
      if (!response.ok) throw new Error(`No se pudo abrir la captura (${response.status})`)
      setImage({ id: item.id, url: URL.createObjectURL(await response.blob()) })
    } catch (err) { setError(err.message) }
  }

  return <section className="diagnostics-panel" aria-label="Diagnóstico">
    <div className="section-heading"><h2>Diagnóstico {task ? `· Tarea #${task.id}` : ''}</h2>{task && <button type="button" className="button secondary" aria-expanded={expanded} onClick={() => setExpanded(value => !value)}>{expanded ? "Ocultar diagnóstico" : "Mostrar diagnóstico"}</button>}</div>
    {!task && <p className="subtle">Seleccioná una tarea para ver su diagnóstico.</p>}
    {task && expanded && authChecked && !authenticated && <form className="diagnostics-unlock" onSubmit={login}>
      <label>La sesión administrativa expiró. Ingresá la clave administrativa existente.<input type="password" autoComplete="current-password" value={password} onChange={event => setPassword(event.target.value)} required /></label>
      <button className="button primary" type="submit">Abrir diagnóstico</button>
    </form>}
    {expanded && error && <p className="diagnostics-error" role="alert">{error}</p>}
    {expanded && authenticated && data && <>
      <div className="diagnostics-summary">
        <div><span>Etapa actual</span><strong>{stageLabels[data.stage] || data.stage}</strong><small>{dateTime(data.stage_at)}</small></div>
        <div><span>Último avance real</span><strong>{dateTime(data.last_progress_at)}</strong></div>
        <div><span>Último evento significativo</span><strong>{data.last_event?.kind || 'Sin eventos'}</strong><small>{dateTime(data.last_event?.created_at)}</small></div>
      </div>
      {!data.items.length && <p className="subtle">No se guardó evidencia de esta tarea. Las capturas anteriores a esta actualización no se pueden reconstruir.</p>}
      <div className="diagnostics-list">{data.items.map(item => <article className="diagnostic-card" key={item.id}>
        <div className="diagnostic-card-head"><strong>{categoryLabels[item.category] || item.category}</strong><time>{dateTime(item.created_at)}</time></div>
        <p>{item.summary}</p>
        {requestedPostUrl(item) && <p className="subtle">Publicación solicitada: {requestedPostUrl(item)}</p>}
        {item.category === 'navigation' && <p className="subtle">La captura se omite porque Inicio puede mostrar contenido privado. Revisá el enlace del sorteo y abrilo manualmente con esa cuenta.</p>}
        <dl><div><dt>Etapa</dt><dd>{stageLabels[item.stage] || item.stage}</dd></div><div><dt>Operación</dt><dd>{item.operation || 'No registrada'}</dd></div><div><dt>Condición</dt><dd>{item.condition || 'No registrada'}</dd></div><div><dt>Error</dt><dd>{item.error_type}</dd></div><div><dt>Selector</dt><dd>{item.selector || 'No aplica'}</dd></div><div><dt>URL</dt><dd>{item.page_url || 'No disponible'}</dd></div><div><dt>Título</dt><dd>{item.page_title || 'No disponible'}</dd></div><div><dt>Documento</dt><dd>{item.ready_state}</dd></div><div><dt>Navegador</dt><dd>{item.browser_responding ? 'Responde' : 'No responde'}</dd></div><div><dt>Elementos / visibles</dt><dd>{item.matching_elements ?? '?'} / {item.visible_elements ?? '?'}</dd></div><div><dt>Diálogos</dt><dd>{item.dialog_count ?? '?'}</dd></div></dl>
        {item.error_message && <details><summary>Mensaje técnico de Selenium (datos sensibles ocultos)</summary><pre className="diagnostic-technical">{item.error_message}</pre></details>}
        {item.control_state && item.control_state !== '{}' && <details><summary>{item.stage === 'chrome_start' ? 'Recursos al fallar Chrome' : 'Estado del control'}</summary><pre className="diagnostic-technical">{item.control_state}</pre></details>}
        {item.control_structure && <details><summary>HTML estructural depurado</summary><pre className="diagnostic-technical">{item.control_structure}</pre></details>}
        <small>ID: {item.id}</small>
        {item.has_screenshot ? <button className="button secondary" onClick={() => showScreenshot(item)}>Ver captura</button> : <span className="subtle">Sin captura por privacidad o navegador no disponible</span>}
        {image?.id === item.id && <div className="diagnostic-image"><img src={image.url} alt={`Captura del diagnóstico ${item.id}`} /><button className="button secondary" onClick={() => setImage(null)}>Cerrar captura</button></div>}
      </article>)}</div>
    </>}
  </section>
}
