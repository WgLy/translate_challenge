"""
app_v2.py - Flask + Socket.IO main server for AI Translation Challenge V2
"""

import threading
import logging
from flask import Flask, render_template, jsonify, request, redirect
from flask_socketio import SocketIO, emit, join_room, disconnect

from game_state_v2 import game_state_v2
import ai_service

app = Flask(__name__, static_url_path='/ai_translate/static')
app.config["SECRET_KEY"] = "translate_challenge_v2_secret_2026"

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading",
    logger=False,
    engineio_logger=False,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("App_V2")

client_roles = {}

# ─── HTTP Routes ─────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return redirect("/ai_translate/team/a")

@app.route("/ai_translate/team/<side>")
def team_view(side):
    if side not in ["a", "b"]:
        return "Invalid side", 400
    return render_template("team.html")

@app.route("/ai_translate/admin")
def admin_page():
    return render_template("admin.html")

@app.route("/ai_translate/api/status")
def api_status():
    ollama_ok = ai_service.test_connection()
    cfg = ai_service.get_config()
    return jsonify({
        "ollama": ollama_ok,
        "model": cfg["model"],
        "review_model": cfg.get("review_model"),
        "url": cfg["url"],
        "state": game_state_v2.get_state()["phase"],
    })

@app.route("/ai_translate/api/scan_models")
def api_scan_models():
    """掃描 ollama_ports.json 中所有 Ollama 服務，回傳可用模型列表（含各自 URL）。"""
    models = ai_service.scan_all_models()
    return jsonify({"models": models})

# ─── Socket.IO Helpers ────────────────────────────────────────────────────────

def broadcast_state():
    """Push filtered state to teams and full state to admin."""
    # Send to Team A
    socketio.emit("state_update", game_state_v2.get_filtered_state("team_a"), room="team_a")
    # Send to Team B
    socketio.emit("state_update", game_state_v2.get_filtered_state("team_b"), room="team_b")
    # Send full state to Admin
    socketio.emit("state_update", game_state_v2.get_state(), room="admin")

def notify(message: str, type_: str = "info", room: str = "all"):
    if room == "all":
        socketio.emit("notification", {"type": type_, "message": message})
    else:
        socketio.emit("notification", {"type": type_, "message": message}, room=room)

# ─── Connection Events ────────────────────────────────────────────────────────

@socketio.on("connect")
def handle_connect():
    pass

@socketio.on("disconnect")
def handle_disconnect():
    if request.sid in client_roles:
        del client_roles[request.sid]

@socketio.on("join_role")
def handle_join_role(data):
    role = data.get("role", "admin")
    password = data.get("password", "")
    
    if role == "admin" and password != "admin123":
        emit("notification", {"type": "error", "message": "密碼錯誤，拒絕存取"})
        disconnect()
        return
        
    client_roles[request.sid] = role
    join_room(role)
    if role in ["team_a", "team_b"]:
        emit("state_update", game_state_v2.get_filtered_state(role))
    else:
        emit("state_update", game_state_v2.get_state())

# ─── Lobby Events ─────────────────────────────────────────────────────────────

@socketio.on("set_ready")
def handle_set_ready(data):
    side = client_roles.get(request.sid)
    if side not in ["team_a", "team_b"]: return
    
    try:
        team_id = int(data.get("team_id"))
    except (TypeError, ValueError):
        emit("notification", {"type": "error", "message": "無效的小隊編號"})
        return
        
    result = game_state_v2.set_ready(side, team_id)
    if result.get("warning"):
        emit("notification", {"type": "warning", "message": result["warning"]})
        return
        
    broadcast_state()
    
    if game_state_v2.can_start():
        if game_state_v2.start_game():
            broadcast_state()
            notify("🎮 雙方已準備完成！遊戲開始！", "success")
        else:
            notify("⚠️ 無法開始遊戲（可能有其他遊戲進行中或無題庫）", "warning")

@socketio.on("cancel_ready")
def handle_cancel_ready(data):
    side = client_roles.get(request.sid)
    if side in ["team_a", "team_b"]:
        game_state_v2.cancel_ready(side)
        broadcast_state()

# ─── Selecting Text Events ────────────────────────────────────────────────────

