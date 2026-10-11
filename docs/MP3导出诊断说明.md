# 任务09：真实MP3导出

状态：2026-10-10真实合成、编码、完整解码和Chrome播放通过；后端56项测试通过。没有新增正式产品播放器或下载按钮。

- `backend/app/music/audio.py`：主数据先导出MIDI，FluidSynth用已验证的吉他SoundFont合成16位PCM WAV，再由FFmpeg的libmp3lame编码192kbps/44100Hz MP3。使用固定参数数组，不拼接执行用户输入；没有节拍器事件。
- 检查WAV有非零声音、长度不短于作品；FFprobe确认一个MP3音轨及实际时长，FFmpeg完整解码确认文件可解码。使用临时目录，全部通过后才替换目标MP3，失败不交付半成品并保留旧目标文件。
- 根据本机实测尾音，生成前预留3秒，即本轮音频管线演奏时长最多57秒；这属于尾音余量，产品最终上限仍为60秒。编码后再次检查，超限明确失败，不用截掉末尾音符来满足上限。
- `backend/scripts/check_audio.py` 和 `检查MP3.command`：固定样例诊断，无AI费用。双击入口生成后使用本机播放器播放。
- `backend/app/main.py`：固定诊断音频地址，仅用于开发检查，不是任务12的正式作品文件接口。

采用[FluidSynth官方文件渲染方法](https://www.fluidsynth.org/wiki/UserManual/)和[FFprobe官方格式检查参数](https://ffmpeg.org/ffprobe.html)。音乐指令来自同一主数据；所有弦通道使用尼龙弦吉他音色，未启用打击通道。

## 用户操作

双击项目根目录 `检查MP3.command`，应看到“真实MP3生成、格式与完整解码检查通过”，随后播放吉他样例。样例音乐含旋律和低音；演奏6秒，文件含尾音约8.606秒，不是全静音。

服务运行时，也可在Chrome打开 `http://127.0.0.1:8000/diagnostics/audio-check.mp3`，使用浏览器自带控件播放。文件保存在 `runtime/diagnostics/composition-check.mp3`，同目录 `composition-check-audio.json` 是编码和时长检查报告，不进入Git。

命令验证（项目根目录）：

```bash
backend/.venv/bin/python backend/scripts/check_audio.py
backend/.venv/bin/python backend/scripts/check_audio.py --case missing-ffmpeg
backend/.venv/bin/python backend/scripts/check_audio.py --case missing-font
backend/.venv/bin/python backend/scripts/check_audio.py --case failing-ffmpeg
backend/.venv/bin/python backend/scripts/check_audio.py --case tail-overflow
backend/.venv/bin/python backend/scripts/check_audio.py --case encoded-overflow
```

第一条成功，其余故意失败并返回1。缺失工具/音色报具体原因；failing-ffmpeg验证实际编码工具失败；tail-overflow验证生成前留尾音；encoded-overflow仅在该独立诊断进程跳过预留，以实测编码后超60秒会被拒绝，不改变持久配置或产品规则。各失败分支都没有产生对应的 `audio-failure-*.mp3`。

## 验收证据与限度

本机样例：WAV 8.605895692秒、44100Hz双声道、非零峰值1579；MP3 208186字节、约8.605896秒，完整解码成功。Chrome实际进入播放状态，并自然播放至0:08后显示播放按钮；未把“生成文件”当作浏览器播放成功。

另外实测演奏60秒的诊断作品编码后为62.488秒，最终时长检查拒绝，没有截音交付。原样例保持可用。合成音色和音乐听感的人工评价统一放到任务19；本轮没有宣称人工试听评价通过。
