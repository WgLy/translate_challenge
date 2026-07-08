"""
app_v2.py - Flask + Socket.IO main server for AI Translation Challenge V2
"""

import threading
import logging
import time
from flask import Flask, render_template, jsonify, request, redirect
from flask_socketio import SocketIO, emit, join_room, disconnect

from game_state_v2 import game_state_v2, MATCH_TO_SIDES
import ai_service

app = Flask(__name__, static_url_path='/ai_translate/static')
app.config["SECRET_KEY"] = "translate_challenge_v2_secret_2026"

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading",
    path="/ai_translate/socket.io",
    logger=False,
    engineio_logger=False,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("App_V2")

client_roles = {}

# --- Timer Mode (Feature 1) ---
_active_timers = {}
_timer_lock = threading.Lock()

def _start_game_timer(match_id: str, seconds: int):
    global _active_timers
    
    with _timer_lock:
        _cancel_game_timer_locked(match_id)
        
    start_time = time.time()
    match = game_state_v2.get_match_by_id(match_id)
    if not match: return
    
    with match._lock:
        match._state["timer_start_timestamp"] = start_time
        match._state["timer_running"] = True
        
    broadcast_state(match_id)
    
    # Broadcast timer_start to all sides of this match
    for r in MATCH_TO_SIDES[match_id]:
        socketio.emit("timer_start", {
            "total_seconds": seconds,
            "start_timestamp": start_time
        }, room=r)
    
    def timer_worker():
        time.sleep(seconds)
        _on_timer_expired(match_id)
        
    t = threading.Thread(target=timer_worker, daemon=True)
    with _timer_lock:
        _active_timers[match_id] = t
    t.start()

def _cancel_game_timer_locked(match_id: str):
    global _active_timers
    _active_timers[match_id] = None
    match = game_state_v2.get_match_by_id(match_id)
    if match:
        with match._lock:
            match._state["timer_running"] = False
            match._state["timer_start_timestamp"] = None

def _cancel_game_timer(match_id: str):
    with _timer_lock:
        _cancel_game_timer_locked(match_id)
    for r in MATCH_TO_SIDES[match_id]:
        socketio.emit("timer_cancel", {}, room=r)

def _on_timer_expired(match_id: str):
    logger.info(f"⏰ match {match_id} timer expired! forcing submission.")
    match = game_state_v2.get_match_by_id(match_id)
    if not match: return
    
    with match._lock:
        state = match._state
        if state["phase"] not in ["LOBBY", "SELECTING_TEXT", "EDITING"]:
            return
            
        state["timer_running"] = False
        
        for side in (match.side_a, match.side_b):
            st = state[side]
            if not st.get("confirmed_selection"):
                topic = st.get("topic")
                if topic and topic.get("texts"):
                    first_text = topic["texts"][0]
                    st["selected_text_id"] = first_text["id"]
                    st["confirmed_selection"] = True
                    match._init_editing_for_side(side)
            st["confirmed_edit"] = True
            
    match.set_translating_phase()
    broadcast_state(match_id)
    
    for r in MATCH_TO_SIDES[match_id]:
        notify("⏰ 時間到！系統強制送出當前文本翻譯。", "warning", room=r)
    
    state = match.get_state()
    count = state["translation_count"]
    text_a = match.get_plain_edited_text(match.side_a)
    text_b = match.get_plain_edited_text(match.side_b)
    
    t_a = threading.Thread(target=_run_translation, args=(match_id, match.side_a, text_a, count), daemon=True)
    t_b = threading.Thread(target=_run_translation, args=(match_id, match.side_b, text_b, count), daemon=True)
    t_a.start()
    t_b.start()


# --- Client Match Mapping Helper ---
def get_client_match_and_side(sid):
    role = client_roles.get(sid)
    if role and role in ["team_a", "team_b", "team_c", "team_d", "team_e", "team_f", "team_g", "team_h"]:
        return game_state_v2.get_match_and_side(role)
    return None, None


# ─── HTTP Routes ─────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return redirect("/ai_translate/team/a")

