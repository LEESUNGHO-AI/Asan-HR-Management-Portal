#!/usr/bin/env python3
"""
아산시 스마트시티 HR 대시보드 — Notion → GitHub Pages 자동 동기화
Notion 대시보드 페이지의 테이블 데이터를 파싱하여 index.html을 생성합니다.

파이프라인: Notion Page → Notion API → parse → HTML → git push → GitHub Pages

환경변수:
  NOTION_TOKEN  : Notion Integration 토큰

v2.1 수정사항:
  - callout 파싱 버그 수정: 파일명의 숫자(202601)를 인원수로 오인하는 문제
    → re.search(r"(\d+)") → re.search(r"등록인원[:\s]*(\d+)") 등 키워드 기반 정확 추출
  - 활성비율 0.0% 표시 버그 수정
"""
import os, sys, json, re, requests
from datetime import datetime, date

# ─── 설정 ───
NOTION_PAGE_ID = "2b850aa9577d8128ad35d86b79f67d12"
NOTION_API     = "https://api.notion.com/v1"
NOTION_VER     = "2022-06-28"

ORG_ORDER = [
    "제일엔지니어링종합건축사사무소",
    "충남연구원",
    "한국과학기술원 (KAIST)",
    "호서대학교 산학협력단",
]
ORG_SHORT = {
    "제일엔지니어링종합건축사사무소": "제일엔지니어링",
    "충남연구원": "충남연구원",
    "한국과학기술원 (KAIST)": "KAIST",
    "호서대학교 산학협력단": "호서대학교",
}
ORG_ROLE = {
    "제일엔지니어링종합건축사사무소": "직접보조사업자 (수행기관)",
    "충남연구원": "간접보조사업자",
    "한국과학기술원 (KAIST)": "간접보조사업자",
    "호서대학교 산학협력단": "간접보조사업자",
}

# ─── Notion API ───
def _hdr(tk):
    return {"Authorization": f"Bearer {tk}", "Notion-Version": NOTION_VER}

def get_blocks(tk, block_id):
    blocks, url = [], f"{NOTION_API}/blocks/{block_id}/children?page_size=100"
    while url:
        r = requests.get(url, headers=_hdr(tk)); r.raise_for_status()
        d = r.json(); blocks.extend(d.get("results", []))
        url = f"{NOTION_API}/blocks/{block_id}/children?page_size=100&start_cursor={d['next_cursor']}" if d.get("has_more") else None
    return blocks

def rt_text(rt_list):
    return "".join(r.get("plain_text", "") for r in rt_list)

def table_rows(tk, tbl):
    rows = []
    for c in get_blocks(tk, tbl["id"]):
        if c["type"] == "table_row":
            rows.append([rt_text(cell) for cell in c["table_row"]["cells"]])
    return rows