@socketio.on("select_text")
def handle_select_text(data):
    side = client_roles.get(request.sid)
    if side not in ["team_a", "team_b"]: return
    text_id = data.get("text_id")
    if side and text_id:
        res = game_state_v2.select_text(side, text_id)
        if "warning" in res:
            emit("notification", {"type": "warning", "message": res["warning"]})
        else:
            broadcast_state()

@socketio.on("confirm_selection")
def handle_confirm_selection(data):
    side = client_roles.get(request.sid)
    if side in ["team_a", "team_b"]:
        res = game_state_v2.confirm_selection(side)
        if "warning" in res:
            emit("notification", {"type": "warning", "message": res["warning"]})
        else:
            broadcast_state()

# ─── Editing Events ───────────────────────────────────────────────────────────

@socketio.on("apply_skill")
def handle_apply_skill(data):
    side = client_roles.get(request.sid)
    if side not in ["team_a", "team_b"]: return
    skill = data.get("skill")
    params = data.get("params", {})
    
    if not skill: return
        
    llm_skills = ["摘要", "誇飾", "插入名詞", "混亂語序"]
    if skill in llm_skills:
        result = game_state_v2.check_and_deduct_card(side, skill)
        if result.get("warning"):
            emit("notification", {"type": "warning", "message": result["warning"]})
            return
            
        notify("✨ 正在呼叫 AI 施放技能，請稍候...", "info", room=side)
        
        def run_llm_skill():
            current_text = game_state_v2.get_plain_edited_text(side)
            new_text = ai_service.apply_llm_skill(current_text, skill)
            
            if new_text.startswith("[連接錯誤") or new_text.startswith("[逾時錯誤"):
                game_state_v2.refund_card(side, skill)
                notify("❌ 技能施放失敗 (AI連線異常)，卡片已退回", "error", room=side)
            else:
                game_state_v2.commit_llm_skill_result(side, skill, new_text)
                broadcast_state()
                notify("✅ 技能施放完成！", "success", room=side)
                
        threading.Thread(target=run_llm_skill, daemon=True).start()
    else:
        result = game_state_v2.apply_skill(side, skill, params)
        if result.get("warning"):
            emit("notification", {"type": "warning", "message": result["warning"]})
        else:
            broadcast_state()

@socketio.on("undo_skill")
def handle_undo_skill(data):
    side = client_roles.get(request.sid)
    if side not in ["team_a", "team_b"]: return
    
    result = game_state_v2.undo_skill(side)
    if result.get("warning"):
        emit("notification", {"type": "warning", "message": result["warning"]})
    else:
        broadcast_state()

@socketio.on("confirm_edit")
def handle_confirm_edit(data):
    side = client_roles.get(request.sid)
    if side not in ["team_a", "team_b"]: return
    
    both_confirmed = game_state_v2.confirm_edit(side)
    broadcast_state()
    
    if both_confirmed:
        game_state_v2.set_translating_phase()
        broadcast_state()
        notify("🔄 雙方皆已確認！開始 AI 翻譯...", "info")
        
        # Start translation threads
        state = game_state_v2.get_state()
        count = state["translation_count"]
        
        text_a = game_state_v2.get_plain_edited_text("team_a")
        text_b = game_state_v2.get_plain_edited_text("team_b")
        
        t_a = threading.Thread(target=_run_translation, args=("team_a", text_a, count), daemon=True)
        t_b = threading.Thread(target=_run_translation, args=("team_b", text_b, count), daemon=True)
        t_a.start()
        t_b.start()

@socketio.on("cancel_confirm_edit")
def handle_cancel_confirm_edit(data):
    side = client_roles.get(request.sid)
    if side not in ["team_a", "team_b"]: return
    game_state_v2.cancel_confirm_edit(side)
    broadcast_state()

