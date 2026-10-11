import test from 'node:test'
import assert from 'node:assert/strict'
import { isActiveResponse, replacementMatches } from '../src/api/generationGuard.ts'
const a = { job_id: 'A', composition_id: 'pieceA', composition: { tempo_bpm: 100, key_signature: 'C' } }
const b = { job_id: 'B', composition_id: 'pieceB', composition: { source_composition_id: 'pieceA', tempo_bpm: 100, key_signature: 'C' } }
test('完整新结果只有来源、速度、调性一致才允许切换', () => {
  assert.equal(replacementMatches(b, a), true)
  for (const change of [{ tempo_bpm: 72 }, { key_signature: 'D' }, { source_composition_id: 'another' }]) assert.equal(replacementMatches({ ...b, composition: { ...b.composition, ...change } }, a), false)
  assert.equal(replacementMatches(a, a), false)
})
test('延迟旧结果不能覆盖已接收的新作品', async () => {
  let current = a
  const deferred = Promise.resolve(a)
  const newEpoch = 2
  if (isActiveResponse(2, newEpoch, 'B', 'B', false)) current = b
  const late = await deferred
  if (isActiveResponse(1, newEpoch, 'A', 'B', false)) current = late
  assert.equal(current, b)
})
test('同任务旧轮询及已取消响应也被拒绝', () => {
  assert.equal(isActiveResponse(1, 2, 'A', 'A', false), false)
  assert.equal(isActiveResponse(2, 2, 'A', 'A', true), false)
  assert.equal(isActiveResponse(2, 2, 'A', 'A', false), true)
})
