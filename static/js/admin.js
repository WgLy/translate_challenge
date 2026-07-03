/**
 * admin.js - Frontend logic for Admin Dashboard V2
 */

const socket = io({ path: '/ai_translate/socket.io' });
let gameState = null;

// DOM Elements
const ui = {
    badges: {
        phase: document.getElementById('admin-phase'),
        round: document.getElementById('admin-round'),
        connText: document.getElementById('conn-text'),
        connDot: document.getElementById('conn-dot'),
        headerPhase: document.getElementById('phase-badge'),
        headerRound: document.getElementById('round-badge'),
    },
    scores: {
        aId: document.getElementById('score-team-a-id'),
        aVal: document.getElementById('score-a'),
        bId: document.getElementById('score-team-b-id'),
        bVal: document.getElementById('score-b'),
    },
    teams: {
        a: {
            id: document.getElementById('admin-team-a-id'),
            ready: document.getElementById('admin-team-a-ready'),
            topic: document.getElementById('admin-topic-a'),
            confirmed: document.getElementById('admin-confirmed-a'),
            actions: document.getElementById('admin-actions-a'),
        },
        b: {
            id: document.getElementById('admin-team-b-id'),
            ready: document.getElementById('admin-team-b-ready'),
            topic: document.getElementById('admin-topic-b'),
            confirmed: document.getElementById('admin-confirmed-b'),
            actions: document.getElementById('admin-actions-b'),
        }
    },
    review: {
        section: document.getElementById('admin-review-section'),
        panels: {
            a: document.getElementById('review-panel-a'),
            b: document.getElementById('review-panel-b')
        },
        texts: {
            origA: document.getElementById('review-original-a'),
            editA: document.getElementById('review-edited-a'),
            transA: document.getElementById('review-translated-a'),
            origB: document.getElementById('review-original-b'),
            editB: document.getElementById('review-edited-b'),
            transB: document.getElementById('review-translated-b'),
        },
        status: {
            a: document.getElementById('review-status-a'),
            b: document.getElementById('review-status-b'),
        }
    },
    params: {
        transCount: document.getElementById('input-trans-count'),
        moveLen: document.getElementById('input-move-length'),
        model: document.getElementById('input-model'),
        reviewModel: document.getElementById('input-review-model'),
        ollamaStatus: document.getElementById('ollama-status'),
        cardControls: document.getElementById('card-controls'),
        scoreControls: document.getElementById('score-controls'),
    }
};

// ─── CONNECTION & STATUS ─────────────────────────────────────────────────────

let adminPassword = null;

socket.on('connect', () => {
    ui.badges.connDot.className = 'pulse-dot green';
    ui.badges.connText.innerText = '已連線';
    
    if (adminPassword === null) {
        adminPassword = prompt("請輸入管理員密碼:") || "";
    }
    
    socket.emit('join_role', { role: 'admin', password: adminPassword });
    checkApiStatus();
    setInterval(checkApiStatus, 5000);
});

socket.on('disconnect', () => {
    ui.badges.connDot.className = 'pulse-dot red';
    ui.badges.connText.innerText = '連線中斷';
    adminPassword = null; // Reset password to prompt again on reconnect
});

async function checkApiStatus() {
    try {
        const res = await fetch('/ai_translate/api/status');
        const data = await res.json();
        
        ui.params.ollamaStatus.className = data.ollama ? 'badge badge-green' : 'badge badge-red';
        ui.params.ollamaStatus.innerText = data.ollama
            ? `正常連線 (${data.url})`
            : '連線失敗';
        
        if (document.activeElement !== ui.params.model) {
            ui.params.model.value = data.model;
        }
        if (document.activeElement !== ui.params.reviewModel) {
            ui.params.reviewModel.value = data.review_model;
        }
    } catch (e) {
        ui.params.ollamaStatus.className = 'badge badge-red';
        ui.params.ollamaStatus.innerText = '錯誤';
    }
}

// 模型掃描：儲存 modelName -> url 的映射
let scannedModelMap = {};

