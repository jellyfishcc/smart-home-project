/* ============================================================
   哨兵模式 - 页面逻辑
   说明：后端 /api/sentry/* 尚未接入时自动降级为本地演示状态，
        片段列表使用演示数据，播放器保持黑屏占位。
   ============================================================ */

const TRIGGER_META = {
    intruder: { label: '未授权人员', badge: 'badge-danger' },
    activity: { label: '有活动', badge: 'badge-warning' },
    motion: { label: '移动侦测', badge: 'badge-warning' },
    patrol: { label: '例行巡检', badge: 'badge-secondary' },
    manual: { label: '手动触发', badge: 'badge-info' },
};

const state = {
    armed: false,
    mode: 'away',
    interval: 10,
    last_patrol: null,
    clips: [],
    activeId: null,
    demo: true,
    playerMode: 'live',      // live = 实时推流，replay = 选中片段的留证回放
    streak: 0,               // 当前轨迹连续命中轮次
    alarmRounds: 3,          // 升级告警所需轮次
    alarmActive: false,      // 是否处于告警态
    lastRound: null,         // 最近一轮巡检结论，驱动页面状态条
};

// 每轮结论的文案（后端已给 label，这里兜底）
const ROUND_META = {
    clear: { label: '无人', detail: '画面内未检测到人员' },
    activity: { label: '有未识别人员活动', detail: '存在未识别人员' },
    authorized: { label: '检测到已录入人脸', detail: '授权人员，正常放行' },
    alarm: { label: '报警', detail: '检测到未授权人员' },
    unavailable: { label: '画面异常', detail: '本轮未取到有效画面' },
    idle: { label: '等待巡检', detail: '布防后每轮巡检结束在此更新结论' },
};

// 播放器运行态：轮播定时器与当前帧序号
const player = {
    frameTimer: null,
    frameIndex: 0,
    liveRetry: null,
};

document.addEventListener('DOMContentLoaded', async () => {
    loadStatus();
    startClock();
    document.getElementById('sentryToggle').addEventListener('change', handleToggle);
    document.getElementById('sentryPatrolBtn').addEventListener('click', handlePatrol);
    document.getElementById('sentrySimulateBtn').addEventListener('click', handleSimulate);
    document.getElementById('sentryClearAlarmBtn').addEventListener('click', handleClearAlarm);

    // 播放器模式切换：实时 / 回放
    document.querySelectorAll('#sentryModeSwitch button').forEach((btn) => {
        btn.addEventListener('click', () => setPlayerMode(btn.dataset.mode));
    });

    // MJPEG 流：加载成功才算真的有画面，失败则降级为无信号提示
    const live = document.getElementById('sentryLive');
    live.addEventListener('load', onLiveLoaded);
    live.addEventListener('error', onLiveError);

    setPlayerMode('live');
    await loadClips();
    applyDeepLink();

    // 巡检结论兜底刷新：WebSocket 断开时也能在 5 秒内看到本轮状态
    setInterval(() => {
        if (!document.hidden) loadStatus();
    }, 5000);
});

/**
 * 深链接：/sentry?mode=replay&clip=12 直接打开某条告警的留证回放。
 * 告警通知里带上这个地址，点开就能看到现场画面。
 */
function applyDeepLink() {
    const params = new URLSearchParams(window.location.search);
    if (params.get('mode') !== 'replay') return;

    const id = params.get('clip');
    const exists = id && state.clips.some((clip) => String(clip.id) === String(id));
    if (exists) {
        selectClip(id);
    } else if (state.clips.length > 0) {
        selectClip(state.clips[0].id);
    }
}

/* -------------------- 手动巡检 / 模拟入侵 -------------------- */

async function withBusy(button, task) {
    if (button.disabled) return;
    const html = button.innerHTML;
    button.disabled = true;
    button.innerHTML = '<i class="bi bi-hourglass-split"></i> 处理中';
    try {
        await task();
    } finally {
        button.disabled = false;
        button.innerHTML = html;
    }
}

