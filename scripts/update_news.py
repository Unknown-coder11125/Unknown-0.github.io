import os, re, json, html, urllib.request
from datetime import datetime, timezone, timedelta
import feedparser

# ===== 설정 (여기만 수정) =====
PER_FEED = 5          # 피드당 가져올 기사 수
PER_CATEGORY = 8      # 분야당 최대 기사 수
MODEL = "claude-haiku-5-5"
PERSPECTIVE = "핵심을 1문장으로 요약하고, 광고·마케팅·미디어 업무에 의미가 있으면 시사점을 한 줄 덧붙인다"

# 분야: [(출처 이름, RSS 주소), ...]  / 분야를 늘리려면 한 줄 추가
FEEDS = {
    "종합": [("매일경제", "https://www.mk.co.kr/rss/40300001/"),
            ("연합뉴스TV", "http://www.yonhapnewstv.co.kr/browse/feed/")],
    "경제": [("연합뉴스TV", "http://www.yonhapnewstv.co.kr/category/news/economy/feed/")],
    "금융·증권": [("세계파이낸셜뉴스", "https://www.segyefn.com/views/rss/finance.xml"),
                 ("세계파이낸셜뉴스", "https://www.segyefn.com/views/rss/stock.xml")],
    "산업·기업": [("세계파이낸셜뉴스", "https://www.segyefn.com/views/rss/industry.xml")],
    "부동산": [("세계파이낸셜뉴스", "https://www.segyefn.com/views/rss/property.xml")],
    "정치": [("매일경제", "https://www.mk.co.kr/rss/30200030/")],
}
# ==============================

KST = timezone(timedelta(hours=9))


def clean(text, n=200):
    text = re.sub(r"<[^>]+>", " ", html.unescape(text or ""))
    return re.sub(r"\s+", " ", text).strip()[:n]


def fetch(cat):
    items, seen = [], set()
    for source, url in FEEDS[cat]:
        d = feedparser.parse(url, agent="Mozilla/5.0")
        print(f"[{cat}] {source} | 피드제목: {d.feed.get('title', '?')} | {len(d.entries)}건 | {url}")
        for e in d.entries[:PER_FEED]:
            title, link = clean(e.get("title"), 150), e.get("link", "")
            if not title or not link.startswith("http") or title in seen:
                continue
            seen.add(title)
            pp = e.get("published_parsed")
            pub = datetime(*pp[:6], tzinfo=timezone.utc).astimezone(KST).strftime("%m-%d %H:%M") if pp else ""
            items.append({"title": title, "link": link, "source": source,
                          "published": pub, "_snippet": clean(e.get("summary"))})
    return items[:PER_CATEGORY]


def summarize(cat, items):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key or not items:
        return  # 키가 없으면 헤드라인+링크만 저장 (무료)
    listing = "\n".join(f'{i + 1}. 제목: {x["title"]} / 발췌: {x["_snippet"]}' for i, x in enumerate(items))
    prompt = (f"{cat} 분야 기사 목록이다. 기사마다 100자 이내로 정리해라.\n"
              "- 기사 문장을 그대로 옮기지 말고 네 말로 다시 쓴다.\n"
              "- 제목과 발췌에 없는 사실은 추측해서 쓰지 않는다.\n"
              f"- 관점: {PERSPECTIVE}\n"
              '- JSON 배열만 출력: [{"id":1,"summary":"..."}]\n\n' + listing)
    body = json.dumps({"model": MODEL, "max_tokens": 3000, "thinking": {"type": "disabled"},
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", body, {
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            text = "".join(b.get("text", "") for b in json.load(r)["content"])
        for row in json.loads(text[text.index("["): text.rindex("]") + 1]):
            items[int(row["id"]) - 1]["summary"] = row["summary"]
    except Exception as ex:
        print(f"[{cat}] 요약 실패(헤드라인만 저장): {ex}")


out = {"updated": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"), "categories": []}
for cat in FEEDS:
    items = fetch(cat)
    summarize(cat, items)
    for x in items:
        x.pop("_snippet", None)
    out["categories"].append({"name": cat, "items": items})

if not any(c["items"] for c in out["categories"]):
    raise SystemExit("모든 피드에서 기사를 가져오지 못했습니다. 기존 데이터를 유지합니다.")

os.makedirs("data", exist_ok=True)
with open("data/news.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print("data/news.json 저장 완료")