window.scanModels = async function() {
    const btn = document.getElementById('btn-scan-models');
    const list = document.getElementById('scan-model-list');
    if (btn) { btn.disabled = true; btn.innerText = '掃描中...'; }
    if (list) list.innerHTML = '';

    scannedModelMap = {};

    try {
        const res = await fetch('/ai_translate/api/scan_models');
        const data = await res.json();
        const models = data.models || [];

        // 更新 datalist
        const dataList = document.getElementById('model-list');
        if (dataList) {
            dataList.innerHTML = '';
            models.forEach(m => {
                const opt = document.createElement('option');
                opt.value = m.name;
                opt.label = `${m.label} — ${m.name}`;
                dataList.appendChild(opt);
                scannedModelMap[m.name] = m.url;
            });
        }

        // 顯示分組清單
        if (list) {
            if (models.length === 0) {
                list.innerHTML = '<div class="text-muted" style="font-size:0.85rem">未在任何設定的 Port 上發現 Ollama 服務。</div>';
            } else {
                // 依 URL 分組
                const groups = {};
                models.forEach(m => {
                    if (!groups[m.url]) groups[m.url] = { label: m.label, models: [] };
                    groups[m.url].models.push(m.name);
                });

                Object.entries(groups).forEach(([url, info]) => {
                    const group = document.createElement('div');
                    group.style.cssText = 'margin-bottom:0.75rem';

                    const header = document.createElement('div');
                    header.style.cssText = 'font-size:0.75rem; color:var(--cyan); margin-bottom:0.35rem; font-weight:600';
                    header.innerText = `📌 ${info.label}  (${url})`;
                    group.appendChild(header);

                    info.models.forEach(name => {
                        const btn2 = document.createElement('button');
                        btn2.className = 'btn btn-sm btn-ghost';
                        btn2.style.cssText = 'margin: 2px; font-size:0.8rem';
                        btn2.innerText = name;
                        btn2.onclick = () => {
                            ui.params.model.value = name;
                            socket.emit('admin_set_model', { model: name, url: url });
                            showToast(`⚙️ 已選擇模型：${name}\n（${url}）`, 'info');
                            setTimeout(checkApiStatus, 800);
                        };
                        group.appendChild(btn2);
                    });

                    list.appendChild(group);
                });
            }
        }

        showToast(`✅ 掃描完成，找到 ${models.length} 個模型。`, 'success');
    } catch (e) {
        if (list) list.innerHTML = '<div class="text-muted">\u6383\u63cf\u5931\u6557\uff0c\u8acb\u78ba\u8a8d\u4f3a\u670d\u5668\u72c0\u614b\u3002</div>';
        showToast('❌ 掃描失敗', 'error');
    } finally {
        if (btn) { btn.disabled = false; btn.innerText = '🔍 掃描'; }
    }
};

// ─── STATE UPDATE ────────────────────────────────────────────────────────────

socket.on('state_update', (state) => {
    gameState = state;
    updateUI();
});

socket.on('notification', (data) => {
    showToast(data.message, data.type);
});

// ─── UI UPDATES ──────────────────────────────────────────────────────────────

function updateUI() {
    if (!gameState) return;

    // Badges
    ui.badges.phase.innerText = gameState.phase;
    ui.badges.headerPhase.innerText = gameState.phase;
    ui.badges.round.innerText = gameState.round_number;
    ui.badges.headerRound.innerText = `R${gameState.round_number}`;

    // Score bar
    ui.scores.aId.innerText = gameState.team_a.team_id || '?';
    ui.scores.bId.innerText = gameState.team_b.team_id || '?';
    ui.scores.aVal.innerText = gameState.team_a.score;
    ui.scores.bVal.innerText = gameState.team_b.score;

    // Team info
    ['team_a', 'team_b'].forEach(side => {
        const d = gameState[side];
        const t = ui.teams[side === 'team_a' ? 'a' : 'b'];
        
        t.id.innerText = d.team_id || '未設定';
        t.ready.className = d.ready ? 'badge badge-green' : 'badge badge-amber';
        t.ready.innerText = d.ready ? '已準備' : '未準備';
        
        t.topic.innerText = d.topic ? d.topic.theme : '—';
        t.confirmed.innerText = d.confirmed_edit ? '✅ 是' : '否';
        t.actions.innerText = d.skill_actions ? d.skill_actions.length : 0;
    });

    // Review Panel
    let bothApproved = gameState.team_a.admin_approved && gameState.team_b.admin_approved;
    let anyNeedReview = false;

    ['team_a', 'team_b'].forEach(side => {
        const d = gameState[side];
        const k = side === 'team_a' ? 'a' : 'b';
        
        // Show panel ONLY if translation is completed AND not yet approved
        if (d.translated_text && !d.admin_approved) {
            anyNeedReview = true;
            ui.review.panels[k].classList.remove('hidden');
            
            const orig = d.original_text || '';
            const edit = Array.isArray(d.edited_text) ? d.edited_text.map(c => c.char).join('') : (d.edited_text || '');
            const trans = d.translated_text;
            
            ui.review.texts['orig'+k.toUpperCase()].innerText = orig;
            ui.review.texts['edit'+k.toUpperCase()].innerText = edit;
            ui.review.texts['trans'+k.toUpperCase()].innerText = trans;
            
            ui.review.status[k].innerHTML = '<span class="badge badge-amber">等待審核</span>';
            ui.review.panels[k].style.borderColor = 'var(--amber)';
        } else {
            ui.review.panels[k].classList.add('hidden');
        }
    });

    const allAppMsg = document.getElementById('review-all-approved');
    if (allAppMsg) {
        if (bothApproved && !anyNeedReview && !['LOBBY', 'SELECTING_TEXT', 'EDITING', 'TRANSLATING'].includes(gameState.phase)) {
            allAppMsg.classList.remove('hidden');
        } else {
            allAppMsg.classList.add('hidden');
        }
    }

    // Dynamic Parameter Inputs
    if (document.activeElement !== ui.params.transCount) {
        ui.params.transCount.value = gameState.translation_count;
    }
    
    const autoReviewToggle = document.getElementById("toggle-auto-review");
    if (autoReviewToggle && gameState.auto_review !== undefined) {
        autoReviewToggle.checked = gameState.auto_review;
    }
    
    if (document.activeElement !== ui.params.moveLen && gameState.skill_registry['搬移']) {
        ui.params.moveLen.value = gameState.skill_registry['搬移'].params.segment_length;
    }

    // Dynamic Controls Generation
    renderCardControls();
    renderScoreControls();
}