async function handlePatrol() {
    const button = document.getElementById('sentryPatrolBtn');
    await withBusy(button, async () => {
        try {
            const res = await API.post('/api/sentry/patrol', {});
            const data = (res && res.data) || {};
            if (res.code !== 0) {
                showToast(res.message || '巡检失败', 'error');
                return;
            }
            if (data.action === 'alarm') {
                showToast(`升级告警：${data.reason || '未授权人员'}`, 'error', 5000);
            } else if (data.action === 'alarm_ongoing') {
                showToast('告警持续中，已追加本轮留证', 'error');
            } else if (data.action === 'activity') {
                showToast(`记录活动：第 ${data.round} 轮，未达告警轮次`, 'warning');
            } else if (data.recognized) {
                const purged = data.purged ? `，已清理 ${data.purged} 张误报留证` : '';
                showToast('巡检完成：' + (data.person_name || '授权人员') + purged, 'success');
            } else {
                showToast('巡检完成：' + (data.reason || '未发现异常'), 'info');
            }
            await loadStatus();
            await loadClips();
        } catch (e) {
            showToast('巡检接口不可用', 'error');
        }
    });
}

async function handleSimulate() {
    const button = document.getElementById('sentrySimulateBtn');
    await withBusy(button, async () => {
        try {
            const res = await API.post('/api/sentry/simulate', { note: '模拟入侵（演示）' });
            if (res.code !== 0) {
                showToast(res.message || '模拟失败', 'error');
                return;
            }
            showToast('已触发模拟入侵，告警已记录', 'error');
            await loadStatus();
            await loadClips();
        } catch (e) {
            showToast('模拟接口不可用', 'error');
        }
    });
}

/* -------------------- 手动解除告警 -------------------- */

async function handleClearAlarm() {
    const button = document.getElementById('sentryClearAlarmBtn');
    if (!state.alarmActive) {
        showToast('当前没有待解除的告警', 'info');
        return;
    }
    await withBusy(button, async () => {
        try {
            const res = await API.post('/api/sentry/alarm/clear', { operator: 'developer' });
            if (res.code !== 0) {
                showToast(res.message || '解除失败', 'error');
                return;
            }
            const data = res.data || {};
            if (data.cleared) {
                showToast(`告警已解除，共 ${data.rounds} 轮；哨兵继续值守`, 'success');
            } else {
                showToast('当前没有待解除的告警', 'info');
            }
            await loadStatus();
            await loadClips();
        } catch (e) {
            showToast('解除接口不可用', 'error');
        }
    });
}

/* -------------------- 状态 -------------------- */

async function loadStatus() {
    try {
        const res = await API.get('/api/sentry/status');
        if (res.code === 0) {
            applyStatus(res.data);
            state.demo = false;
        } else {
            throw new Error('接口返回异常');
        }
    } catch (e) {
        applyStatus({ armed: false, mode: 'away', interval: 10, last_patrol: null });
        state.demo = true;
    }
    updateDemoBadge();
}

function applyStatus(data) {
    state.armed = !!data.armed;
    state.mode = data.mode || 'away';
    state.interval = data.interval || 10;
    state.last_patrol = data.last_patrol || null;
    state.streak = data.streak || 0;
    state.alarmRounds = data.alarm_rounds || 3;
    state.alarmActive = !!data.alarm_active;
    state.lastRound = data.last_round || null;

    document.getElementById('sentryToggle').checked = state.armed;
    document.getElementById('sentryStateText').textContent = state.armed ? '哨兵已布防' : '哨兵已撤防';

    // 副标题优先展示轨迹进度：观察中 -> 第 2/3 轮；告警中 -> 已连续 N 轮
    let sub;
    if (!state.armed) {
        sub = '开启后按设定间隔自动巡检摄像头，发现异常立即告警';
    } else if (state.alarmActive) {
        sub = state.streak > 0
            ? `告警中 · 已连续 ${state.streak} 轮发现未授权人员，点右上角「解除告警」结束`
            : '告警中 · 等待处理，点右上角「解除告警」结束';
    } else if (state.streak > 0) {
        const left = Math.max(0, state.alarmRounds - state.streak);
        sub = `观察中 · 第 ${state.streak}/${state.alarmRounds} 轮，再停留 ${left} 轮将升级为告警`;
    } else {
        sub = `正在值守，有人先记为活动，连续 ${state.alarmRounds} 轮才告警`;
    }
    document.getElementById('sentryStateSub').textContent = sub;
    document.querySelector('.sentry-control').classList.toggle('is-armed', state.armed);
    // 观察态用琥珀描边，和告警态的红色区分开
    document.querySelector('.sentry-control').classList.toggle(
        'is-watching', state.armed && state.streak > 0 && !state.alarmActive);

    const badge = document.getElementById('sentryHeaderBadge');
    if (state.alarmActive) {
        badge.textContent = '告警中';
        badge.className = 'badge badge-danger';
    } else if (state.armed && state.streak > 0) {
        badge.textContent = `观察中 ${state.streak}/${state.alarmRounds}`;
        badge.className = 'badge badge-warning';
    } else if (state.armed) {
        badge.textContent = '布防中';
        badge.className = 'badge badge-danger';
    } else {
        badge.textContent = '已撤防';
        badge.className = 'badge badge-secondary';
    }

    // 解除告警按钮：只有真处于告警态时才可点
    const clearBtn = document.getElementById('sentryClearAlarmBtn');
    if (clearBtn) {
        clearBtn.disabled = !state.alarmActive;
        clearBtn.className = 'btn btn-sm ' + (state.alarmActive ? 'btn-warning' : 'btn-outline');
    }

    document.getElementById('sentryModeText').textContent = state.mode === 'home' ? '在家布防' : '离家布防';
    document.getElementById('sentryIntervalText').textContent = state.interval + ' 秒';
    document.getElementById('sentryLastPatrol').textContent = state.last_patrol
        ? formatTime(state.last_patrol)
        : '--';
    document.getElementById('hudRec').className = 'sentry-rec' + (state.armed ? '' : ' off');
    renderRoundStatus();
}

