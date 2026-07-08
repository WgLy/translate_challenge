"""
game_state_v2.py - In-memory game state manager for V2
Symmetric dual-team gameplay with character-level skills.
"""

import json
import random
import os
import threading
import logging
import copy

logger = logging.getLogger(__name__)

SKILL_REGISTRY = {
    "增字": {
        "id": "add_char",
        "name": "增字",
        "description": "在文本的任意位置插入一個字元",
        "default_count": 3,
        "params": {},
        "icon": "✍️",
        "category": "manual",
    },
    "刪字": {
        "id": "delete_char",
        "name": "刪字",
        "description": "刪除文本中的任意一個字",
        "default_count": 3,
        "params": {},
        "icon": "✂️",
        "category": "manual",
    },
    "改字": {
        "id": "replace_char",
        "name": "改字",
        "description": "將文本中的一個字元替換為另一個字元",
        "default_count": 3,
        "params": {},
        "icon": "🔄",
        "category": "manual",
    },
    "搬移": {
        "id": "move_segment",
        "name": "搬移",
        "description": "將一段特定長度的連續文字搬移到文本的另一位置",
        "default_count": 1,
        "params": {"segment_length": 10},
        "icon": "🔀",
        "category": "manual",
    },
    "摘要": {
        "id": "summarize",
        "name": "摘要",
        "description": "將文本進行精簡與摘要",
        "default_count": 1,
        "params": {},
        "icon": "📝",
        "category": "ai",
    },
    "誇飾": {
        "id": "exaggerate",
        "name": "誇飾",
        "description": "將文本進行誇飾處理",
        "default_count": 1,
        "params": {},
        "icon": "🎭",
        "category": "ai",
    },
    "插入名詞": {
        "id": "insert_noun",
        "name": "插入名詞",
        "description": "隨機在文本中插入一些不相干的名詞",
        "default_count": 1,
        "params": {},
        "icon": "🔤",
        "category": "ai",
    },
    "混亂語序": {
        "id": "scramble",
        "name": "混亂語序",
        "description": "打亂文本的語序",
        "default_count": 1,
        "params": {},
        "icon": "🌪️",
        "category": "ai",
    }
}

PHASE_LOBBY = "LOBBY"
PHASE_SELECTING_TEXT = "SELECTING_TEXT"
PHASE_EDITING = "EDITING"
PHASE_TRANSLATING = "TRANSLATING"
PHASE_ADMIN_REVIEW = "ADMIN_REVIEW"
PHASE_GUESSING = "GUESSING"
PHASE_RESULT = "RESULT"
PHASE_TERMINATED = "TERMINATED"

def _empty_team_round() -> dict:
    return {
        "team_id": None,
        "ready": False,
        "confirmed_selection": False,
        "confirmed_edit": False,
        "confirmed_result": False,
        "topic": None,           # {"id": ..., "theme": "...", "texts": [...]}
        "selected_text_id": None,# str, id of the chosen text before confirm
        "attack_text": None,     # {"id": "...", "original": "..."}
        "correct_index": None,   # 0~3
        "original_text": None,   # string
        "edited_text": [],       # list of dicts: {"char": str, "edited": bool}
        "history": [],           # list of edited_text states for undo
        "skill_actions": [],     # list of dicts: {"skill": "...", "params": {...}}
        "translated_text": None, # string
        "translation_progress": 0,
        "translation_lang": "",
        "admin_approved": False,
        "guess_choice": None,    # int
        "guess_correct": None,   # bool
    }

def _load_questions() -> list:
    path = os.path.join(os.path.dirname(__file__), "data", "questions_v2.json")
    if not os.path.exists(path):
        logger.warning(f"Questions file not found at {path}. Using empty list.")
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading questions: {e}")
        return []

