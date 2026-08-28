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

function taipeiDateFromIso(isoDate) {
  const value = /^\d{4}-\d{2}-\d{2}$/.test(isoDate || "") ? isoDate : taipeiToday();
  return new Date(`${value}T12:00:00+08:00`);
}

function dateParts(date) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Taipei",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    weekday: "short",
  }).formatToParts(date);
  const get = (type) => parts.find((part) => part.type === type)?.value || "";
  return {
    year: Number(get("year")),
    month: Number(get("month")),
    day: Number(get("day")),
    weekday: get("weekday"),
  };
}

function chineseCalendarParts(date) {
  try {
    const parts = new Intl.DateTimeFormat("en-u-ca-chinese", {
      timeZone: "Asia/Taipei",
      month: "numeric",
      day: "numeric",
    }).formatToParts(date);
    const monthRaw = parts.find((part) => part.type === "month")?.value || "";
    const dayRaw = parts.find((part) => part.type === "day")?.value || "";
    const leap = /bis|leap/i.test(monthRaw);
    const month = Number.parseInt(monthRaw, 10);
    const day = Number.parseInt(dayRaw, 10);
    if (!Number.isFinite(month) || !Number.isFinite(day)) return null;
    return { month, day, leap };
  } catch {
    return null;
  }
}

function addTaipeiDays(date, days) {
  return new Date(date.getTime() + days * 24 * 60 * 60 * 1000);
}

function qingmingDay(year) {
  if (year >= 2000 && year <= 2099) {
    const y = year % 100;
    return Math.floor(y * 0.2422 + 4.81) - Math.floor(y / 4);
  }
  return 4;
}

function lunarHolidayName(date) {
  const lunar = chineseCalendarParts(date);
  if (!lunar || lunar.leap) return null;

  const tomorrow = chineseCalendarParts(addTaipeiDays(date, 1));
  if (tomorrow && !tomorrow.leap && tomorrow.month === 1 && tomorrow.day === 1) {
    return "除夕";
  }
  if (lunar.month === 1 && lunar.day === 1) return "春節";
  if (lunar.month === 1 && lunar.day === 15) return "元宵節";
  if (lunar.month === 5 && lunar.day === 5) return "端午節";
  if (lunar.month === 7 && lunar.day === 7) return "七夕";
  if (lunar.month === 8 && lunar.day === 15) return "中秋節";
  if (lunar.month === 9 && lunar.day === 9) return "重陽節";
  return null;
}