def _run_translation(side: str, text: str, count: int):
    """Background translation thread."""
    def progress_cb(step, total, lang, current_text):
        game_state_v2.update_translation_progress(side, step, total, lang)
        # Emit progress to all
        socketio.emit("translation_progress", {
            "side": side,
            "step": step,
            "total": total,
            "percent": round(step / total * 100),
            "lang": lang
        })
        
    try:
        final_text, path = ai_service.recursive_translate(text, count, progress_cb)
        game_state_v2.set_translation_result(side, final_text, path)
        broadcast_state()
        
        # Check if both are done
        if game_state_v2.both_translations_done():
            state = game_state_v2.get_state()
            if state.get("auto_review", False):
                notify("⚙️ 正在進行 AI 自動審核...", "info")
                
                sides_to_approve = []
                sides_to_reject = []
                
                for s in ["team_a", "team_b"]:
                    if state[s].get("admin_approved"):
                        continue
                    text_s = state[s]["translated_text"]
                    
                    is_error = False
                    if text_s:
                        if any(k in text_s for k in ["[連接錯誤", "OpenRouter 錯誤", "Ollama 錯誤", "[逾時錯誤"]):
                            is_error = True
                        else:
                            is_error = ai_service.evaluate_translation_error(text_s)
                            
                    if is_error:
                        sides_to_reject.append(s)
                    else:
                        sides_to_approve.append(s)
                
                for s in sides_to_approve:
                    game_state_v2.admin_approve(s)
                
                for s in sides_to_reject:
                    game_state_v2.admin_reject(s)
                    broadcast_state()
                    notify(f"⚠️ 偵測到 {s} 翻譯出現連線等異常，自動退回重新翻譯...", "warning")
                    
                    count = state["translation_count"]
                    t_text = game_state_v2.get_plain_edited_text(s)
                    t = threading.Thread(target=_run_translation, args=(s, t_text, count), daemon=True)
                    t.start()
                
                broadcast_state()
                if game_state_v2.both_approved():
                    notify("✅ 自動審核全部通過！請雙方開始猜題。", "success")
            else:
                notify("✅ 雙方翻譯完成！等待管理員審核。", "success")
    except Exception as e:
        logger.error(f"Translation error on {side}: {e}")
        notify(f"❌ 翻譯發生錯誤 ({side})：{e}", "error")

# ─── Admin Review Events ──────────────────────────────────────────────────────

@socketio.on("admin_approve")
def handle_admin_approve(data):
    if client_roles.get(request.sid) != "admin": return
    side = data.get("side")
    if not side: return
    game_state_v2.admin_approve(side)
    broadcast_state()
    
    if game_state_v2.both_approved():
        notify("✅ 審核全部通過！請雙方開始猜題。", "success")

@socketio.on("admin_reject")
def handle_admin_reject(data):
    if client_roles.get(request.sid) != "admin": return
    side = data.get("side")
    if not side: return
    
    game_state_v2.admin_reject(side)
    broadcast_state()
    notify(f"⚠️ 管理員已退回 {side} 的翻譯，重新翻譯中...", "warning")
    
    # Restart translation for this side
    state = game_state_v2.get_state()
    count = state["translation_count"]
    text = game_state_v2.get_plain_edited_text(side)
    
    t = threading.Thread(target=_run_translation, args=(side, text, count), daemon=True)
    t.start()

# ─── Guessing Events ──────────────────────────────────────────────────────────

@socketio.on("request_guess_data")
def handle_request_guess_data(data):
    side = client_roles.get(request.sid)
    if side in ["team_a", "team_b"]:
        guess_data = game_state_v2.get_guess_data(side)
        emit("guess_data", guess_data)

@socketio.on("submit_guess")
def handle_submit_guess(data):
    side = client_roles.get(request.sid)
    if side not in ["team_a", "team_b"]: return
    
    try:
        choice_idx = int(data.get("choice"))
    except (TypeError, ValueError):
        emit("notification", {"type": "error", "message": "無效的選項"})
        return
        
    game_state_v2.submit_guess(side, choice_idx)
    broadcast_state()
    
    if game_state_v2.get_state()["phase"] == "RESULT":
        notify("📊 雙方皆已作答！結果出爐！", "success")

# ─── Result Events ────────────────────────────────────────────────────────────

@socketio.on("confirm_result")
def handle_confirm_result(data):
    side = client_roles.get(request.sid)
    if side not in ["team_a", "team_b"]: return
    
    if game_state_v2.confirm_result(side):
        game_state_v2.next_round()
        broadcast_state()
        notify("🔄 進入下一回合！請重新準備。", "info")
    else:
        broadcast_state()

# ─── Admin Controls ───────────────────────────────────────────────────────────

