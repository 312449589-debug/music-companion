import test from 'node:test'
import assert from 'node:assert/strict'
import { fetchDownload } from '../src/api/download.ts'
const id = '11111111-1111-4111-8111-111111111111'
const signal = () => new AbortController().signal

test('两类文件仅GET原任务，使用匹配文件类型与文件名', async () => {
  for (const [kind, endpoint, mime] of [['MP3', 'audio', 'audio/mpeg'], ['PDF', 'pdf', 'application/pdf']]) {
    globalThis.fetch = async (path, init) => {
      assert.equal(path, `/api/jobs/${id}/${endpoint}?download=true`)
      assert.equal(init.method, 'GET'); assert.equal(init.cache, 'no-store')
      return new Response('real-file-bytes', { headers: { 'content-type': mime } })
    }
    const file = await fetchDownload(id, kind, signal())
    assert.equal(file.filename, `music-${id}.${kind.toLowerCase()}`)
    assert.equal(await file.blob.text(), 'real-file-bytes')
  }
})
test('拒绝错误状态、HTML错误页和空文件，不当作下载成功', async () => {
  for (const response of [new Response('error', { status: 409 }), new Response('<html>error</html>', { headers: { 'content-type': 'text/html' } }), new Response('', { headers: { 'content-type': 'audio/mpeg' } })]) {
    globalThis.fetch = async () => response
    await assert.rejects(fetchDownload(id, 'MP3', signal()))
  }
})
test('MP3失败后PDF仍可请求，MP3重试不会提交生成任务', async () => {
  const calls = []; let mp3Attempts = 0
  globalThis.fetch = async (path, init) => {
    assert.equal(init.method, 'GET'); calls.push(path)
    if (path.includes('/audio') && ++mp3Attempts === 1) throw new TypeError('offline')
    return new Response('bytes', { headers: { 'content-type': path.includes('/audio') ? 'audio/mpeg' : 'application/pdf' } })
  }
  await assert.rejects(fetchDownload(id, 'MP3', signal()))
  await fetchDownload(id, 'PDF', signal()); await fetchDownload(id, 'MP3', signal())
  assert.equal(calls.length, 3); assert.equal(mp3Attempts, 2)
})
test('无效任务编号不请求任意地址', async () => {
  globalThis.fetch = async () => { assert.fail('不应请求') }
  await assert.rejects(fetchDownload('../other', 'PDF', signal()))
})