@app.route("/ai_translate/team/<side>")
def team_view(side):
    if side not in ["a", "b", "c", "d", "e", "f", "g", "h"]:
        return "Invalid side", 400
    return render_template("team.html")

@app.route("/ai_translate/admin")
def admin_page():
    return render_template("admin.html")

@app.route("/ai_translate/tutorial")
def tutorial_page():
    return render_template("tutorial.html")

@app.route("/ai_translate/api/status")
def api_status():
    ollama_ok = ai_service.test_connection()
    cfg = ai_service.get_config()
    match_ab = game_state_v2.get_match_by_id("ab")
    return jsonify({
        "ollama": ollama_ok,
        "model": cfg["model"],
        "review_model": cfg.get("review_model"),
        "url": cfg["url"],
        "state": match_ab.get_state()["phase"] if match_ab else "LOBBY"
    })

@app.route("/ai_translate/api/debug_paths")
def debug_paths():
    import os
    try:
        static_files = os.listdir(app.static_folder)
        js_files = os.listdir(os.path.join(app.static_folder, 'js'))
    except Exception as e:
        static_files = str(e)
        js_files = str(e)
        
    return jsonify({
        "root_path": app.root_path,
        "static_folder": app.static_folder,
        "static_files": static_files,
        "js_files": js_files
    })

@app.route("/ai_translate/dynamic_static/<path:filepath>")
def dynamic_static(filepath):
    from flask import send_from_directory
    actual_filename = filepath.replace("_js", ".js").replace("_css", ".css").lstrip('/')
    
    mimetype = "text/plain"
    if actual_filename.endswith(".js"): mimetype = "application/javascript"
    elif actual_filename.endswith(".css"): mimetype = "text/css"
    
    return send_from_directory(app.static_folder, actual_filename, mimetype=mimetype)

@app.route("/ai_translate/api/scan_models")
def api_scan_models():
    models = ai_service.scan_all_models()
    return jsonify({"models": models})


# ─── Socket.IO Helpers ────────────────────────────────────────────────────────

def broadcast_state(match_id: str = None):
    """Push filtered states to respective match side rooms, and all matches to admin."""
    mids = [match_id] if match_id else list(game_state_v2.matches.keys())
    
    for mid in mids:
        match = game_state_v2.get_match_by_id(mid)
        if not match: continue
        
        room_a, room_b = MATCH_TO_SIDES[mid]
        # Emit filtered states using their internal representation
        socketio.emit("state_update", match.get_filtered_state(match.side_a), room=room_a)
        socketio.emit("state_update", match.get_filtered_state(match.side_b), room=room_b)
        
    # Send dict of all states to admin
    socketio.emit("state_update", game_state_v2.get_all_states(), room="admin")

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
    
    # Send initial state
    if role == "admin":
        emit("state_update", game_state_v2.get_all_states())
    elif role in ["team_a", "team_b", "team_c", "team_d", "team_e", "team_f", "team_g", "team_h"]:
        match, side = game_state_v2.get_match_and_side(role)
        emit("state_update", match.get_filtered_state(side))


# ─── Lobby Events ─────────────────────────────────────────────────────────────

@socketio.on("set_ready")
def handle_set_ready(data):
    match, side = get_client_match_and_side(request.sid)
    if not match: return
    
    try:
        team_id = int(data.get("team_id"))
    except (TypeError, ValueError):
        emit("notification", {"type": "error", "message": "無效的小隊編號"})
        return
        
    result = match.set_ready(side, team_id)
    if result.get("warning"):
        emit("notification", {"type": "warning", "message": result["warning"]})
        return
        
    broadcast_state(match.match_id)
    
    if match.can_start():
        if match.start_game():
            broadcast_state(match.match_id)
            notify("🎮 雙方已準備完成！遊戲開始！", "success", room=match.match_id)
            state = match.get_state()
            if state.get("timer_enabled"):
                _start_game_timer(match.match_id, state.get("timer_seconds", 300))
        else:
            notify("⚠️ 無法開始遊戲（可能有其他遊戲進行中或無題庫）", "warning", room=match.match_id)

