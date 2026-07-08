/* 仪表盘 JavaScript */

let tempChart = null;

// 初始化
document.addEventListener('DOMContentLoaded', () => {
    loadDashboard();
    loadTempHistory();
    setupSocketListeners();
    // 定时刷新
    setInterval(loadDashboard, 30000); // 每30秒刷新一次
    loadLightingSummary();
});

// SocketIO 实时监听
function setupSocketListeners() {
    socket.on('sensor_update', (data) => {
        updateSensorDisplay(data);
    });

    socket.on('device_update', (data) => {
        updateDeviceDisplay(data.device, data.state);
    });
}

// 加载仪表盘数据
async function loadDashboard() {
    try {
        const res = await API.get('/api/dashboard');
        if (res.code === 0) {
            const d = res.data;
            updateSensorDisplay(d.sensor);
            updateAllDevices(d.devices);
            updateRecentAccess(d.recent_access);
            updateRecentDetections(d.recent_detections);
            updatePersonStats(d.person_stats);
        }
    } catch (e) {
        console.error('加载仪表盘失败:', e);
    }
}

// 更新传感器显示
function updateSensorDisplay(sensor) {
    if (!sensor) return;
    document.getElementById('tempValue').textContent = sensor.temperature + '°C';

    const trend = document.getElementById('tempTrend');
    if (sensor.temperature > sensor.threshold) {
        trend.textContent = `高于阈值 ${sensor.threshold}°C - 风扇已激活`;
        trend.className = 'stat-trend up';
    } else {
        trend.textContent = `正常 (阈值 ${sensor.threshold}°C)`;
        trend.className = 'stat-trend normal';
    }
}

// 更新所有设备显示
function updateAllDevices(devices) {
    if (!devices) return;

    // 灯光
    document.getElementById('lightValue').textContent = devices.light.brightness + '%';
    document.getElementById('lightStatus').textContent = devices.light.on ? '开启' : '关闭';

    // 门
    document.getElementById('doorValue').textContent = devices.door.locked ? '锁定' : '已开锁';
    document.getElementById('doorStatus').textContent = devices.door.locked ? '安全锁定' : '已开锁';

    // 窗户
    document.getElementById('windowValue').textContent = devices.window.closed ? '关闭' : '打开';
    document.getElementById('windowStatus').textContent = devices.window.closed ? '已关闭' : '已打开';

    // 风扇
    document.getElementById('fanValue').textContent = devices.fan.on ? `档${devices.fan.speed}` : '关闭';
    document.getElementById('fanStatus').textContent = devices.fan.on ? '运行中' : '停止';

    // 空调
    document.getElementById('acValue').textContent = devices.ac.on ? `${devices.ac.temp}°C` : '关闭';
    document.getElementById('acStatus').textContent = devices.ac.on ? '运行中' : '关闭';
}

// 更新单个设备显示
function updateDeviceDisplay(device, state) {
    if (device === 'light') {
        document.getElementById('lightValue').textContent = state.brightness + '%';
        document.getElementById('lightStatus').textContent = state.on ? '开启' : '关闭';
    } else if (device === 'door') {
        document.getElementById('doorValue').textContent = state.locked ? '锁定' : '已开锁';
        document.getElementById('doorStatus').textContent = state.locked ? '安全锁定' : '已开锁';
    } else if (device === 'window') {
        document.getElementById('windowValue').textContent = state.closed ? '关闭' : '打开';
        document.getElementById('windowStatus').textContent = state.closed ? '已关闭' : '已打开';
    } else if (device === 'fan') {
        document.getElementById('fanValue').textContent = state.on ? `档${state.speed}` : '关闭';
        document.getElementById('fanStatus').textContent = state.on ? '运行中' : '停止';
    } else if (device === 'ac') {
        document.getElementById('acValue').textContent = state.on ? `${state.temp}°C` : '关闭';
        document.getElementById('acStatus').textContent = state.on ? '运行中' : '关闭';
    }
}

