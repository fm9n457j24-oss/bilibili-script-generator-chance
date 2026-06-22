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
    """调用 OpenAI 兼容的 chat completions 接口（带重试）

    兼容智谱GLM / 通义千问 / DeepSeek / OpenAI 等。
    如果 response_format 导致 400 错误，会自动移除该参数重试。
    """
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

    use_response_format = response_format_json
    if use_response_format:
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

            # 如果是 400 错误且使用了 response_format，可能是模型不支持，移除后重试
            if resp.status_code == 400 and use_response_format:
                logger.info("可能是 response_format 不被支持，移除该参数后重试...")
                payload.pop("response_format", None)
                use_response_format = False
                continue

            # 如果是 400 错误且涉及 max_tokens 限制，自动降低后重试
            if resp.status_code == 400 and "max_tokens" in last_error.lower():
                import re
                m = re.search(r'(\d+)', last_error)
                new_limit = int(m.group(1)) if m else 1024
                if payload.get("max_tokens", 0) > new_limit:
                    logger.info(f"max_tokens 超限，降低为 {new_limit} 后重试...")
                    payload["max_tokens"] = new_limit
                    continue

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

    针对智谱GLM-4V等限制单次图片数量的模型，采用分批策略：
    每批发送最多 MAX_IMAGES_PER_BATCH 张图片，最后合并分析结果。
    """
    vision_model = Config.AI_VISION_MODEL or Config.AI_MODEL

    # 限制字幕长度
    if subtitle_text and len(subtitle_text) > 3000:
        subtitle_text = subtitle_text[:3000] + "\n...(字幕过长已截断)"

    # 编码所有图片
    encoded_frames = []
    for timestamp, fpath in frames:
        try:
            data_url = _encode_image(fpath)
            mm, ss = divmod(int(timestamp), 60)
            label = f"[{mm:02d}:{ss:02d}]"
            encoded_frames.append((label, data_url))
        except Exception as e:
            logger.warning(f"跳过帧 {fpath}: {e}")
            continue

    if not encoded_frames:
        raise AnalyzerError("没有可用的画面帧用于分析")

    logger.info(f"内容分析: 共 {len(encoded_frames)} 张图片, 模型={vision_model}")

    # 分批处理（每批最多 4 张，留 1 张余量）
    MAX_IMAGES_PER_BATCH = 4
    batches = []
    for i in range(0, len(encoded_frames), MAX_IMAGES_PER_BATCH):
        batches.append(encoded_frames[i:i + MAX_IMAGES_PER_BATCH])

    logger.info(f"分为 {len(batches)} 批，每批最多 {MAX_IMAGES_PER_BATCH} 张图片")

    # 如果只有一批，直接单次调用
    if len(batches) == 1:
        return _analyze_single_batch(batches[0], subtitle_text, video_title, video_desc, vision_model)

    # 多批：逐批分析，最后合并
    batch_results = []
    for i, batch in enumerate(batches):
        batch_num = i + 1
        total_batches = len(batches)
        time_range = f"{batch[0][0]} ~ {batch[-1][0]}"

        logger.info(f"分析第 {batch_num}/{total_batches} 批 ({time_range}), {len(batch)} 张图片")

        # 第一批附带字幕和视频信息，后续批次只分析画面
        batch_subtitle = subtitle_text if i == 0 else ""
        batch_desc = video_desc if i == 0 else ""

        result = _analyze_single_batch(
            batch, batch_subtitle, video_title, batch_desc, vision_model,
            batch_num=batch_num, total_batches=total_batches, time_range=time_range
        )
        batch_results.append(result)

    # 合并所有批次的分析结果
    logger.info("合并所有批次的分析结果...")
    return _merge_batch_results(batch_results, video_title, subtitle_text, video_desc)


def _analyze_single_batch(batch_frames, subtitle_text, video_title, video_desc,
                          vision_model, batch_num=None, total_batches=None, time_range=None):
    """分析单批图片"""
    content_parts = []

    # 文字说明
    if batch_num and total_batches:
        text_intro = (
            f"以下是来自B站视频《{video_title}》的画面截图（第{batch_num}/{total_batches}批，"
            f"时间段 {time_range}）。\n"
        )
    else:
        text_intro = (
            f"以下是来自B站视频《{video_title}》的画面截图（每隔0.5秒截取，已均匀采样）。\n"
        )

    if video_desc:
        text_intro += f"视频简介：{video_desc}\n"
    if subtitle_text:
        text_intro += f"\n字幕内容：\n{subtitle_text}\n"

    if batch_num and total_batches:
        text_intro += (
            f"\n请分析这批画面（时间段 {time_range}），包括：\n"
            "1. 这批画面的主要内容\n"
            "2. 画面风格（色调、构图）\n"
            "3. 关键场景描述\n"
            "4. 情感基调\n"
            "5. 可借鉴的剪辑手法\n"
        )
    else:
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

    # 添加本批图片
    for label, data_url in batch_frames:
        content_parts.append({"type": "text", "text": label})
        content_parts.append({
            "type": "image_url",
            "image_url": {"url": data_url},
        })

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

    return _call_ai(messages, model=vision_model, temperature=0.5, max_tokens=1024)


def _merge_batch_results(batch_results, video_title, subtitle_text, video_desc):
    """将多批次的分析结果合并为一份完整报告"""
    combined = "\n\n---\n\n".join(
        f"【第{i+1}批分析】\n{r}" for i, r in enumerate(batch_results)
    )

    prompt = f"""以下是对B站视频《{video_title}》分批进行画面分析的结果。
{"视频简介：" + video_desc if video_desc else ""}
{"字幕内容：" + subtitle_text[:1500] if subtitle_text else ""}

