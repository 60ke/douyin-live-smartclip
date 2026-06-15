# 视频后处理产品化 TODO

本文档记录智能切片后的短视频增强能力设计，覆盖硬字幕、高能片头、自定义封面三类需求。当前阶段先作为 TODO 方案，不直接修改业务代码。

## 目标

在现有直播录制与智能切片流程之后，为每个切片生成更适合抖音等短视频平台发布的成片：

```text
原始切片视频
  -> 可选：烧录硬字幕
  -> 可选：生成高能片头
  -> 可选：生成自定义封面首帧
  -> 最终发布视频
```

最终推荐播放顺序：

```text
封面 1s -> 高能片头 3-8s -> 原切片正文
```

其中：

- 硬字幕：解决平台上传时字幕文件不能单独生效的问题。
- 高能片头：把切片内最有吸引力的 3-8 秒复制到视频开头，提高完播和停留。
- 自定义封面：根据图片和标题生成适配视频比例的封面，并作为首帧或 1 秒封面片段拼接到视频开头。

## 总体原则

- 所有增强能力必须是开关控制，不影响默认切片主流程。
- 所有后处理产物不能覆盖原始切片视频和原始字幕。
- API 与前端应明确区分原始视频、硬字幕视频、封面图、最终发布视频。
- 前端播放硬字幕切片或最终发布视频时，不应再加载外挂字幕，避免画面出现重复字幕。
- 前端播放未硬字幕的视频、录制原视频或调试预览视频时，仍按原有策略加载外挂字幕。
- 已生成的切片应该可以单独触发后处理重跑。
- 后处理失败不应影响原始切片的可用性。

## 建议流水线

在 `EXPORT_CLIPS` 之后新增一个或多个后处理步骤。

```text
EXPORT_CLIPS
  -> BURN_SUBTITLE
  -> PREPEND_HIGHLIGHT
  -> PREPEND_COVER
  -> FINALIZE_CLIP_ASSET
```

MVP 可以先实现为一个聚合步骤：

```text
POST_PROCESS_CLIPS
```

内部按配置执行：

```text
for each clip:
  1. 读取 clip 视频和 clip 字幕
  2. 探测视频规格
  3. 可选生成硬字幕视频
  4. 可选判断并生成高能片头
  5. 可选生成封面图和封面视频片段
  6. 拼接最终发布视频
  7. 更新 clips 表产物路径和状态
```

长期建议拆成独立步骤，便于前端展示进度和失败重试。

## 一、硬字幕

### 业务说明

抖音等平台上传视频时，独立字幕文件通常不会自动作为外挂字幕生效。因此需要把 clip 对应字幕烧录到视频画面中，生成带硬字幕的视频文件。

硬字幕应基于 clip 对应的原始字幕片段，而不是 `run_combine.srt`。`run_combine.srt` 是内部给 LLM 做规划的合并字幕，不适合作为用户可见字幕。

### 输入

```text
clip_001.mp4
clip_001.srt
```

### 输出

```text
clip_001.ass
clip_001_subtitled.mp4
```

### 推荐实现

使用 ASS 作为中间字幕格式，再通过 FFmpeg 烧录：

```text
SRT -> ASS -> ffmpeg subtitles filter -> MP4
```

不建议直接用 SRT 烧录，因为 SRT 样式表达能力弱，不方便控制字体、描边、位置、换行和安全区。

### 字幕样式策略

基础样式：

```text
字体：Noto Sans CJK / 思源黑体 / PingFang SC
颜色：白色
描边：黑色 3-5px
阴影：1-2px
位置：底部居中
最多行数：2 行
```

字号计算：

```text
font_size = clamp(short_side * 0.045, 34, 56)
```

示例：

```text
720x1280  -> 34px 左右
1080x1920 -> 48px 左右
1920x1080 -> 48px 左右
```

每行字数计算：

```text
max_chars_per_line = floor(video_width * 0.82 / font_size)
```

再按方向限制：

```text
竖屏：12-18 字/行
横屏：18-26 字/行
```

换行策略：

1. 优先按中文标点切分。
2. 其次按语义停顿切分。
3. 最后按最大字数硬切。
4. 单条字幕最多 2 行，超过时需要进一步拆分时间段或压缩文本。

字幕安全区：

```text
bottom_margin = video_height * 0.10
```

竖屏短视频需要避免字幕过低，被平台底部 UI、标题栏或操作区遮挡。

### TODO

- [ ] 增加字幕样式配置模型，例如 `SubtitleBurnConfig`。
- [ ] 增加视频规格探测工具，读取宽高、帧率、时长、旋转信息。
- [ ] 增加 SRT 到 ASS 的转换器。
- [ ] 增加中文换行和两行限制逻辑。
- [ ] 增加 FFmpeg 硬字幕烧录封装。
- [ ] 增加硬字幕产物路径字段。
- [ ] 增加后处理失败重试能力。

