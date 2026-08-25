const CATEGORY_CONFIG = {
  weather: { list: "weatherList", count: "weatherCount", label: "天氣" },
  instant: { list: "instantList", count: "instantCount", label: "即時" },
  finance: { list: "financeList", count: "financeCount", label: "金融" },
  housing: { list: "housingList", count: "housingCount", label: "房市" },
};

const CATEGORY_ORDER = ["weather", "instant", "finance", "housing"];

const state = {
  payload: null,
  selected: {
    weather: null,
    instant: null,
    finance: null,
    housing: null,
  },
};

const $ = (id) => document.getElementById(id);

function taipeiToday() {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Taipei",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const get = (type) => parts.find((p) => p.type === type)?.value;
  return `${get("year")}-${get("month")}-${get("day")}`;
}

function taipeiClockParts() {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Taipei",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(new Date());
  const get = (type) => Number(parts.find((p) => p.type === type)?.value || 0);
  return { hour: get("hour"), minute: get("minute") };
}

function updateNextUpdateNotice() {
  const wrap = $("nextUpdateWrap");
  const text = $("nextUpdateAt");
  const card = $("statusCard");
  if (!wrap || !text || !card) return;

  const { hour } = taipeiClockParts();
  const overnightPause = hour >= 21 || hour < 6;

  wrap.hidden = !overnightPause;
  card.classList.toggle("has-next-update", overnightPause);

  if (!overnightPause) return;
  text.textContent = hour >= 21
    ? "明日 06:00 開始更新"
    : "今日 06:00 開始更新";
}

function displayDate(isoDate) {
  return (isoDate || "").replaceAll("-", "/");
}

function displayUpdated(isoDateTime) {
  if (!isoDateTime) return "—";
  try {
    return new Intl.DateTimeFormat("zh-TW", {
      timeZone: "Asia/Taipei",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(new Date(isoDateTime));
  } catch {
    return isoDateTime;
  }
}

function escapeHtml(value = "") {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function setPanelCollapsed(category, collapsed) {
  const panel = document.querySelector(`.news-panel[data-category="${category}"]`);
  if (!panel) return;
  const head = panel.querySelector(".panel-head");
  panel.classList.toggle("collapsed", collapsed);
  head?.setAttribute("aria-expanded", String(!collapsed));
}

function togglePanel(category) {
  const panel = document.querySelector(`.news-panel[data-category="${category}"]`);
  if (!panel) return;
  setPanelCollapsed(category, !panel.classList.contains("collapsed"));
}

function advanceToNextCategory(currentCategory) {
  const currentIndex = CATEGORY_ORDER.indexOf(currentCategory);
  if (currentIndex < 0) return;

  const nextCategory = CATEGORY_ORDER
    .slice(currentIndex + 1)
    .find((category) => !state.selected[category]);

  if (!nextCategory) return;

  setPanelCollapsed(currentCategory, true);
  setPanelCollapsed(nextCategory, false);

  const nextPanel = document.querySelector(`.news-panel[data-category="${nextCategory}"]`);
  window.setTimeout(() => {
    nextPanel?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, 140);
}

function setupPanelToggles() {
  document.querySelectorAll(".news-panel").forEach((panel) => {
    const category = panel.dataset.category;
    const head = panel.querySelector(".panel-head");
    if (!category || !head) return;

    head.addEventListener("click", () => togglePanel(category));
    head.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        togglePanel(category);
      }
    });
  });
}

function renderCategory(category, items = []) {
  const config = CATEGORY_CONFIG[category];
  const list = $(config.list);
  $(config.count).textContent = items.length;
  list.innerHTML = "";

  if (!items.length) {
    list.innerHTML = `<div class="empty">目前還沒有今天的${config.label}新聞。<br>資料更新後會自動出現在這裡。</div>`;
    return;
  }

  items.forEach((item) => {
    const row = document.createElement("div");
    row.className = "news-item";
    row.dataset.id = item.id;

    const summary = item.summary
      ? `<p class="news-summary">${escapeHtml(item.summary)}</p>`
      : "";

    row.innerHTML = `
      <input class="news-check" type="checkbox" aria-label="選取 ${escapeHtml(item.title)}">
      <div class="news-meta">
        <span>${escapeHtml(item.time || "")}</span>
        <span>•</span>
        <span>${escapeHtml(item.source || config.label)}</span>
      </div>
      <a class="news-title" href="${escapeHtml(item.url)}"
         target="_blank" rel="noopener noreferrer">${escapeHtml(item.title)}</a>
      ${summary}
    `;

    const checkbox = row.querySelector(".news-check");
    checkbox.addEventListener("click", (event) => event.stopPropagation());
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) {
        list.querySelectorAll(".news-check").forEach((other) => {
          if (other !== checkbox) {
            other.checked = false;
            other.closest(".news-item")?.classList.remove("selected");
          }
        });
        state.selected[category] = item;
        row.classList.add("selected");
        updateSelectedCount();
        advanceToNextCategory(category);
      } else {
        state.selected[category] = null;
        row.classList.remove("selected");
        updateSelectedCount();
      }
    });

    list.appendChild(row);
  });
}

