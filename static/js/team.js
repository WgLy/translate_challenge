/**
 * team.js - Frontend logic for Team Page
 */

// Connect to Socket.IO backend, forcing polling if proxy blocks WebSockets
const socket = io({ 
    path: '/ai_translate/socket.io',
    transports: ['polling']
});

// Auto-detect side from URL path
let pathSide = window.location.pathname.split('/').pop();
let realSide = 'team_' + pathSide;
let mySide = ['a', 'c', 'e', 'g'].includes(pathSide) ? 'team_a' : 'team_b';

// State
let gameState = null;
let editingMode = null; // null, 'add', 'delete', 'move-select', 'move-place'
let moveSourcePos = -1;
let skillParams = {};
let isCastingAiSkill = false;

// DOM Elements
const ui = {
    badges: {
        phase: document.getElementById('phase-badge'),
        round: document.getElementById('round-badge'),
    },
    conn: {
        dot: document.getElementById('conn-dot'),
        text: document.getElementById('conn-text'),
    },
    scores: {
        aId: document.getElementById('score-team-a-id'),
        aVal: document.getElementById('score-a'),
        bId: document.getElementById('score-team-b-id'),
        bVal: document.getElementById('score-b'),
    },
    panels: {
        lobby: document.getElementById('phase-lobby'),
        selecting: document.getElementById('phase-selecting-text'),
        editing: document.getElementById('phase-editing'),
        translating: document.getElementById('phase-translating'),
        adminReview: document.getElementById('phase-admin-review'),
        guessing: document.getElementById('phase-guessing'),
        result: document.getElementById('phase-result'),
        terminated: document.getElementById('phase-terminated'),
    },
    lobby: {
        slot: document.getElementById('my-lobby-slot'),
        label: document.getElementById('my-slot-label'),
        input: document.getElementById('my-input-team'),
        btnReady: document.getElementById('my-btn-ready'),
        btnCancel: document.getElementById('my-btn-cancel'),
        indicator: document.getElementById('my-ready-indicator'),
    },
    select: {
        theme: document.getElementById('select-topic-theme'),
        container: document.getElementById('select-options-container'),
        btnConfirm: document.getElementById('btn-confirm-selection'),
        waitStatus: document.getElementById('selection-wait-status'),
    },
    edit: {
        topic: document.getElementById('edit-topic'),
        original: document.getElementById('edit-original'),
        skills: document.getElementById('skill-panel'),
        instruction: document.getElementById('skill-instruction'),
        display: document.getElementById('text-display'),
        history: document.getElementById('action-history'),
        count: document.getElementById('action-count'),
        confirmBar: document.getElementById('edit-confirm-bar'),
        btnConfirm: document.getElementById('btn-confirm-edit'),
        btnCancel: document.getElementById('btn-cancel-confirm'),
        oppStatus: document.getElementById('opponent-edit-status'),
        popover: document.getElementById('char-popover'),
        charInput: document.getElementById('char-input'),
    },
    trans: {
        a: { pct: document.getElementById('trans-percent-a'), bar: document.getElementById('trans-bar-a'), lang: document.getElementById('trans-lang-a') },
        b: { pct: document.getElementById('trans-percent-b'), bar: document.getElementById('trans-bar-b'), lang: document.getElementById('trans-lang-b') },
    },
    review: {
        a: document.getElementById('review-badge-a'),
        b: document.getElementById('review-badge-b'),
    },
    guess: {
        text: document.getElementById('guess-translated-text'),
        grid: document.getElementById('guess-grid'),
        btn: document.getElementById('btn-submit-guess'),
        oppStatus: document.getElementById('opponent-guess-status'),
    },
    result: {
        a: { icon: document.getElementById('result-icon-a'), id: document.getElementById('result-team-a-id'), detail: document.getElementById('result-detail-a') },
        b: { icon: document.getElementById('result-icon-b'), id: document.getElementById('result-team-b-id'), detail: document.getElementById('result-detail-b') },
    }
};

// ─── CONNECTION ──────────────────────────────────────────────────────────────

socket.on('connect', () => {
    ui.conn.dot.className = 'pulse-dot green';
    ui.conn.text.innerText = '已連線';
    socket.emit('join_role', { role: realSide });
});

socket.on('disconnect', () => {
    ui.conn.dot.className = 'pulse-dot red';
    ui.conn.text.innerText = '連線中斷';
});

// ─── STATE UPDATE ────────────────────────────────────────────────────────────

