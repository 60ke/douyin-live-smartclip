# liveclip — 抖音直播录制与 AI 智能切片系统

对 [douyin-live-recorder-smartclip](https://github.com/ihmily/douyin-live-recorder) 的重写，精简为专注抖音平台，保持录制和 AI 切片逻辑与原项目完全一致。

## 环境要求

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) 包管理器
- FFmpeg（用于录制和视频切割）

## 快速开始

```bash
git clone git@github.com:60ke/douyin-live-smartclip.git
cd douyin-live-smartclip

# 安装依赖
uv sync

# 配置
cp .env.example .env
cp configs/app.example.toml configs/app.toml
# 编辑 .env 设置 LLM_API_KEY
```

## 环境变量

`.env` 文件：

```ini
LIVECLIP_CONFIG=configs/app.toml
LLM_API_KEY=sk-xxxxx          # OpenAI 兼容的 API key
LLM_MODEL=deepseek-ai/DeepSeek-V4-Flash   # 模型名称（可选）
LLM_BASE_URL=https://api.siliconflow.cn/v1/chat/completions  # API 地址（可选）
DOUYIN_COOKIE=                 # 抖音 Cookie，某些直播间需要（可选）
```

## CLI 命令

### `liveclip clip srt` — 字幕智能切片（最常用）

从 SRT 字幕文件智能规划片段，导出切片 SRT，可选切割视频。

```bash
# 仅导出 SRT 切片（不切视频）
uv run liveclip clip srt tests/video/video.srt -o output/my_clips --mode full

# 完整流程：SRT 片段 + 视频切割
uv run liveclip clip srt tests/video/video.srt \
  -o output/my_clips \
  --video video.mp4 \
  --mode full

# 指定视频导出并发数；不指定时默认 min(3, CPU 核心数的一半)
uv run liveclip clip srt tests/video/video.srt \
  -o output/my_clips \
  --video video.mp4 \
  --jobs 2

# 打印 LLM 提示词方便调试
uv run liveclip clip srt tests/video/video.srt -o output/debug --dump-prompts

# 调整切片参数
uv run liveclip clip srt tests/video/video.srt \
  -o output/custom \
  --video video.mp4 \
  --min-seconds 60 \
  --target-seconds 90 \
  --max-seconds 120 \
  --hard-max-seconds 150 \
  --min-score 0.6 \
  --min-export-seconds 30
```

**参数说明：**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `SRT_PATH` | 必填 | SRT 字幕文件路径 |
| `-o, --output-dir` | `data/local_srt_clips/` | 输出目录 |
| `--video` | 无 | 视频文件，提供则切割视频 |
| `--jobs` | `min(3, CPU核心数/2)`（至少 1） | 视频导出并发数，仅在提供 `--video` 时生效 |
| `--fast-seek / --precise-seek` | `--precise-seek` | 视频切割定位方式；默认精确定位，对齐旧项目 |
| `--mode` | `full` | 切分模式：`full` 两阶段（推荐）/ `one-shot` 单次 LLM |
| `--min-seconds` | 90 | 片段最短时长（秒） |
| `--target-seconds` | 120 | 片段目标时长（秒） |
| `--max-seconds` | 150 | 片段可接受最长时长（秒） |
| `--hard-max-seconds` | 180 | 片段硬性上限（秒） |
| `--min-score` | 0.5 | 最低评分阈值 |
| `--min-export-seconds` | 配置值，默认 45 | 低分片段的最短保留时长（秒） |
| `--export-high-score-threshold` | 配置值，默认 0.8 | 短片段低于该评分才会被过滤 |
| `--dump-prompts` | false | 保存 LLM 提示词和响应到输出目录 |
| `--boundary-llm` | true | 启用 LLM 边界二次校验，对齐旧项目默认行为 |

**智能复用：** 如果输出目录已有 plan 结果（`plans/validated_plan.json`），自动跳过 LLM 调用，直接导出 SRT / 切割视频。

**性能说明：** 当前默认使用 `libx264` 重编码以保持与旧项目一致。视频导出主要瓶颈在编码而不是 seek；后续服务器有 NVIDIA GPU 时，可增加可选的 `h264_nvenc` 硬件编码配置用于提速。

---

### CLI 执行流程

CLI 入口由 `pyproject.toml` 注册：

```toml
[project.scripts]
liveclip = "liveclip.cli.app:app"
```

`uv run liveclip ...` 会进入 `src/liveclip/cli/app.py`，再分发到 `api`、`worker`、`room`、`task`、`run`、`clip`、`db` 等子命令。

#### 本地字幕切片：`liveclip clip srt`

这个命令用于调试和复现旧项目的 `subtitle-clip` / `clip --srt` 行为，不依赖数据库。

```bash
uv run liveclip clip srt tests/video/video.srt \
  -o output/my_clips \
  --mode full \
  --video /path/to/video.mp4
```

执行顺序：