function fixedDateName(date) {
  const { year, month, day, weekday } = dateParts(date);
  const key = `${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
  const qingming = qingmingDay(year);

  if (key === "01-01") return "元旦";
  if (key === "02-14") return "情人節";
  if (key === "02-28") return "和平紀念日";
  if (key === "04-04" && day === qingming) return "兒童節暨清明節";
  if (key === "04-04") return "兒童節";
  if (month === 4 && day === qingming) return "清明節";
  if (key === "05-01") return "勞動節";
  if (month === 5 && weekday === "Sun" && day >= 8 && day <= 14) return "母親節";
  if (key === "08-08") return "父親節";
  if (key === "09-28") return "教師節";
  if (key === "10-10") return "國慶日";
  if (key === "10-25") return "光復節";
  if (key === "12-24") return "平安夜";
  if (key === "12-25") return "聖誕節";
  if (key === "12-31") return "跨年夜";
  return null;
}

function lunarGreeting(date) {
  const lunar = chineseCalendarParts(date);
  if (!lunar || lunar.leap) return null;

  const tomorrow = chineseCalendarParts(addTaipeiDays(date, 1));
  if (tomorrow && !tomorrow.leap && tomorrow.month === 1 && tomorrow.day === 1) {
    return "🧧 除夕團圓，永慶房屋祝福您闔家平安、團圓喜樂，迎接新的一年順心如意！";
  }

  if (lunar.month === 1 && lunar.day >= 1 && lunar.day <= 5) {
    return "🧧 新春愉快！永慶房屋祝福您新的一年平安順遂、闔家幸福、好運常伴！";
  }
  if (lunar.month === 1 && lunar.day === 15) {
    return "🏮 元宵佳節愉快！永慶房屋祝福您闔家團圓、平安喜樂，日子圓滿順心！";
  }
  if (lunar.month === 5 && lunar.day === 5) {
    return "🐲 端午安康！永慶房屋祝福您與家人平安健康、順心如意，度過舒心佳節！";
  }
  if (lunar.month === 7 && lunar.day === 7) {
    return "💞 七夕愉快！永慶房屋祝福您與珍惜的人相伴美好，生活甜蜜、幸福常在！";
  }
  if (lunar.month === 8 && lunar.day === 15) {
    return "🌕 中秋佳節愉快！永慶房屋祝福您闔家團圓、平安喜樂，月圓人圓、事事圓滿！";
  }
  if (lunar.month === 9 && lunar.day === 9) {
    return "🌼 重陽安康！永慶房屋祝福您與家人健康平安、福氣常在，日日順心！";
  }

  return null;
}

function fixedDateGreeting(date) {
  const { year, month, day, weekday } = dateParts(date);
  const key = `${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
  const qingming = qingmingDay(year);

  if (key === "01-01") {
    return "🎊 元旦愉快！永慶房屋祝福您新的一年平安順心、好運常伴，事事都有好開始！";
  }
  if (key === "02-14") {
    return "💝 情人節愉快！永慶房屋祝福您與珍惜的人共享美好時光，幸福常伴、生活甜蜜！";
  }
  if (key === "02-28") {
    return "🕊️ 和平紀念日，願我們珍惜得來不易的和平與安定，永慶房屋也祝福您與家人平安順心。";
  }
  if (key === "04-04" && day === qingming) {
    return "🧒🌿 兒童節與清明時節，永慶房屋祝福孩子們健康快樂成長，也願您與家人平安相聚、出行順心！";
  }
  if (key === "04-04") {
    return "🧒 兒童節快樂！永慶房屋祝福每個孩子健康成長、天天開心，也願每個家庭充滿歡笑與幸福！";
  }
  if (month === 4 && day === qingming) {
    return "🌿 清明時節，慎終追遠、思念故人，永慶房屋願您與家人平安順心，返鄉祭祖一路平安。";
  }
  if (key === "05-01") {
    return "🛠️ 勞動節愉快！永慶房屋向每一位認真生活、努力工作的您致意，祝福您稍作休息、平安順心！";
  }
  if (month === 5 && weekday === "Sun" && day >= 8 && day <= 14) {
    return "🌷 母親節快樂！永慶房屋祝福天下媽媽健康平安、幸福常伴，也祝您與家人共享溫馨時光！";
  }
  if (key === "08-08") {
    return "💙 父親節快樂！永慶房屋祝福天下爸爸健康平安、幸福常伴，也祝您與家人溫馨相聚！";
  }
  if (key === "09-28") {
    return "📚 教師節，永慶房屋向每一位用心付出的老師致上敬意，感謝一路上的教導與陪伴，祝福平安順心！";
  }
  if (key === "10-10") {
    return "🇹🇼 國慶日愉快！永慶房屋祝福您與家人平安順心，假期愉快、出行順利！";
  }
  if (key === "10-25") {
    return "🇹🇼 光復節，願我們珍惜今日安定的生活，永慶房屋也祝福您與家人平安順心、日子和樂。";
  }
  if (key === "12-24") {
    return "🎄 平安夜，永慶房屋祝福您與家人平安喜樂、溫暖相伴，享受溫馨美好的夜晚！";
  }
  if (key === "12-25") {
    return "🎄 聖誕佳節愉快！永慶房屋祝福您平安喜樂、幸福滿滿，生活充滿美好與好消息！";
  }
  if (key === "12-31") {
    return "🎆 歲末將至，感謝今年一路的相遇與陪伴，永慶房屋祝福您為今年畫下美好句點，迎接平安順遂的新一年！";
  }

  return null;
}

const HOLIDAY_EVE_MESSAGES = {
  "元旦": "🎆 明天迎接新的一年，永慶房屋提前祝福您歲末平安、新年順心，為新的一年開個好彩頭！",
  "情人節": "💝 明天就是情人節，永慶房屋提前祝福您與珍惜的人共享美好時光，幸福常伴！",
  "和平紀念日": "🕊️ 明天是和平紀念日，願您在假日中放慢腳步、平安順心，也一同珍惜眼前安定的日常。",
  "兒童節": "🧒 明天就是兒童節，永慶房屋提前祝福孩子們健康快樂，也祝您與家人共享歡樂時光！",
  "清明節": "🌿 明天是清明節，永慶房屋提醒您返鄉祭祖與出行多留意安全，願一路平安、闔家順心。",
  "兒童節暨清明節": "🧒🌿 明天適逢兒童節與清明節，永慶房屋祝福您與家人平安相聚，也祝孩子們健康快樂！",
  "勞動節": "🛠️ 明天是勞動節，辛苦了！永慶房屋提前祝福您好好休息、放鬆充電，假期平安順心！",
  "母親節": "🌷 明天就是母親節，別忘了向媽媽說聲謝謝，永慶房屋提前祝福天下媽媽健康平安、幸福常伴！",
  "父親節": "💙 明天就是父親節，永慶房屋提前祝福天下爸爸健康平安，也祝您與家人溫馨相聚！",
  "教師節": "📚 明天是教師節，永慶房屋提前向每一位用心付出的老師致上敬意，祝福平安順心！",
  "國慶日": "🇹🇼 明天是國慶日，永慶房屋提前祝福您假期平安順心、闔家愉快，出行一路順利！",
  "光復節": "🇹🇼 明天是光復節，願您與家人平安順心，也一同珍惜安定美好的日常。",
  "平安夜": "🎄 明天就是平安夜，永慶房屋提前祝福您與家人平安喜樂、溫暖相伴！",
  "聖誕節": "🎄 明天就是聖誕節，永慶房屋提前祝福您平安喜樂、幸福滿滿，佳節愉快！",
  "跨年夜": "🎆 明天就是歲末最後一天，永慶房屋提前祝福您平安順心，為今年畫下美好句點！",
  "除夕": "🧧 明天就是除夕，永慶房屋提前祝福您返鄉一路平安、闔家團圓，迎接幸福新年！",
  "春節": "🧧 新春將至，永慶房屋提前祝福您新的一年平安順遂、闔家幸福、好運常伴！",
  "元宵節": "🏮 明天就是元宵節，永慶房屋提前祝福您闔家團圓、平安喜樂，事事圓滿！",
  "端午節": "🐲 明天就是端午節，永慶房屋提前祝福您與家人平安健康、佳節順心！",
  "七夕": "💞 明天就是七夕，永慶房屋提前祝福您與珍惜的人相伴美好、幸福常在！",
  "中秋節": "🌕 明天就是中秋節，永慶房屋提前祝福您闔家團圓、平安喜樂，佳節愉快！",
  "重陽節": "🌼 明天就是重陽節，永慶房屋提前祝福您與家人健康平安、福氣常在！",
};

function holidayEveGreeting(date) {
  const tomorrow = addTaipeiDays(date, 1);
  const name = fixedDateName(tomorrow) || lunarHolidayName(tomorrow);
  if (!name) return null;

  const publicHolidays = new Set([
    "元旦", "和平紀念日", "兒童節", "清明節", "兒童節暨清明節",
    "勞動節", "春節", "端午節", "中秋節", "國慶日", "光復節"
  ]);
  const sensitiveHolidays = new Set(["和平紀念日", "清明節", "兒童節暨清明節", "光復節"]);
  const tomorrowWeekday = dateParts(tomorrow).weekday;
  const isLongWeekendEve = publicHolidays.has(name)
    && (tomorrowWeekday === "Fri" || tomorrowWeekday === "Mon");

  if (isLongWeekendEve && !sensitiveHolidays.has(name)) {
    return `🌿 連假前夕，明天就是${name}，永慶房屋提前祝福您與家人假期平安順心；若有出遊或返鄉安排，也祝一路順利！`;
  }

  return HOLIDAY_EVE_MESSAGES[name]
    || `✨ ${name}將至，永慶房屋提前祝福您平安順心、闔家愉快，度過美好的一天！`;
}

function dailyGreeting(isoDate) {
  const date = taipeiDateFromIso(isoDate);
  const specialGreeting = fixedDateGreeting(date) || lunarGreeting(date);
  if (specialGreeting) return specialGreeting;

  const eveGreeting = holidayEveGreeting(date);
  if (eveGreeting) return eveGreeting;

  const { weekday } = dateParts(date);
  if (weekday === "Sat" || weekday === "Sun") {
    return "🌿 週末愉快！永慶房屋祝福您放慢腳步、好好休息，與家人共享美好時光，平安順心！";
  }

  return "😊 永慶房屋祝福您今天一切順利、平安健康，工作與生活都順心如意！";
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

  const isoDate = state.payload?.date || taipeiToday();
  const todayIso = taipeiToday();
  const date = displayDate(isoDate);
  const todayDate = taipeiDateFromIso(todayIso);
  const yesterdayParts = dateParts(addTaipeiDays(todayDate, -1));
  const yesterdayIso = `${yesterdayParts.year}-${String(yesterdayParts.month).padStart(2, "0")}-${String(yesterdayParts.day).padStart(2, "0")}`;
  const newsDayLabel = isoDate === todayIso ? "今日" : (isoDate === yesterdayIso ? "昨日" : "近期");
  const divider = "━━━━━━━━━━━━━━";

  const intro = [
    "🌞 親愛的貴賓早安",
    "",
    "📢 台灣房仲第一品牌—永慶房產集團宣布啟動大展店計畫，喊出「3年全台達成2500店」的新里程碑！",
    "",
    "🏆 雙北展店目標邁向350店！展店目標將以「更貼近社區、更快速回應客戶需求」為核心，持續提供更優質、更即時的房產服務。",
    "",
    `跟您分享幾則${newsDayLabel}（${date}）重點新聞📰`,
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
    dailyGreeting(todayIso),
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