socket.on('state_update', (state) => {
    gameState = state;
    updateUI();
});

socket.on('notification', (data) => {
    showToast(data.message, data.type);
});

socket.on('translation_progress', (data) => {
    const p = ui.trans[data.side === 'team_a' ? 'a' : 'b'];
    p.pct.innerText = `${data.percent}%`;
    p.bar.style.width = `${data.percent}%`;
    p.lang.innerText = data.lang;
});

// ─── UI UPDATES ──────────────────────────────────────────────────────────────

function updateUI() {
    if (!gameState) return;
    isCastingAiSkill = false;

    ui.badges.phase.innerText = gameState.phase;
    ui.badges.round.innerText = `R${gameState.round_number}`;

    updateScoreBar();
    
    // Hide all panels, show current
    Object.values(ui.panels).forEach(p => {
        if(p) p.classList.add('hidden');
    });
    
    // Check timer reconnect
    if (gameState.timer_running && gameState.timer_start_timestamp && !timerInterval) {
        startCountdown(gameState.timer_seconds, gameState.timer_start_timestamp);
    } else if (!gameState.timer_running && timerInterval) {
        stopCountdown();
    }

    if (gameState.phase === 'LOBBY') {
        ui.panels.lobby.classList.remove('hidden');
        updateLobby();
    } else {
        let activePhase = gameState.phase;
        if (activePhase === 'SELECTING_TEXT' && gameState.timer_enabled && gameState[mySide].confirmed_selection) {
            activePhase = 'EDITING';
        }
        
        switch (activePhase) {
            case 'SELECTING_TEXT':
                ui.panels.selecting.classList.remove('hidden');
                updateSelecting();
                break;
            case 'EDITING':
                ui.panels.editing.classList.remove('hidden');
                updateEditing();
                break;
            case 'TRANSLATING':
                ui.panels.translating.classList.remove('hidden');
                ['team_a', 'team_b'].forEach(side => {
                    const k = side === 'team_a' ? 'a' : 'b';
                    const prog = gameState[side].translation_progress;
                    ui.trans[k].pct.innerText = `${prog}%`;
                    ui.trans[k].bar.style.width = `${prog}%`;
                    ui.trans[k].lang.innerText = gameState[side].translation_lang || (prog === 100 ? "翻譯完成" : "準備中...");
                });
                break;
            case 'ADMIN_REVIEW':
                ui.panels.adminReview.classList.remove('hidden');
                updateAdminReviewWait();
                break;
            case 'GUESSING':
                ui.panels.guessing.classList.remove('hidden');
                updateGuessing();
                break;
            case 'RESULT':
                ui.panels.result.classList.remove('hidden');
                updateResult();
                break;
            case 'TERMINATED':
                if (ui.panels.terminated) {
                    ui.panels.terminated.classList.remove('hidden');
                }
                const reason = gameState.terminate_reason || '管理員終止了遊戲';
                const reasonEl = document.getElementById('terminate-reason');
                if (reasonEl) reasonEl.textContent = reason;
                clearMode();
                break;
        }
    }
}

function updateScoreBar() {
    ui.scores.aId.innerText = gameState.team_a.team_id || '?';
    ui.scores.bId.innerText = gameState.team_b.team_id || '?';
    ui.scores.aVal.innerText = gameState.team_a.score;
    ui.scores.bVal.innerText = gameState.team_b.score;
    
    const matchIdToLabels = {
        "ab": ["TEAM A", "TEAM B"],
        "cd": ["TEAM C", "TEAM D"],
        "ef": ["TEAM E", "TEAM F"],
        "gh": ["TEAM G", "TEAM H"]
    };
    const currentMatchId = ["a", "b"].includes(pathSide) ? "ab" :
                         ["c", "d"].includes(pathSide) ? "cd" :
                         ["e", "f"].includes(pathSide) ? "ef" : "gh";
    const labels = matchIdToLabels[currentMatchId] || ["TEAM A", "TEAM B"];
    const labelA = document.getElementById('score-team-a-label');
    const labelB = document.getElementById('score-team-b-label');
    if (labelA) labelA.innerText = labels[0];
    if (labelB) labelB.innerText = labels[1];
    
    const transLabelA = document.getElementById('trans-label-a');
    const transLabelB = document.getElementById('trans-label-b');
    if (transLabelA) transLabelA.innerText = `${labels[0]} 翻譯中...`;
    if (transLabelB) transLabelB.innerText = `${labels[1]} 翻譯中...`;
}