@socketio.on("cancel_ready")
def handle_cancel_ready(data):
    match, side = get_client_match_and_side(request.sid)
    if not match: return
    
    match.cancel_ready(side)
    broadcast_state(match.match_id)


# ─── Selecting Text Events ────────────────────────────────────────────────────

@socketio.on("select_text")
def handle_select_text(data):
    match, side = get_client_match_and_side(request.sid)
    if not match: return
    
    text_id = data.get("text_id")
    if text_id:
        res = match.select_text(side, text_id)
        if "warning" in res:
            emit("notification", {"type": "warning", "message": res["warning"]})
        else:
            broadcast_state(match.match_id)

@socketio.on("confirm_selection")
def handle_confirm_selection(data):
    match, side = get_client_match_and_side(request.sid)
    if not match: return
    
    res = match.confirm_selection(side)
    if "warning" in res:
        emit("notification", {"type": "warning", "message": res["warning"]})
    else:
        broadcast_state(match.match_id)


# ─── Editing Events ───────────────────────────────────────────────────────────

@socketio.on("apply_skill")
def handle_apply_skill(data):
    match, side = get_client_match_and_side(request.sid)
    if not match: return
    
    skill = data.get("skill")
    params = data.get("params", {})
    if not skill: return
    
    llm_skills = ["摘要", "誇飾", "插入名詞", "混難語序", "混亂語序"] # support variants
    if skill in llm_skills:
        result = match.check_and_deduct_card(side, skill)
        if result.get("warning"):
            emit("notification", {"type": "warning", "message": result["warning"]})
            return
            
        real_room = client_roles.get(request.sid)
        notify("✨ 正在呼叫 AI 施放技能，請稍候...", "info", room=real_room)
        
        def run_llm_skill():
            current_text = match.get_plain_edited_text(side)
            new_text = ai_service.apply_llm_skill(current_text, skill)
            
            if new_text.startswith("[連接錯誤") or new_text.startswith("[逾時錯誤"):
                match.refund_card(side, skill)
                notify("❌ 技能施放失敗 (AI連線異常)，卡片已退回", "error", room=real_room)
                broadcast_state(match.match_id)
            else:
                match.commit_llm_skill_result(side, skill, new_text)
                broadcast_state(match.match_id)
                notify("✅ 技能施放完成！", "success", room=real_room)
                
        threading.Thread(target=run_llm_skill, daemon=True).start()
    else:
        result = match.apply_skill(side, skill, params)
        if result.get("warning"):
            emit("notification", {"type": "warning", "message": result["warning"]})
        else:
            broadcast_state(match.match_id)

@socketio.on("undo_skill")
def handle_undo_skill(data):
    match, side = get_client_match_and_side(request.sid)
    if not match: return
    
    result = match.undo_skill(side)
    if result.get("warning"):
        emit("notification", {"type": "warning", "message": result["warning"]})
    else:
        broadcast_state(match.match_id)

@socketio.on("confirm_edit")
def handle_confirm_edit(data):
    match, side = get_client_match_and_side(request.sid)
    if not match: return
    
    text = match.get_plain_edited_text(side)
    if not text.strip():
        emit("notification", {"type": "error", "message": "編輯文本內容不能為空！"})
        return
        
    both_confirmed = match.confirm_edit(side)
    broadcast_state(match.match_id)
    
    if both_confirmed:
        _cancel_game_timer(match.match_id)
        match.set_translating_phase()
        broadcast_state(match.match_id)
        
        for r in MATCH_TO_SIDES[match.match_id]:
            notify("🔄 雙方皆已確認！開始 AI 翻譯...", "info", room=r)
            
        state = match.get_state()
        count = state["translation_count"]
        
        text_a = match.get_plain_edited_text(match.side_a)
        text_b = match.get_plain_edited_text(match.side_b)
        
        t_a = threading.Thread(target=_run_translation, args=(match.match_id, match.side_a, text_a, count), daemon=True)
        t_b = threading.Thread(target=_run_translation, args=(match.match_id, match.side_b, text_b, count), daemon=True)
        t_a.start()
        t_b.start()