class MatchState:
    def __init__(self, match_id: str, side_a: str, side_b: str, questions: list):
        self._lock = threading.Lock()
        self._game_lock = threading.Lock()
        self.match_id = match_id
        self.side_a = side_a
        self.side_b = side_b
        self.questions = questions
        self._state = {}
        self.reset(full=True)

    def _get_team(self, team_id) -> dict:
        key = str(team_id)
        if key not in self._state["teams"]:
            cards = {}
            for name, info in self._state["skill_registry"].items():
                if info.get("category") == "ai":
                    cards[name] = -1
                else:
                    cards[name] = info["default_count"]
            self._state["teams"][key] = {
                "score": 0,
                "cards": cards,
                "ai_skill_uses": self._state.get("ai_skill_shared_count", 2),
            }
        return self._state["teams"][key]

    def reset(self, full: bool = False):
        with self._lock:
            preserved_teams = {} if full else copy.deepcopy(self._state.get("teams", {}))
            preserved_count = 10 if full else self._state.get("translation_count", 10)
            preserved_registry = copy.deepcopy(SKILL_REGISTRY) if full else copy.deepcopy(self._state.get("skill_registry", SKILL_REGISTRY))
            preserved_auto_review = True if full else self._state.get("auto_review", True)
            preserved_ai_count = 2 if full else self._state.get("ai_skill_shared_count", 2)
            
            preserved_pct_mode = False if full else self._state.get("skill_percent_mode", False)
            preserved_pct_vals = {"增字": 5, "刪字": 5, "改字": 5, "搬移": 2} if full else self._state.get("skill_percent_values", {"增字": 5, "刪字": 5, "改字": 5, "搬移": 2})
            preserved_ai_pct = 3 if full else self._state.get("ai_skill_percent_value", 3)
            
            preserved_timer_enabled = False if full else self._state.get("timer_enabled", False)
            preserved_timer_seconds = 300 if full else self._state.get("timer_seconds", 300)
            
            # preserve team IDs in lobby if not full reset
            team_a_id = None
            team_b_id = None
            if not full and self.side_a in self._state:
                team_a_id = self._state[self.side_a]["team_id"]
                team_b_id = self._state[self.side_b]["team_id"]

            team_a_state = _empty_team_round()
            team_b_state = _empty_team_round()
            
            team_a_state["team_id"] = team_a_id
            team_b_state["team_id"] = team_b_id

            self._state = {
                "phase": PHASE_LOBBY,
                "round_number": 1 if full else self._state.get("round_number", 1),
                "translation_count": preserved_count,
                "auto_review": preserved_auto_review,
                "ai_skill_shared_count": preserved_ai_count,
                "skill_percent_mode": preserved_pct_mode,
                "skill_percent_values": preserved_pct_vals,
                "ai_skill_percent_value": preserved_ai_pct,
                "timer_enabled": preserved_timer_enabled,
                "timer_seconds": preserved_timer_seconds,
                "timer_start_timestamp": None if full else self._state.get("timer_start_timestamp"),
                "timer_running": False if full else self._state.get("timer_running", False),
                self.side_a: team_a_state,
                self.side_b: team_b_state,
                "teams": preserved_teams,
                "skill_registry": preserved_registry,
            }

    def get_state(self) -> dict:
        with self._lock:
            state = copy.deepcopy(self._state)

        for side in (self.side_a, self.side_b):
            tid = state[side].get("team_id")
            if tid is not None:
                team = state["teams"].get(str(tid), {})
                state[side]["score"] = team.get("score", 0)
                state[side]["cards"] = copy.deepcopy(team.get("cards", {}))
                state[side]["ai_skill_uses"] = team.get("ai_skill_uses", 2)
            else:
                state[side]["score"] = 0
                state[side]["cards"] = {}
                state[side]["ai_skill_uses"] = 2
        return state

    def get_filtered_state(self, requester_side: str) -> dict:
        """Filter out sensitive information based on the requester's side."""
        state = self.get_state()
        other_side = self.side_b if requester_side == self.side_a else self.side_a
        phase = state["phase"]

        if phase in [PHASE_SELECTING_TEXT, PHASE_EDITING, PHASE_TRANSLATING]:
            # Hide other team's topic and text details
            state[other_side]["topic"] = None
            state[other_side]["selected_text_id"] = None
            state[other_side]["attack_text"] = None
            state[other_side]["original_text"] = None
            state[other_side]["edited_text"] = []
            state[other_side]["skill_actions"] = []
            
        if phase in [PHASE_SELECTING_TEXT, PHASE_EDITING, PHASE_TRANSLATING, PHASE_ADMIN_REVIEW, PHASE_GUESSING]:
            # Hide other team's guess until RESULT
            state[other_side]["guess_choice"] = None
            
        if phase == PHASE_GUESSING:
            # During guessing, hide the correct answer of the other team
            state[other_side]["correct_index"] = None

        return state

    # ─── LOBBY ────────────────────────────────────────────────────────────

    def set_ready(self, side: str, team_id) -> dict:
        with self._lock:
            if self._state["phase"] != PHASE_LOBBY:
                return {"warning": "遊戲不在大廳階段！"}

            other_side = self.side_b if side == self.side_a else self.side_a
            other_id = self._state[other_side]["team_id"]

            if other_id is not None and str(other_id) == str(team_id):
                return {"warning": f"小隊 {team_id} 已在另一側準備中！"}

            cur = self._state[side]
            cur["team_id"] = team_id
            cur["ready"] = True
            self._get_team(team_id)
            return {"success": True}

    def cancel_ready(self, side: str):
        with self._lock:
            self._state[side]["ready"] = False

    def can_start(self) -> bool:
        with self._lock:
            s = self._state
            return s[self.side_a]["ready"] and s[self.side_b]["ready"] and s["phase"] == PHASE_LOBBY

    def start_game(self) -> bool:
        if not self._game_lock.acquire(blocking=False):
            return False # Another game is starting/running

        with self._lock:
            if not self.questions:
                self._game_lock.release()
                return False
                
            # Group topics by char_group
            groups = {}
            for q in self.questions:
                g = q.get("char_group", "medium")
                groups.setdefault(g, []).append(q)
            
            # Try to pick a group with at least 2 topics
            eligible_groups = [g for g, topics in groups.items() if len(topics) >= 2]
            
            if eligible_groups:
                chosen_group = random.choice(eligible_groups)
                chosen_topics = random.sample(groups[chosen_group], 2)
                self._state[self.side_a]["topic"] = chosen_topics[0]
                self._state[self.side_b]["topic"] = chosen_topics[1]
            else:
                # Fallback to random independent selection if no group has 2+ topics
                for side in (self.side_a, self.side_b):
                    self._state[side]["topic"] = random.choice(self.questions)
                    
            for side in (self.side_a, self.side_b):
                self._state[side]["selected_text_id"] = None
                self._state[side]["confirmed_selection"] = False
                
            self._state["phase"] = PHASE_SELECTING_TEXT
            
        return True

    def end_game_lock(self):
        try:
            self._game_lock.release()
        except RuntimeError:
            pass

    # ─── SELECTING TEXT ───────────────────────────────────────────────────

    def select_text(self, side: str, text_id: str) -> dict:
        with self._lock:
            if self._state["phase"] != PHASE_SELECTING_TEXT:
                return {"warning": "目前不在選題階段"}
            if self._state[side]["confirmed_selection"]:
                return {"warning": "已確認選擇，無法更改"}
            
            self._state[side]["selected_text_id"] = text_id
            return {"success": True}

    def confirm_selection(self, side: str) -> dict:
        with self._lock:
            if self._state["phase"] != PHASE_SELECTING_TEXT:
                return {"warning": "目前不在選題階段"}
            if not self._state[side]["selected_text_id"]:
                return {"warning": "尚未選擇任何文本"}
            
            self._state[side]["confirmed_selection"] = True
            
            # Check if both confirmed
            if self._state[self.side_a]["confirmed_selection"] and self._state[self.side_b]["confirmed_selection"]:
                self._transition_to_editing()
                return {"success": True, "phase_changed": True, "both_confirmed": True}
                
            if self._state.get("timer_enabled"):
                self._init_editing_for_side(side)
                return {"success": True, "phase_changed": False, "can_edit_early": True, "both_confirmed": False}
                
            return {"success": True, "phase_changed": False}

    def _apply_percent_mode_cards(self, side: str, team_id, text_len: int):
        team = self._get_team(team_id)
        if self._state.get("skill_percent_mode"):
            pcts = self._state.get("skill_percent_values", {"增字": 5, "刪字": 5, "改字": 5, "搬移": 2})
            for skill, pct in pcts.items():
                team["cards"][skill] = max(1, round(text_len * pct / 100))
            ai_pct = self._state.get("ai_skill_percent_value", 3)
            team["ai_skill_uses"] = max(1, round(text_len * ai_pct / 100))

    def _init_editing_for_side(self, side: str):
        st = self._state[side]
        if st.get("edited_text"):
            return
        topic = st["topic"]
        selected_id = st["selected_text_id"]
        for idx, text_obj in enumerate(topic["texts"]):
            if text_obj["id"] == selected_id:
                st["attack_text"] = text_obj
                st["correct_index"] = idx
                st["original_text"] = text_obj["original"]
                st["edited_text"] = [{"char": c, "edited": False} for c in text_obj["original"]]
                if st.get("team_id"):
                    self._apply_percent_mode_cards(side, st["team_id"], len(text_obj["original"]))
                break
        st["history"] = []
        st["skill_actions"] = []
        st["confirmed_edit"] = False

    def _transition_to_editing(self):
        for side in (self.side_a, self.side_b):
            self._init_editing_for_side(side)
        self._state["phase"] = PHASE_EDITING


    # ─── EDITING ──────────────────────────────────────────────────────────

    def _check_card_available(self, team: dict, skill: str) -> bool:
        """檢查技能卡是否可用。"""
        registry = self._state["skill_registry"]
        info = registry.get(skill)
        if not info:
            return False
        
        if info.get("category") == "ai":
            # AI 卡檢查共享次數
            return team.get("ai_skill_uses", 0) > 0
        else:
            # 手動卡檢查個別次數
            return team["cards"].get(skill, 0) > 0

    def _deduct_card(self, team: dict, skill: str):
        """扣減一張技能卡。"""
        registry = self._state["skill_registry"]
        info = registry.get(skill)
        if not info:
            return
        
        if info.get("category") == "ai":
            if team.get("ai_skill_uses", 0) > 0:
                team["ai_skill_uses"] -= 1
        else:
            if skill in team["cards"] and team["cards"][skill] > 0:
                team["cards"][skill] -= 1

    def _refund_card(self, team: dict, skill: str):
        """退回一張技能卡。"""
        registry = self._state["skill_registry"]
        info = registry.get(skill)
        if not info:
            return
        
        if info.get("category") == "ai":
            team["ai_skill_uses"] = team.get("ai_skill_uses", 0) + 1
        else:
            if skill in team["cards"] and team["cards"][skill] != -1:
                team["cards"][skill] += 1

    def _is_editing_allowed(self, side: str) -> bool:
        phase = self._state["phase"]
        if phase == PHASE_EDITING:
            return True
        if phase == PHASE_SELECTING_TEXT and self._state.get("timer_enabled") and self._state[side].get("confirmed_selection"):
            return True
        return False

    def apply_skill(self, side: str, skill: str, params: dict) -> dict:
        with self._lock:
            if not self._is_editing_allowed(side):
                return {"warning": "目前不在編輯階段"}
                
            team_state = self._state[side]
            if team_state["confirmed_edit"]:
                return {"warning": "已確認編輯，無法再使用技能"}
                
            team_id = team_state["team_id"]
            if not team_id:
                return {"warning": "隊伍不存在"}
                
            team = self._get_team(team_id)
            
            if not self._check_card_available(team, skill):
                return {"warning": f"「{skill}」卡片不足！"}

            text_list = copy.deepcopy(team_state["edited_text"])
            
            # Apply transformation
            try:
                new_text_list = self._transform_text(text_list, skill, params)
            except Exception as e:
                return {"warning": f"技能操作失敗: {e}"}

            # Deduct card and apply
            self._deduct_card(team, skill)
                
            team_state["history"].append(copy.deepcopy(team_state["edited_text"]))
            team_state["edited_text"] = new_text_list
            team_state["skill_actions"].append({"skill": skill, "params": params})
            
            return {"success": True}

    def _transform_text(self, text: list, skill: str, params: dict) -> list:
        if skill == "增字":
            pos = params.get("position", 0)
            char = params.get("char", "")
            if not char or len(char) > 1:
                raise ValueError("增字只能包含一個字元")
            pos = max(0, min(pos, len(text)))
            text.insert(pos, {"char": char, "edited": True})
            return text
            
        elif skill == "刪字":
            pos = params.get("position", 0)
            if pos < 0 or pos >= len(text):
                raise ValueError("無效的位置")
            text.pop(pos)
            return text
            
        elif skill == "改字":
            pos = params.get("position", 0)
            new_char = params.get("char", "")
            if not new_char or len(new_char) > 1:
                raise ValueError("改字只能包含一個字元")
            if pos < 0 or pos >= len(text):
                raise ValueError("無效的位置")
            text[pos] = {"char": new_char, "edited": True}
            return text
            
        elif skill == "搬移":
            from_pos = params.get("from_pos", 0)
            to_pos = params.get("to_pos", 0)
            seg_len = self._state["skill_registry"]["搬移"]["params"]["segment_length"]
            
            if from_pos < 0 or from_pos >= len(text):
                raise ValueError("無效的起點位置")
                
            actual_len = min(seg_len, len(text) - from_pos)
            segment = text[from_pos:from_pos+actual_len]
            
            # Mark segment as edited
            for item in segment:
                item["edited"] = True
            
            # Remove segment
            del text[from_pos:from_pos+actual_len]
            
            # Adjust target position if it was after the removed segment
            if to_pos > from_pos:
                to_pos = max(0, to_pos - actual_len)
                
            to_pos = max(0, min(to_pos, len(text)))
            
            # Insert segment
            text = text[:to_pos] + segment + text[to_pos:]
            return text
            
        else:
            raise ValueError(f"未知的技能: {skill}")

    def undo_skill(self, side: str) -> dict:
        with self._lock:
            if not self._is_editing_allowed(side):
                return {"warning": "目前不在編輯階段"}
                
            team_state = self._state[side]
            if team_state["confirmed_edit"]:
                return {"warning": "已確認編輯，無法撤銷"}
                
            if not team_state["skill_actions"] or not team_state.get("history"):
                return {"warning": "沒有可撤銷的操作"}
                
            last_action = team_state["skill_actions"].pop()
            skill = last_action["skill"]
            
            # Refund card
            team_id = team_state["team_id"]
            if team_id:
                team = self._get_team(team_id)
                self._refund_card(team, skill)
            
            # Restore previous state
            team_state["edited_text"] = team_state["history"].pop()
            return {"success": True}

    def check_and_deduct_card(self, side: str, skill: str) -> dict:
        with self._lock:
            if not self._is_editing_allowed(side):
                return {"warning": "目前不在編輯階段"}
                
            team_state = self._state[side]
            if team_state["confirmed_edit"]:
                return {"warning": "已確認編輯，無法再使用技能"}
                
            team_id = team_state["team_id"]
            if not team_id:
                return {"warning": "隊伍不存在"}
                
            team = self._get_team(team_id)
            
            if not self._check_card_available(team, skill):
                return {"warning": f"「{skill}」卡片不足！"}

            # Deduct card temporarily
            self._deduct_card(team, skill)
                
            return {"success": True}

    def refund_card(self, side: str, skill: str):
        with self._lock:
            team_id = self._state[side]["team_id"]
            if team_id:
                team = self._get_team(team_id)
                self._refund_card(team, skill)

    def commit_llm_skill_result(self, side: str, skill: str, new_text: str) -> bool:
        with self._lock:
            if not self._is_editing_allowed(side) or self._state[side]["confirmed_edit"]:
                return False
            team_state = self._state[side]
            team_state["history"].append(copy.deepcopy(team_state["edited_text"]))
            team_state["edited_text"] = [{"char": c, "edited": True} for c in new_text]
            team_state["skill_actions"].append({"skill": skill, "params": {}})
            return True

    def confirm_edit(self, side: str) -> bool:
        with self._lock:
            if self._state["phase"] == PHASE_EDITING:
                self._state[side]["confirmed_edit"] = True
                
            return self.both_edits_confirmed()

    def cancel_confirm_edit(self, side: str):
        with self._lock:
            if self._state["phase"] == PHASE_EDITING:
                self._state[side]["confirmed_edit"] = False

    def both_edits_confirmed(self) -> bool:
        return self._state["team_a"]["confirmed_edit"] and self._state["team_b"]["confirmed_edit"]

    def set_translating_phase(self):
        with self._lock:
            self._state["phase"] = PHASE_TRANSLATING

    def get_plain_edited_text(self, side: str) -> str:
        """Helper to get string version of edited_text for translation"""
        with self._lock:
            return "".join(item["char"] for item in self._state[side]["edited_text"])

    # ─── TRANSLATING ──────────────────────────────────────────────────────

    def update_translation_progress(self, side: str, step: int, total: int, lang: str):
        with self._lock:
            if self._state["phase"] == PHASE_TRANSLATING:
                self._state[side]["translation_progress"] = round(step / total * 100)
                self._state[side]["translation_lang"] = lang

    def set_translation_result(self, side: str, text: str, path: list) -> bool:
        with self._lock:
            if self._state["phase"] != PHASE_TRANSLATING:
                return False
            self._state[side]["translated_text"] = text
            self._state[side]["translation_progress"] = 100
            
            if self.both_translations_done():
                self._state["phase"] = PHASE_ADMIN_REVIEW
            return True

    def both_translations_done(self) -> bool:
        return (self._state["team_a"]["translated_text"] is not None and 
                self._state["team_b"]["translated_text"] is not None)

    # ─── ADMIN REVIEW ─────────────────────────────────────────────────────

    def admin_approve(self, side: str):
        with self._lock:
            if self._state["phase"] == PHASE_ADMIN_REVIEW:
                self._state[side]["admin_approved"] = True
                if self.both_approved():
                    self._state["phase"] = PHASE_GUESSING

    def admin_reject(self, side: str):
        with self._lock:
            if self._state["phase"] == PHASE_ADMIN_REVIEW:
                self._state[side]["admin_approved"] = False
                self._state[side]["translated_text"] = None
                self._state[side]["translation_progress"] = 0
                self._state[side]["translation_lang"] = ""
                self._state["phase"] = PHASE_TRANSLATING

    def both_approved(self) -> bool:
        return self._state["team_a"]["admin_approved"] and self._state["team_b"]["admin_approved"]

    # ─── GUESSING ─────────────────────────────────────────────────────────

    def get_guess_data(self, side: str) -> dict:
        """Returns the OTHER team's translated text and options for guessing."""
        with self._lock:
            other_side = self.side_b if side == self.side_a else self.side_a
            other_state = self._state[other_side]
            
            return {
                "translated_text": other_state["translated_text"],
                "options": other_state["topic"]["texts"] if other_state["topic"] else []
            }

    def submit_guess(self, side: str, choice_idx: int):
        with self._lock:
            if self._state["phase"] == PHASE_GUESSING:
                self._state[side]["guess_choice"] = choice_idx
                
                if self.both_guessed():
                    self.resolve_round()

    def both_guessed(self) -> bool:
        return (self._state[self.side_a]["guess_choice"] is not None and 
                self._state[self.side_b]["guess_choice"] is not None)

    # ─── RESULT ───────────────────────────────────────────────────────────

    def resolve_round(self):
        """Evaluate guesses and award scores."""
        # team_a guesses team_b's text
        correct_for_a = self._state[self.side_b]["correct_index"]
        guess_by_a = self._state[self.side_a]["guess_choice"]
        is_a_correct = (guess_by_a == correct_for_a)
        
        self._state[self.side_a]["guess_correct"] = is_a_correct
        
        # team_b guesses team_a's text
        correct_for_b = self._state[self.side_a]["correct_index"]
        guess_by_b = self._state[self.side_b]["guess_choice"]
        is_b_correct = (guess_by_b == correct_for_b)
        
        self._state[self.side_b]["guess_correct"] = is_b_correct

        # Score logic: 
        # Guess correct -> Guesser +1
        # Guess wrong -> No points awarded
        
        team_a_id = self._state[self.side_a]["team_id"]
        team_b_id = self._state[self.side_b]["team_id"]
        
        if team_a_id:
            team_a_data = self._get_team(team_a_id)
            if is_a_correct:
                team_a_data["score"] += 1
                    
        if team_b_id:
            team_b_data = self._get_team(team_b_id)
            if is_b_correct:
                team_b_data["score"] += 1

        self._state["phase"] = PHASE_RESULT
        self.end_game_lock() # Release lock so next game can start later

    def confirm_result(self, side: str) -> bool:
        with self._lock:
            if self._state["phase"] == PHASE_RESULT:
                self._state[side]["confirmed_result"] = True
                return self._state[self.side_a]["confirmed_result"] and self._state[self.side_b]["confirmed_result"]
        return False

    def next_round(self):
        with self._lock:
            self._state["round_number"] += 1
            team_a_id = self._state[self.side_a]["team_id"]
            team_b_id = self._state[self.side_b]["team_id"]
            
            self._state[self.side_a] = _empty_team_round()
            self._state[self.side_b] = _empty_team_round()
            
            self._state[self.side_a]["team_id"] = team_a_id
            self._state[self.side_b]["team_id"] = team_b_id
            
            self._state["phase"] = PHASE_LOBBY

    # ─── ADMIN CONTROLS ───────────────────────────────────────────────────

    def admin_set_card_count(self, team_id: str, skill: str, count: int):
        with self._lock:
            team = self._get_team(team_id)
            info = self._state["skill_registry"].get(skill)
            if info and info.get("category") == "ai":
                team["ai_skill_uses"] = count
            else:
                team["cards"][skill] = count

    def admin_set_score(self, team_id: str, score: int):
        with self._lock:
            self._get_team(team_id)["score"] = score

    def admin_set_translation_count(self, count: int):
        with self._lock:
            self._state["translation_count"] = max(1, min(30, count))
            
    def admin_set_skill_param(self, skill: str, param: str, value):
        with self._lock:
            if skill in self._state["skill_registry"] and param in self._state["skill_registry"][skill]["params"]:
                self._state["skill_registry"][skill]["params"][param] = value

    def admin_set_auto_review(self, enabled: bool):
        with self._lock:
            self._state["auto_review"] = enabled

    def admin_set_skill_percent_mode(self, enabled: bool, values: dict = None, ai_value: int = 3):
        with self._lock:
            self._state["skill_percent_mode"] = enabled
            if values:
                self._state["skill_percent_values"] = values
            self._state["ai_skill_percent_value"] = ai_value

    def admin_reset(self):
        self.end_game_lock()
        self.reset(full=True)

    def admin_terminate(self, reason: str = ""):
        """緊急終止遊戲。"""
        self.end_game_lock()
        with self._lock:
            self._state["phase"] = PHASE_TERMINATED
            self._state["terminate_reason"] = reason

