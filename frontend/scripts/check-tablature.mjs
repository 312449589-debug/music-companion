// Parse generated alphaTex with the real library, independently of browser pixels.
import assert from 'node:assert/strict'
import fs from 'node:fs'
import * as alphaTab from '@coderline/alphatab'

const jobFolder = process.argv[2]
const examples = jobFolder ? [{
  name: '真实AI作品',
  composition: JSON.parse(fs.readFileSync(`${jobFolder}/artifacts/composition.json`, 'utf8')),
  alphatex: fs.readFileSync(`${jobFolder}/artifacts/score.alphatex`, 'utf8'),
}] : JSON.parse(fs.readFileSync(new URL('../public/diagnostics/tablature.json', import.meta.url), 'utf8'))
const canonical = notes => notes.sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b)))
for (const example of examples) {
  const importer = new alphaTab.importer.AlphaTexImporter()
  importer.initFromString(example.alphatex, new alphaTab.Settings())
  const score = importer.readScore()
  const piece = example.composition
  assert.equal(score.masterBars.length, piece.measures.length)
  assert.equal(score.tempo, piece.tempo_bpm)
  const staff = score.tracks[0].staves[0]
  assert.equal(staff.tuning.length, 6)
  const actual = []
  for (const bar of staff.bars) for (const voice of bar.voices) for (const beat of voice.beats) {
    for (const note of beat.notes) actual.push({
      // alphaTex uses highest string=1; alphaTab's internal model reverses it.
      string: 7 - note.string, fret: note.fret, pitch: note.realValue,
      onset: beat.absolutePlaybackStart / 960 * piece.ppq,
      duration: beat.playbackDuration / 960 * piece.ppq,
    })
  }
  const expected = piece.measures.flatMap(bar => bar.events.filter(e => e.kind === 'note').map(e => ({
    string: e.string, fret: e.fret, pitch: e.midi_pitch, onset: e.onset_tick, duration: e.duration_ticks,
  })))
  assert.deepEqual(canonical(actual), canonical(expected))
  console.log(`${example.name}：真实alphaTab解析通过，${actual.length}个音符的弦号、品位、音高、起点与长度均匹配主数据。`)
}
