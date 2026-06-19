# ============================================================ #
#  B站视频混剪脚本生成器 —— Docker 镜像
#  基于 Python 3.10 + ffmpeg，可在任何云服务器上一键部署
# ============================================================ #

FROM python:3.10-slim

# 设置时区
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 安装系统依赖：ffmpeg（截帧必需）+ 中文字体（DOCX 生成）
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fonts-wqy-zenhei \
    fonts-noto-cjk \
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

# 暴露端口
EXPOSE 5000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import requests; requests.get('http://127.0.0.1:5000/health', timeout=5)" || exit 1

# 使用 gunicorn 生产级 WSGI 服务器启动
# -w 4: 4个工作进程
# -b: 绑定地址
# --timeout 600: 视频处理可能耗时较长，设置10分钟超时
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "--timeout", "600", "--access-logfile", "-", "--error-logfile", "-", "app:app"]
