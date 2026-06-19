# -*- coding: utf-8 -*-
"""
AI 内容分析 & 脚本生成模块
功能：
  1. 将截取的视频画面 + 字幕发送给视觉大模型进行内容分析
  2. 根据分析结果 + 用户需求生成结构化混剪脚本
"""

import os
import json
import base64
import requests
from typing import List, Tuple

from config import Config


class AnalyzerError(Exception):
    pass


# ------------------------------------------------------------------ #
#  内部：调用 OpenAI 兼容接口
# ------------------------------------------------------------------ #
def _call_ai(messages: list, model: str = None, temperature: float = 0.7,
             max_tokens: int = 4096, response_format_json: bool = False) -> str:
    """调用 OpenAI 兼容的 chat completions 接口"""
    if not Config.AI_API_KEY:
        raise AnalyzerError("未配置 AI API Key，请在设置页面填写")

    url = f"{Config.AI_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {Config.AI_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model or Config.AI_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    if response_format_json:
        payload["response_format"] = {"type": "json_object"}

    resp = requests.post(url, headers=headers, json=payload, timeout=120)

    if resp.status_code != 200:
        error_msg = ""
        try:
            error_msg = resp.json().get("error", {}).get("message", "")
        except Exception:
            error_msg = resp.text[:300]
        raise AnalyzerError(f"AI 接口调用失败 (HTTP {resp.status_code}): {error_msg}")

    data = resp.json()
    return data["choices"][0]["message"]["content"]


def _encode_image(path: str, max_size: int = 1280) -> str:
    """将图片编码为 base64 data URL（自动缩放以减小体积）"""
    try:
        from PIL import Image
        import io

        img = Image.open(path)
        # 等比缩放
        if max(img.size) > max_size:
            ratio = max_size / max(img.size)
            new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
            img = img.resize(new_size, Image.LANCZOS)

        buf = io.BytesIO()
        img = img.convert("RGB")
        img.save(buf, format="JPEG", quality=75)
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        return f"data:image/jpeg;base64,{b64}"
    except Exception:
        # 回退：直接读取文件
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        return f"data:image/jpeg;base64,{b64}"


# ------------------------------------------------------------------ #
#  阶段一：内容分析
# ------------------------------------------------------------------ #
def analyze_content(frames: List[Tuple[float, str]], subtitle_text: str,
                    video_title: str = "", video_desc: str = "") -> str:
    """
    将采样后的视频画面 + 字幕发送给视觉模型，获取内容分析报告。

    Returns:
        分析报告文本
    """
    vision_model = Config.AI_VISION_MODEL or Config.AI_MODEL

    # 构建消息内容
    content_parts = []

    # 文字说明
    text_intro = (
        f"以下是来自B站视频《{video_title}》的画面截图（每隔0.5秒截取，已均匀采样）。\n"
    )
    if video_desc:
        text_intro += f"视频简介：{video_desc}\n"
    if subtitle_text:
        text_intro += f"\n字幕内容：\n{subtitle_text}\n"
    text_intro += (
        "\n请仔细观察这些画面并结合字幕，对视频内容进行全面分析，包括：\n"
        "1. 视频主题与核心内容\n"
        "2. 画面风格（色调、构图、转场特点）\n"
        "3. 内容结构与节奏（开头、发展、高潮、结尾）\n"
        "4. 关键场景描述（标注大致时间点）\n"
        "5. 情感基调与氛围\n"
        "6. 字幕/旁白的要点总结\n"
        "7. 可借鉴的剪辑手法与创意亮点\n"
    )

    content_parts.append({"type": "text", "text": text_intro})

    # 添加图片（分批以避免消息过大）
    for timestamp, fpath in frames:
        try:
            data_url = _encode_image(fpath)
            mm, ss = divmod(int(timestamp), 60)
            label = f"[{mm:02d}:{ss:02d}]"
            content_parts.append({"type": "text", "text": label})
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": data_url},
            })
        except Exception:
            continue

    messages = [
        {
            "role": "system",
            "content": (
                "你是一位专业的视频内容分析师和混剪脚本编剧。"
                "你擅长分析视频画面、理解内容结构，并提炼出可用于二次创作的关键信息。"
            ),
        },
        {
            "role": "user",
            "content": content_parts,
        },
    ]

    return _call_ai(messages, model=vision_model, temperature=0.5, max_tokens=4096)


