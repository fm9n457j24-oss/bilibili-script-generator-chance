# -*- coding: utf-8 -*-
"""全局配置文件 —— 通过环境变量或 config.json 覆盖默认值

部署模式说明：
  - 本地开发：通过网页「设置」页面配置，保存到 config.json
  - 云端部署：通过环境变量配置（Docker / 云平台），终端用户无需配置
  - 当 AI_API_KEY 通过环境变量设置时，自动进入「预配置模式」，
    终端用户无需（且无法）修改 API 配置。
"""

import os
import json

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ------------------------------------------------------------------ #
#  尝试读取 config.json（用户可在网页端设置后自动生成）
# ------------------------------------------------------------------ #
_config_json = {}
_config_path = os.path.join(_BASE_DIR, "config.json")
if os.path.exists(_config_path):
    try:
        with open(_config_path, "r", encoding="utf-8") as f:
            _config_json = json.load(f)
    except Exception:
        _config_json = {}


def _get(key, default=""):
    """优先级: 环境变量 > config.json > 默认值

    环境变量优先级最高，确保 Docker/云部署时环境变量配置不被 config.json 覆盖。
    """
    env_val = os.environ.get(key.upper(), None)
    if env_val is not None and env_val != "":
        return env_val
    if key in _config_json:
        return _config_json[key]
    return default


class Config:
    # ======================== AI 接口配置 ========================
    # 支持 OpenAI 兼容接口（OpenAI / DeepSeek / 通义千问 / Moonshot 等）
    AI_API_KEY = _get("ai_api_key", "")
    AI_BASE_URL = _get("ai_base_url", "https://api.openai.com/v1")
    AI_MODEL = _get("ai_model", "gpt-4o")
    # 视觉分析使用的模型（需支持图片输入），留空则与 AI_MODEL 相同
    AI_VISION_MODEL = _get("ai_vision_model", "")

    # ======================== B站配置 ========================
    # 可选：填入登录后的 SESSDATA cookie 值，可下载更高清晰度
    BILI_SESSDATA = _get("bili_sessdata", "")

    # ======================== 服务器配置 ========================
    HOST = _get("host", "0.0.0.0")
    PORT = int(_get("port", 5000))

    # ======================== 管理员配置 ========================
    # 设置后，访问设置页面需要输入密码，防止终端用户修改配置
    ADMIN_PASSWORD = _get("admin_password", "")

    # ======================== 处理参数 ========================
    FRAME_INTERVAL = 0.5          # 截帧间隔（秒）
    MAX_FRAMES_FOR_VISION = 24    # 发送给视觉模型的最大帧数
    FRAME_QUALITY = 32            # 下载清晰度 80=1080P 64=720P 32=480P 16=360P

    # ======================== 目录 ========================
    BASE_DIR = _BASE_DIR
    TEMP_DIR = os.path.join(_BASE_DIR, "temp")
    OUTPUT_DIR = os.path.join(_BASE_DIR, "outputs")

    # JSON key → 类属性名 映射
    _KEY_MAP = {
        "ai_api_key": "AI_API_KEY",
        "ai_base_url": "AI_BASE_URL",
        "ai_model": "AI_MODEL",
        "ai_vision_model": "AI_VISION_MODEL",
        "bili_sessdata": "BILI_SESSDATA",
        "host": "HOST",
        "port": "PORT",
        "admin_password": "ADMIN_PASSWORD",
    }

    @classmethod
    def is_preconfigured(cls):
        """是否为预配置模式（API Key 通过环境变量设置）。
        此模式下终端用户无需配置，设置页面自动隐藏。
        """
        return bool(os.environ.get("AI_API_KEY"))

    @classmethod
    def save(cls, **kwargs):
        """将配置写入 config.json 并刷新内存中的类属性。
        预配置模式下不允许修改 AI 相关配置。
        """
        if cls.is_preconfigured():
            # 预配置模式下，过滤掉 AI 相关的配置项
            protected = {"ai_api_key", "ai_base_url", "ai_model", "ai_vision_model"}
            kwargs = {k: v for k, v in kwargs.items() if k not in protected}

        if kwargs:
            _config_json.update(kwargs)
            with open(_config_path, "w", encoding="utf-8") as f:
                json.dump(_config_json, f, ensure_ascii=False, indent=2)
            # 刷新内存：将 JSON 小写 key 映射到类的大写属性名
            for k, v in kwargs.items():
                attr_name = cls._KEY_MAP.get(k, k.upper())
                setattr(cls, attr_name, v)

    @classmethod
    def to_dict(cls):
        return {
            "ai_api_key": cls.AI_API_KEY[:8] + "***" if len(cls.AI_API_KEY) > 8 else ("***" if cls.AI_API_KEY else ""),
            "ai_base_url": cls.AI_BASE_URL,
            "ai_model": cls.AI_MODEL,
            "ai_vision_model": cls.AI_VISION_MODEL,
            "bili_sessdata": "***" if cls.BILI_SESSDATA else "",
            "host": cls.HOST,
            "port": cls.PORT,
            "configured": bool(cls.AI_API_KEY),
            "preconfigured": cls.is_preconfigured(),
            "has_admin_password": bool(cls.ADMIN_PASSWORD),
        }

    @classmethod
    def ensure_dirs(cls):
        os.makedirs(cls.TEMP_DIR, exist_ok=True)
        os.makedirs(cls.OUTPUT_DIR, exist_ok=True)
