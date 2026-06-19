# -*- coding: utf-8 -*-
"""
视频画面截取 & 字幕处理模块
功能：使用 ffmpeg（imageio-ffmpeg 内置）每隔 0.5 秒截取视频画面
"""

import os
import glob
import subprocess
from typing import List, Tuple

from config import Config

try:
    from imageio_ffmpeg import get_ffmpeg_exe
    _FFMPEG_PATH = get_ffmpeg_exe()
except Exception:
    _FFMPEG_PATH = "ffmpeg"  # 回退到系统 ffmpeg


def extract_frames(video_path: str, output_dir: str = None,
                   interval: float = None) -> List[Tuple[float, str]]:
    """
    每隔 interval 秒截取一帧画面。

    Args:
        video_path: 视频文件路径
        output_dir: 截图输出目录
        interval: 截帧间隔（秒），默认 0.5

    Returns:
        [(timestamp, frame_path), ...] 按时间排序
    """
    if output_dir is None:
        output_dir = os.path.join(Config.TEMP_DIR, "frames")
    if interval is None:
        interval = Config.FRAME_INTERVAL

    os.makedirs(output_dir, exist_ok=True)

    # 清空旧帧
    for old in glob.glob(os.path.join(output_dir, "frame_*.jpg")):
        try:
            os.remove(old)
        except OSError:
            pass

    fps = 1.0 / interval  # 例如 interval=0.5 → fps=2

    cmd = [
        _FFMPEG_PATH,
        "-i", video_path,
        "-vf", f"fps={fps}",
        "-q:v", "3",            # JPEG 质量 (2-31, 越小越好)
        "-y",                   # 覆盖输出
        os.path.join(output_dir, "frame_%06d.jpg"),
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=600,
    )

    if result.returncode != 0:
        # 某些视频可能需要更多处理，尝试不带 fps 滤镜
        cmd2 = [
            _FFMPEG_PATH,
            "-i", video_path,
            "-vf", f"fps={fps},scale='min(1280,iw)':-2",
            "-q:v", "3",
            "-y",
            os.path.join(output_dir, "frame_%06d.jpg"),
        ]
        result2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=600)
        if result2.returncode != 0:
            raise RuntimeError(
                f"ffmpeg 截帧失败:\n{result2.stderr[-500:] if result2.stderr else '未知错误'}"
            )

    # 收集所有帧并计算时间戳
    frames = sorted(glob.glob(os.path.join(output_dir, "frame_*.jpg")))
    result_list = []
    for i, fpath in enumerate(frames):
        timestamp = i * interval
        result_list.append((timestamp, fpath))

    return result_list


def sample_frames_for_vision(frames: List[Tuple[float, str]],
                             max_count: int = None) -> List[Tuple[float, str]]:
    """
    从全部帧中均匀采样，用于发送给视觉模型。
    避免发送过多图片导致 API 超限。

    Args:
        frames: 全部帧列表 [(timestamp, path), ...]
        max_count: 最大采样数

    Returns:
        采样后的帧列表
    """
    if max_count is None:
        max_count = Config.MAX_FRAMES_FOR_VISION

    if len(frames) <= max_count:
        return frames

    step = len(frames) / max_count
    indices = [int(i * step) for i in range(max_count)]
    # 确保不重复且不越界
    indices = sorted(set(indices))
    return [frames[i] for i in indices if i < len(frames)]


def get_video_duration(video_path: str) -> float:
    """使用 ffprobe 获取视频时长（秒）"""
    try:
        # imageio-ffmpeg 也提供 ffprobe 路径
        ffprobe_path = _FFMPEG_PATH.replace("ffmpeg", "ffprobe")
        if not os.path.exists(ffprobe_path):
            ffprobe_path = "ffprobe"

        cmd = [
            ffprobe_path,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            return float(result.stdout.strip())
    except Exception:
        pass
    return 0.0


def cleanup_frames(output_dir: str = None):
    """清理截帧临时文件"""
    if output_dir is None:
        output_dir = os.path.join(Config.TEMP_DIR, "frames")
    for f in glob.glob(os.path.join(output_dir, "frame_*.jpg")):
        try:
            os.remove(f)
        except OSError:
            pass