请将以下分批分析结果整合为一份完整、连贯的视频内容分析报告，包括：
1. 视频主题与核心内容
2. 画面风格（色调、构图、转场特点）
3. 内容结构与节奏（开头、发展、高潮、结尾）
4. 关键场景描述（标注大致时间点）
5. 情感基调与氛围
6. 字幕/旁白的要点总结
7. 可借鉴的剪辑手法与创意亮点

分批分析结果：
{combined}

请输出整合后的完整分析报告："""

    messages = [
        {
            "role": "system",
            "content": "你是一位专业的视频内容分析师，擅长将分段分析整合为完整报告。",
        },
        {"role": "user", "content": prompt},
    ]

    # 合并阶段使用文本模型（不需要视觉），max_tokens 可以更大
    text_model = Config.AI_MODEL
    return _call_ai(messages, model=text_model, temperature=0.5, max_tokens=4096)


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

    # 检测是否为教育类需求
    education_keywords = [
        "教育", "课程", "教学", "学习", "培训", "老师", "学生", "家长", "孩子",
        "辅导", "提分", "数学", "语文", "英语", "物理", "化学", "网课", "在线课",
        "知识付费", "考研", "高考", "中考", "启蒙", "少儿", "K12", "留学",
        "编程", "技能", "职业培训", "公开课", "讲座", "授课", "课堂",
    ]
    combined_text = f"{topic} {style} {extra} {video_title}"
    is_education = any(kw in combined_text for kw in education_keywords)

    # 教育类专用技巧模块
    education_module = ""
    if is_education:
        education_module = """
## 教育类脚本专用技巧（本条脚本必须额外遵循）

### 教育类脚本的底层逻辑
教育类产品转化脚本不要先证明"课程多好"，要先让家长/学员觉得：
"这说的就是我家孩子/我的问题，而且对方真的懂。"

推荐骨架：
真实场景痛点 → 精准命名问题 → 给出小方法/小演示/小诊断 → 产品自然承接 → 低门槛转化
产品出现前，必须先让用户觉得"我刚刚听到了有用的东西"。

### 教育类开头钩子（优先使用以下类型）
1. **反常识型**：很多孩子数学掉队，不一定是题刷少了。
2. **具体场景型**：同一道题昨天刚讲过，今天换个问法，孩子又卡住了。
3. **热点切入型**：先复述热点里的具体画面和情绪，再引出教育观点。
4. **老师人格型**：用老师的口头禅、课堂状态、学生评价开头，让内容先像人物故事。
5. **家长自述型**：用"我给孩子选课时最看重什么"切入。
开头不要做的事：不堆课程名/价格/优惠；不讲抽象道理；不用无关热梗。