// ─── PHASE: LOBBY ────────────────────────────────────────────────────────────

function updateLobby() {
    const state = gameState[mySide];

    ui.lobby.label.innerText = 'Team ' + pathSide.toUpperCase();
    ui.lobby.label.style.color = mySide === 'team_a' ? 'var(--team-a-color)' : 'var(--team-b-color)';
    ui.lobby.slot.classList.add(mySide === 'team_a' ? 'team-a' : 'team-b');

    if (state.ready) {
        ui.lobby.input.value = state.team_id;
        ui.lobby.input.disabled = true;
        ui.lobby.indicator.className = 'ready-indicator ready';
        ui.lobby.indicator.innerHTML = '✅ 已準備';
        
        ui.lobby.btnReady.classList.add('hidden');
        ui.lobby.btnCancel.classList.remove('hidden');
    } else {
        ui.lobby.input.disabled = false;
        ui.lobby.indicator.className = 'ready-indicator waiting';
        ui.lobby.indicator.innerHTML = '<div class="pulse-dot amber"></div><span>等待中</span>';
        
        ui.lobby.btnReady.classList.remove('hidden');
        ui.lobby.btnCancel.classList.add('hidden');
    }
}

window.setReady = function() {
    const teamId = ui.lobby.input.value.trim();
    
    if (teamId === "") {
        showToast('請輸入小隊編號', 'warning');
        return;
    }
    
    const val = parseInt(teamId);
    if (isNaN(val) || val < 0 || val > 1000) {
        showToast('小隊編號必須在 0 到 1000 之間', 'warning');
        return;
    }
    
    socket.emit('set_ready', { side: mySide, team_id: val });
};

window.cancelReady = function() {
    socket.emit('cancel_ready', { side: mySide });
};

// ─── PHASE: SELECTING TEXT ───────────────────────────────────────────────────

function updateSelecting() {
    const st = gameState[mySide];
    if (!st.topic) return;

    ui.select.theme.innerText = st.topic.theme;
    
    // Only rebuild if not already built or topic changed
    if (ui.select.container.dataset.theme !== st.topic.theme) {
        ui.select.container.innerHTML = '';
        st.topic.texts.forEach(t => {
            const opt = document.createElement('div');
            opt.className = 'text-option';
            opt.dataset.id = t.id;
            opt.innerText = t.original;
            opt.onclick = () => {
                if (st.confirmed_selection) return;
                socket.emit('select_text', { side: mySide, text_id: t.id });
            };
            ui.select.container.appendChild(opt);
        });
        ui.select.container.dataset.theme = st.topic.theme;
    }
    
    // Update selection UI
    document.querySelectorAll('.text-option').forEach(el => {
        if (el.dataset.id === st.selected_text_id) {
            el.classList.add('selected');
        } else {
            el.classList.remove('selected');
        }
    });
    
    if (st.confirmed_selection) {
        ui.select.btnConfirm.disabled = true;
        ui.select.waitStatus.classList.remove('hidden');
        ui.select.container.style.pointerEvents = 'none';
        ui.select.container.style.opacity = '0.7';
    } else {
        ui.select.btnConfirm.disabled = !st.selected_text_id;
        ui.select.waitStatus.classList.add('hidden');
        ui.select.container.style.pointerEvents = 'auto';
        ui.select.container.style.opacity = '1';
    }
}

window.confirmSelection = function() {
    socket.emit('confirm_selection', { side: mySide });
};

// ─── PHASE: EDITING ──────────────────────────────────────────────────────────

