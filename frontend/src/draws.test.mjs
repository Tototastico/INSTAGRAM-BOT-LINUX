import assert from 'node:assert/strict'
import test from 'node:test'
import { deadlineFor, drawState, reminderDue, sortDraws } from './draws.mjs'

test('timed deadline controls status and reminder window', () => {
  const draw = { id: 1, end_date: '2030-12-31', end_time: '18:30', archived: 0 }
  assert.equal(deadlineFor(draw).getHours(), 18)
  assert.equal(reminderDue(draw, 24, new Date(2030, 11, 30, 18, 29)), false)
  assert.equal(reminderDue(draw, 24, new Date(2030, 11, 30, 18, 30)), true)
  assert.equal(reminderDue(draw, 12, new Date(2030, 11, 31, 6, 30)), true)
  assert.equal(reminderDue(draw, 6, new Date(2030, 11, 31, 12, 30)), true)
  assert.equal(drawState(draw, new Date(2030, 11, 31, 18, 30)), 'finished')
  assert.equal(reminderDue(draw, 6, new Date(2030, 11, 31, 18, 30)), false)
})

test('untimed draws end after their date and archived draws never remind', () => {
  const draw = { id: 1, end_date: '2030-12-31', end_time: null, archived: 0 }
  assert.equal(drawState(draw, new Date(2030, 11, 31, 23, 59)), 'active')
  assert.equal(drawState(draw, new Date(2031, 0, 1)), 'finished')
  assert.equal(reminderDue({ ...draw, archived: 1 }, 24, new Date(2030, 11, 31)), false)
})

test('date sorting keeps undated draws last in both directions', () => {
  const draws = [
    { id: 1, end_date: null },
    { id: 2, end_date: '2030-12-31', end_time: '12:00' },
    { id: 3, end_date: '2030-12-31', end_time: '18:00' },
  ]
  assert.deepEqual(sortDraws(draws, 'date_desc').map(draw => draw.id), [3, 2, 1])
  assert.deepEqual(sortDraws(draws, 'date_asc').map(draw => draw.id), [2, 3, 1])
  assert.deepEqual(draws.map(draw => draw.id), [1, 2, 3])
})

test('comment sorting puts measured totals first without treating zero as missing', () => {
  const draws = [
    { id: 1, comment_count: null },
    { id: 2, comment_count: 0 },
    { id: 3, comment_count: 6681 },
  ]
  assert.deepEqual(sortDraws(draws, 'comments_desc').map(draw => draw.id), [3, 2, 1])
})