### 痛点必须具体（教育类核心要求）
理论不能直接当痛点。必须先写具体场景，再解释背后原因。
痛点判断标准：能不能被拍出来？家长有没有见过？孩子有没有真实反应？
例：
- 痛点场景：孩子题也刷了，公式也背了，可一到应用题还是先发懵。
- 解释：这背后不是孩子不用功，而是他没有看懂题目里的数量关系。

### 每一段都要承接
每段必须回答上一段留下的问题，或制造下一段必须解决的新问题。
产品卖点必须回答前文已经出现的问题，不能突然从痛点跳到"课程很好"。

### 产品卖点写法
卖点不要平铺，要跟当条脚本主题绑定。
一个卖点最好承担一个明确任务：解决痛点 / 证明方法 / 降低疑虑 / 推动转化。
不要为了"显得课程丰富"把所有卖点都塞进去。

### 案例和演示比空讲更有用
中段最好有一个小演示，让家长/学员看见方法差异。
演示要服务一个观点，不要变成完整授课。

### 老师背书怎么放
顺序：先抛问题 → 再给观点 → 用户产生兴趣后 → 集中出现一次老师背书 → 后文用教学判断体现专业度。

### 语言要像人说话
多用短句；多用设问和自问自答；抽象概念出现后立刻翻译成人话；
少用"体系化""赋能""闭环"等广告词；允许有情绪，但最后要给路径。

### 教育类合规底线（必须遵守）
避免：保证提分、逆袭、包过、保录、最高级表达、唯一、最强、官方指定、
未经证实的满意率/通过率、虚假成绩对比、过度制造焦虑。
更稳的表达：帮助孩子看清薄弱点；提供学习路径建议；适合想先诊断再规划的家庭；
可以先体验再判断是否适合；具体学习效果因人而异。

### 教育类万能框架
开头钩子（反常识/热点/具体场景/老师人格）→ 痛点展开（看见真实卡点）→
问题命名（不是孩子笨，是方法/路径/反馈机制出了问题）→ 方法演示（看见差异）→
课程承接（卖点只回答前文问题）→ 收尾转化（筛选目标家长，给低门槛行动）。
"""

    prompt = f"""你是一位顶级的混剪脚本编剧和短视频内容策划专家，精通爆款短视频脚本创作技巧。
请根据以下视频内容分析报告，创作一份高质量的混剪脚本。

## 视频内容分析报告
{analysis}

## 用户创作需求
- 脚本主题/方向：{topic or "根据原视频内容提炼并创新"}
- 剪辑风格：{style or "参考原视频风格并优化"}
- 目标时长：{duration}
- 画面方向：{orientation}
- 额外要求：{extra or "无"}
{education_module}

## 爆款脚本创作方法论（必须遵循）

### 一、黄金3秒开头钩子（最重要！）
第一个镜头必须是"钩子"，用以下5种公式之一设计开头：
1. **时间+结果法**（制造极致落差）：用了【时间】，我做到了【具体结果】
   - 例："3个月，从负债10万到月入5万"
2. **痛点共鸣法**（让他觉得"这说的就是我"）：你是不是也【具体痛点场景】
   - 例："你是不是也每天忙得要死，却什么都没干？"
3. **反常识颠覆法**（让他忍不住"哎？"一下）：你以为【常识】，其实【真相】
   - 例："你以为存钱是靠省，其实靠赚"
4. **极简对比法**（制造强烈的获得感）：我只做了【极简动作】，但结果【出乎意料】
   - 例："我只改了简历的一句话，面试通过率翻了3倍"
5. **情绪掏心法**（先共情，再给方法）：如果你也【某种经历】，请一定看完
   - 例："如果你现在也很迷茫，请一定看完"

### 二、PAS痛点营销结构（广告痛点抓取）
脚本整体结构采用 PAS（Problem-Agitation-Solution）框架：
- **P（痛点）**：开头3秒直击用户痛点，用具体场景而非抽象描述
- **A（放大焦虑）**：用2-3个镜头放大痛点带来的后果，制造紧迫感
- **S（解决方案）**：切入核心内容/产品，展示解决后的美好画面
如果是非广告类内容，采用 SCQA 结构（情境-冲突-疑问-解答）

### 三、情绪过山车设计
- 每3-5个镜头制造一次情绪转折（从低落到高昂，或从紧张到释放）
- 在视频30%-40%处设置"小高潮"（ surprising moment）
- 在70%-80%处设置"大高潮"（emotional peak）
- 结尾设置"金句收尾"或"行动号召"（CTA）