function renderCardControls() {
    ui.params.cardControls.innerHTML = '';
    
    // For each actual team in 'teams' dict
    for (const [teamId, data] of Object.entries(gameState.teams)) {
        const row = document.createElement('div');
        row.className = 'admin-row mt-sm';
        row.innerHTML = `<label style="color:var(--cyan)">Team ${teamId}</label>`;
        
        for (const [skill, count] of Object.entries(data.cards)) {
            const wrap = document.createElement('div');
            wrap.className = 'flex items-center gap-xs mr-sm';
            
            wrap.innerHTML = `
                <span class="text-muted" style="font-size:0.8rem">${skill}</span>
                <input type="number" class="input" style="width:60px; padding:4px 8px; font-size:0.8rem" 
                       value="${count}" 
                       onchange="setCardCount('${teamId}', '${skill}', this.value)">
            `;
            row.appendChild(wrap);
        }
        ui.params.cardControls.appendChild(row);
    }
    if (Object.keys(gameState.teams).length === 0) {
        ui.params.cardControls.innerHTML = '<div class="text-muted mt-sm" style="font-size:0.8rem">無隊伍資料 (需先在大廳準備)</div>';
    }
}

function renderScoreControls() {
    ui.params.scoreControls.innerHTML = '';
    
    for (const [teamId, data] of Object.entries(gameState.teams)) {
        const row = document.createElement('div');
        row.className = 'admin-row';
        row.innerHTML = `
            <label style="color:var(--cyan)">Team ${teamId}</label>
            <input type="number" class="input" style="width:80px;" 
                   value="${data.score}" 
                   onchange="setScore('${teamId}', this.value)">
        `;
        ui.params.scoreControls.appendChild(row);
    }
    if (Object.keys(gameState.teams).length === 0) {
        ui.params.scoreControls.innerHTML = '<div class="text-muted" style="font-size:0.8rem">無隊伍資料 (需先在大廳準備)</div>';
    }
}

// ─── ACTION HANDLERS ─────────────────────────────────────────────────────────

window.switchTab = function(tabId) {
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.admin-tab').forEach(el => el.classList.remove('active'));
    
    document.getElementById(tabId).classList.add('active');
    
    const tabs = Array.from(document.querySelectorAll('.admin-tab'));
    const activeBtn = tabs.find(b => b.getAttribute('onclick').includes(tabId));
    if (activeBtn) activeBtn.classList.add('active');
};

window.adminApprove = function(side) {
    if (confirm(`確定通過 ${side} 的翻譯嗎？`)) {
        socket.emit('admin_approve', { side: side });
    }
};

window.adminReject = function(side) {
    if (confirm(`確定退回 ${side} 的翻譯並重新翻譯嗎？`)) {
        socket.emit('admin_reject', { side: side });
    }
};

window.setTranslationCount = function() {
    const val = parseInt(ui.params.transCount.value);
    if (val >= 1 && val <= 30) {
        socket.emit('admin_set_translations', { count: val });
    }
};

window.toggleAutoReview = function(enabled) {
    socket.emit('admin_set_auto_review', { enabled: enabled });
};

window.setSkillParam = function(skill, param) {
    let val = null;
    if (skill === '搬移' && param === 'segment_length') {
        val = parseInt(ui.params.moveLen.value);
    }
    
    if (val !== null) {
        socket.emit('admin_set_skill_param', { skill, param, value: val });
    }
};

window.setModel = function() {
    const model = ui.params.model.value.trim();
    if (model) {
        // 如果是經過掃描知道 URL，就一併傳送
        const url = scannedModelMap[model] || null;
        socket.emit('admin_set_model', { model, url });
        setTimeout(checkApiStatus, 1000);
    }
};

window.setReviewModel = function() {
    const model = ui.params.reviewModel.value.trim();
    if (model) {
        const url = scannedModelMap[model] || null;
        socket.emit('admin_set_review_model', { model, url });
        setTimeout(checkApiStatus, 1000);
    }
};

window.setCardCount = function(teamId, skill, count) {
    socket.emit('admin_set_cards', { team_id: teamId, skill: skill, count: parseInt(count) });
};

window.setScore = function(teamId, score) {
    socket.emit('admin_set_score', { team_id: teamId, score: parseInt(score) });
};

window.adminReset = function() {
    if (confirm("⚠️ 警告：即將清除所有遊戲進度、分數與隊伍設定！\n確定要繼續嗎？")) {
        socket.emit('admin_reset');
    }
};

window.forcePhase = function(phase) {
    if (confirm(`確定要強制跳轉到 ${phase} 階段嗎？這可能會造成狀態不一致。`)) {
        socket.emit('admin_force_phase', { phase: phase });
    }
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