```text
读取配置和环境变量
  → 可选 LLM 健康检查
  → 构造本地 RunPaths：<output>/room_1/run_1
  → 写入 TRANSCRIBE step 结果，指向传入的 SRT
  → PLAN_CLIPS：结构分析 + 逐候选 refine + 去重/拆分
  → VALIDATE_BOUNDARY：边界校验、重叠裁剪、时长过滤
  → 导出 srt_segments/*.srt 和 srt_segments/segments.json
  → 如果传入 --video，执行 EXPORT_CLIPS 导出 clips/*.mp4
```

主要产物：

```text
<output>/room_1/run_1/plans/normalized_plan.json
<output>/room_1/run_1/plans/validated_plan.json
<output>/room_1/run_1/plans/boundary_report.json
<output>/room_1/run_1/srt_segments/*.srt
<output>/room_1/run_1/srt_segments/segments.json
<output>/room_1/run_1/clips/*.mp4
```

复用规则：

- 默认每次重新请求 LLM。
- 加 `--reuse-plan` 且 `plans/validated_plan.json` 已存在时，会跳过 `PLAN_CLIPS` 和 `VALIDATE_BOUNDARY`，只重新导出字幕/视频。
- 加 `--dump-prompts` 会把 LLM 请求和响应保存到 `<output>/room_1/run_1/llm_prompts/`。
- 加 `--fast` 会跳过 LLM 边界二次校验，对齐旧项目的 fast 模式。

#### 生产全流程：DB + Worker

推荐用一条命令完成“建表 → 添加/复用直播间 → 创建任务 → 触发运行 → 执行 worker once”：

```bash
uv run liveclip run start \
  --url https://live.douyin.com/926637114034 \
  --max-duration 300 \
  --quality origin \
  2>&1 | tee "logs/full_pipeline_$(date +%Y%m%d_%H%M%S).log"
```

也可以拆成底层命令手动执行：

```bash
uv run liveclip db init
uv run liveclip room add https://live.douyin.com/926637114034 --max-duration 300 --quality origin
uv run liveclip task create --room <ROOM_ID>
uv run liveclip run trigger <TASK_ID>
uv run liveclip worker run --once 2>&1 | tee "logs/full_pipeline_$(date +%Y%m%d_%H%M%S).log"
```

执行顺序：

```text
room add
  → 解析抖音直播间 URL
  → 如果未传 --name，尝试从直播间页面自动获取名称
  → 保存 live_rooms

task create
  → 创建录制/切片任务
  → 保存 tasks

run trigger
  → 创建 task_runs
  → 创建 8 个 task_steps

worker run
  → 轮询 pending run
  → 构造 PipelineContext
  → StepExecutor 按顺序执行已启用步骤
```

`run start` 为避免队列里旧的 pending run 抢占执行，会直接执行它刚创建的指定 run。

Worker 的默认步骤：

```text
RECORD_TS
  → 获取直播状态和流地址
  → ffmpeg 录制 TS

CONVERT_MP4
  → TS 转 MP4

TRANSCRIBE
  → FunASR 生成原始 SRT

PREPROCESS_SUBTITLE
  → 字幕断句、清洗、索引映射

PLAN_CLIPS
  → LLM 结构分析 + refine，生成 normalized_plan.json

VALIDATE_BOUNDARY
  → 可选 LLM 边界校验
  → 代码级边界 snap
  → 重叠裁剪
  → 按 min_export_segment_seconds 和 export_high_score_threshold 过滤低分短片段
  → 生成 validated_plan.json 和 boundary_report.json

EXPORT_CLIPS
  → ffmpeg 导出视频切片
  → 导出对应 SRT

FINALIZE
  → 汇总运行结果
```

全流程产物默认写到：

```text
data/room_<ROOM_ID>/run_<RUN_ID>/raw/
data/room_<ROOM_ID>/run_<RUN_ID>/media/
data/room_<ROOM_ID>/run_<RUN_ID>/subtitles/
data/room_<ROOM_ID>/run_<RUN_ID>/preprocess/
data/room_<ROOM_ID>/run_<RUN_ID>/plans/
data/room_<ROOM_ID>/run_<RUN_ID>/srt_segments/
data/room_<ROOM_ID>/run_<RUN_ID>/clips/
```

如果 `EXPORT_CLIPS` 提示“校验后方案为空”，优先看：

```text
data/room_<ROOM_ID>/run_<RUN_ID>/plans/boundary_report.json
```

其中 `filtered_out` 会列出被过滤的片段、时长、分数和原因。短片段过滤阈值可以在 `configs/app.toml` 里调整：

```toml
[clip_segment]
min_export_segment_seconds = 30.0
export_high_score_threshold = 0.8
```

---

### `liveclip clip list` — 查看切片

```bash
uv run liveclip clip list <RUN_ID>
uv run liveclip clip list <RUN_ID> --json
```

---

### `liveclip room` — 直播间管理

```bash
# 添加直播间
uv run liveclip room add --url https://live.douyin.com/xxxxx

# 列表
uv run liveclip room list

# 更新 / 删除
uv run liveclip room update <ROOM_ID> --url https://live.douyin.com/yyyyy
uv run liveclip room remove <ROOM_ID>
```

