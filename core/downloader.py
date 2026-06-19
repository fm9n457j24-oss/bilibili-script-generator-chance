# -*- coding: utf-8 -*-
"""
B站视频下载器
参考 Henryhaohao/Bilibili_video_download 项目思路，使用现代 B站 API 实现。
功能：解析视频链接 → 获取视频信息 → 下载视频流 → 获取字幕
"""

import os
import re
import json
import time
import requests

from config import Config


# ------------------------------------------------------------------ #
#  常量
# ------------------------------------------------------------------ #
BILI_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com",
    "Origin": "https://www.bilibili.com",
}

API_VIEW = "https://api.bilibili.com/x/web-interface/view"
API_PLAYURL = "https://api.bilibili.com/x/player/playurl"
API_PLAYER_V2 = "https://api.bilibili.com/x/player/v2"


class DownloadError(Exception):
    """下载异常"""
    pass


class VideoInfo:
    """视频信息数据类"""

    def __init__(self):
        self.bvid = ""
        self.aid = ""
        self.cid = ""
        self.title = ""
        self.desc = ""
        self.duration = 0          # 秒
        self.video_path = ""       # 下载后的视频文件路径
        self.subtitle_text = ""    # 字幕全文
        self.cover_url = ""        # 封面图 URL

    def to_dict(self):
        return {
            "bvid": self.bvid,
            "title": self.title,
            "desc": self.desc,
            "duration": self.duration,
            "video_path": self.video_path,
            "subtitle_text": self.subtitle_text[:500] + "..." if len(self.subtitle_text) > 500 else self.subtitle_text,
            "cover_url": self.cover_url,
        }


# ------------------------------------------------------------------ #
#  公开接口
# ------------------------------------------------------------------ #
def parse_bvid(url: str) -> str:
    """
    从各种格式的 B站链接中提取 BV 号。
    支持:
      - https://www.bilibili.com/video/BV1xx411c7mD
      - https://www.bilibili.com/video/BV1xx411c7mD?p=2
      - https://b23.tv/xxxxxxx  (短链)
      - BV1xx411c7mD
    """
    url = url.strip()

    # 直接传入 BV 号
    m = re.match(r'^(BV[\w]+)$', url)
    if m:
        return m.group(1)

    # 短链 b23.tv —— 需要跟随重定向
    if 'b23.tv' in url:
        try:
            resp = requests.get(url, headers=BILI_HEADERS, allow_redirects=True, timeout=10)
            url = resp.url
        except Exception:
            raise DownloadError("短链解析失败，请检查链接是否有效")

    # 从 URL 中提取 BV 号
    m = re.search(r'/(BV[\w]+)', url)
    if m:
        return m.group(1)

    # 尝试 av 号
    m = re.search(r'/av(\d+)', url)
    if m:
        # 通过 API 转换为 bvid
        aid = m.group(1)
        try:
            resp = requests.get(
                API_VIEW,
                params={"aid": aid},
                headers=BILI_HEADERS,
                timeout=10,
            )
            data = resp.json().get("data", {})
            return data.get("bvid", "")
        except Exception:
            pass

    raise DownloadError(f"无法从链接中解析 BV 号: {url}")


def get_video_info(bvid: str) -> dict:
    """
    获取视频基本信息（cid、标题、简介、时长、封面等）。
    返回原始 API data 字段。
    """
    cookies = {}
    if Config.BILI_SESSDATA:
        cookies["SESSDATA"] = Config.BILI_SESSDATA

    resp = requests.get(
        API_VIEW,
        params={"bvid": bvid},
        headers=BILI_HEADERS,
        cookies=cookies,
        timeout=15,
    )
    result = resp.json()
    if result.get("code") != 0:
        raise DownloadError(f"获取视频信息失败: {result.get('message', '未知错误')}")

    return result["data"]


def download_video_stream(bvid: str, cid: str, output_dir: str,
                          quality: int = None, progress_callback=None) -> str:
    """
    下载视频流（仅视频，不含音频）。
    使用 DASH 格式，下载视频流即可用于截帧分析。

    Args:
        bvid: BV 号
        cid: 视频 cid
        output_dir: 输出目录
        quality: 清晰度 80=1080P 64=720P 32=480P 16=360P
        progress_callback: 回调函数 (downloaded_bytes, total_bytes)

    Returns:
        下载后的视频文件路径
    """
    if quality is None:
        quality = Config.FRAME_QUALITY

    cookies = {}
    if Config.BILI_SESSDATA:
        cookies["SESSDATA"] = Config.BILI_SESSDATA

    # 获取播放地址
    resp = requests.get(
        API_PLAYURL,
        params={
            "bvid": bvid,
            "cid": cid,
            "qn": quality,
            "fnval": 16,   # DASH 格式
            "fourk": 0,
        },
        headers=BILI_HEADERS,
        cookies=cookies,
        timeout=15,
    )
    result = resp.json()
    if result.get("code") != 0:
        raise DownloadError(f"获取播放地址失败: {result.get('message', '未知错误')}")

    data = result["data"]

    # ---------------------------------------------------------------- #
    #  优先 DASH 格式
    # ---------------------------------------------------------------- #
    if "dash" in data and data["dash"]:
        dash = data["dash"]
        video_streams = dash.get("video", [])

        if not video_streams:
            raise DownloadError("未找到可用的视频流")

        # 选择指定清晰度的视频流，找不到则取第一个
        target = None
        for v in video_streams:
            if v.get("id") == quality:
                target = v
                break
        if target is None:
            target = video_streams[0]

        video_url = target.get("baseUrl") or target.get("base_url") or ""
        if not video_url:
            # 尝试 backupUrl
            backup = target.get("backupUrl") or target.get("backup_url") or []
            if backup:
                video_url = backup[0]

        if not video_url:
            raise DownloadError("无法获取视频流下载地址")

        # 确保是完整 URL
        if video_url.startswith("//"):
            video_url = "https:" + video_url

        ext = "mp4"
        output_path = os.path.join(output_dir, f"{bvid}_video.{ext}")

        _download_file(video_url, output_path, progress_callback)
        return output_path

    # ---------------------------------------------------------------- #
    #  回退：durl 格式（FLV 分段）
    # ---------------------------------------------------------------- #
    elif "durl" in data and data["durl"]:
        durl_list = data["durl"]
        if len(durl_list) == 1:
            output_path = os.path.join(output_dir, f"{bvid}_video.flv")
            _download_file(durl_list[0]["url"], output_path, progress_callback)
            return output_path
        else:
            # 多段下载后合并（简单拼接）
            paths = []
            for i, seg in enumerate(durl_list):
                p = os.path.join(output_dir, f"{bvid}_part{i}.flv")
                _download_file(seg["url"], p, progress_callback)
                paths.append(p)
            # 返回第一段路径（截帧用第一段即可，或后续合并）
            output_path = os.path.join(output_dir, f"{bvid}_video.flv")
            _merge_flv(paths, output_path)
            return output_path

    raise DownloadError("未找到可用的视频流（既无 DASH 也无 durl）")


