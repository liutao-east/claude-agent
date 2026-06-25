// 场景图标与头像数据(纯数据 + 纯函数,顶层禁止 DOM 访问)。

export const ICON_EMOJIS = ["💻", "🔧", "🐛", "📄", "🗄️", "⚡", "🔍", "🧩", "🛠️", "📦"];

// 按场景名做稳定哈希 -> 取一个 emoji(同名恒定、不闪烁)
export function pickIcon(name) {
  const s = String(name || "");
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return ICON_EMOJIS[h % ICON_EMOJIS.length];
}

export const BOT_AVATAR = "🤖";
export function userAvatar() { return "你"; }