/**
 * 页面状态条：把最近一轮结论画出来。
 * 优先级：撤防 > 告警 > 本轮结论 > 等待首轮。
 */
function renderRoundStatus() {
    const box = document.getElementById('sentryRound');
    if (!box) return;

    const labelEl = document.getElementById('sentryRoundLabel');
    const detailEl = document.getElementById('sentryRoundDetail');
    const timeEl = document.getElementById('sentryRoundTime');
    const round = state.lastRound;

    let key = 'idle';
    let label = '等待巡检';
    let detail = '布防后每轮巡检结束在此更新结论';
    let at = '--:--:--';

    if (!state.armed) {
        key = 'idle';
        label = '已撤防';
        detail = '开启哨兵后按间隔自动巡检并更新结论';
    } else if (state.alarmActive) {
        // 告警态优先：即使本轮恰好认出了已录入人员，也仍然显示报警
        key = 'alarm';
        label = '报警';
        detail = (round && round.state === 'alarm' && round.detail)
            ? round.detail
            : (state.streak > 0
                ? `告警持续中 · 已连续 ${state.streak} 轮`
                : '告警待处理，点右上角「解除告警」结束');
        at = (round && round.at) || at;
    } else if (round) {
        key = round.state || 'clear';
        label = round.label || (ROUND_META[key] || {}).label || '巡检结果';
        detail = round.detail || (ROUND_META[key] || {}).detail || '';
        at = round.at || at;
    } else {
        detail = '值守中，等待首轮巡检结果…';
    }

    box.dataset.state = key;
    labelEl.textContent = label;
    detailEl.textContent = detail;
    detailEl.title = detail;
    timeEl.textContent = at;
}

async function handleToggle(event) {
    const shouldArm = event.target.checked;

    try {
        const res = shouldArm
            ? await API.post('/api/sentry/arm', { mode: state.mode, interval: state.interval })
            : await API.post('/api/sentry/disarm', {});

        if (res && res.code === 0) {
            state.demo = false;
            // 直接用后端返回的完整状态：布防时 last_round 已清空，页面回到「等待首轮」
            applyStatus(res.data || {
                armed: shouldArm,
                mode: state.mode,
                interval: state.interval,
                last_patrol: state.last_patrol,
                last_round: null,
            });
            showToast(shouldArm ? '哨兵已布防' : '哨兵已撤防', 'success');
            updateDemoBadge();
            return;
        }
        throw new Error(res && res.message ? res.message : '接口不可用');
    } catch (e) {
        // 后端未接入：切换仅在本地生效，便于先把界面走通
        state.demo = true;
        applyStatus({
            armed: shouldArm,
            mode: state.mode,
            interval: state.interval,
            last_patrol: state.last_patrol,
        });
        showToast(shouldArm ? '哨兵已布防（演示状态，接口未接入）' : '哨兵已撤防（演示状态）', 'warning');
        updateDemoBadge();
    }
}