def get_subtitles(bvid: str, cid: str) -> str:
    """
    获取视频字幕文本。
    通过 player/v2 接口获取字幕列表，下载并拼接为纯文本。

    Returns:
        字幕全文（带时间戳），若无字幕则返回空字符串
    """
    cookies = {}
    if Config.BILI_SESSDATA:
        cookies["SESSDATA"] = Config.BILI_SESSDATA

    try:
        resp = requests.get(
            API_PLAYER_V2,
            params={"cid": cid, "bvid": bvid},
            headers=BILI_HEADERS,
            cookies=cookies,
            timeout=15,
        )
        result = resp.json()
        if result.get("code") != 0:
            return ""

        subtitle_info = result.get("data", {}).get("subtitle", {})
        subtitles = subtitle_info.get("subtitles", [])

        if not subtitles:
            return ""

        # 优先选择中文字幕
        target_sub = None
        for s in subtitles:
            lan_doc = s.get("lan_doc", "")
            if "中" in lan_doc or s.get("lan") == "zh-CN":
                target_sub = s
                break
        if target_sub is None:
            target_sub = subtitles[0]

        sub_url = target_sub.get("subtitle_url", "")
        if not sub_url:
            return ""
        if sub_url.startswith("//"):
            sub_url = "https:" + sub_url

        # 下载字幕 JSON
        sub_resp = requests.get(sub_url, headers=BILI_HEADERS, timeout=15)
        sub_data = sub_resp.json()
        body = sub_data.get("body", [])

        lines = []
        for item in body:
            start = item.get("from", 0)
            content = item.get("content", "").strip()
            if content:
                mm, ss = divmod(int(start), 60)
                lines.append(f"[{mm:02d}:{ss:02d}] {content}")

        return "\n".join(lines)

    except Exception:
        return ""


def download_video(url: str, output_dir: str, progress_callback=None) -> VideoInfo:
    """
    完整下载流程：解析链接 → 获取信息 → 下载视频 → 获取字幕

    Args:
        url: B站视频链接或 BV 号
        output_dir: 输出目录
        progress_callback: 下载进度回调

    Returns:
        VideoInfo 对象
    """
    os.makedirs(output_dir, exist_ok=True)

    # 1. 解析 BV 号
    bvid = parse_bvid(url)

    # 2. 获取视频信息
    info_data = get_video_info(bvid)

    vi = VideoInfo()
    vi.bvid = bvid
    vi.aid = str(info_data.get("aid", ""))
    vi.cid = str(info_data.get("cid", ""))
    vi.title = info_data.get("title", bvid)
    vi.desc = info_data.get("desc", "")
    vi.duration = info_data.get("duration", 0)
    vi.cover_url = info_data.get("pic", "")

    # 处理多 P 视频：默认取第一集
    pages = info_data.get("pages", [])
    if pages:
        vi.cid = str(pages[0].get("cid", vi.cid))

    # 3. 下载视频流
    vi.video_path = download_video_stream(
        vi.bvid, vi.cid, output_dir,
        progress_callback=progress_callback,
    )

    # 4. 获取字幕
    vi.subtitle_text = get_subtitles(vi.bvid, vi.cid)

    return vi


# ------------------------------------------------------------------ #
#  内部工具
# ------------------------------------------------------------------ #
def _download_file(url: str, output_path: str, progress_callback=None):
    """下载文件（带进度回调）"""
    headers = dict(BILI_HEADERS)
    headers["Range"] = "bytes=0-"

    resp = requests.get(url, headers=headers, stream=True, timeout=30)
    if resp.status_code not in (200, 206):
        raise DownloadError(f"下载失败，HTTP {resp.status_code}")

    total = int(resp.headers.get("content-length", 0))
    downloaded = 0
    chunk_size = 1024 * 256  # 256KB

    with open(output_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=chunk_size):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                if progress_callback:
                    progress_callback(downloaded, total)

    if progress_callback:
        progress_callback(total, total)


def _merge_flv(paths: list, output_path: str):
    """简单合并 FLV 文件（二进制拼接）"""
    with open(output_path, "wb") as out:
        for p in paths:
            with open(p, "rb") as f:
                out.write(f.read())
    # 清理临时分段
    for p in paths:
        try:
            os.remove(p)
        except OSError:
            pass
