# -*- coding: utf-8 -*-
"""
B站视频混剪脚本生成器 —— Flask Web 应用
用户通过浏览器访问即可使用，无需安装任何客户端软件。

部署模式：
  - 本地开发：python app.py，通过网页设置配置 API Key
  - Docker/云部署：通过环境变量预配置 API Key，终端用户直接使用

任务存储：使用文件型存储（core/task_store.py），支持 gunicorn 多 worker 共享状态。
"""

import os
import uuid
import json
import logging
import threading
from datetime import datetime
from functools import wraps

from flask import Flask, request, jsonify, send_file, render_template, session

from config import Config
from core.downloader import download_video, DownloadError
from core.extractor import extract_frames, sample_frames_for_vision, cleanup_frames
from core.analyzer import analyze_and_generate, AnalyzerError, test_ai_connection
from core.docx_writer import generate_docx
from core.task_store import create_task, update_task, get_task, cleanup_old_tasks

# ------------------------------------------------------------------ #
#  日志配置
# ------------------------------------------------------------------ #
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(process)d] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.environ.get("SECRET_KEY", "bili-script-gen-secret-2024")

Config.ensure_dirs()


# ------------------------------------------------------------------ #
#  后台任务处理
# ------------------------------------------------------------------ #
def _process_task(task_id, params):
    """后台处理线程：下载 → 截帧 → 分析 → 生成脚本 → 输出 DOCX
    任务状态通过文件存储共享，所有 gunicorn worker 都能读取。
    """
    try:
        url = params["url"]
        requirements = {
            "script_topic": params.get("script_topic", ""),
            "script_style": params.get("script_style", ""),
            "target_duration": params.get("target_duration", "2-3分钟"),
            "orientation": params.get("orientation", "横版"),
            "extra_notes": params.get("extra_notes", ""),
        }

        task_dir = os.path.join(Config.TEMP_DIR, task_id)
        os.makedirs(task_dir, exist_ok=True)

        logger.info(f"任务 {task_id} 开始: {url}")

        # ---- 阶段 1：下载视频 ----
        update_task(task_id, status="downloading", message="正在解析视频链接并下载视频...",
                    progress=5)

        def dl_progress(downloaded, total):
            if total > 0:
                pct = min(25, 5 + int(downloaded / total * 20))
                update_task(task_id, progress=pct,
                            message=f"正在下载视频... {downloaded // 1024}KB / {total // 1024}KB")

        video_info = download_video(url, task_dir, progress_callback=dl_progress)

        update_task(task_id, progress=28,
                    message=f"视频下载完成：{video_info.title}",
                    video_info=video_info.to_dict())

        # ---- 阶段 2：截取画面 ----
        update_task(task_id, status="extracting", message="正在每隔0.5秒截取视频画面...",
                    progress=30)

        frames_dir = os.path.join(task_dir, "frames")
        all_frames = extract_frames(video_info.video_path, frames_dir)

        if not all_frames:
            raise RuntimeError("截帧失败，未获取到任何画面")

        update_task(task_id, progress=45,
                    message=f"截取完成，共 {len(all_frames)} 帧画面")

        # 采样用于 AI 分析
        sampled = sample_frames_for_vision(all_frames)

        # ---- 阶段 3：AI 内容分析 ----
        update_task(task_id, status="analyzing",
                    message=f"正在发送 {len(sampled)} 帧画面给 AI 进行内容分析...",
                    progress=50)

        def analysis_progress(stage, msg):
            if stage == "analyzing":
                update_task(task_id, progress=55, message=msg)
            elif stage == "generating":
                update_task(task_id, progress=80, message=msg)

        script_data = analyze_and_generate(
            frames=sampled,
            subtitle_text=video_info.subtitle_text,
            user_requirements=requirements,
            video_title=video_info.title,
            video_desc=video_info.desc,
            progress_callback=analysis_progress,
        )

        # ---- 阶段 4：生成 DOCX ----
        update_task(task_id, status="generating", message="正在生成 Word 脚本文档...",
                    progress=92)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_title = "".join(c for c in video_info.title if c not in r'\/:*?"<>|')[:30]
        filename = f"混剪脚本_{safe_title}_{timestamp}.docx"
        output_path = os.path.join(Config.OUTPUT_DIR, filename)

        generate_docx(script_data, output_path)

        # ---- 完成 ----
        logger.info(f"任务 {task_id} 完成: {filename}")
        update_task(task_id, status="done", message="脚本生成完成！",
                    progress=100,
                    result={
                        "filename": filename,
                        "script_data": script_data,
                        "video_info": video_info.to_dict(),
                        "frame_count": len(all_frames),
                    })

        # 清理临时文件
        try:
            cleanup_frames(frames_dir)
            if os.path.exists(video_info.video_path):
                os.remove(video_info.video_path)
        except Exception:
            pass

    except DownloadError as e:
        logger.error(f"任务 {task_id} 下载失败: {e}")
        update_task(task_id, status="error", message=f"下载失败: {e}", progress=0)
    except AnalyzerError as e:
        logger.error(f"任务 {task_id} AI分析失败: {e}")
        update_task(task_id, status="error", message=f"AI 分析失败: {e}", progress=0)
    except Exception as e:
        logger.error(f"任务 {task_id} 处理失败: {e}")
        update_task(task_id, status="error", message=f"处理失败: {e}", progress=0)