### 四、分镜节奏控制
- 开头钩子镜头：1-2秒（快节奏，强冲击）
- 痛点放大镜头：2-3秒（中节奏，情绪递进）
- 解决方案镜头：3-5秒（慢节奏，细节展示）
- 高潮镜头：1-3秒（快剪，节奏密集）
- 金句收尾镜头：3-5秒（慢节奏，留白回味）

### 五、字幕/台词写作技巧
- 使用短句，每句不超过15个字
- 多用疑问句和感叹句，少用陈述句
- 善用数字制造具体感（"3个方法"比"几个方法"更吸引人）
- 植入"社交货币"——让观众觉得"转发这个视频显得我很懂"
- 避免极限词（"最"、"绝对"、"100%"等广告法禁用语）

### 六、画面参考写作要求
- 必须具体可执行，能直接指导拍摄或剪辑
- 包含景别（特写/近景/中景/远景）
- 包含运镜方式（固定/推拉/摇移/跟拍）
- 包含画面主体动作和情绪状态
- 参考原视频素材但要有创新角度

## 脚本格式要求
请严格按照以下混剪脚本模板格式输出，包含表头信息和分镜表格：

1. 脚本标题（要有吸引力，包含数字或痛点关键词）
2. 时长：{duration}
3. 横/竖板：{orientation}
4. 剪辑风格参考：（简要描述参考风格）
5. 开头钩子类型：（注明使用了哪种钩子公式）
6. 脚本结构：（注明PAS或SCQA及各阶段对应的镜号范围）

分镜表格列说明：
- 镜号：镜头编号（1, 2, 3...）
- 后期：后期处理说明（如调色、特效、转场、速度变化、BGM节奏等）
- 画面参考：画面内容描述（含景别、运镜、主体动作、情绪状态，具体可执行）
- 字幕/台词：该镜头的字幕或旁白内容（短句、有感染力、符合钩子策略）
- 备注：补充说明（音乐节奏、情绪提示、结构阶段标注如"【钩子】""【痛点放大】""【解决方案】""【高潮】""【CTA】"等）

## 输出要求
请输出 JSON 格式（不要包含 markdown 代码块标记），结构如下：
{{
  "title": "脚本标题（含数字或痛点关键词）",
  "duration": "{duration}",
  "orientation": "{orientation}",
  "style_reference": "剪辑风格参考描述",
  "hook_type": "开头钩子类型（如：痛点共鸣法）",
  "script_structure": "脚本结构说明（如：PAS结构，镜1-2为痛点，镜3-5为放大焦虑，镜6-10为解决方案，镜11为CTA）",
  "rows": [
    {{
      "shot_number": "1",
      "post_production": "后期处理说明（含BGM、调色、转场、速度等）",
      "visual_reference": "画面参考描述（含景别、运镜、主体动作、情绪）",
      "subtitle_dialogue": "字幕/台词（短句、有感染力）",
      "notes": "备注（含结构阶段标注、情绪提示）"
    }}
  ]
}}

注意：
- 第一个镜头必须是黄金3秒钩子，使用上述5种公式之一
- 分镜数量根据时长合理安排，通常每个镜头 1-8 秒（开头快、中间慢、高潮快）
- 画面参考要具体、可执行，包含景别和运镜方式
- 字幕/台词要有感染力，短句为主，每句不超过15字
- 后期处理要明确具体（如"暖色调调色"、"0.5倍速慢放"、"闪白转场"、"BGM渐强"等）
- 备注中必须标注该镜头属于哪个结构阶段（如【钩子】【痛点放大】【解决方案】【高潮】【CTA】）
- 确保脚本整体有起承转合，情绪有起伏，节奏感强
- 如果是广告/带货类脚本，必须抓住目标用户的核心痛点"""

    messages = [
        {
            "role": "system",
            "content": (
                "你是一位顶级的混剪脚本编剧和短视频内容策划专家，精通爆款短视频脚本创作技巧。"
                "你深谙黄金3秒钩子理论、PAS痛点营销结构、SCQA叙事框架、情绪过山车设计等方法论。"
                "你擅长根据视频素材创作有创意、可执行、高转化率的混剪脚本。"
                "你必须只输出有效的 JSON。"
            ),
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
