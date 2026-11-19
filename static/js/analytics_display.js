/* Shared display units; values always come from recorded-history APIs. */
function formatRecordedDuration(seconds) {
    const value = Number(seconds);
    if (!Number.isFinite(value) || value < 0) return '暂无数据';
    if (value < 60) return `${Number(value.toFixed(3))} 秒`;
    if (value < 3600) return `${Number((value / 60).toFixed(2))} 分钟`;
    return `${Number((value / 3600).toFixed(2))} 小时`;
}