---

### `liveclip task` — 录制任务管理

```bash
# 创建录制任务
uv run liveclip task create --room-id <ID> --max-duration 3600 --quality origin

# 列表 / 详情 / 启停
uv run liveclip task list
uv run liveclip task detail <TASK_ID>
uv run liveclip task enable <TASK_ID>
uv run liveclip task disable <TASK_ID>
```

---

### `liveclip run` — 运行管理

```bash
# 触发运行
uv run liveclip run trigger --task-id <ID>

# 列表 / 详情
uv run liveclip run list
uv run liveclip run detail <RUN_ID>

# 取消运行
uv run liveclip run cancel <RUN_ID>
```

---

### `liveclip worker` — Worker 进程

```bash
# 启动 worker（轮询并执行录制+切片任务）
uv run liveclip worker run
```

---

### `liveclip api` — API 服务器

```bash
uv run liveclip api serve              # 默认 0.0.0.0:8000
uv run liveclip api serve --port 9000
```

---

## Docker 部署

`docker-compose.yml` 默认将容器内 `8000` 映射到宿主机 `9889`，适合 staging 环境通过 nginx 反向代理访问：

```bash
cp .env.example .env
cp configs/app.example.toml configs/app.toml
```

编辑 `.env`，至少配置：

```ini
LIVECLIP_CONFIG=configs/app.toml
LLM_API_KEY=sk-xxxxx
LLM_MODEL=deepseek-ai/DeepSeek-V4-Flash
LLM_BASE_URL=https://api.siliconflow.cn/v1/chat/completions
DOUYIN_COOKIE=
```

确认 `configs/app.toml` 中 API 与内置 worker 配置：

```toml
[server]
host = "0.0.0.0"
port = 8000

[worker]
auto_start_with_api = true
```

启动：

```bash
docker compose up -d --build
docker compose logs -f liveclip
```

验证：

```bash
curl http://127.0.0.1:9889/health
curl 'http://127.0.0.1:9889/api/v1/live-rooms/?offset=0&limit=5'
```

运行数据会持久化到宿主机目录：

```text
./data   # SQLite 数据库、录制视频、字幕、切片结果
./cache  # FunASR / Hugging Face / ModelScope 缓存
./logs   # 日志
```

Dockerfile 已配置国内构建源：apt 使用清华 Debian 源，Python/uv 使用清华 PyPI 源，Hugging Face 默认使用 `https://hf-mirror.com`。基础镜像 `python:3.11-slim` 的拉取镜像源由服务器 Docker daemon 的 registry mirror 配置决定。

---

### `liveclip db` — 数据库管理

```bash
uv run liveclip db init                # 建表
uv run liveclip db migrate             # Alembic 迁移
uv run liveclip db reset               # 重建（有确认）
```

---

## 项目结构

```
src/liveclip/
├── adapters/           # 外部依赖适配层
│   ├── douyin/         # 抖音 API（开播检测、流地址、录制）
│   ├── ffmpeg/         # FFmpeg 命令构建、切片、转码
│   ├── funasr/         # FunASR 语音转写
│   └── llm/            # LLM API 客户端、Prompt 模板
├── api/                # FastAPI 路由
├── cli/                # Typer CLI 命令
├── config/             # 配置加载
├── db/                 # SQLAlchemy ORM + Alembic
├── domain/             # 领域模型
├── pipeline/           # 录制+切片流水线
│   └── steps/          # 8 个管道步骤
├── services/           # 业务服务层
├── subtitle/           # 字幕解析、边界处理、断句
├── worker/             # Worker 进程
└── utils/              # 工具函数
```

## AI 切片流程

与原始项目 `smartclip(mode="full")` 完全对齐：

```
SRT 字幕
  → 结构分析 (LLM: 识别候选主题并给粗边界)
  → 逐候选精修 (LLM: 精确 start/end/parts/评分)
  → 回退全量分析 (LLM: 结构分析失败时)
  → 去重 + 时间维度拆分
  → 边界校验 (代码边界对齐 + 可选 LLM)
  → 重叠裁剪 + 时长过滤
  → 导出视频片段 + 字幕
```

## 配置

参考 `configs/app.example.toml`，复制为 `configs/app.toml` 后修改：

```toml
[server]
host = "0.0.0.0"
port = 8000

[database]
url = "sqlite+aiosqlite:///./data/liveclip.db"

[storage]
base_dir = "./data"

[ffmpeg]
ffmpeg_binary = "ffmpeg"
default_encoder = "libx264"
preset = "veryfast"
crf = 18

[funasr]
device = "auto"          # auto / cpu / cuda / mps

[worker]
max_concurrent_runs = 1
poll_interval_seconds = 5

[clip_segment]
target_segment_seconds = 120.0
min_segment_seconds = 90.0
max_segment_seconds = 150.0
hard_max_segment_seconds = 180.0
min_score = 0.5
min_export_segment_seconds = 45.0
export_high_score_threshold = 0.8
```

## License

MIT
