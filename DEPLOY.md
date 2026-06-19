# 部署指南

本文档介绍如何将「B站视频混剪脚本生成器」部署到云端，让其他用户通过网址直接访问。

---

## 方案一：Docker 部署（推荐）

适用于拥有 Linux 云服务器（VPS）的场景。Docker 容器化部署，一键启动。

### 前提条件
- 一台 Linux 服务器（推荐 2GB 内存以上）
- 已安装 Docker 和 Docker Compose

### 步骤

```bash
# 1. 将项目代码上传到服务器
scp -r ./bilibili-script-generator user@your-server:/opt/

# 2. 进入项目目录
cd /opt/bilibili-script-generator

# 3. 复制环境变量模板并填写配置
cp .env.example .env
vi .env
# 填入以下内容：
#   AI_API_KEY=sk-your-actual-api-key
#   AI_BASE_URL=https://api.openai.com/v1
#   AI_MODEL=gpt-4o
#   AI_VISION_MODEL=gpt-4o
#   ADMIN_PASSWORD=your-admin-password  (可选，保护设置页面)

# 4. 启动服务
docker-compose up -d

# 5. 查看运行状态
docker-compose logs -f
```

启动后，其他用户通过 `http://你的服务器IP:5000` 即可访问。

### 常用命令

```bash
# 停止服务
docker-compose down

# 重启服务
docker-compose restart

# 查看日志
docker-compose logs -f

# 更新代码后重新构建
docker-compose up -d --build
```

---

## 方案二：Railway 部署（最简单）

Railway 是一个零配置的云部署平台，支持 Docker 项目，有免费额度。

### 步骤

1. 将项目代码推送到 GitHub 仓库
2. 访问 [railway.app](https://railway.app)，使用 GitHub 登录
3. 点击「New Project」→「Deploy from GitHub repo」
4. 选择你的仓库，Railway 会自动识别 Dockerfile 并构建
5. 在「Variables」中添加环境变量：
   - `AI_API_KEY` = 你的 API Key
   - `AI_BASE_URL` = https://api.openai.com/v1
   - `AI_MODEL` = gpt-4o
   - `AI_VISION_MODEL` = gpt-4o
6. Railway 会自动分配一个公网域名，如 `xxx.up.railway.app`
7. 将该域名分享给其他用户即可

---

## 方案三：Render 部署

Render 是另一个支持 Docker 的云平台，有免费套餐。

### 步骤

1. 将项目推送到 GitHub
2. 访问 [render.com](https://render.com)，注册登录
3. 点击「New」→「Web Service」
4. 连接 GitHub 仓库
5. 配置：
   - **Runtime**: Docker
   - **Environment Variables**:
     - `AI_API_KEY` = 你的 API Key
     - `AI_BASE_URL` = https://api.openai.com/v1
     - `AI_MODEL` = gpt-4o
     - `AI_VISION_MODEL` = gpt-4o
6. 点击「Create Web Service」
7. 部署完成后获得公网域名

---

## 方案四：本地运行 + 内网穿透

适用于不想租服务器的场景，在自己的电脑上运行，通过内网穿透分享。

### 使用 Cloudflare Tunnel（免费）

```bash
# 1. 安装 cloudflared
# Windows: 下载 https://github.com/cloudflare/cloudflared/releases
# Linux: curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared && chmod +x /usr/local/bin/cloudflared

# 2. 启动应用
python app.py

# 3. 开启隧道（会生成一个临时公网域名）
cloudflared tunnel --url http://localhost:5000
```

将生成的 `https://xxx.trycloudflare.com` 域名分享给其他用户即可。

### 使用 ngrok

```bash
# 1. 安装 ngrok: https://ngrok.com/download
# 2. 启动应用
python app.py

# 3. 开启隧道
ngrok http 5000
```

---

## 方案五：直接在 Linux 服务器运行（不用 Docker）

```bash
# 1. 安装系统依赖
sudo apt update
sudo apt install -y python3 python3-pip ffmpeg

# 2. 上传代码并进入目录
cd /opt/bilibili-script-generator

# 3. 安装 Python 依赖
pip3 install -r requirements.txt

# 4. 配置环境变量
export AI_API_KEY="sk-your-api-key"
export AI_BASE_URL="https://api.openai.com/v1"
export AI_MODEL="gpt-4o"
export AI_VISION_MODEL="gpt-4o"
export ADMIN_PASSWORD="your-admin-password"

# 5. 使用 gunicorn 启动（生产级 WSGI 服务器）
gunicorn --bind 0.0.0.0:5000 --workers 4 --timeout 600 app:app

# 6. （可选）使用 systemd 设置开机自启
# 创建 /etc/systemd/system/bili-script.service
```

systemd 服务文件示例：

```ini
[Unit]
Description=Bilibili Script Generator
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/bilibili-script-generator
Environment=AI_API_KEY=sk-your-api-key
Environment=AI_BASE_URL=https://api.openai.com/v1
Environment=AI_MODEL=gpt-4o
Environment=AI_VISION_MODEL=gpt-4o
Environment=ADMIN_PASSWORD=your-admin-password
ExecStart=/usr/local/bin/gunicorn --bind 0.0.0.0:5000 --workers 4 --timeout 600 app:app
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable bili-script
sudo systemctl start bili-script
```

---

## 环境变量说明

| 变量名 | 必填 | 说明 |
|--------|------|------|
| `AI_API_KEY` | 是 | AI 服务的 API 密钥 |
| `AI_BASE_URL` | 否 | API 地址，默认 OpenAI |
| `AI_MODEL` | 否 | 文本模型，默认 gpt-4o |
| `AI_VISION_MODEL` | 否 | 视觉模型，留空同上 |
| `BILI_SESSDATA` | 否 | B站 Cookie，用于高清晰度下载 |
| `ADMIN_PASSWORD` | 否 | 管理员密码，保护设置页面 |
| `SECRET_KEY` | 否 | Flask 密钥，建议生产环境设置 |

### 常见模型配置

| 平台 | AI_BASE_URL | AI_MODEL | AI_VISION_MODEL |
|------|-------------|----------|-----------------|
| OpenAI | https://api.openai.com/v1 | gpt-4o | gpt-4o |
| DeepSeek | https://api.deepseek.com/v1 | deepseek-chat | deepseek-chat |
| 通义千问 | https://dashscope.aliyuncs.com/compatible-mode/v1 | qwen-plus | qwen-vl-plus |
| Moonshot | https://api.moonshot.cn/v1 | moonshot-v1-8k | - |

---

## 预配置模式说明

当通过环境变量设置 `AI_API_KEY` 时，应用自动进入**预配置模式**：

- 终端用户无需配置任何 API 信息，打开网页直接使用
- 设置页面自动隐藏 API 配置表单
- 如设置了 `ADMIN_PASSWORD`，管理员可通过密码登录修改配置
- 终端用户无法看到或修改 API Key

这是分享给其他用户使用的推荐模式。

---

## Nginx 反向代理（可选）

如果需要 HTTPS 或自定义域名，可在服务器上配置 Nginx 反向代理：

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 600s;  # 视频处理可能耗时较长
    }
}
```

配合 Let's Encrypt 可免费获取 SSL 证书：

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```
