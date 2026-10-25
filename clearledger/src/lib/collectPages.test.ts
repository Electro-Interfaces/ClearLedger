import { test } from 'node:test'
import assert from 'node:assert/strict'
import { collectPages } from './collectPages.ts'

test('полная выгрузка включает строки за первой страницей и короткий хвост', async () => {
  const all=Array.from({length:2111},(_,i)=>({id:String(i)}))
  const result=await collectPages(async(offset,limit)=>({rows:all.slice(offset,offset+limit),total:all.length}))
  assert.deepEqual(result,all)
})
test('обрыв не выдаётся за полный файл', async () => {
  await assert.rejects(collectPages(async()=>({rows:[],total:10})),/неполная/)
})
test('изменение объёма и дубли останавливают выгрузку', async () => {
  await assert.rejects(collectPages(async offset=>({rows:[{id:String(offset)}],total:offset?3:2}),1),/изменился/)
  await assert.rejects(collectPages(async()=>({rows:[{id:'same'}],total:2}),1),/Повтор записи/)
})
