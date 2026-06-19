# -*- coding: utf-8 -*-
"""
文件型任务存储 —— 解决 gunicorn 多 worker 下任务状态不共享的问题。
每个任务的状态保存在一个 JSON 文件中，所有 worker 都能读写同一目录。
"""

import os
import json
import threading
from datetime import datetime
from typing import Optional


# 任务文件存放目录
_TASKS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "temp", "tasks")

# 写锁（同一进程内的线程安全）
_write_lock = threading.Lock()


def _ensure_dir():
    os.makedirs(_TASKS_DIR, exist_ok=True)


def _task_path(task_id: str) -> str:
    return os.path.join(_TASKS_DIR, f"{task_id}.json")


def create_task(task_id: str, initial_data: dict):
    """创建一个新任务"""
    _ensure_dir()
    data = {
        "status": "pending",
        "message": "任务已创建，等待处理...",
        "progress": 0,
        "created_at": datetime.now().isoformat(),
    }
    data.update(initial_data)
    with _write_lock:
        with open(_task_path(task_id), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)


def update_task(task_id: str, **kwargs):
    """更新任务状态（合并写入）"""
    path = _task_path(task_id)
    if not os.path.exists(path):
        return

    with _write_lock:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            data = {}

        data.update(kwargs)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)


def get_task(task_id: str) -> Optional[dict]:
    """读取任务状态，不存在返回 None"""
    path = _task_path(task_id)
    if not os.path.exists(path):
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def delete_task(task_id: str):
    """删除任务文件"""
    path = _task_path(task_id)
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def cleanup_old_tasks(max_age_hours: int = 2):
    """清理超过指定时间的旧任务文件"""
    _ensure_dir()
    now = datetime.now()
    for fname in os.listdir(_TASKS_DIR):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(_TASKS_DIR, fname)
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(path))
            if (now - mtime).total_seconds() > max_age_hours * 3600:
                os.remove(path)
        except OSError:
            pass