function updateEditing() {
    const myState = gameState[mySide];
    const oppState = gameState[mySide === 'team_a' ? 'team_b' : 'team_a'];
    const locked = myState.confirmed_edit;

    if (editingMode) {
        const myCards = myState.cards || {};
        const skillName = skillParams.skillName;
        const count = skillName === 'AI_SHARED' ? (myState.ai_skill_uses || 0) : (myCards[skillName] || 0);
        if (count <= 0) {
            clearMode();
        }
    }

    // Topic & Original
    if (myState.topic) {
        ui.edit.topic.innerText = myState.topic.theme;
        ui.edit.original.innerText = myState.original_text;
    }

    // Opponent status
    if (oppState.confirmed_edit) {
        ui.edit.oppStatus.innerHTML = '✅ 對方已確認';
        ui.edit.oppStatus.style.borderColor = 'var(--green)';
        ui.edit.oppStatus.style.color = 'var(--green)';
    } else {
        ui.edit.oppStatus.innerHTML = '<div class="pulse-dot amber"></div><span>對方編輯中</span>';
        ui.edit.oppStatus.style.borderColor = '';
        ui.edit.oppStatus.style.color = '';
    }

    // Render Skills
    ui.edit.skills.innerHTML = '';
    const myCards = myState.cards || {};
    const registry = gameState.skill_registry || {};
    const aiRemaining = myState.ai_skill_uses || 0;
    
    ['增字', '刪字', '改字', '搬移', '批量修改', '摘要', '誇飾', '插入名詞', '混亂語序'].forEach(skillName => {
        const info = registry[skillName];
        if (!info) return;
        
        const isAi = info.category === 'ai';
        const count = isAi ? aiRemaining : (myCards[skillName] || 0);
        if (count === 0) return; // Hide card if count is 0
        
        const isDisabled = locked || isCastingAiSkill;
        const isActive = editingMode === info.id;
        
        const card = document.createElement('div');
        card.className = `skill-card ${isDisabled ? 'disabled' : ''} ${isActive ? 'active' : ''}`;
        card.dataset.skill = skillName;
        
        let countText = `剩 ${count} 張`;
        if (isAi) {
            countText = `共享 (剩 ${count} 次)`;
            card.classList.add('ai-skill-card');
        }
        
        card.innerHTML = `
            <div class="skill-icon">${info.icon}</div>
            <div class="skill-name">${info.name}</div>
            <div class="skill-count">${countText}</div>
        `;
        
        if (!isDisabled) {
            // LLM skills trigger immediately, char skills require mode
            if (isAi) {
                card.onclick = () => {
                    if (isCastingAiSkill) return;
                    isCastingAiSkill = true;
                    updateEditing();
                    skillParams = { skillName: 'AI_SHARED' };
                    socket.emit('apply_skill', { side: mySide, skill: skillName, params: {} });
                };
            } else {
                card.onclick = () => toggleSkillMode(info.id, skillName);
            }
        }
        ui.edit.skills.appendChild(card);
    });

    // Render Action History
    ui.edit.history.innerHTML = '';
    ui.edit.count.innerText = `${myState.skill_actions.length} 次操作`;
    
    if (myState.skill_actions.length === 0) {
        ui.edit.history.innerHTML = '<div class="text-muted text-center" style="font-size:0.82rem; padding:8px;">尚無操作</div>';
    } else {
        myState.skill_actions.forEach((action, idx) => {
            const el = document.createElement('div');
            el.className = 'action-item';
            
            let desc = '';
            if (action.skill === '增字') desc = `插入 "${action.params.char}" 於 ${action.params.position}`;
            else if (action.skill === '刪字') desc = `刪除字元於 ${action.params.position}`;
            else if (action.skill === '搬移') desc = `搬移文字從 ${action.params.from_pos} 到 ${action.params.to_pos}`;
            else if (action.skill === '批量修改') desc = `將 "${action.params.target}" 批量替換為 "${action.params.replacement}"`;
            else desc = `使用 AI 修改文字`;
            
            el.innerHTML = `
                <div class="action-desc">
                    <span style="color:var(--cyan)">[${action.skill}]</span> ${desc}
                </div>
                ${!locked && !isCastingAiSkill && idx === myState.skill_actions.length - 1 ? 
                  `<div class="action-undo" onclick="undoSkill()">↩️ 復原</div>` : ''}
            `;
            ui.edit.history.appendChild(el);
        });
        ui.edit.history.scrollTop = ui.edit.history.scrollHeight;
    }

    // Render Text Cells
    renderTextCells(myState.edited_text, locked || isCastingAiSkill);

    // Confirm Buttons
    if (locked) {
        ui.edit.btnConfirm.classList.add('hidden');
        ui.edit.btnCancel.classList.remove('hidden');
        ui.edit.skills.style.pointerEvents = 'none';
        ui.edit.skills.style.opacity = '0.5';
        setSkillInstruction('已鎖定，等待對方確認');
        clearMode();
    } else {
        ui.edit.btnConfirm.classList.remove('hidden');
        ui.edit.btnCancel.classList.add('hidden');
        
        ui.edit.skills.style.pointerEvents = isCastingAiSkill ? 'none' : 'auto';
        ui.edit.skills.style.opacity = isCastingAiSkill ? '0.5' : '1';
        
        if (isCastingAiSkill) {
            setSkillInstruction('正在施放 AI 技能，請稍候...');
            ui.edit.btnConfirm.disabled = true;
        } else {
            ui.edit.btnConfirm.disabled = false;
        }
        ui.edit.skills.style.pointerEvents = 'auto';
        ui.edit.skills.style.opacity = '1';
        if (!editingMode) {
            setSkillInstruction('請選擇要使用的技能卡');
        }
    }
}

