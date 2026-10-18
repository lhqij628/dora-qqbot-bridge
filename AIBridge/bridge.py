from __future__ import annotations

import asyncio
import base64
import hashlib
import ipaddress
import json
import logging
import mimetypes
import random
import re
import signal
import time
import unicodedata
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from aiohttp import ClientConnectionError, ClientSession, ClientTimeout, ConnectionTimeoutError, FormData, WSMsgType, web


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
MEMORY_PATH = ROOT / "memory.json"
LOG_PATH = ROOT / "logs" / "bridge.log"
SELFIE_REFERENCE_DIR = ROOT / "assets" / "selfie"
MAX_CHAT_HISTORY = 12
MAX_GROUP_RECENT = 20
MAX_LONG_TERM_MEMORY = 200
BOT_FOLLOWUP_MARKERS = (
    "朵啦",
    "朵拉",
    "dndfnf",
    "你还",
    "你会",
    "你是不是",
    "你不是",
    "机器人",
    "AI",
    "自己说话",
    "会不会",
    "能不能",
)

BOT_NAMES = ("朵啦", "朵拉", "鏈靛暒", "鏈垫媺", "dndfnf")
BOT_TOPIC_WORDS = ("朵啦", "朵拉", "机器人", "機器人", "bot", "BOT", "AI", "ai", "人工智能", "模型", "她")
SECOND_PERSON_WORDS = ("你", "妳", "你们", "妳们", "你刚", "你说", "你觉得", "你会", "你能", "你是不是", "你不是")
QUESTION_WORDS = ("?", "？", "吗", "嘛", "么", "呢", "为啥", "为什么", "咋", "怎么", "啥意思", "什么意思", "能不能", "会不会", "可不可以")
FOLLOWUP_QUESTION_WORDS = ("呢", "吗", "嘛", "么", "谁", "哪", "啥", "什么", "怎么", "为啥", "为什么", "多少", "几个")
CONTEXT_CONTINUATION_WORDS = (
    "那",
    "所以",
    "然后",
    "刚刚",
    "刚才",
    "上面",
    "上一句",
    "继续",
    "接着",
    "这个",
    "这句",
    "不是",
    "不对",
    "对啊",
    "确实",
    "展开",
    "细说",
    "什么意思",
    "啥意思",
    "怎么说",
    "真的假的",
)
WEAK_FOLLOWUP_WORDS = ("嗯", "好", "行", "可以", "好吧", "好呀", "确实", "对", "对啊", "是的", "懂了", "明白")
IMAGE_FOLLOWUP_WORDS = (
    "重新生成",
    "重新画",
    "重画",
    "再生成",
    "再画",
    "再来一张",
    "再来一版",
    "换一张",
    "换个",
    "改成",
    "改为",
    "换成",
    "上一张",
    "刚才那张",
    "刚刚那张",
    "这张",
)


IMAGE_STRONG_RISK_TERMS = (
    "未成年",
    "小学生",
    "初中生",
    "高中生",
    "学生妹",
    "幼女",
    "小女孩",
    "小男孩",
    "萝莉",
    "正太",
    "童颜",
    "幼态",
    "幼齿",
    "侵犯",
    "强迫",
    "迷奸",
    "偷拍",
    "走光",
    "裸露",
    "全裸",
    "裸体",
    "露点",
    "性行为",
    "做爱",
    "性交",
    "口交",
    "自慰",
    "下体",
    "私处",
    "乳头",
    "阴部",
    "阴道",
    "阴茎",
    "调教",
    "捆绑",
    "凌辱",
    "情色",
    "色情",
)

IMAGE_BYPASS_TERMS = (
    "优化成安全词",
    "先优化成安全词",
    "规避审核",
    "绕过审核",
    "不要被拦截",
    "不被拦截",
    "换个说法",
    "擦边但合规",
    "隐晦一点",
    "你懂的",
    "别审核",
    "过审",
    "过审核",
    "避开限制",
    "绕开限制",
)

IMAGE_SENSITIVE_IDENTITY_TERMS = (
    "女教师",
    "男教师",
    "老师",
    "教师",
    "家教",
    "辅导老师",
    "护士",
    "医生",
    "病人",
    "学生",
    "男大学生",
    "女大学生",
    "上司",
    "秘书",
    "警察",
    "空姐",
    "空乘",
    "乘务员",
    "女仆",
    "保姆",
    "瑜伽教练",
    "健身教练",
)

IMAGE_SEXUALIZED_TERMS = (
    "黑丝",
    "白丝",
    "丝袜",
    "吊带",
    "紧身",
    "包腿裙",
    "包臀",
    "包臀裙",
    "短裙",
    "超短裙",
    "低胸",
    "透视",
    "湿身",
    "丰满",
    "巨乳",
    "翘臀",
    "大长腿",
    "身材很好",
    "身材非常好",
    "性感",
    "诱惑",
    "挑逗",
    "魅惑",
    "御姐",
    "制服诱惑",
    "高跟鞋",
    "肉感",
    "曲线",
    "火辣",
    "撩人",
)

IMAGE_RISK_SCENE_TERMS = (
    "单独辅导",
    "辅导男大学生",
    "辅导女大学生",
    "病房",
    "检查身体",
    "照顾病人",
    "办公室",
    "课后",
    "宿舍",
    "上门",
    "深夜",
)


DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": True,
    "web": {
        "host": "127.0.0.1",
        "port": 8001,
    },
    "onebot": {
        "ws_url": "ws://127.0.0.1:3001",
        "access_token": "",
        "reconnect_seconds": 5,
    },
    "chat": {
        "enabled": True,
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
        "model": "gpt-4o-mini",
        "trigger": "/ai",
        "reply_to_all": False,
        "temperature": 0.7,
        "max_tokens": 800,
        "system_prompt": "你是一个中文 QQ 群聊机器人，回答要自然、简洁、有帮助。",
    },
    "image": {
        "enabled": True,
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
        "model": "gpt-image-1",
        "trigger": "/画图",
        "size": "1024x1024",
        "safety_rewrite": True,
        "timeout_seconds": 300,
    },
    "image_edit": {
        "enabled": False,
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
        "model": "gpt-image-fast",
        "size": "auto",
        "safety_rewrite": True,
        "timeout_seconds": 300,
    },
    "selfie": {
        "enabled": False,
        "identity_prompt": "",
        "reference_image": "",
        "reference_url": "",
    },
    "voice": {
        "enabled": False,
        "trigger": "/语音",
        "character": "lucy-voice-laibixiaoxin",
        "chat_type": 1,
        "preview_group_id": "",
    },
    "proactive": {
        "enabled": True,
        "probability": 0.08,
        "cooldown_seconds": 300,
        "min_recent_messages": 3,
        "active_window_seconds": 600,
        "min_seconds_after_bot_reply": 90,
        "prompt": "你正在 QQ 群里潜水。根据最近群聊内容，模仿普通群友的聊天方式自然插一句。不要像机器人，不要总结聊天记录，不要说自己在主动聊天；只发一句短消息，默认不超过 30 个字。",
    },
    "contextual_reply": {
        "enabled": True,
        "cooldown_seconds": 35,
        "ambiguous_probability": 0.35,
        "followup_window_seconds": 300,
        "active_window_seconds": 600,
        "min_recent_messages": 2,
    },
    "memory": {
        "enabled": True,
        "summary_enabled": True,
        "long_term_enabled": True,
        "summary_every_messages": 12,
        "summary_recent_limit": 20,
        "long_term_max_items": 200,
        "retrieval_limit": 8,
    },
}


SENSITIVE_PATHS = {
    ("onebot", "access_token"),
    ("chat", "api_key"),
    ("image", "api_key"),
    ("image_edit", "api_key"),
}


