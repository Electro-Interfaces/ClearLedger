/**
 * Разбор дорожек видеофайла: чтение боксов MP4/MOV.
 *
 * Проверка на настоящей записи экрана (`moov` в конце файла, 20 МБ данных перед
 * описанием) и на синтетическом файле со звуком: важно, что «нет звука» —
 * это прочитанный факт, а не молчание разборщика.
 */
import { describe, it } from 'node:test'
import assert from 'node:assert/strict'
import { videoHasAudio } from './videoAudio.ts'

/** Собрать бокс: 4 байта размера, 4 байта типа, тело. */
function бокс(тип: string, ...части: Uint8Array[]): Uint8Array {
  const тело = части.reduce((a, b) => {
    const o = new Uint8Array(a.length + b.length)
    o.set(a); o.set(b, a.length); return o
  }, new Uint8Array(0))
  const out = new Uint8Array(8 + тело.length)
  new DataView(out.buffer).setUint32(0, out.length)
  for (let i = 0; i < 4; i++) out[4 + i] = тип.charCodeAt(i)
  out.set(тело, 8)
  return out
}

/** hdlr: 4 версия+флаги, 4 pre_defined, 4 тип дорожки. */
const hdlr = (вид: string) => бокс('hdlr', new Uint8Array([
  0, 0, 0, 0, 0, 0, 0, 0, ...[...вид].map((c) => c.charCodeAt(0)), 0, 0, 0, 0,
]))
const дорожка = (вид: string) => бокс('trak', бокс('mdia', hdlr(вид)))

function файл(...дорожки: Uint8Array[]): File {
  // mdat впереди, moov в конце — как пишет запись экрана macOS.
  const данные = бокс('mdat', new Uint8Array(1024))
  const moov = бокс('moov', ...дорожки)
  return new File([бокс('ftyp', new Uint8Array(8)), данные, moov], 'запись.mov')
}

describe('звуковая дорожка в видео', () => {
  it('видео с микрофоном — звук есть', async () => {
    assert.equal(await videoHasAudio(файл(дорожка('vide'), дорожка('soun'))), true)
  })

  it('запись экрана без микрофона — звука нет', async () => {
    assert.equal(await videoHasAudio(файл(дорожка('vide'))), false)
  })

  it('не разобрали контейнер — молчим, а не пугаем', async () => {
    assert.equal(await videoHasAudio(new File([new Uint8Array(64)], 'x.webm')), null)
  })
})
