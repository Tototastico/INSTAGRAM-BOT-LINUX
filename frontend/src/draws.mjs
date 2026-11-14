export function deadlineFor(draw) {
  if (!draw.end_date) return null
  const [year, month, day] = draw.end_date.split('-').map(Number)
  const [hour, minute] = draw.end_time ? draw.end_time.split(':').map(Number) : [23, 59]
  return new Date(year, month - 1, day, hour, minute, draw.end_time ? 0 : 59, draw.end_time ? 0 : 999)
}

export function drawState(draw, now = new Date()) {
  if (draw.archived) return 'archived'
  const deadline = deadlineFor(draw)
  return deadline && deadline <= now ? 'finished' : 'active'
}

export function reminderDue(draw, hoursBefore, now = new Date()) {
  if (drawState(draw, now) !== 'active') return false
  const deadline = deadlineFor(draw)
  return !!deadline && now >= new Date(deadline.getTime() - hoursBefore * 3600000)
}

export function timeLeft(draw, now = new Date()) {
  const deadline = deadlineFor(draw)
  if (!deadline) return 'Sin fecha'
  const remaining = deadline.getTime() - now.getTime()
  if (remaining <= 0) return 'Finalizado'
  if (remaining < 3600000) return 'Menos de 1 h'
  if (remaining < 86400000) return `${Math.ceil(remaining / 3600000)} h`
  return `${Math.ceil(remaining / 86400000)} dias`
}

export function sortDraws(draws, order) {
  return [...draws].sort((a, b) => {
    if (order === 'comments_desc') {
      if (a.comment_count == null || b.comment_count == null) {
        if (a.comment_count == null && b.comment_count == null) return b.id - a.id
        return a.comment_count == null ? 1 : -1
      }
      if (a.comment_count !== b.comment_count) return b.comment_count - a.comment_count
    }
    const first = deadlineFor(a)?.getTime()
    const second = deadlineFor(b)?.getTime()
    if (first == null || second == null) return first == null && second == null ? b.id - a.id : first == null ? 1 : -1
    return (order === 'date_asc' ? first - second : second - first) || b.id - a.id
  })
}
