"""
ai_service.py - V2 同步 Ollama 客戶端，用於 Flask 線程模式翻譯。
在後台線程中運行；通過 Socket.IO 進度回調通知前端。

改進點（相比 V1）：
  - OLLAMA_MODEL 支持環境變數覆蓋
  - 提供 get_model / set_model 運行時切換模型（並同時切換對應 URL）
  - 新增 get_config() 返回當前配置
  - 線程安全的模型名稱與 URL 讀寫（threading.Lock）
  - 支持從 ollama_ports.json 掃描多個 Ollama 服務端點
"""

import os
import re
import json
import random
import logging
import threading
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

# ─── 可用翻譯語言池 ──────────────────────────────────────────────
LANGUAGES = [
    "Japanese", "Korean", "French", "German", "Spanish",
    "Italian", "Russian", "Arabic", "Portuguese", "Thai",
    "Vietnamese", "Greek", "Dutch", "Turkish", "Hindi",
    "Polish", "Swedish", "Norwegian", "Czech", "Hungarian",
]

# ─── Ports 設定檔路徑（相對於本檔案） ────────────────────────────
_PORTS_CONFIG_PATH = Path(__file__).parent / "ollama_ports.json"

# ─── 用於清除 <think>...</think> 塊的正則 ────────────────────────
_THINK_RE = re.compile(r"<think>.*?</think>", flags=re.DOTALL)

# ─── 當前使用的 URL 與模型（線程安全） ───────────────────────────
_model_lock = threading.Lock()
_ollama_model: str = os.environ.get("OLLAMA_MODEL", "qwen3:8b")
_ollama_url: str = os.environ.get("OLLAMA_URL", "http://localhost:11434")


# =====================================================================
#  Ports 設定檔讀取
# =====================================================================