@socketio.on("cancel_confirm_edit")
def handle_cancel_confirm_edit(data):
    match, side = get_client_match_and_side(request.sid)
    if not match: return
    
    match.cancel_confirm_edit(side)
    broadcast_state(match.match_id)

def _run_translation(match_id: str, side: str, text: str, count: int):
    """Background translation thread."""
    match = game_state_v2.get_match_by_id(match_id)
    if not match: return
    
    room_a, room_b = MATCH_TO_SIDES[match_id]
    
    def progress_cb(step, total, lang, current_text):
        match.update_translation_progress(side, step, total, lang)
        for r in (room_a, room_b):
            socketio.emit("translation_progress", {
                "side": side,
                "step": step,
                "total": total,
                "percent": round(step / total * 100),
                "lang": lang
            }, room=r)
            
    try:
        final_text, path = ai_service.recursive_translate(text, count, progress_cb)
        match.set_translation_result(side, final_text, path)
        broadcast_state(match_id)
        
        if match.both_translations_done():
            state = match.get_state()
            if state.get("auto_review", False):
                for r in (room_a, room_b):
                    notify("⚙️ 正在進行 AI 自動審核...", "info", room=r)
                
                sides_to_approve = []
                sides_to_reject = []
                
                for s in [match.side_a, match.side_b]:
                    if state[s].get("admin_approved"):
                        continue
                    text_s = state[s]["translated_text"]
                    
                    is_error = False
                    if text_s:
                        if text_s.startswith("[") and ("錯誤" in text_s or "逾時" in text_s):
                            is_error = True
                        else:
                            is_error = ai_service.evaluate_translation_error(text_s)
                            
                    if is_error:
                        sides_to_reject.append(s)
                    else:
                        sides_to_approve.append(s)
                        
                for s in sides_to_approve:
                    match.admin_approve(s)
                    
                for s in sides_to_reject:
                    match.admin_reject(s)
                    broadcast_state(match_id)
                    for r in (room_a, room_b):
                        notify(f"⚠️ 偵測到 {s} 翻譯出現連線等異常，自動退回重新翻譯...", "warning", room=r)
                    
                    count = state["translation_count"]
                    t_text = match.get_plain_edited_text(s)
                    t = threading.Thread(target=_run_translation, args=(match_id, s, t_text, count), daemon=True)
                    t.start()
                    
                broadcast_state(match_id)
                if match.both_approved():
                    for r in (room_a, room_b):
                        notify("✅ 自動審核全部通過！請雙方開始猜題。", "success", room=r)
            else:
                for r in (room_a, room_b):
                    notify("✅ 雙方翻譯完成！等待管理員審核。", "success", room=r)
    except Exception as e:
        logger.error(f"Translation error on {side} in match {match_id}: {e}")
        for r in (room_a, room_b):
            notify(f"❌ 翻譯發生錯誤 ({side})：{e}", "error", room=r)


# ─── Admin Review Events ──────────────────────────────────────────────────────

@socketio.on("admin_approve")
def handle_admin_approve(data):
    if client_roles.get(request.sid) != "admin": return
    match_id = data.get("match_id", "ab")
    side = data.get("side")
    if not side: return
    
    match = game_state_v2.get_match_by_id(match_id)
    if match:
        match.admin_approve(side)
        broadcast_state(match_id)
        if match.both_approved():
            for r in MATCH_TO_SIDES[match_id]:
                notify("✅ 審核全部通過！請雙方開始猜題。", "success", room=r)

@socketio.on("admin_reject")
def handle_admin_reject(data):
    if client_roles.get(request.sid) != "admin": return
    match_id = data.get("match_id", "ab")
    side = data.get("side")
    if not side: return
    
    match = game_state_v2.get_match_by_id(match_id)
    if match:
        match.admin_reject(side)
        broadcast_state(match_id)
        for r in MATCH_TO_SIDES[match_id]:
            notify(f"⚠️ 管理員已退回 {side} 的翻譯，重新翻譯中...", "warning", room=r)
        
        state = match.get_state()
        count = state["translation_count"]
        text = match.get_plain_edited_text(side)
        t = threading.Thread(target=_run_translation, args=(match_id, side, text, count), daemon=True)
        t.start()


