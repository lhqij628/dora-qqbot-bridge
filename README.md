# 朵啦 QQ 机器人桥接

基于 LLBot / OneBot 11 的 AI 桥接服务，提供中文聊天、视觉识别、文生图、引用图片改图、人物自拍和群 AI 语音，并附带 Web 配置界面及 Windows 一键启动脚本。

本仓库只包含桥接代码、配置页面和安装脚本。QQ 客户端及 LLBot 请从 [LLBot 官方网站](https://www.llonebot.com/zh-CN/) 单独安装，遵循其各自的使用条款与许可证。

## 功能

- OpenAI 兼容聊天接口；可连接提供兼容接口的 Gemini 等模型，视觉能力取决于所选模型和服务商。
- 文生图、图生图；支持引用当前会话中其他人发送的图片后提出修改要求。
- 人物参考图支持本地上传和公网 URL；先文字回答当前活动，再根据后续的看图请求生成相应场景。
- 群聊主动插话、上下文接话、短期上下文与持久化记忆。
- QQ 群 AI 语音、音色查询；生图前的风险提示词检测与安全改写；文本回复链接过滤。
- 后台配置聊天、图像、图生图、人物参考和语音，并测试聊天 API、生图 API、OneBot 连接。
- 一键启动 LLBot 和桥接，检查端口及 OneBot 连接；重复启动时复用已有进程，不结束其他进程。不启动 Web2Img。

## 环境

- 完整机器人安装流程以 **Windows 10/11、PowerShell 5.1+、Python 3.10+** 为目标，Python 需加入 PATH。
- 已解压的 LLBot CLI，目录结构包含 `CLI/llbot.exe` 和 `CLI/bin/llbot/webui/index.html`。
- 自备 QQ 账号、聊天 API；按需准备图像生成和编辑 API。

| 服务 | 默认地址 | 用途 |
| --- | --- | --- |
| LLBot WebUI | `http://127.0.0.1:3080` | QQ 登录及 OneBot 设置 |
| OneBot 正向 WebSocket | `ws://127.0.0.1:3001` | 消息事件与发送操作 |
| AI 桥接 | `http://127.0.0.1:8001` | 配置接口、健康检查 |

附带页面和启动器按这组默认端口工作；自行更换端口时，需要同步调整页面中的桥接地址、后端 CORS 和启动脚本。

## 安装与启动

1. 从官方安装 LLBot，确认上述 CLI 目录结构。以下假设 LLBot 放在 `C:\qqbot\LLBot`，源码仓库放在其他目录。
2. 在本仓库目录执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -LLBotRoot "C:\qqbot\LLBot"
```

安装器创建 Python 虚拟环境和配置文件，将桥接与配置页面复制到 LLBot 目录，并向其 WebUI 加入 AI 配置入口。已有配置、记忆、参考图会保留；被替换的源码和页面备份到 LLBot 目录的 `installation-backups` 下。请先停止服务再执行升级安装，LLBot 自身升级后可能需要重新安装配置入口。

如需指定 Python，可加 `-PythonCommand "C:\Python313\python.exe"`。离线准备文件可加 `-SkipDependencies`，之后仍需自行创建虚拟环境并安装依赖。

3. 双击仓库目录的 `start-qqbot-full.bat`；也可执行：

```powershell
.\start-qqbot-full.ps1 -LLBotRoot "C:\qqbot\LLBot"
```

4. 首次访问 `http://127.0.0.1:3080` 登录 QQ，在 LLBot 中启用 **OneBot 11 正向 WebSocket 服务**，端口设为 `3001`，开启消息事件上报。如设置访问 Token，请在 AI 配置中填写同一个值。登录尚未完成时，桥接会持续尝试重连。
5. 打开 `http://127.0.0.1:3080/llbot-ai-config.html`，填写 API Base URL、Key 和模型名称，保存后测试连接。Base URL 一般包含 `/v1`，不要填写完整的 `/chat/completions` 路径。

配置实际保存在 **LLBot 安装目录的 `AIBridge/config.json`**。仓库的 `AIBridge/config.example.json` 只作模板；未列出的参数沿用代码默认值。Key 输入框留空保存会保留原值。

## 使用示例

| 功能 | 示例 |
| --- | --- |
| 聊天 | `/ai 今天有什么安排`，或 @机器人提问 |
| 识图 | 发送图片并问“看看这张图里有什么” |
| 文生图 | `/画图 一只在窗边晒太阳的猫`、`生成一张城市夜景图片` |
| 图生图 | 发送图片并附 `/图生图 把背景换成海边` |
| 引用改图 | 引用含图片的消息，再发 `/图生图 改成水彩风格` |
| 人物自拍 | 配置人物参考图后，发“朵啦，发张自拍” |
| 活动接图 | 先问“朵啦在干嘛”，收到文字回答后再说“发个图片看看” |
| 群 AI 语音 | 开启语音后，在群里发 `/语音 你好呀` |

默认名字触发包含“朵啦”和“朵拉”。命令触发词可在后台修改，其他自然语言触发由代码中的规则识别。语音依赖 LLBot 和 QQ 提供的群 AI 音色能力，并非通用 TTS 服务，是否可用取决于账号、群和上游支持。

## 图像接口与人物形象

文生图调用 `POST /images/generations`。一般图生图调用 `POST /images/edits`，通过 multipart 的 `image` / `image[]` 上传参考图；支持返回 URL 或 `b64_json`。请分别配置文本、文生图和图生图的模型与密钥，模型名需以服务商实际支持为准，模板中的 `gpt-image-fast` 不代表每个提供商都支持它。

人物功能需启用图生图及人物形象，在后台上传 PNG/JPEG/WebP，或填写可公开访问的图片 URL。公网 URL 优先于本地图片，以以下 **服务商扩展 JSON 格式**直接发给图生图接口：

```json
{
  "model": "your-image-edit-model",
  "prompt": "人物在吃饭，保持参考图的人物外观",
  "images": [{"image_url": "https://cdn.example.com/character.png"}]
}
```

这个 URL 格式并非所有 OpenAI 兼容服务都接受；已通过本地接口契约测试，尚未对所有上游服务实测。服务商不支持时可清空 URL，改用本地上传。身份一致性由图像模型决定，并非完全保证。参考图及相关提示词会发送给你配置的图像服务商。

图像超时默认 300 秒，可配置到 600 秒。超时不能证明上游已取消，桥接不会自动重试图像 POST；重新发送可能创建新的付费任务。后台“测试生图 API”会实际生成图片，可能计费。安全改写也可能调用聊天 API，效果依赖模型，不应视为完整内容审核。

## 服务器部署与访问

可以在 Windows 服务器按同样流程运行，并通过远程桌面完成 QQ 登录。Python 桥接本身可在 Linux 上运行，但本仓库没有提供经过验证的 Linux QQ 客户端和 LLBot 全套安装方案。

**桥接的管理接口没有内置登录认证**，包括修改配置、读取聊天记忆、上传参考图和发起 API 测试；LLBot WebUI 的密码不会保护端口 `8001`。保持桥接监听 `127.0.0.1`，不要把 `3080`、`3001`、`8001` 直接开放到公网。远程配置优先使用远程桌面或 SSH 本地转发：

```sh
ssh -N -L 3080:127.0.0.1:3080 -L 8001:127.0.0.1:8001 your-user@your-server
```

随后在本机访问 `http://127.0.0.1:3080/llbot-ai-config.html`。其他部署方式需自行增加管理认证和访问控制。当前服务没有群白名单、用户配额或费用上限，部署者应控制机器人加入的群及 API 用量。

## 开发验证

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r .\AIBridge\requirements.txt
Set-Location AIBridge
..\.venv\Scripts\python.exe -m unittest test_image_edit -q
```

Linux 对应使用 `.venv/bin/python`。49 项自动测试使用本地模拟服务，覆盖图片上传、引用图片、人物参考 URL、本地参考图、上下文触发和错误分支，不连接真实 QQ、不调用付费模型。首次开源前已在 Python 3.13 上验证；其他平台由 CI 持续验证。

源码目录中的 `AIBridge/bridge.py` 可以单独运行；首次启动自动创建本地配置。Windows 安装器将运行副本放在 LLBot 安装目录，修改仓库源码后需要重新安装或自行同步，运行副本不会自动更新。

## 数据与许可证

运行配置、API Key、QQ 登录数据、日志、聊天记忆和人物照片均未包含在仓库中。记忆功能开启后会在本机持久化群聊摘要及人物信息；不需要时可在后台关闭，已保存的数据需另行清理。

本仓库原创桥接、页面及脚本采用 [MIT License](LICENSE)。LLBot、QQ、Python 依赖和模型 API 均为独立项目或服务，按各自许可证和服务条款使用。本项目与腾讯及 LLBot 官方无隶属关系。