# Singleton

# --- Multi-match GameManager (Feature 6) ---

SIDE_TO_MATCH = {
    "team_a": ("ab", "team_a"),
    "team_b": ("ab", "team_b"),
    "team_c": ("cd", "team_a"),
    "team_d": ("cd", "team_b"),
    "team_e": ("ef", "team_a"),
    "team_f": ("ef", "team_b"),
    "team_g": ("gh", "team_a"),
    "team_h": ("gh", "team_b"),
}

MATCH_TO_SIDES = {
    "ab": ("team_a", "team_b"),
    "cd": ("team_c", "team_d"),
    "ef": ("team_e", "team_f"),
    "gh": ("team_g", "team_h"),
}

class GameManager:
    def __init__(self):
        self.questions = _load_questions()
        self.matches = {
            "ab": MatchState("ab", "team_a", "team_b", self.questions),
            "cd": MatchState("cd", "team_a", "team_b", self.questions),
            "ef": MatchState("ef", "team_a", "team_b", self.questions),
            "gh": MatchState("gh", "team_a", "team_b", self.questions),
        }
        
    def get_match_and_side(self, side: str):
        if side not in SIDE_TO_MATCH:
            raise ValueError(f"Invalid side: {side}")
        match_id, internal_side = SIDE_TO_MATCH[side]
        return self.matches[match_id], internal_side

    def get_match_by_id(self, match_id: str):
        return self.matches.get(match_id)

    def get_all_states(self) -> dict:
        return {mid: m.get_state() for mid, m in self.matches.items()}

game_state_v2 = GameManager()