function toggleSkillMode(modeId, skillName) {
    if (skillName === '批量修改') {
        openBatchModal();
        return;
    }
    if (editingMode === modeId) {
        clearMode();
        updateEditing(); // re-render to clear active classes
        return;
    }
    
    editingMode = modeId;
    skillParams = { skillName: skillName };
    moveSourcePos = -1;
    
    if (modeId === 'add_char') setSkillInstruction('請點擊文本中你想插入文字的位置（連續模式）');
    if (modeId === 'delete_char') setSkillInstruction('請點擊想刪除的文字（連續模式）');
    if (modeId === 'replace_char') setSkillInstruction('請點擊想修改的文字（連續模式）');
    if (modeId === 'move_segment') {
        const len = gameState.skill_registry['搬移'].params.segment_length;
        skillParams.segLen = len;
        setSkillInstruction(`請點選你想搬移文字的起點（將選取 ${len} 個字）`);
    }
    
    ui.edit.popover.classList.remove('show'); // Hide popover if open
    updateEditing();
}

function clearMode() {
    editingMode = null;
    moveSourcePos = -1;
    skillParams = {};
    ui.edit.popover.classList.remove('show');
}

function setSkillInstruction(msg) {
    ui.edit.instruction.innerText = msg;
}

function renderTextCells(textArray, locked) {
    const container = ui.edit.display;
    container.innerHTML = '';
    container.className = 'text-display'; // reset
    
    if (!textArray || textArray.length === 0) return;
    
    if (!locked && editingMode) {
        if (editingMode === 'delete_char') container.classList.add('mode-delete');
        if (editingMode === 'add_char') container.classList.add('mode-add');
        if (editingMode === 'replace_char') container.classList.add('mode-replace');
        if (editingMode === 'move_segment') {
            if (moveSourcePos === -1) container.classList.add('mode-move-select');
            else container.classList.add('mode-move-place');
        }
    }

    // Always add a leading cursor for inserts at index 0
    if (!locked && (editingMode === 'add_char' || (editingMode === 'move_segment' && moveSourcePos !== -1))) {
        const c0 = document.createElement('div');
        c0.className = 'insert-cursor';
        c0.onclick = (e) => handleInsertClick(0, e);
        container.appendChild(c0);
    }

    for (let i = 0; i < textArray.length; i++) {
        const charObj = textArray[i];
        
        if (charObj.char === '\n') {
            const br = document.createElement('div');
            br.className = 'char-newline';
            container.appendChild(br);
            
            // Add cursor after newline
            if (!locked && (editingMode === 'add_char' || (editingMode === 'move_segment' && moveSourcePos !== -1))) {
                const c = document.createElement('div');
                c.className = 'insert-cursor';
                c.onclick = (e) => handleInsertClick(i+1, e);
                container.appendChild(c);
            }
            continue;
        }

        const cell = document.createElement('div');
        cell.className = 'char-cell';
        if (charObj.edited) {
            cell.classList.add('edited'); // Apply yellow highlight for edited chars
        }
        cell.innerText = charObj.char;
        
        // Highlight logic for move source
        if (editingMode === 'move_segment' && moveSourcePos !== -1) {
            const actualLen = Math.min(skillParams.segLen, textArray.length - moveSourcePos);
            if (i >= moveSourcePos && i < moveSourcePos + actualLen) {
                cell.classList.add('move-selected');
            }
        }
        
        // Click handlers
        if (!locked) {
            cell.onclick = (e) => handleCellClick(i, e);
        }
        
        container.appendChild(cell);

        // Add cursor after char
        if (!locked && (editingMode === 'add_char' || (editingMode === 'move_segment' && moveSourcePos !== -1))) {
            const c = document.createElement('div');
            c.className = 'insert-cursor';
            c.onclick = (e) => handleInsertClick(i+1, e);
            container.appendChild(c);
        }
    }
}