@socketio.on("admin_set_cards")
def handle_admin_set_cards(data):
    if client_roles.get(request.sid) != "admin": return
    team_id = data.get("team_id")
    skill = data.get("skill")
    try:
        count = int(data.get("count"))
    except (TypeError, ValueError): return
    if team_id and skill:
        game_state_v2.admin_set_card_count(team_id, skill, count)
        broadcast_state()

@socketio.on("admin_set_score")
def handle_admin_set_score(data):
    if client_roles.get(request.sid) != "admin": return
    team_id = data.get("team_id")
    try:
        score = int(data.get("score"))
    except (TypeError, ValueError): return
    if team_id:
        game_state_v2.admin_set_score(team_id, score)
        broadcast_state()

@socketio.on("admin_set_translations")
def handle_admin_set_translations(data):
    if client_roles.get(request.sid) != "admin": return
    try:
        count = int(data.get("count"))
    except (TypeError, ValueError): return
    game_state_v2.admin_set_translation_count(count)
    broadcast_state()
    notify(f"⚙️ 翻譯次數已設為 {count} 次", "info")

@socketio.on("admin_set_auto_review")
def handle_admin_set_auto_review(data):
    if client_roles.get(request.sid) != "admin": return
    enabled = bool(data.get("enabled"))
    game_state_v2.admin_set_auto_review(enabled)
    broadcast_state()
    status = "開啟" if enabled else "關閉"
    notify(f"⚙️ AI 自動審核已{status}", "info")

@socketio.on("admin_set_skill_param")
def handle_admin_set_skill_param(data):
    if client_roles.get(request.sid) != "admin": return
    skill = data.get("skill")
    param = data.get("param")
    try:
        value = int(data.get("value"))
    except (TypeError, ValueError): return
    if skill and param:
        game_state_v2.admin_set_skill_param(skill, param, value)
        broadcast_state()
        notify(f"⚙️ {skill} {param} 已設為 {value}", "info")

@socketio.on("admin_set_model")
def handle_admin_set_model(data):
    if client_roles.get(request.sid) != "admin": return
    model = data.get("model")
    url = data.get("url")  # 模型所在的 Ollama 服務 URL（可選）
    if model:
        ai_service.set_model(model, url=url)
        cfg = ai_service.get_config()
        notify(f"⚙️ 翻譯模型已切換為 {model}（{cfg['url']}）", "info")

@socketio.on("admin_set_review_model")
def handle_admin_set_review_model(data):
    if client_roles.get(request.sid) != "admin": return
    model = data.get("model")
    url = data.get("url")
    if model:
        ai_service.set_review_model(model, url=url)
        notify(f"⚙️ 審核模型已切換為 {model}", "info")

@socketio.on("admin_reset")
def handle_admin_reset():
    if client_roles.get(request.sid) != "admin": return
    game_state_v2.admin_reset()
    broadcast_state()
    notify("🔄 遊戲已完全重置！", "warning")

@socketio.on("admin_force_phase")
def handle_admin_force_phase(data):
    if client_roles.get(request.sid) != "admin": return
    phase = data.get("phase")
    allowed = ["LOBBY", "SELECTING_TEXT", "EDITING", "TRANSLATING", "ADMIN_REVIEW", "GUESSING", "RESULT"]
    if phase in allowed:
        with game_state_v2._lock:
            game_state_v2._state["phase"] = phase
        broadcast_state()
        notify(f"⚙️ 強制切換至 {phase} 階段", "warning")

# ─── Main ─────────────────────────────────────────────────────────────────────

import argparse

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run AI Translation Challenge V2 Server")
    parser.add_argument("--api", action="store_true", help="Use OpenRouter API instead of Ollama")
    args = parser.parse_args()

    if args.api:
        ai_service.USE_OPENROUTER = True
        logger.info("OpenRouter API mode enabled via --api flag.")

    logger.info("Starting AI Translation Challenge V2 Server...")
    logger.info("  Team A:   http://localhost:5000/team/a")
    logger.info("  Team B:   http://localhost:5000/team/b")
    logger.info("  Admin:    http://localhost:5000/admin")
    from werkzeug.serving import run_simple
    socketio.run(app, debug=True, host="0.0.0.0", port=5000, use_reloader=False, allow_unsafe_werkzeug=True)
