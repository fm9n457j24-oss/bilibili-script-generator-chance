# ============================================================ #
#  B站视频混剪脚本生成器 —— Docker 镜像
#  支持 Railway / Render / 任意云平台部署
#  Railway 会自动注入 PORT 环境变量
# ============================================================ #

FROM python:3.10-slim

# 设置时区
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 安装系统依赖：ffmpeg（截帧必需）+ 中文字体（DOCX 生成）+ curl（健康检查）
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fonts-wqy-zenhei \
    fonts-noto-cjk \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 设置工作目录
WORKDIR /app

# 先复制依赖文件，利用 Docker 缓存层
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir gunicorn

# 复制项目代码
COPY . .

# 创建必要目录
RUN mkdir -p /app/temp /app/outputs

# Railway 默认端口 5000，Railway 会通过 PORT 环境变量覆盖
ENV PORT=5000
EXPOSE 5000

# 健康检查（使用 curl，不依赖 Python）
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://127.0.0.1:${PORT:-5000}/health || exit 1

# 使用 gunicorn 生产级 WSGI 服务器启动
# --workers 1 --threads 4: 单 worker 多线程，确保后台线程与请求处理在同一进程内
# --timeout 600: 视频处理可能耗时较长，设置10分钟超时
# 使用 shell 形式以支持 ${PORT} 环境变量替换（Railway 会注入 PORT）
CMD gunicorn --bind 0.0.0.0:${PORT:-5000} --workers 1 --threads 4 --timeout 600 --access-logfile - --error-logfile - app:app