function updateDemoBadge() {
    document.getElementById('sentryDemoBadge').style.display = state.demo ? 'inline-block' : 'none';
}

/* -------------------- 片段列表 -------------------- */

async function loadClips() {
    try {
        const res = await API.get('/api/sentry/clips');
        // code 为 0 即视为已接入：即使暂时没有片段，也应显示「暂无」而不是假数据
        if (res.code === 0 && Array.isArray(res.data)) {
            state.clips = res.data;
            state.demo = false;
        } else {
            state.clips = buildDemoClips();
            state.demo = true;
        }
    } catch (e) {
        state.clips = buildDemoClips();
        state.demo = true;
    }

    renderClips();
    updateDemoBadge();

    // 不再自动选中首条：页面默认停在实时画面，点右侧列表才进入回放
    if (state.playerMode === 'replay') {
        renderReplay();
    }
}

function buildDemoClips() {
    const pad = (n) => String(n).padStart(2, '0');
    const now = new Date();

    const make = (index, channel, minutesAgo, duration, trigger) => {
        const d = new Date(now.getTime() - minutesAgo * 60000);
        const started = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} `
            + `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
        return { id: 'demo-clip-' + index, channel, started_at: started, duration, trigger, url: '' };
    };

    return [
        make(1, 'CAM-01 门口', 8, 12, 'intruder'),
        make(2, 'CAM-02 客厅', 26, 9, 'motion'),
        make(3, 'CAM-01 门口', 52, 15, 'patrol'),
        make(4, 'CAM-03 走廊', 87, 7, 'manual'),
        make(5, 'CAM-02 客厅', 140, 11, 'motion'),
        make(6, 'CAM-04 书房', 215, 8, 'patrol'),
    ];
}

function clipDurationText(clip) {
    const shots = Array.isArray(clip.snapshots) ? clip.snapshots.length : 0;
    if (shots > 1 && (clip.duration || 0) <= 2) return '连拍 ' + shots + ' 张';
    return (clip.duration || 0) + ' 秒';
}

function clipThumbText(clip) {
    const shots = Array.isArray(clip.snapshots) ? clip.snapshots.length : 0;
    return shots > 1 ? shots + '张' : (clip.duration || 0) + 's';
}

function renderClips() {
    const list = document.getElementById('sentryClipList');
    document.getElementById('clipCount').textContent = state.clips.length + ' 段';

    if (state.clips.length === 0) {
        list.innerHTML = '<div class="sentry-empty">暂无监控片段</div>';
        return;
    }

    list.innerHTML = state.clips.map((clip) => {
        const meta = TRIGGER_META[clip.trigger] || { label: '片段', badge: 'badge-secondary' };
        const time = (clip.started_at || '').slice(11, 19) || '--:--:--';
        const cover = (Array.isArray(clip.snapshot_urls) && clip.snapshot_urls[0]) || '';
        const thumb = cover
            ? `<img src="${cover}" alt="" loading="lazy">`
            : '<i class="bi bi-film"></i>';
        // 连续轮次优先；没有轮次概念（巡检/手动）时退回显示时长，避免一行放不下
        const rounds = (clip.trigger === 'activity' || clip.trigger === 'intruder')
            && (clip.rounds || 1) > 1 ? `连续 ${clip.rounds} 轮` : '';
        const tail = rounds || clipDurationText(clip);
        return `
            <div class="sentry-clip" data-id="${clip.id}">
                <div class="sentry-clip-thumb">
                    ${thumb}
                    <span class="sentry-clip-duration">${clipThumbText(clip)}</span>
                </div>
                <div class="sentry-clip-info">
                    <div class="sentry-clip-title">
                        <span>${time}</span>
                        <span class="badge ${meta.badge}">${meta.label}</span>
                    </div>
                    <div class="sentry-clip-sub">${escapeHtml(clip.channel || '未知通道')} · ${tail}</div>
                </div>
                <button class="sentry-clip-del" data-del="${clip.id}" title="删除这条记录">
                    <i class="bi bi-x-lg"></i>
                </button>
            </div>
        `;
    }).join('');

    list.querySelectorAll('.sentry-clip').forEach((el) => {
        el.addEventListener('click', () => selectClip(el.dataset.id));
    });
    list.querySelectorAll('.sentry-clip-del').forEach((btn) => {
        btn.addEventListener('click', (ev) => {
            ev.stopPropagation();       // 别连带触发外层的「选中回放」
            handleDeleteClip(btn.dataset.del);
        });
    });
}

