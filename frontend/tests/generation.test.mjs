import test from 'node:test'
import assert from 'node:assert/strict'
import { getGeneration, submitGeneration, RequestFailure } from '../src/api/generation.ts'
const id = '11111111-1111-4111-8111-111111111111'
const pieceId = '22222222-2222-4222-8222-222222222222'
const ready = { job_id: id, status: 'ready', composition_id: pieceId, composition: { origin: 'ai', composition_id: pieceId, title: '协议测试数据', tempo_bpm: 72, key_signature: 'C', measures: [{}] }, alphatex: 'test protocol', audio_seconds: 15, audio_url: `/api/jobs/${id}/audio`, pdf_url: `/api/jobs/${id}/pdf` }
const signal = () => new AbortController().signal
const respond = (value, status = 200) => { globalThis.fetch = async () => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } }) }
test('提交只发一个POST并去掉首尾空格', async () => {
  let calls = 0
  globalThis.fetch = async (path, init) => { calls++; assert.equal(path, '/api/generate'); assert.equal(init.method, 'POST'); assert.deepEqual(JSON.parse(init.body), { prompt: '温暖' }); return new Response(JSON.stringify({ job_id: id }), { status: 202 }) }
  assert.equal(await submitGeneration(' 温暖 ', signal()), id); assert.equal(calls, 1)
})
test('POST连接丢失不自动重试，标记可能已提交', async () => {
  let calls = 0; globalThis.fetch = async () => { calls++; throw new TypeError('secret transport detail') }
  await assert.rejects(submitGeneration('温暖', signal()), (error) => error instanceof RequestFailure && error.uncertain && !error.message.includes('secret'))
  assert.equal(calls, 1)
})
test('查询失败不进行POST，正确接收原任务的失败状态', async () => {
  globalThis.fetch = async (path, init) => { assert.equal(init.method, 'GET'); assert.equal(path, `/api/jobs/${id}`); return new Response(JSON.stringify({ job_id: id, status: 'failed', error: { message: '模型认证失败' } })) }
  assert.equal((await getGeneration(id, signal())).error.message, '模型认证失败')
})
test('完整ready作品才能被发布', async () => { respond(ready); assert.equal((await getGeneration(id, signal())).composition_id, pieceId) })
test('拒绝错配作品、外部文件地址、超时长与缺失谱面', async () => {
  for (const changes of [{ composition_id: id }, { audio_url: 'https://example.com/audio' }, { audio_seconds: 61 }, { alphatex: '' }, { pdf_url: null }, { job_id: pieceId }]) { respond({ ...ready, ...changes }); await assert.rejects(getGeneration(id, signal()), RequestFailure) }
})
test('队列满可明确重试，无原始服务错误泄漏', async () => { respond({ error: 'secret' }, 429); await assert.rejects(submitGeneration('温暖', signal()), (error) => !error.uncertain && error.message.includes('队列已满')) })
test('音乐检查失败转换为普通用户能读懂的提示', async () => {
  respond({ job_id: id, status: 'failed', error: { stage: 'validation', message: 'measures.0.events.0.tie: invalid internal field' } })
  const job = await getGeneration(id, signal())
  assert.equal(job.error.message, '生成的旋律未通过音乐规则检查，请重试。')
})
test('重新生成只提交原作品编号，不能自行指定速度和调性', async () => {
  globalThis.fetch = async (_path, init) => { assert.deepEqual(JSON.parse(init.body), { prompt: '新听感', source_composition_id: pieceId }); return new Response(JSON.stringify({ job_id: id }), { status: 202 }) }
  await submitGeneration('新听感', signal(), pieceId)
})
