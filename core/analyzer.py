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
import time
import logging
import requests
from typing import List, Tuple

from config import Config

logger = logging.getLogger(__name__)


class AnalyzerError(Exception):
    pass


# ------------------------------------------------------------------ #
#  内部：调用 OpenAI 兼容接口
# ------------------------------------------------------------------ #
def _call_ai(messages: list, model: str = None, temperature: float = 0.7,
             max_tokens: int = 4096, response_format_json: bool = False,
             max_retries: int = 2) -> str:
    """调用 OpenAI 兼容的 chat completions 接口（带重试）"""
    if not Config.AI_API_KEY:
        raise AnalyzerError("未配置 AI API Key，请在设置页面填写")

    base_url = Config.AI_BASE_URL.rstrip("/")
    url = f"{base_url}/chat/completions"

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

    last_error = ""
    for attempt in range(max_retries + 1):
        try:
            logger.info(f"AI 调用 (尝试 {attempt + 1}/{max_retries + 1}): model={payload['model']}, url={url}")

            resp = requests.post(url, headers=headers, json=payload, timeout=180)

            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                logger.info(f"AI 调用成功，返回 {len(content)} 字符")
                return content

            # 非 200，解析错误信息
            try:
                err_data = resp.json()
                error_msg = err_data.get("error", {})
                if isinstance(error_msg, dict):
                    last_error = error_msg.get("message", str(error_msg))
                else:
                    last_error = str(error_msg)
            except Exception:
                last_error = resp.text[:500]

            logger.warning(f"AI 调用失败 (HTTP {resp.status_code}): {last_error}")

            # 429 限流或 5xx 服务端错误才重试
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
                wait = (attempt + 1) * 5
                logger.info(f"等待 {wait} 秒后重试...")
                time.sleep(wait)
                continue

            # 400/401/403/404 等客户端错误不重试，直接报错
            raise AnalyzerError(
                f"AI 接口调用失败 (HTTP {resp.status_code}): {last_error}\n"
                f"请检查：\n"
                f"- API Key 是否正确\n"
                f"- Base URL 是否正确（当前: {base_url}）\n"
                f"- 模型名称是否正确（当前: {payload['model']}）\n"
                f"- 账户余额是否充足"
            )

        except requests.exceptions.Timeout:
            last_error = "请求超时（180秒）"
            logger.warning(last_error)
            if attempt < max_retries:
                time.sleep(5)
                continue
            raise AnalyzerError(f"AI 接口请求超时，请稍后重试")

        except requests.exceptions.ConnectionError as e:
            last_error = str(e)
            logger.warning(f"连接失败: {last_error}")
            if attempt < max_retries:
                time.sleep(5)
                continue
            raise AnalyzerError(
                f"无法连接到 AI 接口: {last_error}\n"
                f"请检查 Base URL 是否正确: {base_url}"
            )

        except AnalyzerError:
            raise
        except Exception as e:
            last_error = str(e)
            logger.error(f"AI 调用异常: {last_error}")
            if attempt < max_retries:
                time.sleep(3)
                continue
            raise AnalyzerError(f"AI 接口调用异常: {last_error}")

    raise AnalyzerError(f"AI 接口调用失败（已重试 {max_retries + 1} 次）: {last_error}")


def _encode_image(path: str, max_size: int = 1024) -> str:
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
        img.save(buf, format="JPEG", quality=70)
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        return f"data:image/jpeg;base64,{b64}"
    except Exception as e:
        logger.warning(f"图片编码失败 {path}: {e}")
        # 回退：直接读取文件
        try:
            with open(path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            return f"data:image/jpeg;base64,{b64}"
        except Exception:
            raise


# ------------------------------------------------------------------ #
#  阶段一：内容分析
# ------------------------------------------------------------------ #
def analyze_content(frames: List[Tuple[float, str]], subtitle_text: str,
                    video_title: str = "", video_desc: str = "") -> str:
    """
    将采样后的视频画面 + 字幕发送给视觉模型，获取内容分析报告。
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
        # 限制字幕长度，避免超出 token 限制
        if len(subtitle_text) > 3000:
            subtitle_text = subtitle_text[:3000] + "\n...(字幕过长已截断)"
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

    # 添加图片
    img_count = 0
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
            img_count += 1
        except Exception as e:
            logger.warning(f"跳过帧 {fpath}: {e}")
            continue

    logger.info(f"内容分析: 发送 {img_count} 张图片, 模型={vision_model}")

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
    """根据内容分析报告 + 用户需求，生成结构化混剪脚本。"""
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
            # 去掉第一行（```json 或 ```）
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
        raise AnalyzerError(f"脚本生成结果解析失败: {e}\n原始输出前500字: {raw[:500]}")


# ------------------------------------------------------------------ #
#  诊断接口
# ------------------------------------------------------------------ #
def test_ai_connection() -> dict:
    """测试 AI 接口连接是否正常，返回诊断信息"""
    result = {
        "configured": bool(Config.AI_API_KEY),
        "base_url": Config.AI_BASE_URL,
        "model": Config.AI_MODEL,
        "vision_model": Config.AI_VISION_MODEL or Config.AI_MODEL,
    }

    if not Config.AI_API_KEY:
        result["ok"] = False
        result["error"] = "未配置 AI API Key"
        return result

    base_url = Config.AI_BASE_URL.rstrip("/")
    url = f"{base_url}/chat/completions"

    headers = {
        "Authorization": f"Bearer {Config.AI_API_KEY}",
        "Content-Type": "application/json",
    }

    # 发送一个最简单的文本请求测试连接
    payload = {
        "model": Config.AI_MODEL,
        "messages": [{"role": "user", "content": "请回复'连接成功'四个字"}],
        "max_tokens": 20,
        "temperature": 0,
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        result["status_code"] = resp.status_code

        if resp.status_code == 200:
            data = resp.json()
            reply = data["choices"][0]["message"]["content"]
            result["ok"] = True
            result["reply"] = reply
            result["message"] = "AI 接口连接正常"
        else:
            result["ok"] = False
            try:
                err_data = resp.json()
                error_msg = err_data.get("error", {})
                if isinstance(error_msg, dict):
                    error_msg = error_msg.get("message", str(error_msg))
                result["error"] = f"HTTP {resp.status_code}: {error_msg}"
            except Exception:
                result["error"] = f"HTTP {resp.status_code}: {resp.text[:300]}"

    except requests.exceptions.ConnectionError as e:
        result["ok"] = False
        result["error"] = f"无法连接到 {url}: {e}"
    except requests.exceptions.Timeout:
        result["ok"] = False
        result["error"] = f"请求超时: {url}"
    except Exception as e:
        result["ok"] = False
        result["error"] = str(e)

    return result


# ------------------------------------------------------------------ #
#  完整流程
# ------------------------------------------------------------------ #
def analyze_and_generate(frames: List[Tuple[float, str]],
                         subtitle_text: str,
                         user_requirements: dict,
                         video_title: str = "",
                         video_desc: str = "",
                         progress_callback=None) -> dict:
    """完整的分析 + 生成流程。"""
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