async function handleDeleteClip(id) {
    if (!window.confirm('删除这条记录及其留证图片？该操作不可撤销。')) return;
    try {
        const res = await API.del(`/api/sentry/events/${id}`);
        if (!res || res.code !== 0) {
            showToast((res && res.message) || '删除失败', 'error');
            return;
        }
        const files = (res.data && res.data.files) || 0;
        showToast(`已删除记录，同时清理 ${files} 张留证`, 'success');
        if (String(state.activeId) === String(id)) {
            state.activeId = null;
            if (state.playerMode === 'replay') {
                showPlaceholder('未选择片段', '点击右侧片段查看留证画面');
            }
        }
        await loadClips();
        await loadStatus();
    } catch (e) {
        showToast('删除接口不可用', 'error');
    }
}

function selectClip(id) {
    // dataset 取出来是字符串，后端 id 是数字，统一转成字符串比较
    const clip = state.clips.find((item) => String(item.id) === String(id));
    if (!clip) return;

    state.activeId = clip.id;
    document.querySelectorAll('.sentry-clip').forEach((el) => {
        el.classList.toggle('active', String(el.dataset.id) === String(id));
    });

    // 点片段即进入回放：播放该事件的连拍留证
    setPlayerMode('replay');
}

/* -------------------- 播放器：实时画面 / 片段回放 -------------------- */

function setPlayerMode(mode) {
    if (mode !== 'live' && mode !== 'replay') return;
    state.playerMode = mode;

    document.querySelectorAll('#sentryModeSwitch button').forEach((btn) => {
        btn.classList.toggle('active', btn.dataset.mode === mode);
    });

    if (mode === 'live') {
        startLive();
    } else {
        stopLive();
        renderReplay();
    }
}

function playerEls() {
    return {
        img: document.getElementById('sentryLive'),
        video: document.getElementById('sentryVideo'),
        noSignal: document.getElementById('sentryNoSignal'),
        badge: document.getElementById('playerBadge'),
    };
}

function stopReplayTimer() {
    if (player.frameTimer) {
        clearInterval(player.frameTimer);
        player.frameTimer = null;
    }
}

function showPlaceholder(title, sub) {
    stopReplayTimer();
    const { img, video, noSignal, badge } = playerEls();
    img.hidden = true;
    video.hidden = true;
    video.removeAttribute('src');
    document.getElementById('sentryNoSignalText').textContent = title;
    document.getElementById('sentryNoSignalSub').textContent = sub || '';
    noSignal.style.display = 'flex';
    badge.textContent = '无信号';
    badge.className = 'badge badge-secondary';
}

/* 实时：MJPEG 长连接，直接塞给 <img>，浏览器按视频一样显示 */
function startLive() {
    stopReplayTimer();
    const { img, video, noSignal, badge } = playerEls();

    video.hidden = true;
    video.removeAttribute('src');
    noSignal.style.display = 'none';
    img.hidden = false;
    badge.textContent = '连接中';
    badge.className = 'badge badge-secondary';

    document.getElementById('hudChannel').textContent = 'CAM-01 门口';
    document.getElementById('hudTitle').textContent = 'CAM-01 门口 · 实时画面';
    document.getElementById('hudMeta').textContent = '摄像头实时推流';

    // 带时间戳避免浏览器复用上一次已断开的流
    img.src = '/api/camera/stream?fps=8&t=' + Date.now();
}

function stopLive() {
    if (player.liveRetry) {
        clearTimeout(player.liveRetry);
        player.liveRetry = null;
    }
    const img = document.getElementById('sentryLive');
    if (img.getAttribute('src')) {
        // 断开 MJPEG 长连接，否则后端生成器会一直替这个标签编码画面
        img.removeAttribute('src');
    }
    img.hidden = true;
}

function onLiveLoaded() {
    if (state.playerMode !== 'live') return;
    if (player.liveRetry) {
        clearTimeout(player.liveRetry);
        player.liveRetry = null;
    }
    const { img, noSignal, badge } = playerEls();
    img.hidden = false;
    noSignal.style.display = 'none';
    badge.textContent = '实时画面';
    badge.className = 'badge badge-success';
    document.getElementById('hudMeta').textContent =
        `摄像头实时推流 · ${img.naturalWidth}×${img.naturalHeight}`;
}

