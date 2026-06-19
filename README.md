# B站视频混剪脚本生成器

输入B站视频链接 → 自动下载视频 → 每隔0.5秒截取画面 → AI分析画面与字幕 → 生成混剪脚本（Word文档）

## ✨ 功能特点

- **一键生成**：粘贴B站视频链接，填写需求，自动生成混剪脚本
- **画面分析**：每隔0.5秒截取视频画面，发送给AI视觉模型进行内容分析
- **字幕提取**：自动获取B站视频字幕，结合画面进行综合分析
- **模板格式**：生成的脚本严格按照混剪脚本模板格式（镜号/后期/画面参考/字幕台词/备注）
- **云端部署**：支持 Docker / Railway / Render 等多种云平台部署，分享网址即可使用
- **预配置模式**：部署者通过环境变量配置 API Key，终端用户无需任何配置
- **多模型支持**：支持 OpenAI / DeepSeek / 通义千问 / Moonshot 等 OpenAI 兼容接口

## 🚀 快速开始

### 本地运行

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动服务
python app.py

# 3. 浏览器访问 http://127.0.0.1:5000
# 4. 点击「设置」配置 AI API Key
# 5. 粘贴B站链接，生成脚本
```

### 云端部署（分享给其他用户）

详见 [DEPLOY.md](DEPLOY.md)，支持以下方案：

| 方案 | 适用场景 | 难度 |
|------|----------|------|
| Docker + VPS | 拥有云服务器 | ★★☆ |
| Railway | 无服务器，免费额度 | ★☆☆ |
| Render | 无服务器，免费额度 | ★☆☆ |
| Cloudflare Tunnel | 本地运行+内网穿透 | ★☆☆ |
| 直接运行 | Linux 服务器 | ★★☆ |

**最简部署流程（Railway）：**
1. 推送代码到 GitHub
2. 在 Railway 导入仓库
3. 设置环境变量 `AI_API_KEY`
4. 自动获得公网域名，分享给用户

## 📐 工作流程

```
B站视频链接
    │
    ▼
┌──────────────────┐
│  下载视频流       │  ← B站 API 获取视频信息与播放地址
└──────┬───────────┘
       ▼
┌──────────────────┐
│  截取画面         │  ← 每隔0.5秒截取一帧（ffmpeg）
└──────┬───────────┘
       ▼
┌──────────────────┐
│  获取字幕         │  ← B站字幕 API
└──────┬───────────┘
       ▼
┌──────────────────┐
│  AI 内容分析      │  ← 视觉模型分析画面 + 字幕
└──────┬───────────┘
       ▼
┌──────────────────┐
│  生成混剪脚本     │  ← 根据分析结果 + 用户需求创作脚本
└──────┬───────────┘
       ▼
┌──────────────────┐
│  输出 Word 文档   │  ← 按模板格式生成 .docx
└──────────────────┘
```

## 📁 项目结构

```
├── app.py                  # Flask Web 应用主程序
├── config.py               # 全局配置（支持环境变量）
├── requirements.txt        # Python 依赖
├── Dockerfile              # Docker 镜像配置
├── docker-compose.yml      # Docker Compose 部署
├── .env.example            # 环境变量模板
├── DEPLOY.md               # 部署指南
├── core/
│   ├── downloader.py       # B站视频下载器
│   ├── extractor.py        # 画面截取模块
│   ├── analyzer.py         # AI 分析与脚本生成
│   └── docx_writer.py      # Word 文档生成
├── templates/
│   └── index.html          # Web 界面
├── static/
│   ├── css/style.css       # 样式
│   └── js/app.js           # 前端逻辑
├── outputs/                # 生成的脚本文件
└── temp/                   # 临时文件（视频、截图）
```

## ⚙️ 配置说明

### 环境变量（云端部署用）

| 变量名 | 必填 | 说明 |
|--------|------|------|
| `AI_API_KEY` | 是 | AI 服务的 API 密钥 |
| `AI_BASE_URL` | 否 | API 地址（默认 OpenAI） |
| `AI_MODEL` | 否 | 文本模型（默认 gpt-4o） |
| `AI_VISION_MODEL` | 否 | 视觉模型（留空同上） |
| `BILI_SESSDATA` | 否 | B站 Cookie，下载高清晰度 |
| `ADMIN_PASSWORD` | 否 | 管理员密码，保护设置页面 |

### 常见模型配置

| 平台 | AI_BASE_URL | AI_MODEL | AI_VISION_MODEL |
|------|-------------|----------|-----------------|
| OpenAI | https://api.openai.com/v1 | gpt-4o | gpt-4o |
| DeepSeek | https://api.deepseek.com/v1 | deepseek-chat | deepseek-chat |
| 通义千问 | https://dashscope.aliyuncs.com/compatible-mode/v1 | qwen-plus | qwen-vl-plus |
| Moonshot | https://api.moonshot.cn/v1 | moonshot-v1-8k | - |

### 预配置模式

当通过环境变量设置 `AI_API_KEY` 时，应用自动进入预配置模式：
- 终端用户无需配置，打开网页直接使用
- 设置页面自动隐藏 API 配置
- 可选设置 `ADMIN_PASSWORD` 保护配置页面

## 🔧 技术说明

- **视频下载**：参考 [Henryhaohao/Bilibili_video_download](https://github.com/Henryhaohao/Bilibili_video_download) 项目思路
- **画面截取**：使用 `imageio-ffmpeg` 内置 ffmpeg，Docker 镜像中预装系统 ffmpeg
- **AI 分析**：通过 OpenAI 兼容接口调用视觉大模型
- **文档生成**：使用 `python-docx` 生成 Word 文档
- **生产部署**：使用 `gunicorn` WSGI 服务器，支持多 worker 并发

## ⚠️ 注意事项

1. 本工具仅供学习交流使用，请勿用于商业用途
2. AI 分析质量取决于所用模型能力，建议使用支持视觉的模型（如 GPT-4o）
3. 部分B站视频可能因版权或区域限制无法下载
4. 视频处理需要较多内存，建议服务器配置 2GB 以上
5. 请遵守B站使用条款和相关法律法规