# ─── Notion 파싱 ───
def parse_notion(tk):
    blocks = get_blocks(tk, NOTION_PAGE_ID)
    data = {
        "base_month": "", "total": 0, "active": 0, "update_date": "",
        "org_summary": [],
        "org_members": {o: {"active": [], "ended": []} for o in ORG_ORDER},
    }

    cur_org, cur_status, section = None, None, ""

    for b in blocks:
        bt = b["type"]

        if bt == "callout":
            txt = rt_text(b["callout"]["rich_text"])
            if "기준월" in txt:
                # ★ v2.1 수정: 줄 단위 → 키워드 단위 정확 추출 ★
                # 기준월 추출
                m = re.search(r"기준월[:\s]*([\d]{4}-[\d]{2})", txt)
                if m: data["base_month"] = m.group(1)

                # ★ 핵심 수정: 키워드 바로 뒤의 숫자만 추출 (파일명 숫자 오염 방지) ★
                m = re.search(r"등록인원[:\s]*(\d+)", txt)
                if m: data["total"] = int(m.group(1))

                m = re.search(r"활성인원[:\s]*(\d+)", txt)
                if m: data["active"] = int(m.group(1))

                m = re.search(r"업데이트[:\s]*([\d-]+)", txt)
                if m: data["update_date"] = m.group(1)

        elif bt == "heading_2":
            section = rt_text(b["heading_2"]["rich_text"])
        elif bt == "heading_3":
            h3 = rt_text(b["heading_3"]["rich_text"])
            for o in ORG_ORDER:
                if o in h3: cur_org = o; break
            cur_status = None

        elif bt == "paragraph":
            pt = rt_text(b["paragraph"]["rich_text"])
            if "✅ 활성" in pt: cur_status = "active"
            elif "⬜ 종료" in pt: cur_status = "ended"

        elif bt == "table":
            rows = table_rows(tk, b)
            if not rows: continue
            hdr = rows[0]

            # 기관별 현황 요약
            if "기관별" in section and len(hdr) >= 5 and "기관명" in hdr[0]:
                for r in rows[1:]:
                    if r[0].startswith("합계") or r[0].startswith("**"): continue
                    data["org_summary"].append({
                        "org": r[0].replace("**",""), "role": r[1] if len(r)>1 else "",
                        "total": r[2] if len(r)>2 else "0",
                        "active": r[3] if len(r)>3 else "0",
                        "ended": r[4] if len(r)>4 else "0",
                    })
                continue

            # 인력 목록 테이블
            if cur_org and cur_status:
                for r in rows[1:]:
                    if len(hdr) == 6:
                        m = {"no":r[0],"name":r[1],"title":r[2] if len(r)>2 else "",
                             "role":r[3] if len(r)>3 else "","rate":r[4] if len(r)>4 else "",
                             "period":r[5] if len(r)>5 else ""}
                    elif len(hdr) == 5:
                        m = {"no":r[0],"name":r[1],"title":"","role":"",
                             "rate":r[2] if len(r)>2 else "","period":r[3] if len(r)>3 else ""}
                    else: continue
                    if m.get("name"):
                        data["org_members"].setdefault(cur_org, {"active":[],"ended":[]})
                        data["org_members"][cur_org][cur_status].append(m)

    # 보정: callout에서 파싱 실패 시 테이블 데이터로 계산
    if not data["total"]:
        data["total"] = sum(len(v["active"])+len(v["ended"]) for v in data["org_members"].values())
    if not data["active"]:
        data["active"] = sum(len(v["active"]) for v in data["org_members"].values())
    if not data["update_date"]: data["update_date"] = date.today().isoformat()
    if not data["base_month"]: data["base_month"] = date.today().strftime("%Y-%m")
    return data

# ─── HTML 생성 ───
def gen_html(d):
    today_str = date.today().isoformat()
    bm = d["base_month"]; total = d["total"]; active = d["active"]
    ended = total - active
    pct = round(active/total*100,1) if total else 0
    dday = max(0, (date(2026,12,31)-date.today()).days)

    cl, cd, ba, be = [], [], [], []
    org_rows_html = ""
    for info in d["org_summary"]:
        o = info["org"]; s = ORG_SHORT.get(o,o)
        tn = int(re.sub(r'\D','',info["total"]) or 0)
        an = int(re.sub(r'\D','',info["active"]) or 0)
        en = int(re.sub(r'\D','',info["ended"]) or 0)
        r_ = round(an/tn*100,1) if tn else 0
        cl.append(s); cd.append(tn); ba.append(an); be.append(en)
        bdg = "active" if an>0 else "inactive"
        org_rows_html += f'<tr><td><strong>{o}</strong></td><td>{tn}명</td><td>{an}명</td><td>{en}명</td><td>{r_}%</td><td><span class="badge {bdg}">{ORG_ROLE.get(o,"")}</span></td></tr>\n'

    cards = ""
    for org in ORG_ORDER:
        mem = d["org_members"].get(org,{"active":[],"ended":[]})
        am, em = mem["active"], mem["ended"]
        tot = len(am)+len(em)
        if not tot: continue
        arows = ""
        for m in am:
            rd = m.get("role","") or m.get("title","") or "-"
            arows += f'<tr><td>{m["name"]}</td><td>{m.get("title","-")}</td><td>{rd}</td><td><span class="badge active">{m.get("rate","-")}</span></td><td>{m.get("period","-")}</td><td><span class="badge active">✅ 활성</span></td></tr>\n'
        erows = ""
        for m in em:
            rd = m.get("role","") or m.get("title","") or "-"
            erows += f'<tr><td>{m["name"]}</td><td>{m.get("title","-")}</td><td>{rd}</td><td><span class="badge inactive">{m.get("rate","-")}</span></td><td>{m.get("period","-")}</td><td><span class="badge inactive">⬜ 종료</span></td></tr>\n'
        cards += f'''<div class="org-card">
<div class="org-card-header"><div class="org-card-title"><i class="ri-building-2-fill"></i> {org}</div>
<div class="org-card-stats"><span class="badge active">활성 {len(am)}명</span><span class="badge inactive">종료 {len(em)}명</span><span class="meta">전체 {tot}명</span></div></div>
<div class="org-card-body"><table class="dt"><thead><tr><th>성명</th><th>직급</th><th>역할</th><th>투입률</th><th>투입기간</th><th>상태</th></tr></thead><tbody>{arows}{erows}</tbody></table></div></div>\n'''

    return HTML_TPL.format(
        bm=bm, today=today_str, dday=dday, total=total, active=active,
        ended=ended, pct=pct, org_rows=org_rows_html, cards=cards,
        cl=json.dumps(cl,ensure_ascii=False), cd=json.dumps(cd),
        ba=json.dumps(ba), be=json.dumps(be), page_id=NOTION_PAGE_ID)

