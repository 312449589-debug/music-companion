"""Conservative tonal prototype checks; one declared chord per bar, not full theory analysis."""
import re
from app.music.validation import MusicIssue, MusicValidationError

ROOTS = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
QUALITIES = {'': (0, 4, 7), 'maj': (0, 4, 7), 'm': (0, 3, 7), 'min': (0, 3, 7),
             '7': (0, 4, 7, 10), 'maj7': (0, 4, 7, 11), 'm7': (0, 3, 7, 10),
             'dim': (0, 3, 6), 'dim7': (0, 3, 6, 9), 'm7b5': (0, 3, 6, 10)}


def root_pc(letter, accidental):
    return (ROOTS[letter] + {'': 0, '#': 1, 'b': -1}[accidental]) % 12


def tonal_key(text):
    value = text.strip().replace('♯', '#').replace('♭', 'b')
    match = re.fullmatch(r'([A-G])([#b]?)(?:\s*(major|minor|maj|min|m))?', value)
    if not match: raise ValueError('暂不支持该调性写法')
    return root_pc(match[1], match[2]), match[3] in ('minor', 'min', 'm')


def chord_info(text):
    value = (text or '').strip().replace('♯', '#').replace('♭', 'b').replace('°', 'dim')
    match = re.fullmatch(r'([A-G])([#b]?)(maj7|m7b5|dim7|dim|maj|min|m7|m|7)?(?:/([A-G])([#b]?))?', value)
    if not match: raise ValueError('需使用支持的三和弦/七和弦符号，每小节一个和弦')
    root = root_pc(match[1], match[2]); intervals = QUALITIES[match[3] or '']
    pcs = {(root + interval) % 12 for interval in intervals}
    bass = root_pc(match[4], match[5]) if match[4] else root
    if bass not in pcs: raise ValueError('转位低音必须属于和弦')
    return root, intervals, pcs, bass