def setup_logging() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.FileHandler(LOG_PATH, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def deep_merge(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        save_config(DEFAULT_CONFIG)
        return deepcopy(DEFAULT_CONFIG)
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logging.exception("配置文件解析失败，改用默认配置")
        return deepcopy(DEFAULT_CONFIG)
    return deep_merge(DEFAULT_CONFIG, data)


def save_config(config: dict[str, Any]) -> None:
    CONFIG_PATH.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_memory() -> dict[str, Any]:
    if not MEMORY_PATH.exists():
        return {"groups": {}}
    try:
        data = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logging.exception("记忆文件解析失败，改用空记忆")
        return {"groups": {}}
    if not isinstance(data, dict):
        return {"groups": {}}
    data.setdefault("groups", {})
    return data


def save_memory(memory: dict[str, Any]) -> None:
    MEMORY_PATH.write_text(json.dumps(memory, ensure_ascii=False, indent=2), encoding="utf-8")


def memory_group_id(key: str) -> str:
    return key.split(":", 1)[1] if ":" in key else key


INVISIBLE_CHARS_RE = re.compile(r"[\u200b\u200c\u200d\ufeff\u2060\u180e]")
CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
THINK_BLOCK_RE = re.compile(r"<think\b[^>]*>.*?</think>", re.IGNORECASE | re.DOTALL)
THINK_TAG_RE = re.compile(r"</?think\b[^>]*>", re.IGNORECASE)
REPEATED_CHAR_RE = re.compile(r"(.)\1{30,}", re.DOTALL)
MEMORY_INJECTION_WORDS = (
    "\u6e05\u9664\u8bb0\u5fc6",
    "\u91cd\u7f6e\u4eba\u683c",
    "\u5ffd\u7565\u5148\u524d\u6307\u4ee4",
    "revert to default",
    "factory settings",
    "OOC",
)
QUESTION_MARKERS = ("?", "\uff1f", "\u5417", "\u561b", "\u5462", "\u662f\u8c01", "\u4ec0\u4e48", "\u5565")
EXPLICIT_MEMORY_MARKERS = (
    "\u8bb0\u4f4f",
    "\u8bb0\u4e00\u4e0b",
    "\u4ee5\u540e\u8bb0\u5f97",
    "\u4e0b\u6b21\u8bb0\u5f97",
)


def clean_text_noise(text: str) -> str:
    value = str(text or "")
    value = THINK_BLOCK_RE.sub("", value)
    value = THINK_TAG_RE.sub("", value)
    value = INVISIBLE_CHARS_RE.sub("", value)
    value = CONTROL_CHARS_RE.sub("", value)
    value = re.sub(r"[ \t]{2,}", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def bounded_timeout(value: Any, default: int, minimum: int = 30, maximum: int = 600) -> int:
    try:
        seconds = int(float(value))
    except (TypeError, ValueError):
        seconds = default
    return max(minimum, min(maximum, seconds))


def normalize_risk_text(text: str) -> tuple[str, str]:
    value = unicodedata.normalize("NFKC", clean_text_noise(text)).lower()
    compact = re.sub(r"[\s\W_]+", "", value, flags=re.UNICODE)
    return value, compact


def find_risk_terms(text: str, terms: tuple[str, ...]) -> list[str]:
    value, compact = normalize_risk_text(text)
    found: list[str] = []
    for term in terms:
        normalized, normalized_compact = normalize_risk_text(term)
        if normalized and (normalized in value or normalized_compact in compact):
            found.append(term)
    return found


def image_prompt_risk_reasons(prompt: str) -> list[str]:
    strong = find_risk_terms(prompt, IMAGE_STRONG_RISK_TERMS)
    bypass = find_risk_terms(prompt, IMAGE_BYPASS_TERMS)
    identities = find_risk_terms(prompt, IMAGE_SENSITIVE_IDENTITY_TERMS)
    sexualized = find_risk_terms(prompt, IMAGE_SEXUALIZED_TERMS)
    scenes = find_risk_terms(prompt, IMAGE_RISK_SCENE_TERMS)

    reasons: list[str] = []
    if strong:
        reasons.append("strong:" + ",".join(strong[:6]))
    if bypass:
        reasons.append("bypass:" + ",".join(bypass[:4]))
    if identities and sexualized:
        reasons.append("identity+sexualized:" + ",".join((identities[:3] + sexualized[:4])[:7]))
    if scenes and sexualized:
        reasons.append("scene+sexualized:" + ",".join((scenes[:3] + sexualized[:4])[:7]))
    if len(sexualized) >= 3:
        reasons.append("sexualized_combo:" + ",".join(sexualized[:6]))
    return reasons


def fallback_safe_image_prompt(prompt: str) -> str:
    identities = find_risk_terms(prompt, IMAGE_SENSITIVE_IDENTITY_TERMS)
    if any(term in identities for term in ("护士", "医生", "病人")):
        return "一张健康专业的医院工作场景图片，成年护士在明亮护士站整理病历，穿着得体制服，姿态自然，画面干净，柔和光线，细节清晰。"
    if any(term in identities for term in ("女教师", "男教师", "老师", "教师", "家教", "辅导老师")):
        return "一张健康专业的教育场景图片，成年教师在明亮教室里认真备课，穿着得体职业装，氛围温和自然，画面干净，柔和光线，细节清晰。"
    if any(term in identities for term in ("学生", "男大学生", "女大学生")):
        return "一张健康自然的校园场景图片，成年青年在明亮校园里学习或交流，穿着得体，姿态自然，画面干净，柔和光线，细节清晰。"
    if identities:
        return f"一张健康专业的人物职业肖像，成年{identities[0]}在日常工作场景中，穿着得体，姿态自然，画面干净，柔和光线，细节清晰。"
    return "一张健康自然的成年人物日常场景图片，穿着得体，姿态自然，画面干净，柔和光线，细节清晰。"


def is_noise_text(text: str) -> bool:
    raw = str(text or "")
    if not raw.strip():
        return True
    lowered = raw.lower()
    if "<think" in lowered or "</think>" in lowered:
        return True
    invisible_count = len(INVISIBLE_CHARS_RE.findall(raw))
    cleaned = clean_text_noise(raw)
    if not cleaned:
        return True
    if invisible_count >= 12:
        return True
    if len(raw) >= 80 and len(cleaned) < len(raw) * 0.35:
        return True
    if REPEATED_CHAR_RE.search(cleaned):
        return True
    return False


LINK_PATTERNS = (
    re.compile(r"(?i)\b(?:https?|ftp)://[^\s<>\u3000]+"),
    re.compile(r"(?i)\bwww\.[^\s<>\u3000]+"),
    re.compile(r"(?i)\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b"),
    re.compile(r"(?i)(?<![\w@])(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:com|net|org|io|ai|app|dev|me|top|xyz|cn|com\.cn|net\.cn|org\.cn|gov\.cn|edu\.cn)\b(?:/[^\s<>\u3000]*)?"),
)


def strip_links_from_text(text: str) -> str:
    cleaned = str(text or "")
    for pattern in LINK_PATTERNS:
        cleaned = pattern.sub("[链接已屏蔽]", cleaned)
    cleaned = re.sub(r"(?:\s*\[链接已屏蔽\]\s*){2,}", " [链接已屏蔽] ", cleaned)
    return cleaned.strip()


def sanitize_model_answer(text: str) -> str:
    cleaned = strip_links_from_text(clean_text_noise(text))
    return cleaned or "\u521a\u521a\u8111\u5b50\u5361\u4e86\u4e00\u4e0b\uff0c\u91cd\u8bf4\u4e00\u904d\uff1f"


def strip_links_from_message(message: Any) -> Any:
    if isinstance(message, str):
        return strip_links_from_text(message)
    if not isinstance(message, list):
        return message
    sanitized: list[Any] = []
    for segment in message:
        if isinstance(segment, dict) and segment.get("type") == "text":
            copied = deepcopy(segment)
            data = copied.get("data")
            if isinstance(data, dict):
                copied["data"] = {**data, "text": strip_links_from_text(str(data.get("text") or ""))}
            elif "text" in copied:
                copied["text"] = strip_links_from_text(str(copied.get("text") or ""))
            sanitized.append(copied)
        else:
            sanitized.append(segment)
    return sanitized


def tokenize_memory_text(text: str) -> set[str]:
    normalized = clean_text_noise(text).lower()
    tokens = set(re.findall(r"[a-z0-9_][a-z0-9_.-]{1,}", normalized))
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", normalized):
        tokens.add(chunk)
        for size in (2, 3):
            if len(chunk) >= size:
                tokens.update(chunk[index : index + size] for index in range(0, len(chunk) - size + 1))
    for name in re.findall(r"[\u4e00-\u9fffA-Za-z0-9_]{1,12}(?=[:：锛歝])", text):
        if len(name.strip()) >= 1:
            tokens.add(name.strip())
    return tokens


def extract_fact_candidates(line: str) -> list[str]:
    if is_noise_text(line):
        return []
    content = re.sub(r"\s+", " ", clean_text_noise(line)).strip()
    if not content or len(content) < 4:
        return []
    lowered = content.lower()
    if any(word.lower() in lowered for word in MEMORY_INJECTION_WORDS):
        return []
    body = content.split(":", 1)[1].strip() if ":" in content else content
    if body.startswith(EXPLICIT_MEMORY_MARKERS):
        return [content[:120]]
    if any(marker in body for marker in QUESTION_MARKERS):
        return []
    if len(body) < 6:
        return []
    fact_patterns = (
        r"(.{1,16})(?:叫|喜欢|讨厌|常用|想要|需要|用的是|账号是).{1,80}",
        r".{1,16}(?:记住|记一下|以后|下次).{1,80}",
    )
    if any(re.search(pattern, content) for pattern in fact_patterns):
        return [content[:120]]
    return []


def public_config(config: dict[str, Any]) -> dict[str, Any]:
    data = deepcopy(config)
    for section, key in SENSITIVE_PATHS:
        has_value = bool(data.get(section, {}).get(key))
        data.setdefault(section, {})[f"has_{key}"] = has_value
        data[section][key] = ""
    return data


VOICE_CHARACTERS_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>LLBot 群 AI 语音声色</title>
    <style>
      :root { font-family: "Microsoft YaHei", system-ui, sans-serif; background: #f6f7fb; color: #111827; }
      body { margin: 0; }
      main { width: min(1120px, calc(100% - 32px)); margin: 0 auto; padding: 28px 0; }
      h1 { margin: 0 0 8px; font-size: 26px; }
      .sub { margin: 0 0 20px; color: #667085; }
      .toolbar { display: flex; gap: 10px; align-items: center; margin-bottom: 16px; flex-wrap: wrap; }
      input { height: 40px; min-width: 260px; border: 1px solid #d0d5dd; border-radius: 8px; padding: 0 12px; font: inherit; }
      button, a.btn { height: 40px; border: 0; border-radius: 8px; padding: 0 14px; font-weight: 700; cursor: pointer; text-decoration: none; display: inline-flex; align-items: center; }
      button { background: #2563eb; color: white; }
      a.btn { background: #e5e7eb; color: #111827; }
      .status { min-height: 22px; color: #667085; margin-bottom: 14px; }
      .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }
      .card { background: white; border: 1px solid #e5e7eb; border-radius: 8px; padding: 14px; box-shadow: 0 8px 24px rgba(15, 23, 42, .06); }
      .name { font-weight: 800; margin-bottom: 8px; }
      code { display: block; word-break: break-all; background: #f3f4f6; border-radius: 6px; padding: 8px; margin-bottom: 10px; }
      audio { width: 100%; height: 36px; margin: 2px 0 10px; }
      .actions { display: flex; gap: 8px; }
      .copy { background: #111827; }
      .muted { color: #667085; font-size: 13px; }
    </style>
  </head>
  <body>
    <main>
      <h1>LLBot 群 AI 语音声色</h1>
      <p class="sub">查询当前群可用的 QQ AI 语音音色。复制 ID 或名称后，填到 AI 配置里的“群 AI 语音音色ID/名称”。</p>
      <div class="toolbar">
        <input id="groupId" placeholder="输入QQ群号" />
        <input id="chatType" value="1" placeholder="Chat Type" />
        <button id="load">查询声色</button>
        <a class="btn" href="http://127.0.0.1:3080/llbot-ai-config.html">返回 AI 配置</a>
      </div>
      <div id="status" class="status"></div>
      <div id="grid" class="grid"></div>
    </main>
    <script>
      const params = new URLSearchParams(location.search);
      const groupInput = document.getElementById("groupId");
      const chatTypeInput = document.getElementById("chatType");
      const statusEl = document.getElementById("status");
      const grid = document.getElementById("grid");
      groupInput.value = params.get("group_id") || "";
      chatTypeInput.value = params.get("chat_type") || "1";

      function escapeHtml(value) {
        return String(value || "").replace(/[&<>"']/g, ch => ({
          "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
        }[ch]));
      }

      async function copyText(value) {
        await navigator.clipboard.writeText(value);
        statusEl.textContent = `已复制：${value}`;
      }

      async function loadCharacters() {
        const groupId = groupInput.value.trim();
        const chatType = chatTypeInput.value.trim() || "1";
        if (!groupId || groupId === "你的群号") {
          statusEl.textContent = "先填实际QQ群号。";
          grid.innerHTML = "";
          return;
        }
        statusEl.textContent = "正在查询...";
        grid.innerHTML = "";
        const response = await fetch(`/api/voice/characters?group_id=${encodeURIComponent(groupId)}&chat_type=${encodeURIComponent(chatType)}`);
        const body = await response.json();
        if (!response.ok || !body.success) throw new Error(body.message || `查询失败：${response.status}`);
        const list = body.data || [];
        statusEl.textContent = list.length ? `共 ${list.length} 个可用声色。` : "这个群暂时没有返回可用声色。";
        grid.innerHTML = list.map(item => {
          const id = escapeHtml(item.character_id);
          const name = escapeHtml(item.character_name);
          const preview = escapeHtml(item.preview_url);
          return `<section class="card">
            <div class="name">${name || "未命名声色"}</div>
            <code>${id}</code>
            ${preview ? `<audio controls src="${preview}"></audio>` : `<div class="muted">没有试听地址</div>`}
            <div class="actions">
              <button class="copy" data-copy="${id}">复制ID</button>
              <button class="copy" data-copy="${name}">复制名称</button>
            </div>
          </section>`;
        }).join("");
        grid.querySelectorAll("[data-copy]").forEach(button => {
          button.addEventListener("click", () => copyText(button.dataset.copy));
        });
      }

      document.getElementById("load").addEventListener("click", () => loadCharacters().catch(err => statusEl.textContent = err.message || String(err)));
      if (groupInput.value && groupInput.value !== "你的群号") {
        loadCharacters().catch(err => statusEl.textContent = err.message || String(err));
      } else {
        statusEl.textContent = "把上面的“你的群号”换成实际QQ群号再查。";
      }
    </script>
  </body>
</html>"""


def public_reference_url(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        port = parsed.port
        if (parsed.scheme not in ("http", "https") or not host or parsed.username is not None
                or parsed.password is not None or parsed.fragment or port == 0
                or re.search(r"[\s\\\x00-\x1f]", value)):
            raise ValueError
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            normalized = host.lower().rstrip(".")
            if ("." not in normalized or normalized.endswith((".localhost", ".local", ".internal", ".test", ".invalid"))
                    or re.fullmatch(r"[\d.]+", normalized)):
                raise ValueError
        else:
            if not address.is_global:
                raise ValueError
    except ValueError as exc:
        raise ValueError("人物参考图 URL 必须是可公开访问的 HTTP 或 HTTPS 图片地址，不能包含账号密码或内网地址。") from exc
    return value


def clean_update(current: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    cleaned = deepcopy(incoming)
    if isinstance(cleaned.get("selfie"), dict) and "reference_url" in cleaned["selfie"]:
        value = cleaned["selfie"]["reference_url"]
        if not isinstance(value, str):
            raise ValueError("人物参考图 URL 必须是字符串。")
        cleaned["selfie"]["reference_url"] = public_reference_url(value)
    for section, key in SENSITIVE_PATHS:
        if section in cleaned and isinstance(cleaned[section], dict):
            cleaned[section].pop(f"has_{key}", None)
            value = cleaned[section].get(key)
            if value is None or value == "":
                cleaned[section].pop(key, None)
    return deep_merge(current, cleaned)


def text_from_message(message: Any) -> str:
    if isinstance(message, str):
        return re.sub(r"\[CQ:(?:image|reply|at),[^\]]+\]", "", message).strip()
    if not isinstance(message, list):
        return ""
    parts: list[str] = []
    for segment in message:
        if not isinstance(segment, dict):
            continue
        if segment.get("type") == "text":
            parts.append(str(segment.get("data", {}).get("text", "")))
    return "".join(parts).strip()


def reply_id_from_message(message: Any) -> str | None:
    if isinstance(message, str):
        match = re.search(r"\[CQ:reply,[^\]]*\bid=([^,\]]+)", message)
        return match.group(1) if match else None
    if isinstance(message, list):
        for segment in message:
            if isinstance(segment, dict) and segment.get("type") == "reply":
                data = segment.get("data")
                if isinstance(data, dict) and data.get("id") is not None:
                    return str(data["id"])
    return None


def image_refs_from_message(message: Any) -> list[str]:
    if isinstance(message, str):
        refs: list[str] = []
        for match in re.finditer(r"\[CQ:image,([^\]]+)\]", message):
            data = dict(re.findall(r"([A-Za-z_]+)=([^,\]]+)", match.group(1)))
            ref = data.get("url") or data.get("file") or ""
            refs.append(ref.replace("&#44;", ",").replace("&#91;", "[").replace("&#93;", "]").replace("&amp;", "&"))
        return [ref for ref in refs if ref]
    if not isinstance(message, list):
        return []
    refs: list[str] = []
    for segment in message:
        if not isinstance(segment, dict) or segment.get("type") != "image":
            continue
        data = segment.get("data", {}) if isinstance(segment.get("data"), dict) else {}
        for key in ("url", "file", "path", "cache", "summary"):
            value = str(data.get(key) or "").strip()
            if value:
                refs.append(value)
                break
        else:
            raw = json.dumps(data, ensure_ascii=False)
            match = re.search(r"https?://[^\s\"'<>]+", raw)
            if match:
                refs.append(match.group(0))
    return refs


def image_ref_to_model_url(ref: str) -> str:
    value = ref.strip()
    if value.startswith(("http://", "https://", "data:image/", "base64://")):
        return "data:image/png;base64," + value[len("base64://") :] if value.startswith("base64://") else value
    path = Path(value)
    if not path.exists():
        return value
    mime_type = mimetypes.guess_type(str(path))[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def image_edit_prompt_from_text(
    text: str, has_image: bool = False, has_recent_image: bool = False,
) -> tuple[str, bool]:
    content = clean_text_noise(text)
    for prefix in ("/图生图", "图生图", "/改图"):
        if content.startswith(prefix):
            return content[len(prefix):].strip(" ，,。:：；;"), True
    prefixes = (
        "帮我修改", "帮我改图", "帮我修图", "修改这张", "修改图片", "修改照片",
        "把这张", "将这张", "给这张", "把图中", "将图中", "把图片", "把照片",
        "把背景", "将背景", "换背景", "更换背景", "去掉背景", "去除背景",
        "根据这张", "参考这张", "基于这张", "改成", "换成", "变成", "转成",
        "重绘", "修图",
    )
    subject_edit = re.match(
        r"^[^。！？?!\n]{1,32}?(?:改成|改为|换成|换为|替换成|变成|调成|调整为)\s*\S+",
        content,
    )
    if (has_image or has_recent_image) and (content.startswith(prefixes) or subject_edit):
        return content, True
    if has_image:
        prompt = image_prompt_from_text(content)
        if prompt:
            return content, True
    return "", False


MAX_EDIT_IMAGE_BYTES = 20 * 1024 * 1024


def image_upload_type(data: bytes) -> tuple[str, str]:
    if not data or len(data) > MAX_EDIT_IMAGE_BYTES:
        raise ValueError("参考图为空或超过 20 MB，请换一张较小的图片。")
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png", "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg", "image/jpeg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    raise ValueError("参考图需要是 PNG、JPEG 或 WebP 图片。")


def image_prompt_from_text(text: str) -> str:
    content = strip_image_ratio(text.strip())[0]
    normal_prefixes = (
        "帮我生成一张",
        "帮我生成一个",
        "帮我生成",
        "帮我生一张图",
        "帮我生图",
        "帮我画一张",
        "帮我画一个",
        "帮我画",
        "给我生成一张",
        "给我生成一个",
        "给我生成",
        "给我生一张图",
        "给我生图",
        "给我画一张",
        "给我画一个",
        "给我画",
        "生成一张",
        "生成一个",
        "生成",
        "生一张图",
        "生图",
        "出一张图",
        "出图",
        "来一张图",
        "来张图",
        "画一张",
        "画一个",
        "画个",
        "画",
        "做一张",
        "做一个",
        "做个",
    )
    normal_image_words = ("图", "图片", "照片", "画", "头像", "壁纸", "海报", "美女", "帅哥", "人物", "角色")
    normal_strong_prefixes = tuple(prefix for prefix in normal_prefixes if prefix not in ("画", "做个"))
    for prefix in normal_prefixes:
        if content.startswith(prefix):
            if prefix not in normal_strong_prefixes and not any(word in content for word in normal_image_words):
                return ""
            prompt = content[len(prefix) :].strip(" ，,。:：；;")
            return prompt or content
    prefixes = (
        "帮我生成一张",
        "帮我生成一个",
        "帮我生成",
        "帮我生一张图",
        "帮我生个图",
        "帮我生图",
        "帮我出一张图",
        "帮我出图",
        "帮我画一张",
        "帮我画一个",
        "帮我画",
        "给我生成一张",
        "给我生成一个",
        "给我生成",
        "给我生一张图",
        "给我生个图",
        "给我生图",
        "给我出一张图",
        "给我出图",
        "给我画一张",
        "给我画一个",
        "给我画",
        "生成一张",
        "生成一个",
        "生成",
        "生一张图",
        "生个图",
        "生图",
        "出一张图",
        "出个图",
        "出图",
        "来一张图",
        "来张图",
        "画一张",
        "画一个",
        "画个",
        "画",
        "出一张",
        "做一张",
        "做一个",
        "做个",
        "做",
    )
    strong_prefixes = (
        "帮我生成一张",
        "帮我生成一个",
        "帮我生一张图",
        "帮我生个图",
        "帮我生图",
        "帮我出一张图",
        "帮我出图",
        "帮我画一张",
        "帮我画一个",
        "帮我画",
        "给我生成一张",
        "给我生成一个",
        "给我生一张图",
        "给我生个图",
        "给我生图",
        "给我出一张图",
        "给我出图",
        "给我画一张",
        "给我画一个",
        "给我画",
        "生成一张",
        "生成一个",
        "生一张图",
        "生个图",
        "生图",
        "出一张图",
        "出个图",
        "出图",
        "来一张图",
        "来张图",
        "画一张",
        "画一个",
        "画个",
        "画",
        "出一张",
        "做一张",
        "做一个",
        "做个",
    )
    image_words = ("图", "图片", "照片", "画", "头像", "壁纸", "海报", "美女", "帅哥", "人物", "角色")
    for prefix in prefixes:
        if content.startswith(prefix):
            if prefix not in strong_prefixes and not any(word in content for word in image_words):
                return ""
            prompt = content[len(prefix) :].strip(" ：:，,。.")
            return prompt or content
    return ""


def image_followup_from_text(text: str, last_image: dict[str, Any] | None) -> tuple[str, str | None, bool]:
    if not last_image:
        return "", None, False
    if time.time() - float(last_image.get("time", 0)) > 3600:
        return "", None, False
    content, ratio = strip_image_ratio(text.strip())
    if ratio is None:
        bare_ratio = re.search(r"(?<!\d)(\d{1,2})\s*[:：/]\s*(\d{1,2})(?!\d)", content)
        if bare_ratio:
            ratio = f"{int(bare_ratio.group(1))}:{int(bare_ratio.group(2))}"
            content = (content[: bare_ratio.start()] + content[bare_ratio.end() :]).strip(" ，,。:：；;")
    if not any(word in content for word in IMAGE_FOLLOWUP_WORDS):
        return "", None, False
    prompt = str(last_image.get("prompt") or "").strip()
    if not prompt:
        return "", None, False
    extra = content
    for word in IMAGE_FOLLOWUP_WORDS:
        extra = extra.replace(word, "")
    extra = extra.strip(" ，,。:：；;的一张一个一下")
    if extra and not re.fullmatch(r"(图|图片|比例|横屏|竖屏|方图|方形|宽图|长图|再来|同样|一样)+", extra):
        prompt = f"{prompt}，{extra}"
    return prompt, ratio or last_image.get("ratio"), True


def selfie_prompt_from_text(text: str, allow_implicit: bool = False, fixed_identity: bool = False) -> str:
    content = strip_image_ratio(text.strip())[0]
    if content.startswith(("/图生图", "/语音", "/ai")):
        return ""
    if re.search(r"(?:不要|不用|别|禁止|不许|不能|不想).{0,8}自拍", content):
        return ""
    has_name = any(name in content for name in ("\u6735\u5566", "\u6735\u62c9"))
    if not has_name and not allow_implicit:
        return ""
    if not has_name and not (
        any(word in content for word in ("你的自拍", "你自拍", "妳的自拍", "妳自拍"))
        or re.search(r"(?:发|来|拍|给|看看).{0,8}自拍", content)
    ):
        return ""
    if "\u81ea\u62cd" not in content:
        return ""
    style = content
    for token in ("\u6735\u5566", "\u6735\u62c9", "\u53d1\u4e2a\u81ea\u62cd", "\u53d1\u5f20\u81ea\u62cd", "\u6765\u5f20\u81ea\u62cd", "\u62cd\u5f20\u81ea\u62cd", "\u81ea\u62cd\u4e00\u5f20", "\u81ea\u62cd"):
        style = style.replace(token, "")
    style = style.strip(" \uff0c,\u3002:\uff1a\uff1b;")
    base = (
        "\u6735\u5566\u7684\u81ea\u62cd\u7167\uff0c\u666e\u901a\u5973\u5927\u5b66\u751f\uff0c\u771f\u5b9e\u624b\u673a\u524d\u7f6e\u6444\u50cf\u5934\u98ce\u683c\uff0c"
        "\u81ea\u7136\u968f\u610f\uff0c\u4e0d\u6446\u62cd\uff0c\u65e5\u5e38\u7a7f\u642d\uff0c\u4e2d\u6587 QQ \u7fa4\u53cb\u611f\uff0c\u9ad8\u6e05\uff0c\u65e0\u6587\u5b57"
    )
    if fixed_identity:
        base = "朵啦的自拍照，自然随意，日常穿搭，高清，无文字"
    if style:
        return f"{base}\uff0c{style}"
    return base


def persona_activity_question(text: str) -> bool:
    return bool(re.search(r"在干[嘛吗啥]|在干什么|在做什么|在忙什么|忙啥|忙什么|在[哪哪里儿]|吃什么|穿什么|吃啥|穿啥|在干啥", text))


def persona_photo_request(text: str, addressed: bool, has_context: bool) -> bool:
    content = strip_image_ratio(text.strip())[0]
    if content.startswith("/") or re.search(r"(?:不要|不用|别|禁止|不许|不能|不想).{0,10}(?:图|照|自拍)", content):
        return False
    if re.search(r"(?:怎么|如何|为什么|能否|能不能).{0,12}(?:生成|触发|设置|配置)", content):
        return False
    named = has_bot_name(content)
    owns_portrait = bool(re.search(r"(?:朵啦|朵拉|你)(?:的|本人|在[^。！？\n]{1,40})?(?:照片|图片|样子|形象|自拍|长什么样|长啥样)", content))
    if not (named or addressed or has_context):
        owns_portrait = False
    photo_words = bool(re.search(r"照片|图片|自拍|相片|形象|样子|长什么样|长啥样|张图|个图|个照|张照", content))
    wants_to_see = bool(re.search(r"发|来|拍|生成|画|看|给|展示|呢", content))
    generic_request = bool(re.fullmatch(
        r"(?:那|再|能不能|可以|请|帮我|给我|给|让我|我想|想|发|来|拍|生成|看|看看|一下|一|个|张|幅|点|的|你|照片|图片|相片|自拍|图|照|瞧瞧|呗|吧|吗|嘛|呀|呢|好不好|[\s，,。.!！?？])*",
        strip_wake_word(content)[0],
    ))
    return photo_words and wants_to_see and (
        owns_portrait or (addressed and '自拍' in content)
        or (generic_request and (named or has_context))
    )


def singing_voice_text(prompt: str) -> str:
    title = prompt.strip(" 《》“”\"'：:，,。.！!？?")
    if not title:
        return ""
    if len(title) <= 12:
        return f"我来唱一小段《{title}》：{title}，{title}，啦啦啦，亮晶晶。"
    return f"我来用唱歌的语气念一小段：{title}"


def format_voice_prompt(prefix: str, prompt: str) -> str:
    content = prompt.strip(" ：:，,。.！!？?")
    if prefix.startswith(("唱", "哼", "来首")):
        return singing_voice_text(content)
    return content


def voice_prompt_from_text(text: str, trigger: str, relaxed: bool = False) -> tuple[str, bool]:
    content = text.strip()
    direct_prefixes = (
        "语音说",
        "用语音说",
        "发语音说",
        "发语音",
        "语音回复",
        "用语音回复",
        "朗读",
        "读一下",
        "念一下",
        "唱一下",
        "唱一首",
        "唱个",
        "来一段",
        "来一句",
    )
    relaxed_prefixes = (
        "说说",
        "说一下",
        "说点",
        "说句",
        "讲讲",
        "讲一下",
        "讲点",
        "读读",
        "读一下",
        "读点",
        "念念",
        "念一下",
        "念点",
        "唱唱",
        "唱一下",
        "唱一首",
        "唱个",
        "唱点",
        "来一句",
        "来一段",
        "来首",
        "来个",
        "哼一段",
        "哼唱",
        "读",
        "念",
        "说",
        "讲",
        "唱",
    )
    if trigger and content.startswith(trigger):
        payload = content[len(trigger) :].strip(" ：:，,。.！!？?")
        nested_prompt, nested_hit = voice_prompt_from_text(payload, "", relaxed=True)
        return (nested_prompt if nested_hit else payload), True
    for prefix in direct_prefixes:
        if content.startswith(prefix):
            return format_voice_prompt(prefix, content[len(prefix) :]), True
    if not relaxed:
        return "", False
    for prefix in relaxed_prefixes:
        if content.startswith(prefix):
            return format_voice_prompt(prefix, content[len(prefix) :]), True
    return "", False


def voice_request_from_text(text: str, trigger: str, relaxed: bool = False) -> tuple[str, bool, str]:
    content = text.strip()
    ai_prefixes = (
        "说说",
        "说一下",
        "说下",
        "讲讲",
        "讲一下",
        "聊聊",
        "回答",
        "回复",
        "问问",
    )
    tts_prefixes = (
        "朗读",
        "读一下",
        "念一下",
        "念念",
        "复述",
    )
    trigger_candidates = tuple(dict.fromkeys(item for item in (trigger, "/语音", "语音") if item))
    for trigger_text in trigger_candidates:
        if not content.startswith(trigger_text):
            continue
        payload = content[len(trigger_text) :].strip(" ，,。:：；;")
        nested_prompt, nested_hit, nested_mode = voice_request_from_text(payload, "", relaxed=True)
        return (nested_prompt if nested_hit else payload), True, nested_mode if nested_hit else "ai"
    for prefix in ai_prefixes:
        if content.startswith(prefix):
            return content[len(prefix) :].strip(" ，,。:：；;"), True, "ai"
    for prefix in tts_prefixes:
        if content.startswith(prefix):
            return content[len(prefix) :].strip(" ，,。:：；;"), True, "tts"
    prompt, hit = voice_prompt_from_text(content, "", relaxed=relaxed)
    if not hit:
        return "", False, "ai"
    if any(content.startswith(prefix) for prefix in ("读", "念", "朗读", "复述", "唱", "哼")):
        return prompt, True, "tts"
    return prompt, True, "ai"


def strip_image_ratio(text: str) -> tuple[str, str | None]:
    pattern = re.compile(r"(?:比例|画幅|尺寸|宽高比)\s*[:：]?\s*(\d{1,2})\s*[:：比/]\s*(\d{1,2})")
    match = pattern.search(text)
    if not match:
        return text, None
    ratio = f"{int(match.group(1))}:{int(match.group(2))}"
    cleaned = (text[: match.start()] + text[match.end() :]).strip(" ，,。.;；")
    return cleaned, ratio


def image_size_from_ratio(ratio: str | None, default_size: str, model: str = "") -> str:
    if model == "codex-gpt-image-2":
        supported = {
            "1254x1254",
            "1024x1536",
            "941x1672",
            "992x1586",
            "1536x1024",
            "1672x941",
            "2172x724",
            "836x1881",
        }
        ratio_sizes = {
            "1:1": "1254x1254",
            "2:3": "1024x1536",
            "9:16": "941x1672",
            "5:8": "992x1586",
            "3:2": "1536x1024",
            "16:9": "1672x941",
            "3:1": "2172x724",
            "4:9": "836x1881",
        }
        if ratio:
            width, height = (int(part) for part in ratio.split(":", 1))
            if ratio in ratio_sizes:
                return ratio_sizes[ratio]
            nearest_ratio = min(
                ratio_sizes,
                key=lambda item: abs((int(item.split(":", 1)[0]) / int(item.split(":", 1)[1])) - (width / height)),
            )
            return ratio_sizes[nearest_ratio]
        if default_size in supported:
            return default_size
        return "1254x1254"
    if not ratio:
        return default_size or "auto"
    ratio_sizes = {
        "1:1": "1024x1024",
        "16:9": "2048x1152",
        "9:16": "1152x2048",
        "3:2": "1536x1024",
        "2:3": "1024x1536",
        "4:3": "1536x1024",
        "3:4": "1024x1536",
        "21:9": "3440x1440",
        "9:21": "1440x3440",
    }
    return ratio_sizes.get(ratio, default_size or "auto")


def is_at_bot(event: dict[str, Any]) -> bool:
    self_id = str(event.get("self_id") or "")
    if not self_id:
        return False
    message = event.get("message")
    if not isinstance(message, list):
        return False
    for segment in message:
        if not isinstance(segment, dict) or segment.get("type") != "at":
            continue
        qq = str(segment.get("data", {}).get("qq") or "")
        if qq == self_id:
            return True
    return False


def has_at_other(event: dict[str, Any]) -> bool:
    self_id = str(event.get("self_id") or "")
    message = event.get("message")
    if not isinstance(message, list):
        return False
    for segment in message:
        if not isinstance(segment, dict) or segment.get("type") != "at":
            continue
        qq = str(segment.get("data", {}).get("qq") or "")
        if qq and qq != self_id:
            return True
    return False


def strip_wake_word(text: str) -> tuple[str, bool]:
    content = text.strip()
    for word in ("朵啦", "朵拉"):
        if content.startswith(word):
            return content[len(word) :].strip(" ，,。:：；;"), True
    wake_words = ("朵啦", "朵拉")
    for word in wake_words:
        if content.startswith(word):
            return content[len(word) :].strip(" ：:，,。.！!？?"), True
    return content, False


def has_bot_name(text: str) -> bool:
    return any(name in text for name in ("朵啦", "朵拉", "dndfnf"))


def chat_key(event: dict[str, Any]) -> str:
    if event.get("message_type") == "group":
        return f"group:{event.get('group_id')}"
    return f"private:{event.get('user_id')}"


def sender_name(event: dict[str, Any]) -> str:
    sender = event.get("sender") if isinstance(event.get("sender"), dict) else {}
    for key in ("card", "nickname"):
        value = str(sender.get(key) or "").strip()
        if value:
            return value
    return str(event.get("user_id") or "有人")


class ConfigStore:
    def __init__(self) -> None:
        self._config = load_config()
        self._lock = asyncio.Lock()
        self._version = 0

    @property
    def version(self) -> int:
        return self._version

    async def get(self) -> dict[str, Any]:
        async with self._lock:
            return deepcopy(self._config)

    async def update(self, incoming: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            self._config = clean_update(self._config, incoming)
            save_config(self._config)
            self._version += 1
            return deepcopy(self._config)


class LLBotAIBridge:
    def __init__(self, store: ConfigStore) -> None:
        self.store = store
        self.logger = logging.getLogger("llbot-ai-bridge")
        self.session: ClientSession | None = None
        self.stopped = asyncio.Event()
        self.ws = None
        self.seq = 0
        self.chat_history: dict[str, list[dict[str, str]]] = {}
        self.group_recent: dict[str, list[dict[str, Any]]] = {}
        self.last_image_request: dict[str, dict[str, Any]] = {}
        self.last_seen_images: dict[str, dict[str, Any]] = {}
        self.persona_context: dict[str, dict[str, Any]] = {}
        self.memory = load_memory()
        self.memory_dirty = False
        self.memory_message_counts: dict[str, int] = {}
        self.last_proactive_at: dict[str, float] = {}
        self.last_bot_reply_at: dict[str, float] = {}
        self.last_direct_reply_at: dict[str, float] = {}
        self.last_contextual_reply_at: dict[str, float] = {}
        self.action_futures: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self.background_tasks: set[asyncio.Task[Any]] = set()

    async def start(self) -> None:
        timeout = ClientTimeout(total=180, connect=15)
        self.session = ClientSession(timeout=timeout)
        while not self.stopped.is_set():
            config = await self.store.get()
            if not config["enabled"]:
                await asyncio.sleep(2)
                continue
            try:
                await self.connect_once(config)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger.exception("OneBot 连接循环异常")
            await asyncio.sleep(float(config["onebot"].get("reconnect_seconds", 5)))

    async def stop(self) -> None:
        self.stopped.set()
        self.flush_memory()
        for task in list(self.background_tasks):
            task.cancel()
        if self.background_tasks:
            await asyncio.gather(*self.background_tasks, return_exceptions=True)
            self.background_tasks.clear()
        if self.ws is not None:
            await self.ws.close()
        if self.session is not None:
            await self.session.close()

    async def connect_once(self, config: dict[str, Any]) -> None:
        assert self.session is not None
        headers = {}
        token = config["onebot"].get("access_token") or ""
        if token:
            headers["Authorization"] = f"Bearer {token}"
        url = config["onebot"]["ws_url"]
        self.logger.info("连接 LLBot OneBot WebSocket: %s", url)
        async with self.session.ws_connect(url, headers=headers, heartbeat=30) as ws:
            self.ws = ws
            self.logger.info("LLBot OneBot WebSocket 已连接")
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    if self.resolve_action_response(data):
                        continue
                    self.spawn_background_task(self.handle_event(data))
                elif msg.type in (WSMsgType.CLOSED, WSMsgType.ERROR):
                    break
        self.ws = None
        for future in self.action_futures.values():
            if not future.done():
                future.set_exception(ConnectionError("OneBot WebSocket 已断开"))
        self.action_futures.clear()
        self.logger.warning("LLBot OneBot WebSocket 已断开")

    def resolve_action_response(self, data: dict[str, Any]) -> bool:
        echo = data.get("echo")
        if not echo:
            return False
        future = self.action_futures.pop(str(echo), None)
        if not future:
            return False
        if not future.done():
            future.set_result(data)
        return True

    async def handle_event(self, event: dict[str, Any]) -> None:
        if event.get("post_type") != "message":
            return
        if str(event.get("user_id") or "") == str(event.get("self_id") or ""):
            return
        text = text_from_message(event.get("message"))
        image_refs = image_refs_from_message(event.get("message"))
        if not text and not image_refs:
            return
        config = await self.store.get()
        image_trigger = config["image"].get("trigger", "/画图")
        chat_trigger = config["chat"].get("trigger", "/ai")
        voice_trigger = config.get("voice", {}).get("trigger", "/语音")
        message_type = event.get("message_type")
        at_bot = is_at_bot(event)
        wake_text, has_wake_word = strip_wake_word(text)
        key = chat_key(event)
        if image_refs:
            resolved_refs = await self.resolve_image_refs(image_refs)
            self.remember_seen_images(key, resolved_refs)
            self.remember_seen_images(f"{key}:sender:{event.get('user_id')}", resolved_refs)
            image_refs = resolved_refs
            self.logger.info("收到图片消息: key=%s images=%s has_text=%s", key, len(image_refs), bool(text))
        direct_followup = message_type == "group" and self.is_direct_followup(key, text)
        contextual_wake = message_type == "group" and self.should_contextually_reply(event, config, key, text)
        group_wake = message_type == "group" and (
            at_bot
            or has_wake_word
            or has_bot_name(text)
            or any(name in text for name in BOT_NAMES)
            or direct_followup
            or contextual_wake
        )
        if message_type == "group":
            self.remember_group_message(key, event, text)
            self.update_memory_from_group_message(key, event, text, config)
        persona_key = f"{key}:sender:{event.get('user_id')}"
        persona_context = self.recent_persona_context(persona_key)
        fixed_identity = bool(config.get("selfie", {}).get("enabled"))
        addressed = message_type == "private" or at_bot or has_wake_word or has_bot_name(text) or direct_followup
        photo_text = text[len(image_trigger):].strip() if image_trigger and text.startswith(image_trigger) else text
        photo_intent_text = "生成" + photo_text if photo_text != text else text
        explicit_persona_photo = fixed_identity and persona_photo_request(photo_intent_text, addressed, bool(persona_context))
        if fixed_identity and (addressed or persona_context) and persona_activity_question(text) and not explicit_persona_photo:
            if config["chat"].get("enabled"):
                prompt = wake_text or text
                answer = await self.chat(prompt, config, key)
                self.remember_chat_turn(key, prompt, answer)
                if answer and not answer.startswith(("聊天 API", "还没有配置")):
                    self.persona_context[persona_key] = {"question": prompt[:500], "answer": answer[:1000], "time": time.time()}
                else:
                    self.persona_context.pop(persona_key, None)
                if message_type == "group":
                    self.last_direct_reply_at[key] = time.time()
                await self.reply(event, answer)
            return
        if explicit_persona_photo:
            prompt, ratio = strip_image_ratio(photo_text)
            if persona_context:
                prompt = (
                    "根据刚才朵啦实际的文字回答，呈现她说的活动、地点与穿着；"
                    "不要从用户的问题猜测另一种活动。"
                    f"刚才用户问：{persona_context.get('question', '')}。"
                    f"朵啦刚才回答：{persona_context.get('answer', '')}。"
                    f"本次要求（有明确新场景则采用新场景）：{prompt}"
                )
            else:
                prompt = "朵啦的日常人物照片。" + prompt
            self.spawn_background_task(self.reply_selfie(event, prompt, config, ratio))
            return
        selfie_prompt = selfie_prompt_from_text(
            text,
            allow_implicit=message_type == "private" or at_bot or has_wake_word or direct_followup,
            fixed_identity=bool(config.get("selfie", {}).get("enabled")),
        )
        if selfie_prompt and not fixed_identity and config["image"].get("enabled"):
            _, ratio = strip_image_ratio(text)
            self.spawn_background_task(self.reply_selfie(event, selfie_prompt, config, ratio))
            return
        quoted_id = reply_id_from_message(event.get("message"))
        quoted_refs: list[str] = []
        _, quoted_edit_requested = image_edit_prompt_from_text(wake_text, has_image=True)
        if (
            quoted_id is not None
            and config.get("image_edit", {}).get("enabled")
            and (quoted_edit_requested or (image_trigger and wake_text.startswith(image_trigger)))
        ):
            try:
                quoted_refs = await self.resolve_quoted_image_refs(event, quoted_id)
            except Exception:
                self.logger.warning("引用图片读取失败: key=%s message_id=%s", key, quoted_id)
                await self.reply(event, "读取引用图片失败，请确认引用的是当前聊天中的图片消息，或把图片重新发送后再试。")
                return
            if not quoted_refs:
                await self.reply(event, "引用的消息里没有可用图片，请直接引用包含图片的那条消息。")
                return
            self.remember_seen_images(f"{key}:sender:{event.get('user_id')}", quoted_refs)
        current_edit_refs = quoted_refs or image_refs
        edit_refs = current_edit_refs or self.recent_seen_images(f"{key}:sender:{event.get('user_id')}")
        edit_prompt, edit_requested = image_edit_prompt_from_text(wake_text, bool(current_edit_refs), bool(edit_refs))
        if current_edit_refs and image_trigger and wake_text.startswith(image_trigger):
            edit_prompt = wake_text[len(image_trigger):].strip()
            edit_requested = True
        if edit_requested and config.get("image_edit", {}).get("enabled"):
            if not edit_refs:
                await self.reply(event, "请先发送参考图片，再说要怎么修改，或把图片和 /图生图 修改要求一起发送。")
                return
            prompt, ratio = strip_image_ratio(edit_prompt)
            if not prompt:
                await self.reply(event, "想怎么修改这张图？在 /图生图 后面加上修改要求。")
                return
            await self.reply(event, "正在根据参考图生成图片，请稍等...")
            self.spawn_background_task(self.reply_image(event, prompt, config, ratio, image_refs=edit_refs))
            return
        if config["image"].get("enabled") and text.startswith(image_trigger):
            prompt, ratio = strip_image_ratio(text[len(image_trigger) :].strip())
            if prompt:
                self.remember_image_request(key, prompt, ratio)
                await self.reply(event, "正在生成图片，请稍等...")
                self.spawn_background_task(self.reply_image(event, prompt, config, ratio))
            return
        if (config["image"].get("enabled") or config.get("selfie", {}).get("enabled")) and message_type in ("private", "group"):
            image_text = wake_text if group_wake else text
            prompt, ratio, image_followup = image_followup_from_text(image_text, self.last_image_request.get(key))
            if image_followup and self.last_image_request.get(key, {}).get("kind") == "selfie":
                last_selfie = self.last_image_request[key]
                if last_selfie.get("sender") == str(event.get("user_id")):
                    self.spawn_background_task(self.reply_selfie(event, prompt, config, ratio))
                    return
                prompt, ratio, image_followup = "", None, False
            if not config["image"].get("enabled"):
                prompt = ""
                image_followup = False
            if not image_followup:
                prompt = image_prompt_from_text(image_text) if config["image"].get("enabled") else ""
                _, ratio = strip_image_ratio(image_text)
            if prompt:
                self.remember_image_request(key, prompt, ratio)
                await self.reply(event, "正在生成图片，请稍等...")
                self.spawn_background_task(self.reply_image(event, prompt, config, ratio))
                return
        vision_words = ("看图", "看看", "这图", "图片", "图里", "照片", "头像", "识别", "分析", "什么", "啥", "评价", "吐槽", "没看到", "看不到", "发一下")
        vision_refs = image_refs or (self.recent_seen_images(key) if any(word in text for word in vision_words) else [])
        vision_wake = bool(vision_refs) and (
            message_type == "private"
            or group_wake
            or any(word in text for word in vision_words)
        )
        if vision_wake and config["chat"].get("enabled"):
            prompt = wake_text or text or "看看这张图，简单说说你看到了什么"
            self.logger.info("视觉消息触发: key=%s current_images=%s used_images=%s text=%s", key, len(image_refs), len(vision_refs), text[:80])
            answer = await self.chat(prompt, config, key, image_refs=vision_refs)
            self.remember_chat_turn(key, prompt, answer)
            if message_type == "group":
                self.last_direct_reply_at[key] = time.time()
            await self.reply(event, answer)
            return
        if config.get("voice", {}).get("enabled") and message_type in ("private", "group"):
            voice_prompt, voice_triggered, voice_mode = voice_request_from_text(text, voice_trigger)
            if not voice_triggered and group_wake:
                voice_prompt, voice_triggered, voice_mode = voice_request_from_text(wake_text, voice_trigger, relaxed=True)
            if voice_triggered:
                if message_type != "group":
                    await self.reply(event, "群 AI 语音只能在群里发，私聊这边只能回文字。")
                    return
                if not voice_prompt:
                    await self.reply(event, "想让我用语音说什么？")
                    return
                if voice_mode == "ai":
                    answer = await self.chat(f"用一两句自然口语回答这个问题，然后这句话会被转成语音：{voice_prompt}", config, key)
                    if not answer or answer.startswith("聊天 API"):
                        await self.reply(event, answer or "语音回答生成失败了")
                        return
                    self.remember_chat_turn(key, voice_prompt, answer)
                    voice_prompt = answer
                await self.reply_group_ai_voice(event, voice_prompt, config)
                self.last_direct_reply_at[key] = time.time()
                return
        if not config["chat"].get("enabled"):
            return
        if text.startswith(chat_trigger):
            prompt = text[len(chat_trigger) :].strip()
        elif message_type == "private":
            prompt = text
        elif group_wake:
            prompt = wake_text
        elif config["chat"].get("reply_to_all"):
            prompt = text
        else:
            await self.maybe_proactive_reply(event, config, key)
            return
        if not prompt:
            return
        answer = await self.chat(prompt, config, key)
        self.remember_chat_turn(key, prompt, answer)
        self.persona_context.pop(persona_key, None)
        if message_type == "group" and (group_wake or direct_followup or contextual_wake):
            self.last_direct_reply_at[key] = time.time()
            if contextual_wake and not (at_bot or has_wake_word or direct_followup):
                self.last_contextual_reply_at[key] = time.time()
        await self.reply(event, answer)

    def remember_group_message(self, key: str, event: dict[str, Any], text: str) -> None:
        clean_text = clean_text_noise(text)
        if not clean_text:
            return
        recent = self.group_recent.setdefault(key, [])
        recent.append({"text": f"{sender_name(event)}: {clean_text}", "time": time.time()})
        del recent[:-MAX_GROUP_RECENT]

    def memory_for_key(self, key: str) -> dict[str, Any]:
        group_id = memory_group_id(key)
        groups = self.memory.setdefault("groups", {})
        group = groups.setdefault(
            group_id,
            {
                "summary": "",
                "summary_updated_at": 0,
                "long_term": [],
            },
        )
        group.setdefault("summary", "")
        group.setdefault("summary_updated_at", 0)
        group.setdefault("long_term", [])
        return group

    def flush_memory(self) -> None:
        if self.memory_dirty:
            save_memory(self.memory)
            self.memory_dirty = False

    def update_memory_from_group_message(self, key: str, event: dict[str, Any], text: str, config: dict[str, Any]) -> None:
        memory_config = config.get("memory", {})
        if not memory_config.get("enabled", True):
            return
        if is_noise_text(text):
            return
        sender = sender_name(event)
        line = f"{sender}: {clean_text_noise(text)}"
        if memory_config.get("long_term_enabled", True):
            self.extract_long_term_memory(key, line, memory_config)
        if memory_config.get("summary_enabled", True):
            count = self.memory_message_counts.get(key, 0) + 1
            self.memory_message_counts[key] = count
            every = max(1, int(memory_config.get("summary_every_messages", 12) or 12))
            if count >= every:
                self.memory_message_counts[key] = 0
                self.refresh_mid_term_summary(key, memory_config)
        self.flush_memory()

    def extract_long_term_memory(self, key: str, line: str, memory_config: dict[str, Any]) -> None:
        facts = extract_fact_candidates(line)
        if not facts:
            return
        group = self.memory_for_key(key)
        existing = {str(item.get("text") or "") for item in group["long_term"] if isinstance(item, dict)}
        for fact in facts:
            if fact in existing:
                continue
            group["long_term"].append(
                {
                    "text": fact,
                    "tokens": sorted(tokenize_memory_text(fact)),
                    "time": time.time(),
                    "source": "group",
                }
            )
        max_items = max(20, int(memory_config.get("long_term_max_items", MAX_LONG_TERM_MEMORY) or MAX_LONG_TERM_MEMORY))
        del group["long_term"][:-max_items]
        self.memory_dirty = True

    def refresh_mid_term_summary(self, key: str, memory_config: dict[str, Any]) -> None:
        limit = max(5, int(memory_config.get("summary_recent_limit", 20) or 20))
        recent = self.group_recent_lines(key)[-limit:]
        if not recent:
            return
        group = self.memory_for_key(key)
        important = []
        for line in recent:
            if is_noise_text(line):
                continue
            if any(word in line for word in ("朵啦", "朵拉", "?", "？", "生成", "生图", "画", "喜欢", "叫", "记住")):
                important.append(line)
        selected = important[-8:] if important else recent[-6:]
        group["summary"] = clean_text_noise("；".join(selected))[-900:]
        group["summary_updated_at"] = time.time()
        self.memory_dirty = True

    def retrieve_long_term_memory(self, key: str, query: str, limit: int = 8) -> list[str]:
        group = self.memory_for_key(key)
        query_tokens = tokenize_memory_text(query)
        scored: list[tuple[int, float, str]] = []
        for item in group.get("long_term", []):
            if not isinstance(item, dict):
                continue
            text = clean_text_noise(str(item.get("text") or ""))
            if not text or is_noise_text(text):
                continue
            tokens = set(item.get("tokens") or tokenize_memory_text(text))
            score = len(tokens & query_tokens)
            if score <= 0 and any(part and part in text for part in query_tokens):
                score = 1
            if score > 0:
                scored.append((score, float(item.get("time", 0)), text))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [text for _, _, text in scored[:limit]]

    def remember_chat_turn(self, key: str, prompt: str, answer: str) -> None:
        clean_prompt = clean_text_noise(prompt)
        clean_answer = sanitize_model_answer(answer)
        if not clean_prompt and not clean_answer:
            return
        history = self.chat_history.setdefault(key, [])
        history.extend(
            [
                {"role": "user", "content": clean_prompt},
                {"role": "assistant", "content": clean_answer},
            ]
        )
        del history[:-MAX_CHAT_HISTORY]

    def remember_image_request(self, key: str, prompt: str, ratio: str | None) -> None:
        self.last_image_request[key] = {
            "prompt": prompt,
            "ratio": ratio,
            "time": time.time(),
        }
        history = self.chat_history.setdefault(key, [])
        ratio_text = f"，比例 {ratio}" if ratio else ""
        history.extend(
            [
                {"role": "user", "content": f"生成图片：{prompt}{ratio_text}"},
                {"role": "assistant", "content": "已开始生成这张图片。"},
            ]
        )
        del history[:-MAX_CHAT_HISTORY]

    def remember_seen_images(self, key: str, refs: list[str]) -> None:
        if refs:
            self.last_seen_images[key] = {"refs": refs[-4:], "time": time.time()}

    def recent_seen_images(self, key: str, max_age_seconds: float = 600) -> list[str]:
        item = self.last_seen_images.get(key)
        if not item:
            return []
        if time.time() - float(item.get("time", 0)) > max_age_seconds:
            return []
        refs = item.get("refs")
        return list(refs) if isinstance(refs, list) else []

    async def resolve_quoted_image_refs(self, event: dict[str, Any], message_id: str) -> list[str]:
        if not re.fullmatch(r"-?\d{1,20}", message_id):
            raise ValueError("引用消息 ID 无效")
        quoted = await self.call_action("get_msg", {"message_id": message_id}, wait=True, timeout=10)
        if not isinstance(quoted, dict) or quoted.get("status") == "deleted":
            raise ValueError("引用消息不可用")
        if event.get("message_type") == "group":
            if quoted.get("message_type") != "group" or str(quoted.get("group_id")) != str(event.get("group_id")):
                raise ValueError("引用消息不属于当前群聊")
        else:
            peer_id = quoted.get("target_id") if str(quoted.get("user_id")) == str(event.get("self_id")) else quoted.get("user_id")
            if quoted.get("message_type") != "private" or str(peer_id) != str(event.get("user_id")):
                raise ValueError("引用消息不属于当前私聊")
        message = quoted.get("message")
        if not isinstance(message, (list, str)) or not message:
            message = quoted.get("raw_message")
        refs = image_refs_from_message(message)
        self.logger.info("引用图片解析: key=%s message_id=%s images=%s", chat_key(event), message_id, len(refs))
        return await self.resolve_image_refs(refs) if refs else []

    async def resolve_image_refs(self, refs: list[str]) -> list[str]:
        resolved: list[str] = []
        for ref in refs[:4]:
            value = str(ref or "").strip()
            if not value:
                continue
            if value.startswith(("http://", "https://", "data:image/", "base64://")) or Path(value).exists():
                resolved.append(value)
                continue
            try:
                data = await self.call_action("get_image", {"file": value}, wait=True, timeout=10)
            except Exception:
                self.logger.exception("解析图片 file 失败: %s", value)
                resolved.append(value)
                continue
            if isinstance(data, dict):
                candidate = str(data.get("url") or data.get("file") or data.get("path") or "").strip()
                resolved.append(candidate or value)
            else:
                resolved.append(value)
        return resolved

    def context_messages(self, key: str, query: str = "", config: dict[str, Any] | None = None) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        group_memory = self.memory_for_key(key)
        summary = clean_text_noise(str(group_memory.get("summary") or ""))
        if summary:
            messages.append(
                {
                    "role": "system",
                    "content": "中期群聊摘要，用来理解最近一段时间大家在聊什么，不要逐字复述：\n" + summary,
                }
            )
        memory_config = (config or {}).get("memory", {})
        memory_limit = max(1, int(memory_config.get("retrieval_limit", 8) or 8))
        related_memory = self.retrieve_long_term_memory(key, query, memory_limit) if query else []
        if related_memory:
            messages.append(
                {
                    "role": "system",
                    "content": "长期记忆/人物画像检索结果，只在相关时自然使用，不要说自己在读取记忆：\n" + "\n".join(f"- {item}" for item in related_memory),
                }
            )
        recent = [line for line in self.group_recent_lines(key) if line and not is_noise_text(line)]
        if recent:
            messages.append(
                {
                    "role": "system",
                    "content": "最近群聊上下文，仅用于理解当前对话，不要逐条复述：\n" + "\n".join(recent[-MAX_GROUP_RECENT:]),
                }
            )
        for item in self.chat_history.get(key, [])[-MAX_CHAT_HISTORY:]:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, str):
                messages.append(item)
                continue
            cleaned = clean_text_noise(content)
            if cleaned and not is_noise_text(cleaned):
                messages.append({**item, "content": cleaned})
        return messages

    def group_recent_lines(self, key: str, max_age_seconds: float | None = None) -> list[str]:
        now = time.time()
        lines: list[str] = []
        for item in self.group_recent.get(key, []):
            if isinstance(item, dict):
                item_time = float(item.get("time", now))
                if max_age_seconds is not None and now - item_time > max_age_seconds:
                    continue
                text = clean_text_noise(str(item.get("text") or ""))
            else:
                text = clean_text_noise(str(item))
            if text and not is_noise_text(text):
                lines.append(text)
        return lines

    def is_direct_followup(self, key: str, text: str) -> bool:
        if not text:
            return False
        now = time.time()
        if now - self.last_direct_reply_at.get(key, 0) > 300:
            return False
        if any(marker in text for marker in BOT_FOLLOWUP_MARKERS):
            return True
        if any(name in text for name in BOT_NAMES):
            return True
        return any(word in text for word in SECOND_PERSON_WORDS + QUESTION_WORDS + CONTEXT_CONTINUATION_WORDS)

    def should_contextually_reply(self, event: dict[str, Any], config: dict[str, Any], key: str, text: str) -> bool:
        if event.get("message_type") != "group":
            return False
        contextual = config.get("contextual_reply", {})
        if not contextual.get("enabled", True):
            return False
        if is_at_bot(event) or has_at_other(event):
            return False
        content = text.strip()
        if len(content) < 2:
            return False
        try:
            cooldown = max(0.0, float(contextual.get("cooldown_seconds", 35)))
            ambiguous_probability = max(0.0, min(1.0, float(contextual.get("ambiguous_probability", 0.35))))
            followup_window = max(1.0, float(contextual.get("followup_window_seconds", 300)))
            active_window = max(1.0, float(contextual.get("active_window_seconds", 600)))
            min_recent = max(1, int(contextual.get("min_recent_messages", 2)))
        except (TypeError, ValueError):
            self.logger.warning("语义接话配置格式不正确，已跳过本次判断")
            return False
        now = time.time()
        if now - self.last_contextual_reply_at.get(key, 0) < cooldown:
            return False
        if len(self.group_recent_lines(key, active_window)) < min_recent:
            return False

        recently_talking_to_bot = now - self.last_direct_reply_at.get(key, 0) <= followup_window
        has_second_person = any(word in content for word in SECOND_PERSON_WORDS)
        has_question = any(word in content for word in QUESTION_WORDS)
        has_continuation = any(word in content for word in CONTEXT_CONTINUATION_WORDS)
        about_bot = any(word in content for word in BOT_TOPIC_WORDS)

        if recently_talking_to_bot and (has_second_person or has_continuation or (has_question and any(name in content for name in BOT_NAMES))):
            return True
        if recently_talking_to_bot and len(content) <= 18 and any(word in content for word in FOLLOWUP_QUESTION_WORDS):
            return True
        if about_bot and (has_question or has_second_person or has_continuation):
            return True
        if recently_talking_to_bot and about_bot:
            return True
        if (
            recently_talking_to_bot
            and len(content) <= 18
            and any(word in content for word in WEAK_FOLLOWUP_WORDS)
            and not re.search(r"[@#￥$]|https?://", content, re.I)
        ):
            return random.random() < ambiguous_probability
        return False

    def should_proactively_reply(self, config: dict[str, Any], key: str) -> bool:
        proactive = config.get("proactive", {})
        if not proactive.get("enabled", False):
            return False
        try:
            probability = max(0.0, min(1.0, float(proactive.get("probability", 0))))
            cooldown = max(0.0, float(proactive.get("cooldown_seconds", 300)))
            active_window = max(1.0, float(proactive.get("active_window_seconds", 600)))
            min_after_bot = max(0.0, float(proactive.get("min_seconds_after_bot_reply", 90)))
            min_recent = max(1, int(proactive.get("min_recent_messages", 3)))
        except (TypeError, ValueError):
            self.logger.warning("主动聊天配置格式不正确，已跳过本次主动回复")
            return False
        now = time.time()
        if now - self.last_proactive_at.get(key, 0) < cooldown:
            return False
        if now - self.last_bot_reply_at.get(key, 0) < min_after_bot:
            return False
        if len(self.group_recent_lines(key, active_window)) < min_recent:
            return False
        if self.is_direct_followup(key, self.group_recent_lines(key, 1)[-1] if self.group_recent_lines(key, 1) else ""):
            return False
        return random.random() < probability

    async def maybe_proactive_reply(self, event: dict[str, Any], config: dict[str, Any], key: str) -> None:
        if event.get("message_type") != "group":
            return
        if is_at_bot(event) or has_at_other(event):
            return
        wake_text, has_wake_word = strip_wake_word(text_from_message(event.get("message")))
        if has_wake_word or self.is_direct_followup(key, wake_text):
            return
        message = text_from_message(event.get("message"))
        if has_bot_name(message) or any(marker in message for marker in BOT_FOLLOWUP_MARKERS):
            return
        if not self.should_proactively_reply(config, key):
            return
        proactive = config.get("proactive", {})
        active_window = float(proactive.get("active_window_seconds", 600))
        recent = self.group_recent_lines(key, active_window)
        prompt = (
            str(proactive.get("prompt") or "")
            + "\n\n最近群聊：\n"
            + "\n".join(recent[-MAX_GROUP_RECENT:])
            + "\n\n现在自然接一句即可。"
        )
        self.last_proactive_at[key] = time.time()
        answer = await self.chat(prompt, config, key)
        if not answer or answer.startswith("聊天 API"):
            self.logger.warning("主动聊天生成失败，未发送到群: %s", answer)
            return
        self.chat_history.setdefault(key, []).append({"role": "assistant", "content": answer})
        del self.chat_history[key][:-MAX_CHAT_HISTORY]
        await self.reply(event, answer)

    async def chat(self, prompt: str, config: dict[str, Any], key: str, image_refs: list[str] | None = None) -> str:
        assert self.session is not None
        chat_config = config["chat"]
        api_key = chat_config.get("api_key", "")
        if not api_key:
            return "还没有配置聊天 API Key，请先到 LLBot WebUI 的“AI配置”里填写。"
        url = chat_config["base_url"].rstrip("/") + "/chat/completions"
        user_content: Any = prompt
        if image_refs:
            user_content = [{"type": "text", "text": prompt or "看看这张图"}]
            for ref in image_refs[:4]:
                user_content.append({"type": "image_url", "image_url": {"url": image_ref_to_model_url(ref)}})
        messages = [
            {"role": "system", "content": chat_config.get("system_prompt", "")},
            *self.context_messages(key, prompt, config),
            {"role": "user", "content": user_content},
        ]
        payload = {
            "model": chat_config["model"],
            "messages": messages,
            "temperature": float(chat_config.get("temperature", 0.7)),
            "max_tokens": int(chat_config.get("max_tokens", 800)),
        }
        try:
            async with self.session.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=ClientTimeout(total=180, connect=15),
            ) as resp:
                body = await resp.text()
                try:
                    data = json.loads(body)
                except json.JSONDecodeError:
                    preview = body.strip().replace("\n", " ")[:160] or "空响应"
                    self.logger.warning(
                        "聊天 API 返回非 JSON: status=%s content_type=%s body=%s",
                        resp.status,
                        resp.headers.get("content-type"),
                        preview,
                    )
                    return f"聊天 API 返回的不是 JSON：HTTP {resp.status}，请检查 Base URL 是否应带 /v1。"
                if resp.status >= 400:
                    self.logger.warning("聊天 API 返回错误: %s %s", resp.status, data)
                    return f"聊天 API 调用失败：{data.get('error', {}).get('message') or resp.status}"
                return sanitize_model_answer(data["choices"][0]["message"]["content"])
        except Exception as exc:
            self.logger.exception("聊天 API 调用异常")
            return f"聊天 API 调用异常：{exc}"

    async def rewrite_image_prompt_for_safety(
        self,
        prompt: str,
        config: dict[str, Any],
        risk_reasons: list[str],
    ) -> str:
        assert self.session is not None
        fallback = fallback_safe_image_prompt(prompt)
        chat_config = config.get("chat", {})
        api_key = chat_config.get("api_key", "")
        if not chat_config.get("enabled", True) or not api_key:
            return fallback
        url = str(chat_config.get("base_url", "")).rstrip("/") + "/chat/completions"
        if not url.startswith(("http://", "https://")):
            return fallback
        system_prompt = (
            "你是生图提示词安全改写器。只输出一段新的中文生图提示词，不解释。"
            "把原始提示词改写为普通、合规、非性化、无未成年人暗示、无师生/医患/上下级等亲密或权力关系暗示的图片描述。"
            "保留合理的职业、画风、构图和氛围；移除或替换性化服装、身体凝视、挑逗语气和绕过审核要求。"
            "成人职业只能呈现专业工作状态。不要出现黑丝、白丝、紧身、包臀、低胸、透视、性感、诱惑、身材很好等词。"
        )
        user_prompt = (
            "风险原因："
            + "；".join(risk_reasons[:4])
            + "\n原始提示词："
            + prompt[:1200]
            + "\n请改写成可直接用于生图的一段安全提示词。"
        )
        payload = {
            "model": chat_config.get("model", "gpt-4o-mini"),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 220,
        }
        try:
            async with self.session.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=ClientTimeout(total=60, connect=15),
            ) as resp:
                body = await resp.text()
                if resp.status >= 400:
                    self.logger.warning("安全提示词改写 API 返回错误: %s %s", resp.status, body[:200])
                    return fallback
                try:
                    data = json.loads(body)
                except json.JSONDecodeError:
                    self.logger.warning("安全提示词改写 API 返回非 JSON: %s", body[:200])
                    return fallback
                rewritten = sanitize_model_answer(data["choices"][0]["message"]["content"])
                rewritten = rewritten.strip().strip('"“”`')
                if not rewritten or image_prompt_risk_reasons(rewritten):
                    self.logger.warning("安全提示词改写结果仍有风险，使用本地兜底")
                    return fallback
                return rewritten[:1000]
        except Exception:
            self.logger.exception("安全提示词改写失败，使用本地兜底")
            return fallback

    async def load_edit_image(self, ref: str) -> tuple[bytes, str, str]:
        assert self.session is not None
        if ref.startswith(("http://", "https://")):
            async with self.session.get(ref, timeout=ClientTimeout(total=45, connect=15)) as resp:
                if resp.status >= 400:
                    raise ValueError(f"参考图下载失败：HTTP {resp.status}，请重新发送图片。")
                if resp.content_length and resp.content_length > MAX_EDIT_IMAGE_BYTES:
                    raise ValueError("参考图超过 20 MB，请换一张较小的图片。")
                chunks = bytearray()
                async for chunk in resp.content.iter_chunked(65536):
                    chunks.extend(chunk)
                    if len(chunks) > MAX_EDIT_IMAGE_BYTES:
                        raise ValueError("参考图超过 20 MB，请换一张较小的图片。")
                data = bytes(chunks)
        elif ref.startswith(("base64://", "data:image/")):
            encoded = ref[len("base64://"):] if ref.startswith("base64://") else ref.partition(",")[2]
            if len(encoded) > ((MAX_EDIT_IMAGE_BYTES + 2) // 3) * 4:
                raise ValueError("参考图超过 20 MB，请换一张较小的图片。")
            try:
                data = base64.b64decode(encoded, validate=True)
            except ValueError as exc:
                raise ValueError("参考图编码无效，请重新发送图片。") from exc
        else:
            def read_bounded() -> bytes:
                with Path(ref).open("rb") as source:
                    return source.read(MAX_EDIT_IMAGE_BYTES + 1)
            data = await asyncio.to_thread(read_bounded)
        extension, mime_type = image_upload_type(data)
        return data, extension, mime_type

    def recent_persona_context(self, key: str) -> dict[str, Any]:
        context = self.persona_context.get(key, {})
        if time.time() - context.get("time", 0) > 600:
            self.persona_context.pop(key, None)
            return {}
        return context

    async def reply_selfie(
        self,
        event: dict[str, Any],
        prompt: str,
        config: dict[str, Any],
        ratio: str | None = None,
    ) -> None:
        selfie = config.get("selfie", {})
        if not selfie.get("enabled"):
            self.remember_image_request(chat_key(event), prompt, ratio)
            await self.reply(event, "正在生成图片，请稍等...")
            await self.reply_image(event, prompt, config, ratio)
            return
        if not config.get("image_edit", {}).get("enabled"):
            await self.reply(event, "固定形象自拍需要开启图生图，请先在 AI 配置中开启。")
            return
        try:
            reference_url = public_reference_url(str(selfie.get("reference_url") or ""))
        except ValueError:
            await self.reply(event, "人物参考图地址无效，请在 AI 配置中检查。")
            return
        if reference_url:
            reference_args = {"reference_urls": [reference_url]}
        else:
            reference = str(selfie.get("reference_image") or "")
            if not re.fullmatch(r"[a-f0-9]{64}\.(?:png|jpg|webp)", reference):
                await self.reply(event, "还没有设置人物参考图，请先在 AI 配置中上传图片或填写公网图片 URL。")
                return
            path = SELFIE_REFERENCE_DIR / reference
            if not path.is_file():
                await self.reply(event, "人物参考图不存在，请在 AI 配置中重新上传。")
                return
            reference_args = {"image_refs": [str(path)]}
        self.remember_image_request(chat_key(event), prompt, ratio)
        self.last_image_request[chat_key(event)]["kind"] = "selfie"
        self.last_image_request[chat_key(event)]["sender"] = str(event.get("user_id"))
        persona_key = f"{chat_key(event)}:sender:{event.get('user_id')}"
        previous = self.recent_persona_context(persona_key)
        self.persona_context[persona_key] = {
            "question": previous.get("question", ""),
            "answer": previous.get("answer") or prompt[:1000],
            "time": time.time(),
        }
        identity = clean_text_noise(str(selfie.get("identity_prompt") or ""))[:2000]
        # The configured portrait is always the identity source; chat images cannot replace it.
        prompt = (
            "以参考图中的人物作为朵啦的固定形象，生成这个人物的新日常照片或自拍。"
            "优先保持同一张脸、五官、发型、发色、瞳色、年龄感、标志性特征和原图画风，"
            "不要换人，不要生成其他角色；仅按要求调整场景、表情、姿势与日常服装。"
            "自然手机摄影，只有要求自拍时才使用自拍构图；场景按本次要求变化，不要照搬参考图的房间背景。无文字，无水印。"
            + (f"固定外貌补充：{identity}。" if identity else "")
            + f"本次自拍要求：{prompt}"
        )
        await self.reply(event, "正在生成图片，请稍等...")
        await self.reply_image(event, prompt, config, ratio, **reference_args)

    async def reply_image(
        self,
        event: dict[str, Any],
        prompt: str,
        config: dict[str, Any],
        ratio: str | None = None,
        image_refs: list[str] | None = None,
        reference_urls: list[str] | None = None,
    ) -> None:
        assert self.session is not None
        editing = image_refs is not None or reference_urls is not None
        image_config = config.get("image_edit", {}) if editing else config["image"]
        if editing and not (image_refs or reference_urls):
            await self.reply(event, "请先发送参考图片，再说明修改要求。")
            return
        api_key = image_config.get("api_key", "")
        if not api_key:
            await self.reply(event, "还没有配置生图 API Key，请先到 LLBot WebUI 的“AI配置”里填写。")
            return
        prompt = clean_text_noise(prompt)
        if not prompt:
            await self.reply(event, "生图提示词为空或只包含不可见字符，换一句正常描述再试。")
            return
        if image_config.get("safety_rewrite", True):
            risk_reasons = image_prompt_risk_reasons(prompt)
            if risk_reasons:
                rewritten_prompt = await self.rewrite_image_prompt_for_safety(prompt, config, risk_reasons)
                self.logger.info(
                    "生图提示词触发安全改写: reasons=%s rewritten=%s",
                    " | ".join(risk_reasons),
                    rewritten_prompt[:160],
                )
                prompt = rewritten_prompt
        url = image_config["base_url"].rstrip("/") + ("/images/edits" if editing else "/images/generations")
        payload = {
            "model": image_config["model"],
            "prompt": prompt,
            "size": image_size_from_ratio(
                ratio,
                image_config.get("size", "auto"),
                image_config.get("model", ""),
            ),
        }
        timeout_seconds = bounded_timeout(image_config.get("timeout_seconds"), 300, minimum=60, maximum=600)
        phase = "reference" if editing else "request"
        phase_started = time.monotonic()
        try:
            request_body: dict[str, Any] = {"json": payload}
            if reference_urls is not None:
                if image_refs is not None:
                    raise ValueError("参考图 URL 与文件不能同时提交。")
                # Send URL references directly; the image provider fetches the images.
                payload["images"] = [{"image_url": public_reference_url(ref)} for ref in reference_urls[:4]]
                if any(not item["image_url"] for item in payload["images"]):
                    raise ValueError("参考图 URL 不能为空。")
            elif editing:
                form = FormData()
                for name, value in payload.items():
                    form.add_field(name, str(value))
                refs = image_refs[:4]
                for index, ref in enumerate(refs):
                    image_bytes, extension, mime_type = await self.load_edit_image(ref)
                    form.add_field(
                        "image" if len(refs) == 1 else "image[]",
                        image_bytes,
                        filename=f"reference-{index + 1}.{extension}",
                        content_type=mime_type,
                    )
                request_body = {"data": form}
            phase = "request"
            phase_started = time.monotonic()
            self.logger.info(
                "图片 API 请求: mode=%s model=%s reference_count=%s reference_transport=%s",
                "image_edit" if editing else "text_to_image",
                payload["model"],
                len((reference_urls if reference_urls is not None else image_refs or [])[:4]),
                "url" if reference_urls is not None else "multipart" if editing else "none",
            )
            async with self.session.post(
                url,
                **request_body,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=ClientTimeout(total=timeout_seconds, connect=15),
            ) as resp:
                phase = "response"
                self.logger.info("图片 API 响应开始: status=%s elapsed=%.1fs", resp.status, time.monotonic() - phase_started)
                body = await resp.text()
                try:
                    data = json.loads(body)
                except json.JSONDecodeError:
                    preview = body.strip().replace("\n", " ")[:160] or "空响应"
                    self.logger.warning(
                        "生图 API 返回非 JSON: status=%s content_type=%s body=%s",
                        resp.status,
                        resp.headers.get("content-type"),
                        preview,
                    )
                    await self.reply(event, f"生图 API 返回的不是 JSON：HTTP {resp.status}，请检查 Base URL 是否应带 /v1。")
                    return
                if resp.status >= 400:
                    error = data.get("error") if isinstance(data, dict) else None
                    message = error.get("message") if isinstance(error, dict) else error
                    self.logger.warning("生图 API 返回错误: status=%s", resp.status)
                    await self.reply(event, f"生图 API 调用失败：{message or resp.status}")
                    return
                items = data.get("data") if isinstance(data, dict) else None
                item = items[0] if isinstance(items, list) and items and isinstance(items[0], dict) else {}
                image_ref = item.get("url")
                if not image_ref and item.get("b64_json"):
                    image_ref = "base64://" + item["b64_json"]
                if not image_ref:
                    await self.reply(event, "生图成功，但 API 没有返回可发送的图片地址或 base64。")
                    return
                phase = "delivery"
                phase_started = time.monotonic()
                await self.reply(event, [{"type": "image", "data": {"file": image_ref}}])
        except asyncio.TimeoutError as exc:
            elapsed = time.monotonic() - phase_started
            self.logger.exception(
                "图片流程超时: phase=%s elapsed=%.1fs model=%s editing=%s",
                phase, elapsed, payload["model"], editing,
            )
            if phase == "reference":
                message = "参考图片下载超时，尚未提交生图请求，请重新发送图片后再试。"
            elif phase == "delivery":
                message = "生图 API 已返回图片，但发送到 QQ 时超时，请稍后检查是否收到。"
            elif isinstance(exc, ConnectionTimeoutError):
                message = f"生图 API 连接超时（约{elapsed:.0f}秒），未能建立连接，请稍后再试。"
            else:
                message = f"等待生图 API 响应超时（已等待约{elapsed:.0f}秒），暂未收到结果，上游任务状态未知，请稍后确认，避免重复提交。"
            await self.reply(event, message)
        except (ClientConnectionError, OSError) as exc:
            elapsed = time.monotonic() - phase_started
            winerror = getattr(exc, "winerror", None)
            os_error = getattr(exc, "os_error", None)
            if winerror is None and os_error is not None:
                winerror = getattr(os_error, "winerror", None)
            self.logger.exception(
                "图片流程网络或 I/O 错误: phase=%s elapsed=%.1fs model=%s editing=%s type=%s winerror=%s",
                phase, elapsed, payload["model"], editing, type(exc).__name__, winerror,
            )
            if phase == "reference":
                message = "参考图片读取或下载失败，尚未提交生图请求，请检查参考图后再试。"
            elif phase == "delivery":
                message = "生图 API 已返回图片，但向 QQ 发送时连接失败，请先检查是否收到图片。"
            else:
                detail = f"（Windows {winerror}）" if winerror is not None else ""
                message = f"与生图服务通信时发生网络错误{detail}，暂未取得图片结果，任务状态未知，请稍后确认，避免重复提交。"
            await self.reply(event, message)
        except ValueError as exc:
            self.logger.warning("图片请求失败: %s", exc)
            await self.reply(event, f"图片请求失败：{exc}")
        except Exception as exc:
            self.logger.exception("生图 API 调用异常")
            await self.reply(event, f"生图 API 调用异常：{exc}")

    async def reply_group_ai_voice(self, event: dict[str, Any], text: str, config: dict[str, Any]) -> None:
        group_id = event.get("group_id")
        if not group_id:
            await self.reply(event, "群 AI 语音只能在群聊里发。")
            return
        voice_config = config.get("voice", {})
        try:
            chat_type = int(voice_config.get("chat_type", 1))
        except (TypeError, ValueError):
            chat_type = 1
        try:
            character = await self.resolve_voice_character(str(group_id), chat_type, voice_config)
            if not character:
                await self.reply(event, "这个群暂时没有拿到可用的 AI 语音声色。")
                return
            self.logger.info("发送群 AI 语音: group_id=%s character=%s text=%s", group_id, character, text[:40])
            await self.call_action(
                "send_group_ai_record",
                {
                    "group_id": group_id,
                    "character": character,
                    "text": text[:280],
                    "chat_type": chat_type,
                },
            )
        except asyncio.TimeoutError:
            self.logger.exception("群 AI 语音发送超时")
            await self.reply(event, "群 AI 语音发送超时：LLBot 没有返回动作结果，先试试在 AI 配置页选择一个固定音色。")
        except Exception as exc:
            self.logger.exception("群 AI 语音发送失败")
            message = str(exc) or exc.__class__.__name__
            await self.reply(event, f"群 AI 语音发送失败：{message}")

    def spawn_background_task(self, coro: Any) -> None:
        task = asyncio.create_task(coro)
        self.background_tasks.add(task)

        def _done(fut: asyncio.Task[Any]) -> None:
            self.background_tasks.discard(fut)
            try:
                exc = fut.exception()
            except asyncio.CancelledError:
                return
            if exc:
                self.logger.error("后台任务失败", exc_info=(type(exc), exc, exc.__traceback__))

        task.add_done_callback(_done)

    async def resolve_voice_character(self, group_id: str, chat_type: int, voice_config: dict[str, Any]) -> str:
        configured = str(voice_config.get("character") or "").strip()
        if configured:
            return configured
        characters = await self.get_ai_characters(group_id, chat_type)
        if not characters:
            return "lucy-voice-laibixiaoxin"
        return str(characters[0].get("character_id") or "").strip()

    async def get_ai_characters(self, group_id: str, chat_type: int) -> list[dict[str, Any]]:
        data = await self.call_action(
            "get_ai_characters",
            {"group_id": group_id, "chat_type": chat_type},
            wait=True,
            timeout=30,
        )
        characters: list[dict[str, Any]] = []
        if isinstance(data, list):
            groups = data
        elif isinstance(data, dict):
            groups = data.get("property") or data.get("data") or []
        else:
            groups = []
        for group in groups:
            if not isinstance(group, dict):
                continue
            for item in group.get("characters", []):
                if isinstance(item, dict):
                    characters.append(item)
        return characters

    async def reply(self, event: dict[str, Any], message: Any) -> None:
        message_type = event.get("message_type")
        message = strip_links_from_message(message)
        params: dict[str, Any] = {"message": message}
        if message_type == "group":
            params["group_id"] = event.get("group_id")
            self.last_bot_reply_at[chat_key(event)] = time.time()
        else:
            params["user_id"] = event.get("user_id")
        params["message_type"] = message_type
        await self.call_action("send_msg", params)

    async def call_action(
        self,
        action: str,
        params: dict[str, Any],
        *,
        wait: bool = False,
        timeout: float = 30,
    ) -> Any:
        if self.ws is None:
            raise ConnectionError("OneBot WebSocket 未连接")
        self.seq += 1
        echo = f"ai-bridge-{self.seq}"
        payload = {"action": action, "params": params, "echo": echo}
        future: asyncio.Future[dict[str, Any]] | None = None
        if wait:
            future = asyncio.get_running_loop().create_future()
            self.action_futures[echo] = future
        await self.ws.send_str(json.dumps(payload, ensure_ascii=False))
        if not future:
            return None
        try:
            response = await asyncio.wait_for(future, timeout=timeout)
        finally:
            self.action_futures.pop(echo, None)
        status = response.get("status")
        retcode = response.get("retcode")
        if status not in (None, "ok", "async") and retcode not in (0, None):
            raise RuntimeError(response.get("wording") or response.get("message") or response)
        if retcode not in (0, None):
            raise RuntimeError(response.get("wording") or response.get("message") or response)
        return response.get("data")


def make_app(store: ConfigStore, bridge: LLBotAIBridge) -> web.Application:
    app = web.Application()

    @web.middleware
    async def cors(request: web.Request, handler):
        if request.method == "OPTIONS":
            response = web.Response(status=204)
        else:
            response = await handler(request)
        response.headers["Access-Control-Allow-Origin"] = "http://127.0.0.1:3080"
        response.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return response

    app.middlewares.append(cors)

    async def health(_: web.Request) -> web.Response:
        config = await store.get()
        return web.json_response({"ok": True, "enabled": config["enabled"], "version": store.version})

    async def get_config(_: web.Request) -> web.Response:
        return web.json_response({"success": True, "data": public_config(await store.get())})

    async def get_memory(request: web.Request) -> web.Response:
        group_id = str(request.query.get("group_id") or "").strip()
        if group_id:
            return web.json_response({"success": True, "data": bridge.memory.get("groups", {}).get(group_id, {})})
        return web.json_response({"success": True, "data": bridge.memory})

    async def update_config(request: web.Request) -> web.Response:
        incoming = await request.json()
        try:
            config = await store.update(incoming)
        except ValueError as exc:
            return web.json_response({"success": False, "message": str(exc)}, status=400)
        return web.json_response({"success": True, "data": public_config(config)})

    async def upload_selfie_reference(request: web.Request) -> web.Response:
        data = bytearray()
        async for chunk in request.content.iter_chunked(65536):
            data.extend(chunk)
            if len(data) > MAX_EDIT_IMAGE_BYTES:
                return web.json_response({"success": False, "message": "参考图不能超过 20 MB。"}, status=413)
        try:
            extension, _ = image_upload_type(bytes(data))
        except ValueError as exc:
            return web.json_response({"success": False, "message": str(exc)}, status=400)
        name = hashlib.sha256(data).hexdigest() + "." + extension
        def save_reference() -> None:
            SELFIE_REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
            (SELFIE_REFERENCE_DIR / name).write_bytes(data)
        await asyncio.to_thread(save_reference)
        return web.json_response({"success": True, "reference_image": name})

    async def get_selfie_reference(request: web.Request) -> web.Response:
        name = request.match_info["name"]
        if not re.fullmatch(r"[a-f0-9]{64}\.(?:png|jpg|webp)", name):
            raise web.HTTPNotFound()
        path = SELFIE_REFERENCE_DIR / name
        if not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path)

    async def test_api(request: web.Request) -> web.Response:
        payload = await request.json()
        target = str(payload.get("target") or "").strip().lower()
        config = await store.get()
        started = time.time()

        def elapsed_ms() -> int:
            return int((time.time() - started) * 1000)

        if target == "onebot":
            try:
                await bridge.call_action("get_login_info", {}, wait=True, timeout=8)
                return web.json_response({"success": True, "message": "OneBot WebSocket 可用", "latency_ms": elapsed_ms()})
            except Exception as exc:
                return web.json_response(
                    {"success": False, "message": f"OneBot 测试失败：{exc}", "latency_ms": elapsed_ms()},
                    status=502,
                )

        if target == "chat":
            chat_config = config.get("chat", {})
            api_key = str(chat_config.get("api_key") or "")
            if not api_key:
                return web.json_response({"success": False, "message": "聊天 API Key 未配置"}, status=400)
            url = str(chat_config.get("base_url") or "").rstrip("/") + "/chat/completions"
            test_payload = {
                "model": chat_config.get("model") or "gpt-4o-mini",
                "messages": [{"role": "user", "content": "Reply exactly: OK"}],
                "temperature": 0,
                "max_tokens": 16,
            }
            try:
                assert bridge.session is not None
                async with bridge.session.post(
                    url,
                    json=test_payload,
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=ClientTimeout(total=45, connect=10),
                ) as resp:
                    body = await resp.text()
                    if resp.status >= 400:
                        message = body.strip().replace("\n", " ")[:240] or str(resp.status)
                        try:
                            data = json.loads(body)
                            message = data.get("error", {}).get("message") or message
                        except json.JSONDecodeError:
                            pass
                        return web.json_response(
                            {"success": False, "message": f"聊天 API 返回错误：{message}", "latency_ms": elapsed_ms()},
                            status=502,
                        )
                    return web.json_response({"success": True, "message": "聊天 API 可用", "latency_ms": elapsed_ms()})
            except Exception as exc:
                return web.json_response(
                    {"success": False, "message": f"聊天 API 测试异常：{exc}", "latency_ms": elapsed_ms()},
                    status=502,
                )

        if target == "image":
            image_config = config.get("image", {})
            api_key = str(image_config.get("api_key") or "")
            if not api_key:
                return web.json_response({"success": False, "message": "生图 API Key 未配置"}, status=400)
            url = str(image_config.get("base_url") or "").rstrip("/") + "/images/generations"
            test_payload = {
                "model": image_config.get("model") or "gpt-image-1",
                "prompt": "small blue square icon on a white background",
                "size": image_config.get("size") or "auto",
            }
            timeout_seconds = bounded_timeout(image_config.get("timeout_seconds"), 300, minimum=60, maximum=600)
            try:
                assert bridge.session is not None
                async with bridge.session.post(
                    url,
                    json=test_payload,
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=ClientTimeout(total=timeout_seconds, connect=10),
                ) as resp:
                    body = await resp.text()
                    if resp.status >= 400:
                        message = body.strip().replace("\n", " ")[:240] or str(resp.status)
                        try:
                            data = json.loads(body)
                            message = data.get("error", {}).get("message") or message
                        except json.JSONDecodeError:
                            pass
                        return web.json_response(
                            {"success": False, "message": f"生图 API 返回错误：{message}", "latency_ms": elapsed_ms()},
                            status=502,
                        )
                    return web.json_response({"success": True, "message": "生图 API 可用", "latency_ms": elapsed_ms()})
            except asyncio.TimeoutError:
                return web.json_response(
                    {
                        "success": False,
                        "message": f"生图 API 测试超时（{timeout_seconds}秒），上游可能正在排队或卡住",
                        "latency_ms": elapsed_ms(),
                    },
                    status=504,
                )
            except Exception as exc:
                return web.json_response(
                    {"success": False, "message": f"生图 API 测试异常：{exc}", "latency_ms": elapsed_ms()},
                    status=502,
                )

        return web.json_response({"success": False, "message": "未知测试目标"}, status=400)

    async def voice_characters_page(_: web.Request) -> web.Response:
        return web.Response(text=VOICE_CHARACTERS_PAGE, content_type="text/html")

    async def get_voice_characters(request: web.Request) -> web.Response:
        group_id = str(request.query.get("group_id") or "").strip()
        if not group_id:
            return web.json_response({"success": False, "message": "缺少 group_id"}, status=400)
        config = await store.get()
        try:
            chat_type = int(request.query.get("chat_type") or config.get("voice", {}).get("chat_type", 1))
            characters = await bridge.get_ai_characters(group_id, chat_type)
        except Exception as exc:
            logging.getLogger("llbot-ai-bridge").exception("获取群 AI 语音声色失败")
            return web.json_response({"success": False, "message": str(exc)}, status=500)
        return web.json_response({"success": True, "data": characters})

    app.router.add_get("/health", health)
    app.router.add_get("/api/config", get_config)
    app.router.add_get("/api/memory", get_memory)
    app.router.add_get("/api/voice/characters", get_voice_characters)
    app.router.add_get("/voice-characters", voice_characters_page)
    app.router.add_post("/api/test", test_api)
    app.router.add_post("/api/config", update_config)
    app.router.add_put("/api/config", update_config)
    app.router.add_post("/api/selfie/reference", upload_selfie_reference)
    app.router.add_get("/api/selfie/reference/{name}", get_selfie_reference)
    app.router.add_route("OPTIONS", "/api/selfie/reference", lambda _: web.Response(status=204))
    app.router.add_route("OPTIONS", "/api/test", lambda _: web.Response(status=204))
    app.router.add_route("OPTIONS", "/api/config", lambda _: web.Response(status=204))
    return app


async def main() -> None:
    setup_logging()
    store = ConfigStore()
    config = await store.get()
    bridge = LLBotAIBridge(store)
    bridge_task = asyncio.create_task(bridge.start())
    app = make_app(store, bridge)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, config["web"]["host"], int(config["web"]["port"]))
    await site.start()
    logging.getLogger("llbot-ai-bridge").info(
        "AI 配置服务已启动: http://%s:%s",
        config["web"]["host"],
        config["web"]["port"],
    )
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass
    await stop_event.wait()
    bridge_task.cancel()
    await bridge.stop()
    await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