function handleCellClick(index, e) {
    if (editingMode === 'delete_char') {
        socket.emit('apply_skill', { side: mySide, skill: '刪字', params: { position: index } });
    } else if (editingMode === 'replace_char') {
        skillParams.position = index;
        
        // Show popover near click
        const rect = e.target.getBoundingClientRect();
        ui.edit.popover.style.left = `${rect.left - 30}px`;
        ui.edit.popover.style.top = `${rect.bottom + 10}px`;
        ui.edit.popover.classList.add('show');
        ui.edit.charInput.value = '';
        ui.edit.charInput.focus();
    } else if (editingMode === 'move_segment' && moveSourcePos === -1) {
        moveSourcePos = index;
        setSkillInstruction('請點擊游標，選擇要插入的位置');
        updateEditing(); // re-render to show selection and cursors
    }
}

function handleInsertClick(index, e) {
    // Highlight cursor
    document.querySelectorAll('.insert-cursor').forEach(c => c.classList.remove('active'));
    e.target.classList.add('active');

    if (editingMode === 'add_char') {
        skillParams.position = index;
        
        // Show popover near click
        const rect = e.target.getBoundingClientRect();
        ui.edit.popover.style.left = `${rect.left - 30}px`;
        ui.edit.popover.style.top = `${rect.bottom + 10}px`;
        ui.edit.popover.classList.add('show');
        ui.edit.charInput.value = '';
        ui.edit.charInput.focus();
    } else if (editingMode === 'move_segment' && moveSourcePos !== -1) {
        socket.emit('apply_skill', { 
            side: mySide, 
            skill: '搬移', 
            params: { from_pos: moveSourcePos, to_pos: index } 
        });
        clearMode();
    }
}

// Add char input handler
ui.edit.charInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
        const char = ui.edit.charInput.value;
        if (char && char.length === 1) {
            if (editingMode === 'add_char') {
                socket.emit('apply_skill', { 
                    side: mySide, 
                    skill: '增字', 
                    params: { position: skillParams.position, char: char } 
                });
                ui.edit.popover.classList.remove('show');
            } else if (editingMode === 'replace_char') {
                socket.emit('apply_skill', {
                    side: mySide,
                    skill: '改字',
                    params: { position: skillParams.position, char: char }
                });
                ui.edit.popover.classList.remove('show');
            }
        } else {
            showToast('請輸入 1 個字元', 'warning');
        }
    }
});

window.undoSkill = function() {
    socket.emit('undo_skill', { side: mySide });
};

window.confirmEdit = function() {
    clearMode();
    socket.emit('confirm_edit', { side: mySide });
};

window.cancelConfirmEdit = function() {
    socket.emit('cancel_confirm_edit', { side: mySide });
};

// ─── PHASE: ADMIN REVIEW ─────────────────────────────────────────────────────

function updateAdminReviewWait() {
    const oppState = gameState[mySide === 'team_a' ? 'team_b' : 'team_a'];
    
    ui.review.a.className = gameState.team_a.admin_approved ? 'badge badge-green' : 'badge badge-amber';
    ui.review.a.innerText = gameState.team_a.admin_approved ? 'Team A: 已通過' : 'Team A: 審核中';
    
    ui.review.b.className = gameState.team_b.admin_approved ? 'badge badge-green' : 'badge badge-amber';
    ui.review.b.innerText = gameState.team_b.admin_approved ? 'Team B: 已通過' : 'Team B: 審核中';
}

// ─── PHASE: GUESSING ─────────────────────────────────────────────────────────

function updateGuessing() {
    const oppSide = mySide === 'team_a' ? 'team_b' : 'team_a';
    const myState = gameState[mySide];
    const oppState = gameState[oppSide];
    
    if (myState.guess_choice === null && ui.guess.grid.innerHTML === '') {
        socket.emit('request_guess_data', { side: mySide });
    }

    if (myState.guess_choice !== null) {
        ui.guess.btn.disabled = true;
        ui.guess.btn.innerText = '✅ 已送出答案';
        ui.guess.grid.style.pointerEvents = 'none';
        
        // Highlight selection
        const opts = document.querySelectorAll('.guess-option');
        opts.forEach((opt, idx) => {
            if (idx === myState.guess_choice) {
                opt.classList.add('selected');
            } else {
                opt.classList.remove('selected');
            }
        });
    } else {
        ui.guess.btn.disabled = false;
        ui.guess.btn.innerText = '📤 送出答案';
        ui.guess.grid.style.pointerEvents = 'auto';
    }

    if (oppState.guess_choice !== null) {
        ui.guess.oppStatus.innerHTML = '✅ 對方已作答';
        ui.guess.oppStatus.style.borderColor = 'var(--green)';
        ui.guess.oppStatus.style.color = 'var(--green)';
    } else {
        ui.guess.oppStatus.innerHTML = '<div class="pulse-dot amber"></div><span>對方作答中</span>';
        ui.guess.oppStatus.style.borderColor = '';
        ui.guess.oppStatus.style.color = '';
    }
}

