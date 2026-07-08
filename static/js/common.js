/* ============================================================
   智能家居系统 - 共享 JavaScript 工具
   ============================================================ */

// API 请求封装
const API = {
    async get(url) {
        const res = await fetch(url);
        return res.json();
    },
    async post(url, data) {
        const res = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        return res.json();
    },
    async upload(url, formData) {
        const res = await fetch(url, {
            method: 'POST',
            body: formData,
        });
        return res.json();
    },
    async put(url, data) {
        const res = await fetch(url, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        return res.json();
    },
    async del(url) {
        const res = await fetch(url, { method: 'DELETE' });
        return res.json();
    },
};

// SocketIO 连接
const socket = io();

socket.on('connect', () => {
    console.log('[SocketIO] 已连接');
});

socket.on('disconnect', () => {
    console.log('[SocketIO] 已断开');
});

// Toast 通知
function showToast(message, type = 'info', duration = 3000) {
    const container = document.getElementById('toastContainer');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `<i class="bi bi-${type === 'success' ? 'check-circle' : type === 'error' ? 'x-circle' : type === 'warning' ? 'exclamation-triangle' : 'info-circle'}"></i> ${message}`;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(100%)';
        setTimeout(() => toast.remove(), 300);
    }, duration);
}

// 格式化时间
function formatTime(dateStr) {
    if (!dateStr) return '-';
    const d = new Date(dateStr);
    return d.toLocaleString('zh-CN', {
        month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit'
    });
}

// 获取状态徽章
function statusBadge(result) {
    const map = {
        'granted': '<span class="badge badge-success"><i class="bi bi-check-circle"></i> 允许</span>',
        'denied': '<span class="badge badge-danger"><i class="bi bi-x-circle"></i> 拒绝</span>',
        'unknown': '<span class="badge badge-warning"><i class="bi bi-question-circle"></i> 未知</span>',
    };
    return map[result] || map['unknown'];
}

// 设备状态文本
function deviceStatusText(device, state) {
    if (device === 'light') return state.on ? `开启 (${state.brightness}%)` : '关闭';
    if (device === 'fan') return state.on ? `开启 (档位${state.speed})` : '关闭';
    if (device === 'door') return state.locked ? '锁定' : '已开锁';
    if (device === 'window') return state.closed ? '关闭' : '打开';
    if (device === 'ac') return state.on ? `开启 (${state.temp}°C)` : '关闭';
    return '-';
}

// HTML 转义
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// 分页组件
function renderPagination(container, currentPage, totalPages, onPageChange) {
    if (totalPages <= 1) {
        container.innerHTML = '';
        return;
    }
    let html = '<div style="display:flex;gap:6px;align-items:center;justify-content:center;padding:12px;">';
    if (currentPage > 1) {
        html += `<button class="btn btn-outline btn-sm" onclick="${onPageChange}(${currentPage - 1})">上一页</button>`;
    }
    for (let i = Math.max(1, currentPage - 2); i <= Math.min(totalPages, currentPage + 2); i++) {
        if (i === currentPage) {
            html += `<button class="btn btn-primary btn-sm">${i}</button>`;
        } else {
            html += `<button class="btn btn-outline btn-sm" onclick="${onPageChange}(${i})">${i}</button>`;
        }
    }
    if (currentPage < totalPages) {
        html += `<button class="btn btn-outline btn-sm" onclick="${onPageChange}(${currentPage + 1})">下一页</button>`;
    }
    html += '</div>';
    container.innerHTML = html;
}
