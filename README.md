# AI Translation Challenge V2 - Web Application
這是 2026 資訊營 AI 大地的其中一關--翻譯挑戰。 

## 遊玩流程
本遊戲需要在有人監督下進行。
首先，互相對戰的雙方填上小隊代號後準備完成。
系統隨機抽取一個主題，主題中有四篇性質相似的文章。雙方需要在其中選擇一篇作為攻擊文本。
雙方選擇完成後，小隊可以選擇使用手上的技能卡片來修改攻擊文本：
1. 增字：在所選位置增加一個字
2. 刪字：使指定的字元被刪除
3. 搬移：選擇一個字元，並選擇另一個位置。該卡片會將該字元後方 n 個字元選取並移動到指定位置插入。n 可以透過後臺設定，預設值為 10 。

修改完成後按下準備完成。
接下來，語言模型會將雙方編輯好的攻擊文本翻譯 20 次 (同樣可以後臺調整數值)。
當文本被翻譯完成，會先送到管理員介面，確認模型沒有報錯、生成不該生成的指示或補充詞語等等。若管理員發現翻譯出現錯誤，可以退回該翻譯重新生成。
當雙方的翻譯內容都被通過，會將翻譯汙染過的攻擊文本送給敵方小隊。同時自身也要從四個原文中，猜出敵方受翻譯汙染後的原文為何。
猜對者得一分，該輪遊戲結束。

---
AI 生的。

## 🌟 核心特點

1. **即時雙團對戰 (Symmetric Dual-Team Gameplay)**
   * 支援 Team A 與 Team B 對稱對決，透過 WebSocket 實現遊戲狀態毫秒級同步。
2. **字元級技能干擾機制 (Character-Level Skills)**
   * **✍️ 增字**：可在文字任意位置插入字元。
   * **✂️ 刪字**：可任意刪除文字中的單個字元。
   * **🔀 搬移**：可將指定長度（預設為 10 字）的連續文字搬移至其他位置。
3. **強大的 AI 翻譯後端 (Ollama Integration)**
   * 即時透過本地/遠端 Ollama 服務進行翻譯。
   * **思維過濾**：自動清除 DeepSeek 等推理模型產生的 `<think>...</think>` 標記，提供乾淨的翻譯結果。
   * **動態掃描與切換**：支援從 `ollama_ports.json` 掃描多個主機上的模型，管理員可在後台即時切換使用的 Ollama 端點與模型。

---

## 📁 目錄結構

* `app_v2.py`：Flask 伺服器主入口，整合 Socket.IO 進行實作連線與路由分發。
* `game_state_v2.py`：記憶體內的遊戲狀態管理器，包含技能邏輯與狀態機。
* `ai_service.py`：與 Ollama 連線的同步客戶端，處理翻譯與模型掃描。
* `ollama_ports.json`：多 Ollama 服務端點掃描設定檔。
* `requirements.txt`：此 Web 專案的 Python 依賴包清單。
* `data/`
  * `questions_v2.json`：翻譯挑戰賽題庫。
* `templates/`：HTML 網頁模板。
  * `team.html`：隊伍（A/B）對戰操作介面。
  * `admin.html`：管理員主控台。
* `static/`：前端 CSS 樣式與即時互動 JavaScript。

---

## 🛠️ 安裝與環境建置

### 1. 安裝依賴包
請確保您已安裝 Python 3.10+，並在 `web_v2` 目錄下執行：
```bash
pip install -r requirements.txt
```

### 2. 設定 Ollama 服務
確保您的 Ollama 服務已在本地（`http://localhost:11434`）啟動，且已下載您想使用的模型（如 `qwen3:8b`）。
* *若有其他 Ollama 伺服器，可在 `ollama_ports.json` 中配置主機列表以進行掃描。*

---

## 🚀 啟動與執行

在 `web_v2` 目錄下執行：
```bash
python app_v2.py
```

啟動後，可在瀏覽器開啟以下網址：
* **A 隊介面**：[http://localhost:5000/team/a](http://localhost:5000/team/a)
* **B 隊介面**：[http://localhost:5000/team/b](http://localhost:5000/team/b)
* **管理員後台**：[http://localhost:5000/admin](http://localhost:5000/admin) *(預設密碼為 `admin123`)*

---

## ⚙️ 環境變數自訂 (選用)

此服務預設會連線至本地 `http://localhost:11434` 並使用 `qwen3:8b` 模型。若您想自訂，可以在執行前設定以下環境變數，或是在 `web_v2` 目錄下新增 `.env` 檔案（需在 `app_v2.py` 中呼叫 `load_dotenv()`）：

```ini
# Ollama 伺服器網址
OLLAMA_URL=http://localhost:11434

# 預設使用的模型名稱
OLLAMA_MODEL=qwen3:8b
```