let currentGuessData = null;
let selectedGuessIndex = null;

socket.on('guess_data', (data) => {
    currentGuessData = data;
    ui.guess.text.innerText = data.translated_text;
    
    ui.guess.grid.innerHTML = '';
    data.options.forEach((opt, idx) => {
        const card = document.createElement('div');
        card.className = 'guess-option glass';
        card.innerHTML = `
            <div class="option-label">Option ${idx + 1}</div>
            <div class="option-text">${opt.original}</div>
        `;
        card.onclick = () => selectGuess(idx, card);
        ui.guess.grid.appendChild(card);
    });
});

function selectGuess(idx, cardElement) {
    selectedGuessIndex = idx;
    document.querySelectorAll('.guess-option').forEach(el => el.classList.remove('selected'));
    cardElement.classList.add('selected');
}

window.submitGuess = function() {
    if (selectedGuessIndex === null) {
        showToast('請先選擇一個選項', 'warning');
        return;
    }
    socket.emit('submit_guess', { side: mySide, choice: selectedGuessIndex });
};

// Request guess data when phase starts
socket.on('state_update', (state) => {
    if (state.phase === 'GUESSING' && gameState && mySide && gameState[mySide].guess_choice === null) {
        socket.emit('request_guess_data', { side: mySide });
    }
});

// ─── PHASE: RESULT ───────────────────────────────────────────────────────────

function updateResult() {
    const a = gameState.team_a;
    const b = gameState.team_b;
    
    const matchIdToLabels = {
        "ab": ["TEAM A", "TEAM B"],
        "cd": ["TEAM C", "TEAM D"],
        "ef": ["TEAM E", "TEAM F"],
        "gh": ["TEAM G", "TEAM H"]
    };
    const currentMatchId = ["a", "b"].includes(pathSide) ? "ab" :
                         ["c", "d"].includes(pathSide) ? "cd" :
                         ["e", "f"].includes(pathSide) ? "ef" : "gh";
    const labels = matchIdToLabels[currentMatchId] || ["TEAM A", "TEAM B"];
    const resultLabelA = document.getElementById('result-team-a-label');
    const resultLabelB = document.getElementById('result-team-b-label');
    if (resultLabelA) resultLabelA.innerText = labels[0];
    if (resultLabelB) resultLabelB.innerText = labels[1];
    
    ui.result.a.id.innerText = a.team_id;
    ui.result.b.id.innerText = b.team_id;
    
    // The correct answer FOR Team A is what Team B's topic correct index points to.
    let aCorrectText = "未知的答案";
    let aGuessText = "未選擇";
    if (b.topic && b.topic.texts) {
        if (b.correct_index !== null) aCorrectText = b.topic.texts[b.correct_index].original;
        if (a.guess_choice !== null) aGuessText = b.topic.texts[a.guess_choice].original;
    }
    let bEditedText = b.edited_text ? b.edited_text.map(item => item.char).join("") : "";
    let bTranslatedText = b.translated_text || "";

    // The correct answer FOR Team B is what Team A's topic correct index points to.
    let bCorrectText = "未知的答案";
    let bGuessText = "未選擇";
    if (a.topic && a.topic.texts) {
        if (a.correct_index !== null) bCorrectText = a.topic.texts[a.correct_index].original;
        if (b.guess_choice !== null) bGuessText = a.topic.texts[b.guess_choice].original;
    }
    let aEditedText = a.edited_text ? a.edited_text.map(item => item.char).join("") : "";
    let aTranslatedText = a.translated_text || "";

    const createDetailHTML = (isCorrect, correctText, guessText, editedText, translatedText) => {
        const titleHTML = isCorrect 
            ? `<span class="text-green">猜測正確！ +1 分</span>`
            : `<span class="text-red">猜測錯誤</span>`;
        return `
            ${titleHTML}
            <details style="margin-top: 12px; padding: 12px; background: rgba(255,255,255,0.05); border-radius: 8px; font-size: 0.85rem; text-align: left; cursor: pointer; border: 1px solid rgba(255,255,255,0.1);">
                <summary style="color: var(--cyan); outline: none; font-weight: bold; margin-bottom: 4px;">查看詳細資訊</summary>
                <div style="margin-top: 8px; display: flex; flex-direction: column; gap: 8px;">
                    <div><strong style="color: #fff;">玩家所選內容：</strong><div style="color: var(--text-muted); margin-top: 2px;">${guessText}</div></div>
                    <div><strong style="color: #fff;">原文答案：</strong><div style="color: var(--text-muted); margin-top: 2px;">${correctText}</div></div>
                    <div><strong style="color: #fff;">技能修改後的原文：</strong><div style="color: var(--text-muted); margin-top: 2px;">${editedText}</div></div>
                    <div><strong style="color: #fff;">翻譯後的文字：</strong><div style="color: var(--text-muted); margin-top: 2px;">${translatedText}</div></div>
                </div>
            </details>
        `;
    };

    // Team A
    if (a.guess_correct) {
        ui.result.a.icon.innerText = '🎯';
        ui.result.a.detail.innerHTML = createDetailHTML(true, aCorrectText, aGuessText, bEditedText, bTranslatedText);
        ui.result.a.detail.parentNode.style.borderColor = 'var(--green)';
    } else {
        ui.result.a.icon.innerText = '❌';
        ui.result.a.detail.innerHTML = createDetailHTML(false, aCorrectText, aGuessText, bEditedText, bTranslatedText);
        ui.result.a.detail.parentNode.style.borderColor = 'var(--red)';
    }
    
    // Team B
    if (b.guess_correct) {
        ui.result.b.icon.innerText = '🎯';
        ui.result.b.detail.innerHTML = createDetailHTML(true, bCorrectText, bGuessText, aEditedText, aTranslatedText);
        ui.result.b.detail.parentNode.style.borderColor = 'var(--green)';
    } else {
        ui.result.b.icon.innerText = '❌';
        ui.result.b.detail.innerHTML = createDetailHTML(false, bCorrectText, bGuessText, aEditedText, aTranslatedText);
        ui.result.b.detail.parentNode.style.borderColor = 'var(--red)';
    }

    const btn = document.getElementById('btn-confirm-result');
    if (gameState[mySide].confirmed_result) {
        btn.disabled = true;
        btn.innerText = '等待對方確認...';
    } else {
        btn.disabled = false;
        btn.innerText = '✅ 確認結果，進入下一回合';
    }
}