def _load_host_list() -> list[dict]:
    """
    從 ollama_ports.json 讀取要掃描的主機列表。
    若檔案不存在，則回傳預設的 localhost:11434。
    """
    try:
        with open(_PORTS_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        hosts = data.get("hosts", [])
        if hosts:
            return hosts
    except FileNotFoundError:
        logger.warning(f"找不到 {_PORTS_CONFIG_PATH}，使用預設主機。")
    except Exception as e:
        logger.error(f"讀取 ollama_ports.json 失敗: {e}")
    return [{"url": "http://localhost:11434", "label": "預設"}]


# =====================================================================
#  模型 getter / setter（線程安全）
# =====================================================================

def get_model() -> str:
    """獲取當前 Ollama 模型名稱。"""
    with _model_lock:
        return _ollama_model


def get_url() -> str:
    """獲取當前使用的 Ollama 服務 URL。"""
    with _model_lock:
        return _ollama_url


def set_model(model_name: str, url: str | None = None) -> None:
    """
    運行時切換 Ollama 模型（管理員可用）。
    若提供 url，則同時切換至對應的服務端點。

    Args:
        model_name: 新的模型名稱，如 'qwen3:8b'。
        url:        該模型所在的 Ollama 服務 URL（可選）。
    """
    global _ollama_model, _ollama_url
    with _model_lock:
        old_model = _ollama_model
        old_url = _ollama_url
        _ollama_model = model_name
        if url:
            _ollama_url = url
    logger.info(f"Ollama 模型已切換: {old_model}@{old_url} → {model_name}@{_ollama_url}")


# =====================================================================
#  配置查詢
# =====================================================================

def get_config() -> dict:
    """
    返回當前 Ollama 配置信息。

    Returns:
        dict: 包含 'url' 和 'model' 的字典。
    """
    return {
        "url": get_url(),
        "model": get_model(),
    }


# =====================================================================
#  多 Port 掃描
# =====================================================================

def _probe_host(host: dict) -> list[dict]:
    """
    嘗試連接單一 Ollama 主機，並回傳該主機上找到的所有模型。

    Args:
        host: {"url": "http://...", "label": "..."}

    Returns:
        找到的模型列表，每項格式為 {"name": ..., "url": ..., "label": ...}
        若連接失敗或無模型，回傳空列表。
    """
    url = host.get("url", "").rstrip("/")
    label = host.get("label", url)
    try:
        resp = requests.get(f"{url}/api/tags", timeout=3)
        if resp.status_code == 200:
            models = resp.json().get("models", [])
            result = []
            for m in models:
                name = m.get("name")
                if name:
                    result.append({"name": name, "url": url, "label": label})
            logger.info(f"[掃描] {label} ({url}): 找到 {len(result)} 個模型")
            return result
        else:
            logger.warning(f"[掃描] {label} ({url}): HTTP {resp.status_code}")
    except requests.exceptions.ConnectionError:
        logger.debug(f"[掃描] {label} ({url}): 無法連接")
    except requests.exceptions.Timeout:
        logger.debug(f"[掃描] {label} ({url}): 連接逾時")
    except Exception as e:
        logger.warning(f"[掃描] {label} ({url}): 錯誤 {e}")
    return []


def scan_all_models() -> list[dict]:
    """
    掃描 ollama_ports.json 中所有設定的 Ollama 主機，
    並使用多線程同步加速。

    Returns:
        所有可用模型的列表，每項格式為:
        {"name": "模型名稱", "url": "http://...", "label": "標籤"}
    """
    hosts = _load_host_list()
    results = []
    threads = []
    lock = threading.Lock()

    def probe_and_collect(host):
        found = _probe_host(host)
        with lock:
            results.extend(found)

    for host in hosts:
        t = threading.Thread(target=probe_and_collect, args=(host,), daemon=True)
        threads.append(t)
        t.start()

    for t in threads:
        t.join(timeout=5)  # 最多等待 5 秒

    # 依照 URL 再依照模型名稱排序，方便閱讀
    results.sort(key=lambda x: (x["url"], x["name"]))
    return results


# =====================================================================
#  底層 Ollama 調用
# =====================================================================

def _call_ollama(prompt: str, system_prompt: str = "You are a helpful translation assistant.") -> str:
    """
    同步調用當前設定的 Ollama 服務進行文本生成。

    Args:
        prompt:        用戶提示詞。
        system_prompt: 系統提示詞，預設為翻譯助手。

    Returns:
        生成的文本；出錯時返回中文錯誤占位符。
    """
    current_url = get_url()
    current_model = get_model()
    api_url = f"{current_url}/api/generate"

    payload = {
        "model": current_model,
        "prompt": prompt,
        "system": system_prompt,
        "stream": False,
        "options": {"temperature": 0.7},
        "think": False,  # 禁用 qwen3 的思維鏈輸出
    }

    try:
        resp = requests.post(api_url, json=payload, timeout=180)
        if resp.status_code == 200:
            text = resp.json().get("response", "").strip()
            # 清除可能殘留的 <think>...</think> 塊
            text = _THINK_RE.sub("", text).strip()
            return text
        elif resp.status_code == 404:
            logger.error(f"Ollama 404 — 模型 '{current_model}' 在 {current_url} 上不存在或路徑錯誤。")
            return f"[錯誤: 模型 '{current_model}' 在 {current_url} 上找不到，請確認模型名稱或重新掃描。]"
        else:
            logger.error(f"Ollama HTTP {resp.status_code}: {resp.text[:200]}")
            return f"[Ollama 錯誤 {resp.status_code}]"
    except requests.exceptions.Timeout:
        logger.error(f"Ollama 請求逾時 (180s) @ {current_url}")
        return "[逾時錯誤]"
    except requests.exceptions.ConnectionError:
        logger.error(f"無法連接 Ollama 服務: {current_url}")
        return "[連接錯誤: 無法連接到 Ollama 服務]"
    except Exception as e:
        logger.error(f"Ollama 調用異常: {e}")
        return f"[連接錯誤: {e}]"


# =====================================================================
#  遞歸翻譯核心邏輯
# =====================================================================

def recursive_translate(
    text: str,
    iterations: int,
    progress_callback=None,
) -> tuple[str, list]:
    """
    執行 `iterations` 輪隨機語言遞歸翻譯，最終翻譯回繁體中文。

    Args:
        text:              原始文本。
        iterations:        翻譯步驟數（例如 10）。
        progress_callback: 可選回調 callable(step, total, lang, current_text)，
                           每完成一步翻譯後調用。

    Returns:
        (final_text, path_list) — 最終文本與翻譯路徑列表。
    """
    logger.info(f"開始遞歸翻譯: 共 {iterations} 步, 模型={get_model()} @ {get_url()}")
    current = text
    path: list[str] = []

    # 構建翻譯路徑：前 N-1 步隨機語言，最後一步回到繁體中文
    for _ in range(iterations - 1):
        path.append(random.choice(LANGUAGES))
    path.append("Traditional Chinese")

    # 逐步執行翻譯
    for i, lang in enumerate(path):
        logger.info(f"  第 {i + 1}/{iterations} 步 → {lang}")
        prompt = (
            f"Translate the following text into {lang}. "
            "Return ONLY the translated text, no explanation, no extra commentary.\n\n"
            f"Text:\n{current}"
        )
        current = _call_ollama(prompt)

        # 通知進度回調
        if progress_callback:
            try:
                progress_callback(i + 1, iterations, lang, current)
            except Exception as cb_err:
                logger.warning(f"進度回調出錯: {cb_err}")

    logger.info("遞歸翻譯完成。")
    return current, path


# =====================================================================
#  連接測試（針對當前 URL）
# =====================================================================

def test_connection() -> bool:
    """
    快速檢測當前設定的 Ollama 服務是否可達。

    Returns:
        True 表示連接正常，False 表示不可達。
    """
    try:
        resp = requests.get(f"{get_url()}/api/tags", timeout=5)
        return resp.status_code == 200
    except Exception:
        return False