function updateSelectedCount() {
  const count = Object.values(state.selected).filter(Boolean).length;
  $("selectedCount").textContent = count;
}

function focusHeading(category, item) {
  if (category === "weather") return "📰 【🌦️ 天氣焦點】";
  if (category === "finance") return "📰 【💹 經濟焦點】";
  if (category === "housing") return "📰 【🏠 房市焦點】";

  const weatherWords = [
    "天氣", "氣象", "颱風", "豪雨", "大雨", "雷雨", "降雨",
    "高溫", "低溫", "冷氣團", "鋒面", "季風", "東北風", "熱浪"
  ];
  const haystack = `${item.title || ""} ${item.summary || ""}`;
  if (weatherWords.some((word) => haystack.includes(word))) {
    return "📰 【🌦️ 天氣焦點】";
  }
  return "📰 【⚡ 即時焦點】";
}

function buildMessage() {
  const selectedEntries = Object.entries(state.selected).filter(([, item]) => item);
  if (!selectedEntries.length) {
    window.alert("請先至少勾選一篇新聞。");
    return "";
  }

  const date = displayDate(state.payload?.date || taipeiToday());
  const divider = "━━━━━━━━━━━━━━";

  const intro = [
    "🌞 親愛的貴賓早安",
    "",
    "📢 台灣房仲第一品牌—永慶房產集團宣布啟動大展店計畫，喊出「3年全台達成2500店」的新里程碑！",
    "",
    "🏆 雙北展店目標邁向350店！展店目標將以「更貼近社區、更快速回應客戶需求」為核心，持續提供更優質、更即時的房產服務。",
    "",
    `跟您分享幾則今日（${date}）重點新聞📰`,
    "",
    divider,
  ];

  const sections = selectedEntries.map(([category, item]) => {
    const summary = item.summary?.trim()
      || "此篇新聞摘要尚未取得，可直接在這裡補上您想分享的新聞重點。";
    return [
      "",
      focusHeading(category, item),
      "",
      item.title,
      "",
      summary,
      "",
      item.url,
      "",
      divider,
    ].join("\n");
  });

  const ending = [
    "",
    "😊 永慶房屋祝福您今天工作順利、平安健康、萬事如意！",
  ].join("\n");

  return `${intro.join("\n")}${sections.join("")}${ending}`;
}

async function loadNews() {
  try {
    const response = await fetch(`news.json?v=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    state.payload = payload;

    Object.keys(state.selected).forEach((key) => { state.selected[key] = null; });
    updateSelectedCount();

    $("newsDate").textContent = displayDate(payload.date);
    $("updatedAt").textContent = displayUpdated(payload.updated_at);

    Object.keys(CATEGORY_CONFIG).forEach((category) => {
      renderCategory(category, payload.categories?.[category] || []);
      setPanelCollapsed(category, false);
    });
  } catch (error) {
    console.error(error);
    $("newsDate").textContent = "讀取失敗";
    $("updatedAt").textContent = "—";
    Object.keys(CATEGORY_CONFIG).forEach((category) => renderCategory(category, []));
  }
}

$("generateBtn").addEventListener("click", () => {
  const message = buildMessage();
  if (!message) return;
  $("outputText").value = message;
  $("outputWrap").hidden = false;
  $("copyStatus").textContent = "";
  $("outputWrap").scrollIntoView({ behavior: "smooth", block: "start" });
});

$("copyBtn").addEventListener("click", async () => {
  const text = $("outputText").value;
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    $("copyStatus").textContent = "已複製";
  } catch {
    $("outputText").focus();
    $("outputText").select();
    document.execCommand("copy");
    $("copyStatus").textContent = "已複製";
  }
});

setupPanelToggles();
updateNextUpdateNotice();
window.setInterval(updateNextUpdateNotice, 60 * 1000);
loadNews();