# ------------------------------------------------------------------ #
#  阶段二：脚本生成
# ------------------------------------------------------------------ #
def generate_script(analysis: str, user_requirements: dict,
                    video_title: str = "") -> dict:
    """
    根据内容分析报告 + 用户需求，生成结构化混剪脚本。

    Args:
        analysis: 阶段一的分析报告
        user_requirements: 用户需求 dict，包含:
            - script_topic: 脚本主题/方向
            - script_style: 剪辑风格
            - target_duration: 目标时长（如 "2-3分钟"）
            - orientation: 横版/竖版
            - extra_notes: 额外要求

    Returns:
        {
            "title": "脚本标题",
            "duration": "2-3分钟",
            "orientation": "横版",
            "style_reference": "剪辑风格参考",
            "rows": [
                {
                    "shot_number": "1",
                    "post_production": "后期处理说明",
                    "visual_reference": "画面参考描述",
                    "subtitle_dialogue": "字幕/台词内容",
                    "notes": "备注"
                },
                ...
            ]
        }
    """
    topic = user_requirements.get("script_topic", "")
    style = user_requirements.get("script_style", "")
    duration = user_requirements.get("target_duration", "2-3分钟")
    orientation = user_requirements.get("orientation", "横版")
    extra = user_requirements.get("extra_notes", "")

    prompt = f"""你是一位专业的混剪脚本编剧。请根据以下视频内容分析报告，创作一份全新的混剪脚本。

## 视频内容分析报告
{analysis}

## 用户创作需求
- 脚本主题/方向：{topic or "根据原视频内容提炼并创新"}
- 剪辑风格：{style or "参考原视频风格并优化"}
- 目标时长：{duration}
- 画面方向：{orientation}
- 额外要求：{extra or "无"}

## 脚本格式要求
请严格按照以下混剪脚本模板格式输出，包含表头信息和分镜表格：

1. 脚本标题
2. 时长：{duration}
3. 横/竖板：{orientation}
4. 剪辑风格参考：（简要描述参考风格）

分镜表格列说明：
- 镜号：镜头编号（1, 2, 3...）
- 后期：后期处理说明（如调色、特效、转场、速度变化等）
- 画面参考：画面内容描述（参考原视频画面并创新，描述应具体可执行）
- 字幕/台词：该镜头的字幕或旁白内容
- 备注：补充说明（如音乐节奏、情绪提示等）

## 输出要求
请输出 JSON 格式（不要包含 markdown 代码块标记），结构如下：
{{
  "title": "脚本标题",
  "duration": "{duration}",
  "orientation": "{orientation}",
  "style_reference": "剪辑风格参考描述",
  "rows": [
    {{
      "shot_number": "1",
      "post_production": "后期处理说明",
      "visual_reference": "画面参考描述",
      "subtitle_dialogue": "字幕/台词",
      "notes": "备注"
    }}
  ]
}}

注意：
- 分镜数量根据时长合理安排，通常每个镜头 3-8 秒
- 画面参考要具体、可执行，能指导实际拍摄或剪辑
- 字幕/台词要有感染力，符合主题
- 后期处理要明确具体（如"暖色调调色"、"0.5倍速慢放"、"闪白转场"等）
- 确保脚本整体有起承转合，节奏感强"""

    messages = [
        {
            "role": "system",
            "content": "你是一位专业的混剪脚本编剧，擅长根据视频素材创作有创意、可执行的混剪脚本。你必须只输出有效的 JSON。",
        },
        {"role": "user", "content": prompt},
    ]

    raw = _call_ai(messages, temperature=0.8, max_tokens=4096,
                   response_format_json=True)

    # 解析 JSON
    try:
        # 去除可能的 markdown 代码块标记
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

        script_data = json.loads(raw)

        # 校验必要字段
        if "rows" not in script_data:
            raise ValueError("缺少 rows 字段")

        return script_data

    except json.JSONDecodeError as e:
        raise AnalyzerError(f"脚本生成结果解析失败: {e}\n原始输出: {raw[:500]}")


# ------------------------------------------------------------------ #
#  完整流程
# ------------------------------------------------------------------ #
def analyze_and_generate(frames: List[Tuple[float, str]],
                         subtitle_text: str,
                         user_requirements: dict,
                         video_title: str = "",
                         video_desc: str = "",
                         progress_callback=None) -> dict:
    """
    完整的分析 + 生成流程。

    Args:
        frames: 采样后的帧列表 [(timestamp, path), ...]
        subtitle_text: 字幕全文
        user_requirements: 用户需求
        video_title: 视频标题
        video_desc: 视频简介
        progress_callback: 回调 (stage, message)

    Returns:
        脚本数据 dict
    """
    # 阶段一：内容分析
    if progress_callback:
        progress_callback("analyzing", f"正在分析 {len(frames)} 帧画面与字幕...")

    analysis = analyze_content(frames, subtitle_text, video_title, video_desc)

    # 阶段二：脚本生成
    if progress_callback:
        progress_callback("generating", "正在根据分析结果生成混剪脚本...")

    script_data = generate_script(analysis, user_requirements, video_title)

    if progress_callback:
        progress_callback("done", "脚本生成完成")

    return script_data