## 二、高能片头

### 业务说明

高能片头用于从当前切片内部找到最有吸引力的短片段，并复制到视频开头。

示例：

```text
原视频：120s
AI 判断 115s-120s 是高能片段
最终视频：0s-5s 高能片段 + 5s-125s 原视频正文
```

注意：高能片段是复制到开头，不是从原视频中移动或删除。

### 开关

必须支持开关：

```text
prepend_highlight_enabled: true / false
```

关闭时跳过高能片头，不影响硬字幕和封面。

### 输入

```text
clip 视频
clip 字幕
clip 标题
clip 摘要
clip 评分和推荐理由
可选：音频峰值、镜头变化、关键帧信息
```

MVP 可以先使用字幕 + 标题 + 评分理由，让 LLM 判断。

### AI 输出

建议结构：

```json
{
  "enabled": true,
  "start_seconds": 115.0,
  "end_seconds": 120.0,
  "reason": "展示最终效果，冲突和结果最强",
  "confidence": 0.86
}
```

### 约束规则

- 高能片头长度建议 3-8 秒。
- 最大不超过 10 秒。
- clip 总时长小于 20 秒时默认不加。
- 高能片段位于原视频开头 0-8 秒内时，可以不重复添加。
- AI 置信度低于阈值时不加。
- 片头片段需要按关键帧安全裁剪，避免音画异常。

### 推荐处理顺序

高能片头应基于已经烧录硬字幕的视频生成：

```text
clip_001_subtitled.mp4
  -> 截取 highlight segment
  -> concat highlight + full clip
  -> clip_001_highlight.mp4
```

如果未开启硬字幕，则基于原始 clip 生成。

### TODO

- [ ] 增加高能片头配置模型，例如 `HighlightIntroConfig`。
- [ ] 增加 LLM 高能片段判断 prompt。
- [ ] 增加高能片段结果表或字段。
- [ ] 增加 FFmpeg 截取与拼接工具。
- [ ] 增加边界校验，避免片段过短、超出时长、重复开头。
- [ ] 增加前端开关和重跑入口。

## 三、自定义封面与首帧

### 业务说明

根据图片和标题生成视频封面，并把封面作为 1 秒视频片段拼接到最终视频开头。

采用顺序：

```text
封面 1s -> 高能片头 3-8s -> 原切片正文
```

封面既要作为独立图片提供给前端下载，也要作为视频首段参与最终成片。

### 开关

```text
cover_enabled: true / false
```

### 输入

```text
标题
直播间名称
clip 摘要
可选用户上传图片
可选 AI 生成图片
可选视频关键帧或高能帧截图
最终视频宽高
```

### 输出

```text
clip_001_cover.png
clip_001_cover_intro.mp4
clip_001_final.mp4
```

### 分辨率适配

必须以最终视频分辨率为准生成封面：

```text
竖屏：1080x1920 / 720x1280
横屏：1920x1080 / 1280x720
```

适配原则：

- 禁止拉伸图片。
- 优先 center crop。
- 如果图片比例不匹配，可使用背景模糊或纯色背景填充。
- 标题文本需要避开平台 UI 安全区。
- 主标题最多 2 行，超出自动缩小字号或截断。

### 封面布局建议

```text
背景：用户图片 / 视频关键帧 / AI 生成图
主标题：大字，2 行以内
副标题：可选
品牌或直播间名：弱展示
安全区：上下各保留 8%-10%
```

### TODO

- [ ] 增加封面配置模型，例如 `CoverConfig`。
- [ ] 增加封面图片生成或合成服务。
- [ ] 增加标题自动换行和字号适配逻辑。
- [ ] 增加图片比例适配策略。
- [ ] 增加封面图片转 1 秒视频片段逻辑。
- [ ] 增加封面片段与后续视频拼接逻辑。
- [ ] 增加封面图下载接口。

## 四、产物命名建议

每个 clip 保留完整产物链：

```text
clip_001.mp4
clip_001.srt
clip_001.ass
clip_001_subtitled.mp4
clip_001_highlight.mp4
clip_001_cover.png
clip_001_cover_intro.mp4
clip_001_final.mp4
```

说明：

- `clip_001.mp4`：原始切片视频。
- `clip_001.srt`：clip 对应原始字幕。
- `clip_001.ass`：硬字幕样式文件。
- `clip_001_subtitled.mp4`：带硬字幕的视频。
- `clip_001_highlight.mp4`：带高能片头的视频。
- `clip_001_cover.png`：封面图片。
- `clip_001_cover_intro.mp4`：1 秒封面视频片段。
- `clip_001_final.mp4`：最终发布视频。