# ─── Guessing Events ──────────────────────────────────────────────────────────

@socketio.on("request_guess_data")
def handle_request_guess_data(data):
    match, side = get_client_match_and_side(request.sid)
    if not match: return
    
    guess_data = match.get_guess_data(side)
    emit("guess_data", guess_data)

@socketio.on("submit_guess")
def handle_submit_guess(data):
    match, side = get_client_match_and_side(request.sid)
    if not match: return
    
    try:
        choice_idx = int(data.get("choice"))
    except (TypeError, ValueError):
        return
        
    match.submit_guess(side, choice_idx)
    broadcast_state(match.match_id)
    
    state = match.get_state()
    if state["phase"] == "RESULT":
        broadcast_state(match.match_id)


# ─── Result / Next Round Events ───────────────────────────────────────────────

@socketio.on("confirm_result")
def handle_confirm_result(data):
    match, side = get_client_match_and_side(request.sid)
    if not match: return
    
    if match.confirm_result(side):
        match.next_round()
    broadcast_state(match.match_id)


# ─── Admin Settings Events ────────────────────────────────────────────────────

@socketio.on("admin_set_cards")
def handle_admin_set_cards(data):
    if client_roles.get(request.sid) != "admin": return
    match_id = data.get("match_id", "ab")
    team_id = data.get("team_id")
    skill = data.get("skill")
    try:
        count = int(data.get("count", 0))
    except (TypeError, ValueError):
        return
        
    match = game_state_v2.get_match_by_id(match_id)
    if match:
        match.admin_set_card_count(team_id, skill, count)
        broadcast_state(match_id)
        notify(f"⚙️ 已將小隊 {team_id} 的「{skill}」卡片數量設為 {count}", "info")

@socketio.on("admin_set_score")
def handle_admin_set_score(data):
    if client_roles.get(request.sid) != "admin": return
    match_id = data.get("match_id", "ab")
    team_id = data.get("team_id")
    try:
        score = int(data.get("score", 0))
    except (TypeError, ValueError):
        return
        
    match = game_state_v2.get_match_by_id(match_id)
    if match:
        match.admin_set_score(team_id, score)
        broadcast_state(match_id)
        notify(f"⚙️ 已將小隊 {team_id} 的分數設為 {score}", "info")

@socketio.on("admin_set_translations")
def handle_admin_set_translations(data):
    if client_roles.get(request.sid) != "admin": return
    match_id = data.get("match_id", "ab")
    try:
        count = int(data.get("count", 10))
    except (TypeError, ValueError):
        return
        
    match = game_state_v2.get_match_by_id(match_id)
    if match:
        match.admin_set_translation_count(count)
        broadcast_state(match_id)
        notify(f"⚙️ 翻譯次數已調整為 {count}", "info")

@socketio.on("admin_set_auto_review")
def handle_admin_set_auto_review(data):
    if client_roles.get(request.sid) != "admin": return
    match_id = data.get("match_id", "ab")
    enabled = bool(data.get("enabled"))
    
    match = game_state_v2.get_match_by_id(match_id)
    if match:
        match.admin_set_auto_review(enabled)
        broadcast_state(match_id)
        status = "開啟" if enabled else "關閉"
        notify(f"⚙️ AI 自動審核模式已{status}", "info")

@socketio.on("admin_set_skill_param")
def handle_admin_set_skill_param(data):
    if client_roles.get(request.sid) != "admin": return
    match_id = data.get("match_id", "ab")
    skill = data.get("skill")
    param = data.get("param")
    value = data.get("value")
    
    match = game_state_v2.get_match_by_id(match_id)
    if match:
        match.admin_set_skill_param(skill, param, value)
        broadcast_state(match_id)
        notify(f"⚙️ {skill} {param} 已設為 {value}", "info")

