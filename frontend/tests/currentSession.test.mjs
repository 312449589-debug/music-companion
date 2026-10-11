import test from 'node:test'
import assert from 'node:assert/strict'
import { loadSession, saveSession } from '../src/api/currentSession.ts'
import { submitGeneration, cancelGeneration } from '../src/api/generation.ts'
const id='11111111-1111-4111-8111-111111111111'
const state={prompt:'温暖',visibleJobId:id,pending:{id,prompt:'新旋律'}}
let stored=null
Object.defineProperty(globalThis,'sessionStorage',{configurable:true,value:{getItem:()=>stored,setItem:(_k,v)=>{stored=v}}})
test('恢复只存当前任务编号及描述，不存谱面或音频副本',()=>{
  assert.equal(saveSession(state),true); assert.deepEqual(loadSession(),state)
  assert.ok(!stored.includes('alphatex'))
})
test('损坏的恢复记录被忽略，不能提交无效任务或超长描述',()=>{
  for(const value of ['bad JSON',JSON.stringify({prompt:'x',pending:{id:'../../x',prompt:'x'}}),JSON.stringify({prompt:'x'.repeat(1001)})]){
    stored=value;assert.equal(loadSession(),null)
  }
})
test('浏览器禁止会话存储时明确报告失败',()=>{
  const original=sessionStorage.setItem
  sessionStorage.setItem=()=>{throw new Error('blocked')}
  assert.equal(saveSession(state),false);sessionStorage.setItem=original
})
test('恢复提交使用同一请求编号，取消使用同一任务编号',async()=>{
  const requests=[]
  globalThis.fetch=async(path,init)=>{
    requests.push([path,init])
    return new Response(JSON.stringify({job_id:id,cancellation_requested:true}),{status:202})
  }
  await submitGeneration('新旋律',new AbortController().signal,undefined,id)
  await submitGeneration('新旋律',new AbortController().signal,undefined,id)
  await cancelGeneration(id,new AbortController().signal)
  assert.deepEqual(JSON.parse(requests[0][1].body),JSON.parse(requests[1][1].body))
  assert.equal(JSON.parse(requests[0][1].body).request_id,id)
  assert.equal(requests[2][0],`/api/jobs/${id}/cancel`)
})
