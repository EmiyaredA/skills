# API 配置指南

通过 `config/providers.yaml` 配置图像、视频和语音提供商。从 `config/providers.yaml.example` 复制 — 切勿提交 API Key。

## 初始设置

```bash
cp config/providers.yaml.example config/providers.yaml
export IMAGE_API_KEY=your_key
export VIDEO_API_KEY=your_key
export VOICE_API_KEY=your_key   # 可选
```

## 提供商槽位

| 槽位 | 是否必需 | 调用脚本 |
|------|----------|----------|
| `image` | 是 | `generate_image.py` |
| `video` | 是 | `generate_video.py` |
| `voice` | 否 | `generate_voice.py` |

## 模板占位符

脚本会将以下占位符替换进 `request_template`：

| 占位符 | 用于 | 说明 |
|--------|------|------|
| `{{prompt}}` | image, video | 生成 prompt |
| `{{reference_url}}` | image | 参考图本地路径或 URL |
| `{{width}}`, `{{height}}` | image | 像素尺寸 |
| `{{duration}}` | video | 目标秒数 |
| `{{aspect_ratio}}` | video | 如 `16:9`、`9:16` |
| `{{reference_images}}` | video | 图像路径 JSON 数组 |
| `{{text}}`, `{{voice_id}}` | voice | TTS 输入文本和音色 ID |

## 模式 A：OpenAI 兼容图像 API

```yaml
image:
  base_url: "https://api.openai.com"
  endpoint: "/v1/images/generations"
  method: POST
  auth_env_var: IMAGE_API_KEY
  auth_header: Authorization
  auth_prefix: "Bearer "
  request_template:
    model: "dall-e-3"
    prompt: "{{prompt}}"
    size: "1024x1024"
    n: 1
  response_image_path: "data.0.url"
  response_format: url
```

## 模式 B：Replicate 风格异步视频 API

```yaml
video:
  base_url: "https://api.replicate.com"
  endpoint: "/v1/predictions"
  method: POST
  auth_env_var: VIDEO_API_KEY
  auth_header: Authorization
  auth_prefix: "Token "
  request_template:
    version: "model-version-id"
    input:
      prompt: "{{prompt}}"
      duration: "{{duration}}"
  response_video_path: "urls.get"
  response_format: url
  poll:
    enabled: true
    endpoint: "/v1/predictions/{{task_id}}"
    task_id_path: "id"
    status_path: "status"
    ready_status: "succeeded"
    video_path: "output"
    interval_sec: 5
    max_attempts: 120
```

## 模式 C：自定义 REST（二进制响应）

```yaml
voice:
  base_url: "https://tts.example.com"
  endpoint: "/v1/synthesize"
  method: POST
  auth_env_var: VOICE_API_KEY
  request_template:
    text: "{{text}}"
    voice: "{{voice_id}}"
  response_format: binary
```

## Mock 模式（本地测试）

```yaml
mock:
  enabled: true
```

或使用内置 JSON 配置：

```bash
python scripts/verify_mock_flow.py   # 完整 mock 流程测试
# 各脚本支持：--config config/providers.mock.json
```

启用后，脚本在不发起网络请求的情况下写入占位 PNG/MP4/WAV 文件。仅用于工作流验证。

## 安全须知

- API Key **仅**通过环境变量注入（`auth_env_var`）
- 切勿将 Key 存入 `state.json`、模板或聊天记录
- 用户项目中的 `config/providers.yaml` 应加入 gitignore

## 扩展鉴权方式

若需 OAuth 或超出 Bearer Token 的请求签名：

1. 在 `providers.yaml` 中添加自定义 header 及静态值，或
2. 在项目专用脚本中封装 `api_client.py` 调用，在请求前注入签名 header

将提供商特有的配置说明记录在用户本地的 `providers.yaml` 注释中。