// 更新最近门禁记录
function updateRecentAccess(logs) {
    const tbody = document.getElementById('recentAccessBody');
    if (!logs || logs.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--color-text-light);padding:30px;">暂无记录</td></tr>';
        return;
    }
    tbody.innerHTML = logs.map(log => `
        <tr>
            <td style="font-size:12px;">${formatTime(log.access_time)}</td>
            <td>${escapeHtml(log.person_name || '未知')}</td>
            <td>${statusBadge(log.access_result)}</td>
            <td style="font-size:12px;">${log.confidence || '-'}</td>
        </tr>
    `).join('');
}

// 更新最近检测记录
function updateRecentDetections(records) {
    const tbody = document.getElementById('recentDetectBody');
    if (!records || records.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--color-text-light);padding:30px;">暂无记录</td></tr>';
        return;
    }
    tbody.innerHTML = records.map(r => {
        const objects = r.objects_detected || [];
        const objNames = objects.map(o => o.class).join(', ') || '无';
        const action = r.triggered_action ? '<span class="badge badge-warning">有</span>' : '<span class="badge badge-secondary">无</span>';
        return `
            <tr>
                <td style="font-size:12px;">${formatTime(r.detected_at)}</td>
                <td style="font-size:12px;">${escapeHtml(objNames)}</td>
                <td>${r.object_count}</td>
                <td>${action}</td>
            </tr>
        `;
    }).join('');
}

// 更新人员统计
function updatePersonStats(stats) {
    if (!stats) return;
    document.getElementById('personCount').textContent = stats.authorized;
    document.getElementById('personDetail').textContent = `共${stats.total}人 (${stats.authorized}授权)`;
    document.getElementById('detectCount').textContent = '查看';
}

// 加载温度历史并绘制图表
async function loadTempHistory() {
    try {
        const res = await API.get('/api/history/temperature?hours=24&interval=hour');
        if (res.code === 0 && res.data.length > 0) {
            renderTempChart(res.data, res.stats);
        }
    } catch (e) {
        console.error('加载温度历史失败:', e);
    }
}

function renderTempChart(data, stats) {
    const ctx = document.getElementById('tempChart').getContext('2d');
    const labels = data.map(d => d.time ? d.time.substring(5, 16) : '');
    const temps = data.map(d => d.temperature || d.temp || 0);

    if (tempChart) tempChart.destroy();

    tempChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: '温度 (°C)',
                data: temps,
                borderColor: '#5A7A9B',
                backgroundColor: 'rgba(90, 122, 155, 0.1)',
                borderWidth: 2,
                fill: true,
                tension: 0.4,
                pointRadius: 3,
                pointBackgroundColor: temps.map(t => t > 28 ? '#E07A7A' : '#5A7A9B'),
                pointRadius: temps.map(t => t > 28 ? 5 : 3),
            }, {
                label: '阈值 (28°C)',
                data: data.map(() => 28),
                borderColor: '#E07A7A',
                borderWidth: 1,
                borderDash: [5, 5],
                pointRadius: 0,
                fill: false,
            }]
        },
        options: {
            responsive: true,
            plugins: {
                legend: { display: true, position: 'top', labels: { font: { size: 11 } } },
                tooltip: {
                    callbacks: {
                        label: (ctx) => `${ctx.dataset.label}: ${ctx.parsed.y}°C`
                    }
                }
            },
            scales: {
                y: {
                    beginAtZero: false,
                    suggestedMin: 18,
                    suggestedMax: 35,
                    grid: { color: 'rgba(0,0,0,0.05)' },
                    ticks: { font: { size: 11 }, callback: (v) => v + '°C' }
                },
                x: {
                    grid: { display: false },
                    ticks: { font: { size: 10 }, maxRotation: 45, minRotation: 0 }
                }
            }
        }
    });
}

// 加载灯光使用摘要
async function loadLightingSummary() {
    try {
        const res = await API.get('/api/lighting/stats?hours=24');
        if (res.code === 0) {
            const d = res.data;
            document.getElementById('dashLightHours').textContent = d.total_on_hours + 'h';
            document.getElementById('dashLightEnergy').textContent = d.total_energy_wh + 'Wh';
            document.getElementById('dashLightCount').textContent = d.total_operations;
            document.getElementById('dashLightAvg').textContent = d.avg_brightness + '%';
        }
    } catch (e) {
        console.error('加载灯光摘要失败:', e);
    }
}
