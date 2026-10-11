# 任务08：MIDI导出与核对

状态：2026-10-10导出、重新读取和53项后端测试通过。本任务不合成MP3，不增加播放器。

- `backend/app/music/midi.py`：用mido1.3.3从主数据导出MIDI，记录全曲速度、拍号和调性；绝对音符位置排序后换成相邻消息的时间差，不改变音高或节奏。每根弦独立通道，全部使用零起点program24尼龙弦吉他，避开打击通道。
- 同一个时刻先结束旧音再触发新音；不同弦上的同音不相互截断；有效延音连线合并为一次持续发声。无法可靠导出的同弦同音重叠会明确失败，不能靠关掉另一声部掩盖错误。
- `backend/scripts/check_midi.py`：导出固定诊断样例并重新读取，列出速度、音色和每个音符的开始/结束位置，检查没有负时间差。
- `backend/tests/test_midi.py`：逐音对照主数据，覆盖并行声部、开放弦、重触发、跨弦同音及延音；诊断入口为根目录 `检查MIDI.command`。

实现采用[Mido官方文件与时间说明](https://mido.readthedocs.io/en/latest/files/)。本产品BPM始终以四分音符为单位；MIDI速度只能保存整数微秒，任意小数BPM存在极小舍入误差，不将其改写为另一种拍号口径。

## 亲自操作

双击项目根目录 `检查MIDI.command`，应看到：

1. “MIDI已导出并重新读取”，文件为 `runtime/diagnostics/composition-check.mid`。
2. 实际长度与主数据演奏长度均为6.000000秒。
3. `set_tempo` 为750000（80 BPM）、`program_change` 为24。
4. 两个 `note_on` 都在tick0开始，音高48和64，代表低音和旋律同时弹奏；同一时刻的结束消息出现在新触发之前。

也可在项目根目录运行：

```bash
backend/.venv/bin/python backend/scripts/check_midi.py
```

MIDI是演奏指令文件，浏览器不能像MP3一样直接播放；此任务的完成标准是重新读取后音高、开始位置、持续时间与源数据逐项一致。试听在任务09接入。