# ------------------------------------------------------------------ #
#  管理员认证
# ------------------------------------------------------------------ #
def admin_required(f):
    """如果设置了 ADMIN_PASSWORD，则要求管理员登录才能访问设置"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if Config.ADMIN_PASSWORD:
            if not session.get("is_admin"):
                return jsonify({"error": "需要管理员密码", "admin_required": True}), 403
        return f(*args, **kwargs)
    return decorated


# ------------------------------------------------------------------ #
#  路由
# ------------------------------------------------------------------ #
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/health")
def health():
    """健康检查端点（供 Docker / 云平台使用）"""
    return jsonify({
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "configured": bool(Config.AI_API_KEY),
    })


@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    if request.method == "POST":
        # 预配置模式下需要管理员权限
        if Config.is_preconfigured() and Config.ADMIN_PASSWORD:
            if not session.get("is_admin"):
                return jsonify({"error": "需要管理员密码", "admin_required": True}), 403

        data = request.json
        Config.save(
            ai_api_key=data.get("ai_api_key", ""),
            ai_base_url=data.get("ai_base_url", "https://api.openai.com/v1"),
            ai_model=data.get("ai_model", "gpt-4o"),
            ai_vision_model=data.get("ai_vision_model", ""),
            bili_sessdata=data.get("bili_sessdata", ""),
        )
        return jsonify({"ok": True, "message": "配置已保存"})

    # GET
    return jsonify(Config.to_dict())


@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    """管理员登录"""
    data = request.json
    password = data.get("password", "")
    if Config.ADMIN_PASSWORD and password == Config.ADMIN_PASSWORD:
        session["is_admin"] = True
        return jsonify({"ok": True, "message": "登录成功"})
    return jsonify({"error": "密码错误"}), 401


@app.route("/api/admin/logout", methods=["POST"])
def admin_logout():
    session.pop("is_admin", None)
    return jsonify({"ok": True})


@app.route("/api/test-ai", methods=["POST"])
def api_test_ai():
    """测试 AI 接口连接是否正常"""
    try:
        result = test_ai_connection()
        return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/generate", methods=["POST"])
def api_generate():
    data = request.json
    url = data.get("url", "").strip()

    if not url:
        return jsonify({"error": "请输入 B站视频链接"}), 400

    if not Config.AI_API_KEY:
        return jsonify({"error": "服务未配置 AI API Key，请联系管理员"}), 400

    task_id = str(uuid.uuid4())[:8]

    # 创建任务文件（所有 worker 共享）
    create_task(task_id, {
        "status": "pending",
        "message": "任务已创建，等待处理...",
        "progress": 0,
        "created_at": datetime.now().isoformat(),
    })

    # 启动后台线程处理（线程在当前 worker 内运行，状态写入文件供其他 worker 读取）
    thread = threading.Thread(target=_process_task, args=(task_id, data), daemon=True)
    thread.start()

    logger.info(f"创建任务 {task_id}: {url}")
    return jsonify({"task_id": task_id})


@app.route("/api/status/<task_id>")
def api_status(task_id):
    # 从文件读取任务状态（任何 worker 都能读到）
    task = get_task(task_id)

    if task is None:
        return jsonify({"error": "任务不存在"}), 404

    return jsonify(task)


@app.route("/download/<filename>")
def download(filename):
    filepath = os.path.join(Config.OUTPUT_DIR, filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "文件不存在"}), 404

    return send_file(filepath, as_attachment=True, download_name=filename)


@app.route("/api/preview/<filename>")
def preview(filename):
    """预览已生成的脚本数据"""
    filepath = os.path.join(Config.OUTPUT_DIR, filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "文件不存在"}), 404
    return send_file(filepath, as_attachment=False)


# ------------------------------------------------------------------ #
#  入口
# ------------------------------------------------------------------ #
if __name__ == "__main__":
    # 启动时清理旧任务
    cleanup_old_tasks(max_age_hours=2)

    print(f"{'=' * 50}")
    print(f"  B站视频混剪脚本生成器")
    print(f"  访问地址: http://127.0.0.1:{Config.PORT}")
    print(f"  AI 模型: {Config.AI_MODEL}")
    print(f"  AI 已配置: {'是' if Config.AI_API_KEY else '否（请在网页设置中配置）'}")
    print(f"  预配置模式: {'是（环境变量配置）' if Config.is_preconfigured() else '否'}")
    print(f"  管理员密码: {'已设置' if Config.ADMIN_PASSWORD else '未设置'}")
    print(f"  任务存储: 文件型（支持多 worker）")
    print(f"{'=' * 50}")

    app.run(host=Config.HOST, port=Config.PORT, debug=False, threaded=True)