function onLiveError() {
    if (state.playerMode !== 'live') return;
    showPlaceholder('摄像头未就绪', '镜头未打开或被其他程序占用，6 秒后自动重连');
    // 自动重连：演示中途弹出摄像头也能自己恢复画面，不用刷新页面
    if (player.liveRetry) clearTimeout(player.liveRetry);
    player.liveRetry = setTimeout(() => {
        player.liveRetry = null;
        if (state.playerMode === 'live') startLive();
    }, 6000);
}

/* 回放：有视频放视频，没有就把连拍快照按 2fps 轮播，等效一段「录像」 */
function renderReplay() {
    stopReplayTimer();
    const clip = state.clips.find((item) => String(item.id) === String(state.activeId));
    const { img, video, noSignal, badge } = playerEls();

    video.hidden = true;
    video.removeAttribute('src');
    img.hidden = true;
    noSignal.style.display = 'none';

    if (!clip) {
        showPlaceholder('未选择片段', '点击右侧片段查看留证画面');
        return;
    }

    const urls = Array.isArray(clip.snapshot_urls) ? clip.snapshot_urls : [];
    const meta = TRIGGER_META[clip.trigger] || { label: '片段' };

    document.getElementById('hudChannel').textContent = clip.channel || 'CAM-01 门口';
    document.getElementById('hudTitle').textContent = `${clip.channel || '监控'} · ${meta.label}`;

    if (clip.url) {
        video.hidden = false;
        video.src = clip.url;
        video.play().catch(() => {});
        badge.textContent = '播放中';
        badge.className = 'badge badge-success';
        document.getElementById('hudMeta').textContent =
            `开始 ${clip.started_at || '--'} · ${clipDurationText(clip)}`;
        return;
    }

    if (urls.length === 0) {
        showPlaceholder('该片段没有留证画面', '事件记录存在，但快照文件已丢失');
        document.getElementById('hudMeta').textContent = `开始 ${clip.started_at || '--'}`;
        return;
    }

    img.hidden = false;
    player.frameIndex = 0;
    img.src = urls[0];
    badge.textContent = urls.length > 1 ? `回放 ${urls.length} 张` : '留证画面';
    badge.className = 'badge badge-info';
    document.getElementById('hudMeta').textContent =
        `开始 ${clip.started_at || '--'} · 第 1/${urls.length} 帧`;

    if (urls.length > 1) {
        player.frameTimer = setInterval(() => {
            player.frameIndex = (player.frameIndex + 1) % urls.length;
            img.src = urls[player.frameIndex];
            document.getElementById('hudMeta').textContent =
                `开始 ${clip.started_at || '--'} · 第 ${player.frameIndex + 1}/${urls.length} 帧`;
        }, 700);
    }
}

/* -------------------- 实时告警 -------------------- */

if (typeof socket !== 'undefined') {
    socket.on('sentry_alarm', (payload) => {
        const event = (payload && payload.event) || {};
        const rounds = (payload && payload.rounds) || 0;
        const prefix = rounds > 1 ? `连续 ${rounds} 轮：` : '';
        showToast(prefix + (event.detail || payload.detail || '检测到异常'), 'error', 5000);
        flashAlarm();
        loadStatus();
        loadClips();
    });

    socket.on('sentry_alarm_cleared', () => {
        loadStatus();
        loadClips();
    });

    // 每轮巡检结束：先按推送内容即时刷新状态条，再拉一次完整状态同步徽标
    socket.on('sentry_patrol', (payload) => {
        if (!payload) return;
        state.lastRound = payload;
        if (typeof payload.streak === 'number') state.streak = payload.streak;
        if (typeof payload.alarm_active === 'boolean') state.alarmActive = payload.alarm_active;
        renderRoundStatus();
        loadStatus();
    });
}

function flashAlarm() {
    const card = document.querySelector('.sentry-player-card');
    if (!card) return;
    card.classList.add('is-alarm');
    setTimeout(() => card.classList.remove('is-alarm'), 3200);
}

/* -------------------- 时钟 -------------------- */

function startClock() {
    const tick = () => {
        const d = new Date();
        const pad = (n) => String(n).padStart(2, '0');
        document.getElementById('hudClock').textContent =
            `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} `
            + `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
    };
    tick();
    setInterval(tick, 1000);
}