def validate_harmony(piece):
    issues = []
    def fail(path, rule, message): issues.append(MusicIssue(path, rule, message))
    try: tonic, minor = tonal_key(piece.key_signature)
    except ValueError as error: raise MusicValidationError([MusicIssue('key_signature', 'harmony_key', str(error))]) from None
    # Includes the raised leading tone for the minor dominant. No borrowed/applied chords yet.
    palette = ([(0,'m','T'),(2,'dim','S'),(3,'','T'),(5,'m','S'),(7,'','D'),(8,'','T'),(11,'dim','D')]
               if minor else [(0,'','T'),(2,'m','S'),(4,'m','T'),(5,'','S'),(7,'','D'),(9,'m','T'),(11,'dim','D')])
    allowed = {(tonic + degree) % 12: (QUALITIES[quality], function) for degree, quality, function in palette}
    harmonies = []
    for bi, bar in enumerate(piece.measures):
        path = f'measures.{bi}'
        try: root, intervals, pcs, bass = chord_info(bar.chord)
        except ValueError as error:
            fail(path+'.chord', 'chord_symbol', str(error)); continue
        expected = allowed.get(root)
        if not expected or intervals[:3] != expected[0]:
            fail(path+'.chord', 'functional_chord', '和弦不在本版支持的调内功能和弦范围'); continue
        if len(intervals) == 4:
            scale = {(tonic + x) % 12 for x in ((0,2,3,5,7,8,11) if minor else (0,2,4,5,7,9,11))}
            if not pcs <= scale: fail(path+'.chord', 'chord_extension', '七和弦音不符合当前调性')
        harmonies.append((root, pcs, expected[1], bass))
        notes = [e for e in bar.events if e.kind == 'note']
        accompaniment = [e for e in notes if e.voice == 'accompaniment']
        if any(e.midi_pitch % 12 not in pcs for e in accompaniment):
            fail(path+'.events', 'harmonic_support', '本版和声伴奏需使用当前和弦音，不可只写和弦标签')
        played = {e.midi_pitch % 12 for e in notes}
        if len(intervals) == 4 and (root + intervals[3]) % 12 not in played:
            fail(path+'.events', 'seventh_evidence', '声明七和弦时实际音符必须包含七音')
        if root not in played or (root + intervals[1]) % 12 not in played:
            fail(path+'.events', 'chord_identity', '实际音符需体现和弦根音与三音')
        starts = sorted(accompaniment, key=lambda e: (e.onset_tick, e.midi_pitch))
        if not starts or starts[0].midi_pitch % 12 != bass:
            fail(path+'.events', 'functional_bass', '伴奏开始低音需支持声明的和弦根音或转位低音')
    if len(harmonies) != len(piece.measures): raise MusicValidationError(issues)
    for bi, (previous, current) in enumerate(zip(harmonies, harmonies[1:]), 1):
        if previous[2] == 'D' and current[2] == 'S':
            fail(f'measures.{bi}.chord', 'function_regression', '本版不接受属功能直接退回下属功能，请组织紧张与解决')
    dominant = (tonic + 7) % 12
    if len(harmonies) < 2 or harmonies[-2][0] != dominant or harmonies[-1][0] != tonic:
        fail('measures', 'closing_cadence', '片段末尾需有属和弦到主和弦的明确解决')
    if len(harmonies) >= 2 and (harmonies[-2][3] != dominant or harmonies[-1][3] != tonic):
        fail('measures', 'cadence_bass', '本轮结束终止需使用原位属和弦及原位主和弦')
    boundary = piece.measures[-1].start_tick
    before = [e for b in piece.measures for e in b.events if e.kind == 'note' and e.onset_tick < boundary <= e.onset_tick+e.duration_ticks]
    arriving = [e for e in piece.measures[-1].events if e.kind == 'note' and e.onset_tick == boundary]
    arriving_pitches = {e.midi_pitch for e in arriving}
    leading = [e for e in before if e.midi_pitch % 12 == (tonic-1)%12]
    if not leading or any(e.midi_pitch+1 not in arriving_pitches for e in leading):
        fail('measures', 'leading_tone_resolution', '属到主连接处实际导音需上行半音解决到同音区主音')
    if len(harmonies)>=2 and len(chord_info(piece.measures[-2].chord)[1])==4:
        sevenths=[e for e in before if e.midi_pitch%12==(tonic+5)%12]
        if any(e.midi_pitch-(2 if minor else 1) not in arriving_pitches for e in sevenths):
            fail('measures', 'seventh_resolution', '终止连接处持续的属七音需下行解决到主和弦三音')
    melody = sorted([e for b in piece.measures for e in b.events if e.kind == 'note' and e.voice == 'melody'], key=lambda e:e.onset_tick)
    for i, note in enumerate(melody):
        bi = next(j for j,b in enumerate(piece.measures) if b.start_tick <= note.onset_tick < b.start_tick+b.duration_ticks)
        if note.midi_pitch % 12 in harmonies[bi][1]: continue
        prev = melody[i-1] if i else None; nxt = melody[i+1] if i+1 < len(melody) else None
        left = note.midi_pitch-prev.midi_pitch if prev else 0
        right = nxt.midi_pitch-note.midi_pitch if nxt else 0
        weak = (note.onset_tick-piece.measures[bi].start_tick) % (piece.ppq*2) != 0
        next_bi = next((j for j,b in enumerate(piece.measures) if nxt and b.start_tick<=nxt.onset_tick<b.start_tick+b.duration_ticks), bi)
        resolved = nxt and nxt.midi_pitch % 12 in harmonies[next_bi][1] and nxt.onset_tick == note.onset_tick+note.duration_ticks
        prepared = prev and prev.onset_tick+prev.duration_ticks == note.onset_tick
        passing_neighbor = weak and prepared and abs(left) in (1,2) and abs(right) in (1,2) and (left*right>0 or prev.midi_pitch==nxt.midi_pitch) if nxt else False
        suspension = prepared and left == 0 and right in (-1,-2)
        appoggiatura = not weak and prepared and abs(left)>2 and abs(right) in (1,2)
        anticipation = weak and prepared and right == 0 and next_bi != bi
        if not (resolved and (passing_neighbor or suspension or appoggiatura or anticipation)):
            fail('events.'+note.id, 'nonchord_resolution', '非和弦旋律音需形成可验证的经过、辅助、倚音、延留或先现，并接到和弦音')
    if not melody or melody[-1].midi_pitch % 12 != tonic:
        fail('measures', 'final_melody_tonic', '旋律最后一个音必须是主音')
    elif harmonies[-1][0] == tonic:
        last = melody[-1]; end=piece.measures[-1].start_tick+piece.measures[-1].duration_ticks
        notes=[e for b in piece.measures for e in b.events if e.kind=='note']
        active=[e for e in notes if e.onset_tick<=last.onset_tick<e.onset_tick+e.duration_ticks]
        triad={tonic,(tonic+(3 if minor else 4))%12,(tonic+7)%12}
        if {e.midi_pitch%12 for e in active} != triad or min(active,key=lambda e:e.midi_pitch).midi_pitch%12 != tonic:
            fail('measures', 'final_sonority', '最后主音起奏时，实际音符需构成完整原位主三和弦')
        if last.onset_tick+last.duration_ticks != end or any(e.onset_tick+e.duration_ticks<end for e in active):
            fail('measures', 'final_sustain', '结束主和弦与主音需共同保持到最后小节结束')
    if issues: raise MusicValidationError(issues)
    return {'functions':[h[2] for h in harmonies], 'chords':[b.chord for b in piece.measures],
            'cadence':'V–i' if minor else 'V–I', 'actual_final_tonic_triad':True,
            'scope':'单小节和弦与有限非和弦音检查，不代表完整和声分析或好听程度'}