## 五、数据库字段建议

`clips` 表建议增加或确认以下字段：

```text
video_file_path              原始切片视频
subtitle_file_path           原始字幕文件
ass_file_path                硬字幕样式文件
burned_video_file_path       带硬字幕视频
highlight_video_file_path    带高能片头视频
cover_image_file_path        封面图片
cover_intro_video_file_path  封面 1 秒视频
final_video_file_path        最终发布视频
post_process_status          后处理状态
post_process_error_message   后处理错误信息
```

高能片头相关字段：

```text
highlight_enabled
highlight_start_seconds
highlight_end_seconds
highlight_reason
highlight_confidence
```

封面相关字段：

```text
cover_enabled
cover_title
cover_source_image_path
```

也可以拆成 `clip_assets` 表，按 `asset_type` 管理不同产物：

```text
ORIGINAL_VIDEO
ORIGINAL_SUBTITLE
ASS_SUBTITLE
BURNED_VIDEO
HIGHLIGHT_VIDEO
COVER_IMAGE
COVER_INTRO_VIDEO
FINAL_VIDEO
```

如果后处理产物会持续增加，推荐使用 `clip_assets`，避免 `clips` 表字段不断膨胀。

## 六、配置建议

任务级配置可以放入 `pipeline_config_json`：

```json
{
  "post_process": {
    "burn_subtitle": {
      "enabled": true,
      "font_family": "Noto Sans CJK SC",
      "font_size_ratio": 0.045,
      "max_lines": 2,
      "vertical_max_chars": 18,
      "horizontal_max_chars": 26
    },
    "highlight_intro": {
      "enabled": false,
      "min_seconds": 3,
      "max_seconds": 8,
      "min_clip_seconds": 20,
      "min_confidence": 0.75
    },
    "cover": {
      "enabled": false,
      "duration_seconds": 1,
      "title": "",
      "source_image_path": ""
    }
  }
}
```

默认建议：

```text
burn_subtitle.enabled = true
highlight_intro.enabled = false
cover.enabled = false
```

高能片头和自定义封面更偏运营决策，默认关闭更稳。

## 七、前端交互建议

在切片列表中提供：

- 原视频预览/下载。
- 原始字幕下载。
- 带字幕视频下载。
- 最终成片下载。
- 后处理状态展示。
- 单个 clip 重新生成按钮。

播放策略：

```text
原始切片视频 / 录制原视频：
  使用原有外挂字幕策略，可加载 subtitle_file_path

带硬字幕视频 / 最终发布视频：
  不加载 subtitle_file_path，避免重复字幕
```

API 返回给前端时建议明确视频类型或字幕策略：

```text
video_variant: original | subtitled | final
subtitle_mode: external | burned | none
```

在任务创建或切片配置中提供开关：

```text
[x] 烧录硬字幕
[ ] 添加高能片头
[ ] 添加自定义封面
```

当开启自定义封面时显示：

```text
封面标题
上传/选择封面图
封面预览
```

当开启高能片头时显示：

```text
片头长度范围
AI 判断阈值
```

所有按钮必须绑定真实接口，不能只做占位。

## 八、验收标准

### 硬字幕

- [ ] 对竖屏和横屏视频均能生成带硬字幕视频。
- [ ] 字幕不超过 2 行。
- [ ] 字幕不被平台常见 UI 安全区遮挡。
- [ ] 原始字幕文件不被覆盖。
- [ ] 原始视频不被覆盖。

### 高能片头

- [ ] 开关关闭时不生成高能片头。
- [ ] 开关开启时由 AI 判断是否需要添加。
- [ ] 高能片头长度控制在 3-8 秒。
- [ ] 高能片段复制到开头，正文完整保留。
- [ ] AI 判断不通过时保持原视频链路继续可用。

### 自定义封面

- [ ] 封面图分辨率与最终视频一致。
- [ ] 图片不被拉伸变形。
- [ ] 标题不溢出、不遮挡主体。
- [ ] 封面显示 1 秒后进入高能片头或正文。
- [ ] 同时产出可下载封面图和最终成片视频。

## 九、推荐实施顺序

1. 实现硬字幕产物生成。
2. 增加 `clip_assets` 或扩展 `clips` 表字段。
3. 增加后处理状态和重试入口。
4. 实现高能片头 AI 判断和视频拼接。
5. 实现封面图片生成与 1 秒封面视频。
6. 前端接入开关、预览、下载和重跑。
7. 增加端到端测试样例。
