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
    },
    "刪字": {
        "id": "delete_char",
        "name": "刪字",
        "description": "刪除文本中的任意一個字",
        "default_count": 3,
        "params": {},
        "icon": "✂️",
    },
    "搬移": {
        "id": "move_segment",
        "name": "搬移",
        "description": "將一段特定長度的連續文字搬移到文本的另一位置",
        "default_count": 1,
        "params": {"segment_length": 10},
        "icon": "🔀",
    },
}

PHASE_LOBBY = "LOBBY"
PHASE_SELECTING_TEXT = "SELECTING_TEXT"
PHASE_EDITING = "EDITING"
PHASE_TRANSLATING = "TRANSLATING"
PHASE_ADMIN_REVIEW = "ADMIN_REVIEW"
PHASE_GUESSING = "GUESSING"
PHASE_RESULT = "RESULT"

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
        "skill_actions": [],     # list of dicts: {"skill": "...", "params": {...}}
        "translated_text": None, # string
        "translation_progress": 0,
        "translation_lang": "",
        "admin_approved": False,
        "guess_choice": None,    # int
        "guess_correct": None,   # bool
    }

class GameStateV2:
    def __init__(self):
        self._lock = threading.Lock()
        self._game_lock = threading.Lock()
        self.questions = self._load_questions()
        self._state = {}
        self.reset(full=True)

    def _load_questions(self) -> list:
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

    def _get_team(self, team_id) -> dict:
        key = str(team_id)
        if key not in self._state["teams"]:
            cards = {name: info["default_count"] for name, info in self._state["skill_registry"].items()}
            self._state["teams"][key] = {
                "score": 0,
                "cards": cards,
            }
        return self._state["teams"][key]

    def reset(self, full: bool = False):
        with self._lock:
            preserved_teams = {} if full else copy.deepcopy(self._state.get("teams", {}))
            preserved_count = 10 if full else self._state.get("translation_count", 10)
            preserved_registry = copy.deepcopy(SKILL_REGISTRY) if full else copy.deepcopy(self._state.get("skill_registry", SKILL_REGISTRY))
            
            # preserve team IDs in lobby if not full reset
            team_a_id = None
            team_b_id = None
            if not full and "team_a" in self._state:
                team_a_id = self._state["team_a"]["team_id"]
                team_b_id = self._state["team_b"]["team_id"]

            team_a_state = _empty_team_round()
            team_b_state = _empty_team_round()
            
            team_a_state["team_id"] = team_a_id
            team_b_state["team_id"] = team_b_id

            self._state = {
                "phase": PHASE_LOBBY,
                "round_number": 1 if full else self._state.get("round_number", 1),
                "translation_count": preserved_count,
                "team_a": team_a_state,
                "team_b": team_b_state,
                "teams": preserved_teams,
                "skill_registry": preserved_registry,
            }

    def get_state(self) -> dict:
        with self._lock:
            state = copy.deepcopy(self._state)

        for side in ("team_a", "team_b"):
            tid = state[side].get("team_id")
            if tid is not None:
                team = state["teams"].get(str(tid), {})
                state[side]["score"] = team.get("score", 0)
                state[side]["cards"] = copy.deepcopy(team.get("cards", {}))
            else:
                state[side]["score"] = 0
                state[side]["cards"] = {}
        return state

    def get_filtered_state(self, requester_side: str) -> dict:
        """Filter out sensitive information based on the requester's side."""
        state = self.get_state()
        other_side = "team_b" if requester_side == "team_a" else "team_a"
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

            other_side = "team_b" if side == "team_a" else "team_a"
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
            return s["team_a"]["ready"] and s["team_b"]["ready"] and s["phase"] == PHASE_LOBBY

    def start_game(self) -> bool:
        if not self._game_lock.acquire(blocking=False):
            return False # Another game is starting/running

        with self._lock:
            if not self.questions:
                self._game_lock.release()
                return False
                
            for side in ("team_a", "team_b"):
                topic = random.choice(self.questions)
                self._state[side]["topic"] = topic
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
            if self._state["team_a"]["confirmed_selection"] and self._state["team_b"]["confirmed_selection"]:
                self._transition_to_editing()
                return {"success": True, "phase_changed": True}
                
            return {"success": True, "phase_changed": False}

    def _transition_to_editing(self):
        for side in ("team_a", "team_b"):
            st = self._state[side]
            topic = st["topic"]
            selected_id = st["selected_text_id"]
            
            # Find the chosen text
            for idx, text_obj in enumerate(topic["texts"]):
                if text_obj["id"] == selected_id:
                    st["attack_text"] = text_obj
                    st["correct_index"] = idx
                    st["original_text"] = text_obj["original"]
                    # Initialize edited_text as list of dicts
                    st["edited_text"] = [{"char": c, "edited": False} for c in text_obj["original"]]
                    break
                    
            st["skill_actions"] = []
            st["confirmed_edit"] = False
            
        self._state["phase"] = PHASE_EDITING


    # ─── EDITING ──────────────────────────────────────────────────────────

    def apply_skill(self, side: str, skill: str, params: dict) -> dict:
        with self._lock:
            if self._state["phase"] != PHASE_EDITING:
                return {"warning": "目前不在編輯階段"}
                
            team_state = self._state[side]
            if team_state["confirmed_edit"]:
                return {"warning": "已確認編輯，無法再使用技能"}
                
            team_id = team_state["team_id"]
            if not team_id:
                return {"warning": "隊伍不存在"}
                
            team = self._get_team(team_id)
            cards = team["cards"]
            
            if skill not in cards or cards[skill] == 0:
                return {"warning": f"「{skill}」卡片不足！"}

            text_list = copy.deepcopy(team_state["edited_text"])
            
            # Apply transformation
            try:
                new_text_list = self._transform_text(text_list, skill, params)
            except Exception as e:
                return {"warning": f"技能操作失敗: {e}"}

            # Deduct card and apply
            if cards[skill] > 0:
                cards[skill] -= 1
                
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
            if self._state["phase"] != PHASE_EDITING:
                return {"warning": "目前不在編輯階段"}
                
            team_state = self._state[side]
            if team_state["confirmed_edit"]:
                return {"warning": "已確認編輯，無法撤銷"}
                
            if not team_state["skill_actions"]:
                return {"warning": "沒有可撤銷的操作"}
                
            last_action = team_state["skill_actions"].pop()
            skill = last_action["skill"]
            
            # Refund card
            team_id = team_state["team_id"]
            if team_id:
                team = self._get_team(team_id)
                if skill in team["cards"] and team["cards"][skill] != -1:
                    team["cards"][skill] += 1
            
            # Reconstruct text from original
            text = [{"char": c, "edited": False} for c in team_state["original_text"]]
            for action in team_state["skill_actions"]:
                text = self._transform_text(text, action["skill"], action["params"])
                
            team_state["edited_text"] = text
            return {"success": True}

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

    def set_translation_result(self, side: str, text: str, path: list):
        with self._lock:
            self._state[side]["translated_text"] = text
            self._state[side]["translation_progress"] = 100
            
            if self.both_translations_done():
                self._state["phase"] = PHASE_ADMIN_REVIEW

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
            other_side = "team_b" if side == "team_a" else "team_a"
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
        return (self._state["team_a"]["guess_choice"] is not None and 
                self._state["team_b"]["guess_choice"] is not None)

    # ─── RESULT ───────────────────────────────────────────────────────────

    def resolve_round(self):
        """Evaluate guesses and award scores."""
        # team_a guesses team_b's text
        correct_for_a = self._state["team_b"]["correct_index"]
        guess_by_a = self._state["team_a"]["guess_choice"]
        is_a_correct = (guess_by_a == correct_for_a)
        
        self._state["team_a"]["guess_correct"] = is_a_correct
        
        # team_b guesses team_a's text
        correct_for_b = self._state["team_a"]["correct_index"]
        guess_by_b = self._state["team_b"]["guess_choice"]
        is_b_correct = (guess_by_b == correct_for_b)
        
        self._state["team_b"]["guess_correct"] = is_b_correct

        # Score logic: 
        # Guess correct -> Guesser +1
        # Guess wrong -> No points awarded
        
        team_a_id = self._state["team_a"]["team_id"]
        team_b_id = self._state["team_b"]["team_id"]
        
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
                return self._state["team_a"]["confirmed_result"] and self._state["team_b"]["confirmed_result"]
        return False

    def next_round(self):
        with self._lock:
            self._state["round_number"] += 1
            team_a_id = self._state["team_a"]["team_id"]
            team_b_id = self._state["team_b"]["team_id"]
            
            self._state["team_a"] = _empty_team_round()
            self._state["team_b"] = _empty_team_round()
            
            self._state["team_a"]["team_id"] = team_a_id
            self._state["team_b"]["team_id"] = team_b_id
            
            self._state["phase"] = PHASE_LOBBY

    # ─── ADMIN CONTROLS ───────────────────────────────────────────────────

    def admin_set_card_count(self, team_id: str, skill: str, count: int):
        with self._lock:
            self._get_team(team_id)["cards"][skill] = count

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

    def admin_reset(self):
        self.end_game_lock()
        self.reset(full=True)

# Singleton
game_state_v2 = GameStateV2()
