# 音乐伙伴 Music Companion

面向吉他指弹学习者与教师的本地 AI 创作原型：输入听感描述，真实千问模型生成简单和声＋旋律；查看六线谱、试听、保持 BPM 与调性整段重新生成，分别下载 MP3 和 PDF。标准定弦，最终 MP3 不超过60秒。无需登录；目标浏览器为电脑 Chrome。

## 当前电脑启动

在 Finder 中双击项目根目录的 `启动音乐伙伴.command`。它先构建最新网页，再启动服务并打开 http://127.0.0.1:8000/ 。保留终端窗口。页面应看到“把你的音乐想法，变成可以亲手弹奏的小作品”、描述输入框、三个示例和作品/试听/下载区域。初始没有作品；生成完成后才能试听和下载。

按 Control+C 停止该窗口启动的服务；正常停止会等有限时的生成任务结束。不要强行关窗口来取消生成。再次启动如果提示8000被占用，关闭原服务窗口后重试；启动器不会沿用旧代码，也不会关闭其他进程。8002/8003 是独立诊断端口，不能代替正式首页。

## 安装或迁移到另一台电脑

本版本已在当前 macOS 上验证，不是已完成的 Android 包；音频工具、字体和浏览器需另行安装。Node/npm 不依赖项目在另一台电脑上的绝对目录：有系统 Node 时启动器优先使用它，否则仅在当前电脑回退到 Codex 提供的运行时。

安装 Node.js 与 npm（当前验证 Node 24），以及 Python（当前实际虚拟环境为3.9；新环境可使用3.11，仍应运行验收）。在项目根目录依次执行：

```bash
cd "/你的路径/music companion"
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements-lock.txt
cd frontend
npm ci
cd ..
cp .env.example .env
```

`frontend/package-lock.json` 与 `backend/requirements-lock.txt` 锁定本次验证的依赖；原 requirements.txt 是顶层依赖清单。Python 锁定清单来自 macOS，其他系统可能需要调整平台包并重新验证。

只在本机编辑 `.env`：填写 DASHSCOPE_API_KEY。模板使用已验证的北京百炼兼容接口、qwen-plus 非思考模式、200元预算和本次验证的单价；实际单价变化时按控制台修改。不要把密钥发到聊天、写进前端或提交 Git。

按 [依赖工具与参数记录](docs/依赖工具与参数记录.md) 安装 FluidSynth、FFmpeg、SoundFont 与中文字体，填写 `.env` 对应路径。浏览器安装命令（根目录）：

```bash
PLAYWRIGHT_BROWSERS_PATH="$PWD/.tools/browsers" backend/.venv/bin/python -m playwright install chromium
```

Chromium 用于服务端打印 PDF，不是要求你把 Chrome 换掉。当前工具版本：FluidSynth 2.6.1、FFmpeg 9.0.2、Playwright 1.58.0 / Chromium 145.0.7632.6。音色及许可见上述记录；不要省略音色许可。

完成安装后可双击启动器，或手动启动同一个入口：

```bash
cd frontend
npm run build
cd ../backend
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

打开 http://127.0.0.1:8000/ 。手动方式保持默认8000端口供 PDF 打印使用；无需 Vite。修改网页后重新构建，修改后端后停止并重新启动。健康检查 http://127.0.0.1:8000/api/health 返回 status: ok；它只证明服务可访问，不证明模型/音色/PDF全部正常。

## 验证与文件有效期

真实生成和重新生成需要网络并计入已配置模型预算。下载重试只请求原文件，不重新调用模型。超时等未知费用保守计入预算；`runtime/ai/` 保存费用账本，**不要为了清理文件删除账本**。这是开发预算保护，不替代云控制台的真实账单。

后端测试：在 backend 内运行 `.venv/bin/python -m pytest -q`。前端构建：在 frontend 内运行 `npm run build`；前端测试在根目录运行 `node --experimental-strip-types --test frontend/tests/*.test.mjs`（当前验证 Node 24）。当前无系统 npm 时，启动器会使用本机 `.tools/npm`；无需自己安装全局工具。

生成过程的临时文件位于 `runtime/jobs/任务编号/`，诊断文件位于 `runtime/diagnostics/`；不提交 Git，也不是永久作品库。本版没有自动过期删除：本地文件未移动、删除或修改时接口仍可读取；外部清理导致文件失效会明确报错。请及时下载 MP3/PDF；刷新网页会丢失当前页面的作品入口，当前不提供作品历史恢复界面。服务重启后，已完成的文件仍保留，未完成任务明确失败，不自动再次请求 AI。正常停止会先等待当前任务结束。

可选整理工具只移走指定的、至少7天未更新的失败诊断任务；成功作品与 queued/running 任务永远跳过，服务运行中的目录拒绝处理。先预览，再执行：

```bash
backend/.venv/bin/python backend/scripts/cleanup_diagnostics.py --root api-jobs --job 这里替换成实际任务编号
backend/.venv/bin/python backend/scripts/cleanup_diagnostics.py --root api-jobs --job 这里替换成实际任务编号 --apply
```

`--root` 只能是 api-jobs、creation-page-jobs、regeneration-page-jobs；多个任务重复 --job。文件移到 `runtime/diagnostics/archive/目录名-任务编号/`，可恢复；工具不永久删除，不处理正式 runtime/jobs、模型费用账本或下载到电脑的文件。有效期只用于手动筛选，默认7天；没有定时清理。关闭对应诊断窗口后才可整理。恢复时关闭诊断服务，将整个归档目录移回原诊断根目录并恢复任务编号目录名，目标已存在时不要覆盖。

## 主要目录

- `frontend/src/pages/`：创作页与开发诊断页。
- `frontend/src/components/`：谱面、播放器和独立下载控件。
- `frontend/src/api/`、`hooks/`：请求、状态查询及新旧作品切换。
- `backend/app/`：接口、真实模型、音乐检查、指型、音频与 PDF 导出。
- `backend/scripts/`、`tests/`：独立诊断与自动测试。
- `docs/`：产品需求、方案、任务和验收记录。
- `.env`、`.tools/`、`runtime/`：本机配置、工具及临时产物，均不包含在交付代码中。

本版未加入局部编辑、练习计划、自动评价、社区、账号、作品库或移动端打包。自动规则通过不代表每个作品都已被人确认容易弹奏；最终指弹审阅见任务19记录。
