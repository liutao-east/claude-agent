// 纯字符串 HTML 转义（不依赖 DOM，便于 Node 测试）
export function escHtml(s) {
  if (s == null) return "";
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

// 相对时间；now 可注入便于测试
export function relTime(iso, now = new Date()) {
  if (!iso) return "";
  const d = new Date(iso);
  const diff = (now - d) / 1000;
  if (diff < 60) return "刚刚";
  if (diff < 3600) return Math.floor(diff / 60) + " 分钟前";
  if (diff < 86400 && d.getDate() === now.getDate()) return d.toTimeString().slice(0, 5);
  if (diff < 172800) return "昨天";
  return `${d.getMonth() + 1}/${d.getDate()}`;
}
