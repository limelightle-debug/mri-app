/* Related books panel, shared by the institute's apps.
   Put <section class="panel books" data-books="vix:9:10 shippai"></section> where it belongs:
   each item is a book key, then the chapters that tab draws on ("parts" for the four parts).
   Covers sit in icons/ next to this script. Titles stay in Japanese; 『VIXの声を聴け』 has an
   English edition, so English readers get that one. Follows <html lang> when the app switches. */
(() => {
  const base = new URL("icons/", document.currentScript.src).href;
  const BOOKS = {
    vix: { t: "VIXの声を聴け", url: "https://amzn.asia/d/0hrhh1Ny", cv: "book-vix.jpg",
      en: { t: "Listen to VIX", url: "https://amzn.asia/d/07rtXhVo", cv: "book-vix-en.jpg" },
      ch: { 2: "黒鳥の飛跡", 3: "風船の膨らみを測る", 8: "VIXを解剖する", 9: "VIXイベント", 10: "コツンが聞こえる",
        11: "弾を選ぶ", 14: "環境を知る", 15: "戦略設計のヒント" },
      parts: ["第一部から第四部 影・心・技・体", "Parts 1-4"] },
    shippai: { t: "失敗の魔術師", url: "https://amzn.asia/d/0hWKU73R", cv: "book-shippai.jpg" },
    anomaly: { t: "相場のアノマリーを斬る", url: "https://amzn.asia/d/0boQWl0D", cv: "book-anomaly.jpg",
      ch: { 17: "モメンタム", 18: "行き過ぎの反動" } }
  };
  const KAN = ["〇", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十", "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八", "十九", "二十"];
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const css = `.books .h2t{font-style:normal}
.books .bk{display:flex;align-items:center;gap:12px;text-decoration:none;color:inherit;padding:6px 0}
.books .bk+.bk{border-top:1px solid var(--line);padding-top:10px}
.books .bk img{width:44px;height:64px;border-radius:4px;object-fit:cover;flex:none;box-shadow:0 0 0 1px var(--line)}
.books .bk div{min-width:0}
.books .bk b{display:block;font-size:15px;color:var(--ink)}
.books .bk small{display:block;font-size:12px;color:var(--ink2);margin-top:2px}
.books .bk span{display:block;font-size:12px;color:var(--accent);margin-top:3px}
.books .bk em{margin-left:auto;font-style:normal;color:var(--accent);font-size:18px}`;
  const st = document.createElement("style"); st.textContent = css; document.head.appendChild(st);

  function render() {
    const en = /^en/i.test(document.documentElement.lang || "");
    document.querySelectorAll(".books[data-books]").forEach(el => {
      const rows = el.dataset.books.trim().split(/\s+/).map(item => {
        const [k, ...chs] = item.split(":"), b = BOOKS[k]; if (!b) return "";
        const e = en && b.en ? b.en : b, title = /^[\x00-\x7F]+$/.test(e.t) ? e.t : `『${e.t}』`;
        const lines = chs.map(c => c === "parts" ? b.parts[en ? 1 : 0]
          : en ? null : `第${KAN[+c]}章 ${b.ch[c]}`).filter(Boolean);
        if (en && chs.length && chs[0] !== "parts") lines.push(`Ch. ${chs.join(", ")}`);
        return `<a class="bk" href="${e.url}" target="_blank" rel="noopener"><img src="${base + e.cv}" alt="" width="44" height="64" loading="lazy"><div><b>${esc(title)}</b>${lines.map(l => `<small>${esc(l)}</small>`).join("")}<span>${en ? "View on Amazon" : "Amazon で見る"}</span></div><em>›</em></a>`;
      }).join("");
      const h = `<h2><i class="h2t">${en ? "Related books" : "関連書籍"}</i></h2>`;
      el.innerHTML = (el.dataset.head === "ph" ? `<div class="ph">${h}</div>` : h) + rows;
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", render); else render();
  new MutationObserver(render).observe(document.documentElement, { attributes: true, attributeFilter: ["lang"] });
})();
