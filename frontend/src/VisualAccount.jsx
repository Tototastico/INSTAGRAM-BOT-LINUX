import { useEffect, useRef, useState } from 'react'
import RFB from '@novnc/novnc/lib/rfb.js'
import './visual-account.css'

async function api(path, options = {}) {
  const response = await fetch(`/api${path}`, { credentials: 'same-origin', cache: 'no-store', ...options })
  if (!response.ok) {
    let detail = `Error ${response.status}`
    try { detail = (await response.json()).detail || detail } catch { /* Status remains visible. */ }
    throw new Error(detail)
  }
  return response.json()
}

const labels = {
  connected: 'Sesión conectada', not_signed_in: 'Sin iniciar sesión',
  verification_required: 'Requiere verificación', session_expired: 'Sesión caducada',
  verification_error: 'Error al verificar', unknown: 'No verificada',
  verification_in_progress: 'Verificación en curso', in_use_by_task: 'En uso por una tarea',
}

export default function VisualAccount({ account, onClose, onChanged }) {
  const [auth, setAuth] = useState(null)
  const [password, setPassword] = useState('')
  const [session, setSession] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [connection, setConnection] = useState('Desconectado')
  const [reconnect, setReconnect] = useState(0)
  const screen = useRef(null)
  const rfb = useRef(null)

  useEffect(() => {
    let live = true
    api('/visual/auth').then(value => { if (live) setAuth(value) }).catch(err => { if (live) setError(err.message) })
    return () => { live = false }
  }, [])

  useEffect(() => {
    if (!auth?.authenticated) return
    let live = true
    const load = () => api(`/accounts/${account.id}/session`).then(value => {
      if (live) setSession(value)
    }).catch(err => { if (live) setError(err.message) })
    load()
    const timer = setInterval(load, 8000)
    return () => { live = false; clearInterval(timer) }
  }, [auth?.authenticated, account.id])

  useEffect(() => {
    if (!auth?.authenticated || !session?.visual?.open || !screen.current) return
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    const socket = new WebSocket(`${protocol}//${location.host}/api/accounts/${account.id}/session/ws`,
      ['binary', `csrf.${auth.csrf}`])
    let remote
    try {
      remote = new RFB(screen.current, socket)
      remote.scaleViewport = true
      remote.resizeSession = false
      remote.focusOnClick = true
      remote.addEventListener('connect', () => setConnection('Conectado'))
      remote.addEventListener('disconnect', () => setConnection('Desconectado; podés reconectar'))
      rfb.current = remote
      setConnection('Conectando…')
    } catch {
      socket.close()
      setConnection('No se pudo iniciar el visor')
    }
    return () => {
      if (remote) remote.disconnect()
      else socket.close()
      rfb.current = null
    }
  }, [auth?.authenticated, auth?.csrf, account.id, session?.visual?.open, reconnect])

  async function action(callback) {
    setBusy(true); setError('')
    try { await callback(); onChanged?.() }
    catch (err) { setError(err.message) }
    finally { setBusy(false) }
  }

  const mutate = (path, method = 'POST', body) => api(path, {
    method, headers: { 'Content-Type': 'application/json', 'X-Visual-CSRF': auth.csrf },
    body: body ? JSON.stringify(body) : undefined,
  })

  function leave() {
    if (session?.visual?.open) {
      action(async () => { await mutate(`/accounts/${account.id}/session/close`); setSession(value => ({ ...value, visual: { open: false } })); onClose() })
    } else onClose()
  }

  return <div className="visual-backdrop" role="presentation">
    <section className="visual-dialog" role="dialog" aria-modal="true" aria-label={`Sesión de ${account.name}`}>
      <header className="visual-head"><div><small>CUENTA DE INSTAGRAM</small><h2>{account.name}</h2><span>Perfil: {account.profile_arg}</span></div><button className="button secondary" onClick={leave} disabled={busy}>Cerrar panel</button></header>
      {error && <p className="visual-error" role="alert">{error}</p>}
      {!auth && <p className="visual-note">Comprobando acceso visual…</p>}
      {auth && !auth.enabled && <p className="visual-note">El acceso visual requiere HTTPS, BOT_PUBLIC_ORIGIN y BOT_VISUAL_ADMIN_PASSWORD_HASH.</p>}
      {auth?.enabled && !auth.authenticated && <form className="visual-login" onSubmit={event => {
        event.preventDefault()
        action(async () => {
          const value = await api('/visual/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password }) })
          setPassword(''); setAuth({ enabled: true, ...value })
        })
      }}><label>Clave de administración visual<input type="password" autoComplete="current-password" value={password} onChange={event => setPassword(event.target.value)} required /></label><button className="button primary" disabled={busy}>Desbloquear</button></form>}
      {auth?.authenticated && <>
        <div className="visual-toolbar"><div><strong>{labels[session?.session_status] || 'No verificada'}</strong><small>Última verificación: {session?.session_checked_at ? new Date(session.session_checked_at).toLocaleString() : 'Nunca'}</small><small>{session?.visual?.open ? connection : 'Navegador cerrado'}</small></div>
          <div className="visual-actions">
            {!session?.visual?.open && <button className="button primary" disabled={busy || session?.session_status === 'in_use_by_task' || session?.session_status === 'verification_in_progress'} onClick={() => action(async () => {
              await mutate(`/accounts/${account.id}/session/open`)
              setSession(value => ({ ...value, visual: { open: true } }))
            })}>{['session_expired', 'verification_required'].includes(session?.session_status) ? 'Reconectar' : 'Iniciar sesión'}</button>}
            <button className="button secondary" disabled={busy || !!session?.visual?.open || session?.session_status === 'in_use_by_task' || session?.session_status === 'verification_in_progress'} onClick={() => action(async () => {
              const result = await mutate(`/accounts/${account.id}/session/verify`)
              setSession(value => ({ ...value, session_status: result.status, session_checked_at: new Date().toISOString() }))
            })}>Verificar conexión</button>
            {session?.visual?.open && <button className="button secondary" disabled={busy} onClick={() => setReconnect(x => x + 1)}>Reconectar visor</button>}
            {session?.visual?.open && <button className="button secondary" disabled={busy} onClick={() => action(async () => {
              await mutate(`/accounts/${account.id}/session/close`)
              setSession(value => ({ ...value, visual: { open: false } }))
            })}>Cerrar navegador</button>}
          </div>
        </div>
        {session?.visual?.open && <div className="visual-screen" ref={screen} aria-label="Navegador remoto de Instagram" />}
        {!session?.visual?.open && <p className="visual-note">Abrí el navegador para iniciar sesión manualmente. Al terminar, cerralo desde este panel para liberar el perfil.</p>}
      </>}
    </section>
  </div>
}