window.confirmResult = function() {
    socket.emit('confirm_result', { side: mySide });
};

// ─── UTILITIES ───────────────────────────────────────────────────────────────

function showToast(msg, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `<div>${msg}</div>`;
    
    container.appendChild(toast);
    
    setTimeout(() => {
        toast.classList.add('removing');
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}


// --- Timer Mode (Feature 1) ---
let timerInterval = null;

socket.on('timer_start', (data) => {
    startCountdown(data.total_seconds, data.start_timestamp);
});

socket.on('timer_cancel', () => {
    stopCountdown();
});

function startCountdown(totalSeconds, startTimestamp) {
    stopCountdown();
    
    const timerEl = document.getElementById('game-timer');
    const displayEl = document.getElementById('timer-display');
    if (!timerEl || !displayEl) return;
    
    timerEl.classList.remove('hidden');
    timerEl.style.display = 'inline-flex';
    
    const endTime = startTimestamp + totalSeconds;
    
    const updateTimer = () => {
        const now = Date.now() / 1000;
        const remaining = Math.max(0, Math.ceil(endTime - now));
        
        const m = Math.floor(remaining / 60);
        const s = remaining % 60;
        displayEl.innerText = `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
        
        if (remaining <= 30) {
            timerEl.style.backgroundColor = '#dc2626';
            timerEl.style.boxShadow = '0 0 10px #dc2626';
        } else {
            timerEl.style.backgroundColor = '';
            timerEl.style.boxShadow = '';
        }
        
        if (remaining <= 0) {
            stopCountdown();
        }
    };
    
    updateTimer();
    timerInterval = setInterval(updateTimer, 500);
}

function stopCountdown() {
    if (timerInterval) {
        clearInterval(timerInterval);
        timerInterval = null;
    }
    const timerEl = document.getElementById('game-timer');
    if (timerEl) {
        timerEl.classList.add('hidden');
        timerEl.style.display = 'none';
    }
}