@socketio.on("admin_set_skill_percent_mode")
def handle_admin_set_skill_percent_mode(data):
    if client_roles.get(request.sid) != "admin": return
    match_id = data.get("match_id", "ab")
    enabled = bool(data.get("enabled"))
    values = data.get("values", {})
    try:
        ai_value = int(data.get("ai_value", 3))
    except (TypeError, ValueError):
        ai_value = 3
    
    match = game_state_v2.get_match_by_id(match_id)
    if match:
        match.admin_set_skill_percent_mode(enabled, values, ai_value)
        broadcast_state(match_id)
        status = "開啟" if enabled else "關閉"
        notify(f"⚙️ 技能卡百分比模式已{status}", "info")

@socketio.on("admin_set_model")
def handle_admin_set_model(data):
    if client_roles.get(request.sid) != "admin": return
    model = data.get("model")
    url = data.get("url")
    if model:
        ai_service.set_model(model, url)
        socketio.emit("notification", {"type": "info", "message": f"⚙️ 已切換 AI 模型至 {model}"})

@socketio.on("admin_set_review_model")
def handle_admin_set_review_model(data):
    if client_roles.get(request.sid) != "admin": return
    model = data.get("model")
    url = data.get("url")
    if model:
        ai_service.set_review_model(model, url)
        socketio.emit("notification", {"type": "info", "message": f"⚙️ 已切換 AI 審核模型至 {model}"})

@socketio.on("admin_reset")
def handle_admin_reset(data=None):
    if client_roles.get(request.sid) != "admin": return
    match_id = "ab"
    if data and isinstance(data, dict):
        match_id = data.get("match_id", "ab")
        
    _cancel_game_timer(match_id)
    match = game_state_v2.get_match_by_id(match_id)
    if match:
        match.admin_reset()
        broadcast_state(match_id)
        notify(f"🔄 遊戲 ({match_id}) 已完全重置！", "warning")

@socketio.on("admin_terminate")
def handle_admin_terminate(data):
    if client_roles.get(request.sid) != "admin": return
    match_id = data.get("match_id", "ab")
    reason = data.get("reason", "管理員終止遊戲")
    
    _cancel_game_timer(match_id)
    match = game_state_v2.get_match_by_id(match_id)
    if match:
        match.admin_terminate(reason)
        broadcast_state(match_id)
        notify(f"🛑 遊戲 ({match_id}) 已被緊急終止：{reason}", "error")

@socketio.on("admin_set_timer")
def handle_admin_set_timer(data):
    if client_roles.get(request.sid) != "admin": return
    match_id = data.get("match_id", "ab")
    enabled = bool(data.get("enabled"))
    try:
        seconds = int(data.get("seconds", 300))
    except (TypeError, ValueError):
        seconds = 300
    
    match = game_state_v2.get_match_by_id(match_id)
    if match:
        with match._lock:
            match._state["timer_enabled"] = enabled
            match._state["timer_seconds"] = seconds
        broadcast_state(match_id)
        status = "開啟（" + str(seconds) + "秒）" if enabled else "關閉"
        notify(f"⏱️ 遊戲 ({match_id}) 全域計時模式已" + status, "info")

@socketio.on("admin_force_phase")
def handle_admin_force_phase(data):
    if client_roles.get(request.sid) != "admin": return
    match_id = data.get("match_id", "ab")
    phase = data.get("phase")
    
    match = game_state_v2.get_match_by_id(match_id)
    if match:
        with match._lock:
            match._state["phase"] = phase
        broadcast_state(match_id)
        notify(f"⚙️ 遊戲 ({match_id}) 階段已強制變更為 {phase}", "warning")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run AI Translation Challenge V2 Server")
    parser.add_argument("--api", action="store_true", help="Use OpenRouter API instead of Ollama")
    args, unknown = parser.parse_known_args()

    if args.api:
        ai_service.USE_OPENROUTER = True
        logger.info("OpenRouter API mode enabled via --api flag.")

    socketio.run(app, host="0.0.0.0", port=5000, debug=True)