HTML_TPL = r'''<!DOCTYPE html>
<html lang="ko"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>아산시 강소형 스마트시티 | 인력관리 대시보드 ({bm})</title>
<link href="https://cdn.jsdelivr.net/npm/remixicon@4.0.1/fonts/remixicon.css" rel="stylesheet">
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@300;400;500;600;700;900&family=Orbitron:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
:root{{--p:#00d4aa;--s:#7B61FF;--ok:#00FF88;--warn:#FFD93D;--err:#FF3366;--bg:#07090f;--card:#0d1117;--card2:#111822;--bdr:#1a2332;--t1:#E6EDF3;--t2:#7D8CA3;--glow:rgba(0,212,170,.15)}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'Noto Sans KR',sans-serif;background:var(--bg);color:var(--t1);min-height:100vh;line-height:1.6}}
.bg{{position:fixed;inset:0;z-index:-1;background:radial-gradient(circle at 15% 85%,rgba(0,212,170,.06),transparent 50%),radial-gradient(circle at 85% 15%,rgba(123,97,255,.06),transparent 50%),var(--bg)}}
header{{background:rgba(13,17,23,.95);border-bottom:1px solid var(--bdr);padding:1rem 2rem;position:sticky;top:0;z-index:100;backdrop-filter:blur(12px)}}
.hc{{max-width:1600px;margin:0 auto;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:.8rem}}
.logo{{display:flex;align-items:center;gap:1rem}}
.logo-i{{width:48px;height:48px;background:linear-gradient(135deg,var(--p),var(--s));border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:1.4rem;box-shadow:0 0 20px var(--glow)}}
.logo h1{{font-size:1.2rem;font-weight:700;background:linear-gradient(135deg,var(--p),#fff);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
.logo p{{font-size:.78rem;color:var(--t2)}}
.hi{{display:flex;align-items:center;gap:1.5rem}}
.dd{{background:rgba(255,51,102,.15);border:1px solid var(--err);border-radius:10px;padding:.4rem 1rem;text-align:center}}
.dd small{{font-size:.7rem;color:var(--t2)}}
.dd b{{font-family:'Orbitron';font-size:1.3rem;color:var(--err);display:block}}
.meta{{font-size:.78rem;color:var(--t2);line-height:1.5;text-align:right}}
main{{max-width:1600px;margin:0 auto;padding:1.5rem 2rem 3rem}}
.sg{{display:grid;grid-template-columns:repeat(4,1fr);gap:1rem;margin-bottom:1.5rem}}
.sc{{background:var(--card);border:1px solid var(--bdr);border-radius:14px;padding:1.3rem;position:relative;overflow:hidden;transition:transform .2s,box-shadow .2s}}
.sc:hover{{transform:translateY(-2px);box-shadow:0 8px 24px rgba(0,0,0,.3)}}
.sc::before{{content:'';position:absolute;top:0;left:0;width:100%;height:3px}}
.sc.p::before{{background:var(--p)}}.sc.g::before{{background:var(--ok)}}.sc.w::before{{background:var(--warn)}}.sc.e::before{{background:var(--err)}}
.si{{width:42px;height:42px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:1.2rem;margin-bottom:.8rem}}
.sc.p .si{{background:rgba(0,212,170,.15);color:var(--p)}}.sc.g .si{{background:rgba(0,255,136,.15);color:var(--ok)}}.sc.w .si{{background:rgba(255,217,61,.15);color:var(--warn)}}.sc.e .si{{background:rgba(255,51,102,.15);color:var(--err)}}
.st{{font-size:.85rem;color:var(--t2);margin-bottom:.3rem}}
.sv{{font-family:'JetBrains Mono';font-size:2rem;font-weight:700}}
.sc.p .sv{{color:var(--p)}}.sc.g .sv{{color:var(--ok)}}.sc.w .sv{{color:var(--warn)}}.sc.e .sv{{color:var(--err)}}
.ss{{font-size:.78rem;color:var(--t2);margin-top:.3rem}}
.cg{{display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:1.5rem}}
.cc{{background:var(--card);border:1px solid var(--bdr);border-radius:14px;padding:1.3rem}}
.ct{{font-size:1rem;font-weight:600;margin-bottom:1rem;display:flex;align-items:center;gap:.5rem}}
.ct i{{color:var(--p)}}
.tc{{background:var(--card);border:1px solid var(--bdr);border-radius:14px;padding:1.3rem;margin-bottom:1.5rem;overflow-x:auto}}
.tt{{font-size:1rem;font-weight:600;margin-bottom:1rem;display:flex;align-items:center;gap:.5rem}}
.tt i{{color:var(--p)}}
table.dt{{width:100%;border-collapse:collapse}}
.dt th{{padding:.7rem .8rem;background:var(--card2);border-bottom:1px solid var(--bdr);text-align:left;font-size:.82rem;font-weight:600;color:var(--p);white-space:nowrap}}
.dt td{{padding:.6rem .8rem;border-bottom:1px solid rgba(26,35,50,.5);font-size:.82rem}}
.dt tbody tr:hover{{background:rgba(0,212,170,.04)}}
.badge{{display:inline-block;padding:.2rem .6rem;border-radius:6px;font-size:.75rem;font-weight:500}}
.badge.active{{background:rgba(0,255,136,.15);color:var(--ok)}}.badge.inactive{{background:rgba(139,156,199,.12);color:var(--t2)}}
.org-card{{background:var(--card);border:1px solid var(--bdr);border-radius:14px;margin-bottom:1rem;overflow:hidden}}
.org-card-header{{padding:1rem 1.3rem;background:var(--card2);border-bottom:1px solid var(--bdr);display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:.5rem}}
.org-card-title{{font-size:1rem;font-weight:700;display:flex;align-items:center;gap:.5rem}}
.org-card-title i{{color:var(--p)}}
.org-card-stats{{display:flex;gap:.5rem;align-items:center;flex-wrap:wrap}}
.org-card-stats .meta{{font-size:.85rem}}
.org-card-body{{padding:.5rem;overflow-x:auto}}
.org-card-body .dt td{{font-size:.8rem}}
footer{{text-align:center;padding:2rem;border-top:1px solid var(--bdr);color:var(--t2);font-size:.8rem}}
footer a{{color:var(--p);text-decoration:none}}
@media(max-width:1024px){{.sg{{grid-template-columns:repeat(2,1fr)}}.cg{{grid-template-columns:1fr}}}}
@media(max-width:640px){{.sg{{grid-template-columns:1fr}}.hc{{flex-direction:column}}main{{padding:1rem}}}}
</style></head>
<body>
<div class="bg"></div>
<header><div class="hc">
<div class="logo"><div class="logo-i">🏛️</div><div><h1>아산시 강소형 스마트시티 조성사업</h1><p>인력관리 대시보드 v{bm}</p></div></div>
<div class="hi"><div class="dd"><small>사업 종료까지</small><b id="dd">D-{dday}</b></div><div class="meta">데이터 기준: {bm}<br>최종 업데이트: {today}</div></div>
</div></header>
<main>
<div class="sg">
<div class="sc p"><div class="si"><i class="ri-team-fill"></i></div><div class="st">총 등록 인력</div><div class="sv">{total}</div><div class="ss">4개 기관 컨소시엄</div></div>
<div class="sc g"><div class="si"><i class="ri-user-follow-fill"></i></div><div class="st">현재 활성 인력</div><div class="sv">{active}</div><div class="ss">활성비율 {pct}%</div></div>
<div class="sc w"><div class="si"><i class="ri-user-unfollow-fill"></i></div><div class="st">종료 인력</div><div class="sv">{ended}</div><div class="ss">투입 종료 인력</div></div>
<div class="sc e"><div class="si"><i class="ri-calendar-close-fill"></i></div><div class="st">사업 잔여일</div><div class="sv">D-{dday}</div><div class="ss">2026-12-31 완료</div></div>
</div>
<div class="cg">
<div class="cc"><div class="ct"><i class="ri-pie-chart-fill"></i> 기관별 인력 분포</div><canvas id="c1" height="220"></canvas></div>
<div class="cc"><div class="ct"><i class="ri-bar-chart-fill"></i> 기관별 활성/종료 현황</div><canvas id="c2" height="220"></canvas></div>
</div>
<div class="tc"><div class="tt"><i class="ri-building-2-fill"></i> 기관별 인력 현황</div>
<table class="dt"><thead><tr><th>기관명</th><th>총원</th><th>활성</th><th>종료</th><th>활성비율</th><th>구분</th></tr></thead>
<tbody>{org_rows}<tr style="font-weight:700;border-top:2px solid var(--bdr)"><td>합계</td><td>{total}명</td><td>{active}명</td><td>{ended}명</td><td>{pct}%</td><td></td></tr></tbody></table></div>
<div style="margin-bottom:1.5rem"><div class="tt" style="margin-bottom:1rem"><i class="ri-contacts-fill"></i> 기관별 참여인력 상세</div>{cards}</div>
</main>
<footer>
<p>📊 아산시 강소형 스마트시티 조성사업 인력관리 대시보드</p>
<p>📅 {today} | ✍️ Notion 자동 동기화 v2.1 | 📧 <a href="mailto:smartcity-pmo@cheileng.com">PMO 문의</a></p>
<p style="margin-top:.5rem"><a href="https://www.notion.so/{page_id}" target="_blank"><i class="ri-notion-fill"></i> Notion 원본 보기</a></p>
</footer>
<script>
(function(){{const e=new Date('2026-12-31'),n=new Date(),d=Math.ceil((e-n)/864e5);document.getElementById('dd').textContent='D-'+(d>0?d:0)}})();
new Chart(document.getElementById('c1').getContext('2d'),{{type:'doughnut',data:{{labels:{cl},datasets:[{{data:{cd},backgroundColor:['#00d4aa','#7B61FF','#FF6B35','#00FF88'],borderWidth:0,hoverOffset:8}}]}},options:{{responsive:true,cutout:'60%',plugins:{{legend:{{position:'right',labels:{{color:'#7D8CA3',font:{{size:12,family:'Noto Sans KR'}},padding:16}}}}}}}}}});
new Chart(document.getElementById('c2').getContext('2d'),{{type:'bar',data:{{labels:{cl},datasets:[{{label:'활성',data:{ba},backgroundColor:'rgba(0,255,136,.7)',borderRadius:4}},{{label:'종료',data:{be},backgroundColor:'rgba(139,156,199,.4)',borderRadius:4}}]}},options:{{responsive:true,plugins:{{legend:{{labels:{{color:'#7D8CA3',font:{{size:11}}}}}}}},scales:{{x:{{grid:{{display:false}},ticks:{{color:'#7D8CA3',font:{{size:11}}}}}},y:{{grid:{{color:'rgba(26,35,50,.6)'}},ticks:{{color:'#7D8CA3',stepSize:5}}}}}}}}}});
</script></body></html>'''

# ─── 메인 ───
def main():
    tk = os.environ.get("NOTION_TOKEN")
    if not tk: print("❌ NOTION_TOKEN 미설정"); sys.exit(1)

    print(f"🔄 Notion 동기화 시작 ({NOTION_PAGE_ID})")
    d = parse_notion(tk)

    print(f"📊 기준월: {d['base_month']} | 총 {d['total']}명 | 활성 {d['active']}명")
    for o in ORG_ORDER:
        m = d["org_members"].get(o, {"active":[],"ended":[]})
        print(f"   {ORG_SHORT.get(o,o)}: 활성 {len(m['active'])}명 / 종료 {len(m['ended'])}명")

    html = gen_html(d)
    with open("index.html", "w", encoding="utf-8") as f: f.write(html)
    print(f"✅ index.html ({len(html):,} bytes)")

if __name__ == "__main__": main()
