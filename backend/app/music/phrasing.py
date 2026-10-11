"""Observable phrase structure, not an automated judgement of musical taste."""


def phrase_diagnostics(piece):
    bars = []
    rhythms = []
    for bar in piece.measures:
        notes = [e for e in bar.events if e.kind == 'note']
        melody = [e for e in notes if e.voice == 'melody']
        end = bar.start_tick + bar.duration_ticks
        # Include notes carried from earlier bars for the actual sounding coverage.
        sounding = [e for b in piece.measures for e in b.events
                    if e.kind == 'note' and e.onset_tick < end
                    and e.onset_tick + e.duration_ticks > bar.start_tick]
        intervals = sorted((max(bar.start_tick, e.onset_tick), min(end, e.onset_tick + e.duration_ticks))
                           for e in sounding)
        covered = 0
        cursor = bar.start_tick
        for left, right in intervals:
            covered += max(0, right - max(cursor, left))
            cursor = max(cursor, right)
        tail = end - max([bar.start_tick] + [right for _, right in intervals])
        rhythm = tuple(sorted((e.onset_tick - bar.start_tick, e.duration_ticks) for e in melody))
        rhythms.append(rhythm)
        bars.append({'order': bar.order, 'melody_note_count': len(melody),
                     'sounding_ticks': covered, 'bar_ticks': bar.duration_ticks,
                     'silent_tail_ticks': tail})
    repeated = len(rhythms) >= 2 and all(r == rhythms[0] for r in rhythms[1:])
    return {'bars': bars, 'all_melody_rhythms_identical': repeated,
            'repeated_half_bar_silence': repeated and all(b['silent_tail_ticks'] * 2 >= b['bar_ticks'] for b in bars),
            'interpretation': '结构观察，不代表听感、主题或人工可演奏性已通过'}
