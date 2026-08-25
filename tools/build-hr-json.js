#!/usr/bin/env node
/* ══════════════════════════════════════════════════════════════════════════
 *  build-hr-json.js — 인력관리 포털(HTML) → data/hr.json 생성기
 *
 *  [배경] 통합보고서 시스템이 HR 포털 HTML을 정규식으로 파싱하고 있어
 *         UI가 바뀌면 인력 데이터가 통째로 유실됨(합계만 잡히고 명부 누락).
 *         → BMS·WBS와 동일하게 JSON 엔드포인트를 제공하도록 전환.
 *
 *  [사용법]
 *    node tools/build-hr-json.js  [입력 HTML]  [출력 JSON]
 *    기본값: index.html → data/hr.json
 *
 *  [권장 배치] Asan-HR-Management-Portal 저장소에 본 스크립트를 두고
 *             GitHub Actions에서 index.html 갱신 시 자동 재생성
 * ══════════════════════════════════════════════════════════════════════════ */
const fs = require("fs");
const path = require("path");

const SRC = process.argv[2] || "index.html";
const OUT = process.argv[3] || "data/hr.json";

const ROLE_BY_ORG = {
  "제일엔지니어링종합건축사사무소": "직접보조사업자(수행기관·총괄 PMO)",
  "호서대학교 산학협력단": "간접보조사업자",
  "충남연구원": "간접보조사업자",
  "한국과학기술원 (KAIST)": "간접보조사업자",
  "한국과학기술원(KAIST)": "간접보조사업자",
};

const strip = (s) => String(s || "").replace(/<[^>]+>/g, "").replace(/&nbsp;/g, " ")
  .replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">")
  .replace(/[\u2705\u274C\u23F8\uFE0F]/g, "").replace(/\s+/g, " ").trim();

function rowsOf(tableHtml) {
  const body = (tableHtml.match(/<tbody[^>]*>([\s\S]*?)<\/tbody>/i) || [null, tableHtml])[1];
  const out = [];
  const rre = /<tr[^>]*>([\s\S]*?)<\/tr>/gi;
  let m;
  while ((m = rre.exec(body))) {
    const cells = [];
    const cre = /<t[dh][^>]*>([\s\S]*?)<\/t[dh]>/gi;
    let c;
    while ((c = cre.exec(m[1]))) cells.push(strip(c[1]));
    if (cells.length) out.push(cells);
  }
  return out;
}

function build(html) {
  /* ── 1. 기관별 요약 표 ── */
  const orgs = [];
  const tables = html.match(/<table[\s\S]*?<\/table>/gi) || [];
  for (const t of tables) {
    const head = strip((t.match(/<thead[\s\S]*?<\/thead>/i) || [""])[0]);
    if (!/기관명/.test(head) || !/총원/.test(head)) continue;
    for (const r of rowsOf(t)) {
      const name = r[0];
      if (!name || name === "합계") continue;
      const n = (i) => parseInt(String(r[i] || "").replace(/[^\d]/g, ""), 10) || 0;
      const rt = parseFloat(String(r[4] || "").replace(/[^\d.]/g, "")) || 0;
      orgs.push({
        org: name, total: n(1), active: n(2), ended: n(3), rate: rt,
        role: ROLE_BY_ORG[name] || r[5] || "간접보조사업자",
        members: [],
      });
    }
    break;
  }

  /* ── 2. 기관별 참여인력 상세(org-card) ── */
  const cards = html.split(/<div class="org-card"[^>]*>/i).slice(1);
  for (const card of cards) {
    const title = strip((card.match(/<div class="org-card-title"[^>]*>([\s\S]*?)<\/div>/i) || [])[1] || "");
    if (!title) continue;
    const org = orgs.find((o) => o.org === title)
      || orgs.find((o) => title.replace(/\s/g, "").includes(o.org.replace(/\s/g, "")))
      || (orgs.push({ org: title, total: 0, active: 0, ended: 0, rate: 0, role: ROLE_BY_ORG[title] || "간접보조사업자", members: [] }), orgs[orgs.length - 1]);
    const t = (card.match(/<table[\s\S]*?<\/table>/i) || [""])[0];
    for (const r of rowsOf(t)) {
      if (r.length < 5) continue;
      const period = r[4] || "";
      const pm = period.match(/(\d{4}-\d{2}-\d{2})\s*~\s*(\d{4}-\d{2}-\d{2})/);
      org.members.push({
        name: r[0], position: r[1], role: r[2],
        ratio: parseFloat(String(r[3] || "").replace(/[^\d.]/g, "")) || 0,
        from: pm ? pm[1] : "", to: pm ? pm[2] : "",
        status: /활성/.test(r[5] || "") ? "활성" : "종료",
      });
    }
  }

  /* ── 3. 정합성 보정: 상세가 있으면 상세 기준으로 합계 재산출 ── */
  for (const o of orgs) {
    if (!o.members.length) continue;
    const uniq = new Map();
    for (const m of o.members) {
      const k = `${m.name}|${m.position}`;
      const prev = uniq.get(k);
      if (!prev) uniq.set(k, { name: m.name, position: m.position, ratio: m.ratio, status: m.status, from: m.from, to: m.to, roles: [m.role] });
      else { prev.ratio += m.ratio; prev.roles.push(m.role); if (m.status === "활성") prev.status = "활성"; }
    }
    o.headcount = uniq.size;                       // 실인원(중복 역할 제거)
    o.manRatio = +[...uniq.values()].reduce((a, m) => a + m.ratio, 0).toFixed(1); // 참여율 합계(%)
    o.activeHeadcount = [...uniq.values()].filter((m) => m.status === "활성").length;
    o.activeManRatio = +[...uniq.values()].filter((m) => m.status === "활성").reduce((a, m) => a + m.ratio, 0).toFixed(1);
  }

  const total = orgs.reduce((a, o) => a + o.total, 0);
  const active = orgs.reduce((a, o) => a + o.active, 0);
  const ended = orgs.reduce((a, o) => a + o.ended, 0);

  const dataBase = (html.match(/데이터 기준:\s*([\d-]+)/) || [])[1] || "";
  const updated = (html.match(/최종 업데이트:\s*([\d-]+)/) || [])[1] || new Date().toISOString().slice(0, 10);

  return {
    meta: {
      project: "아산시 강소형 스마트시티 조성사업",
      source: "Asan-HR-Management-Portal",
      schema: "hr.v1",
      data_base: dataBase,
      generated_at: new Date().toISOString(),
      updated_at: updated,
      note: "인건비 정산은 실지급액 × 참여기간 × 참여율 기준. ratio는 협약상 참여율(%)",
    },
    total, active, ended,
    rate: total ? +((active / total) * 100).toFixed(1) : 0,
    headcount: orgs.reduce((a, o) => a + (o.headcount || 0), 0),
    orgs,
  };
}

const html = fs.readFileSync(SRC, "utf8");
const json = build(html);
fs.mkdirSync(path.dirname(OUT), { recursive: true });
fs.writeFileSync(OUT, JSON.stringify(json, null, 2), "utf8");
console.log(`[hr.json] ${OUT}  기관 ${json.orgs.length} / 등록 ${json.total}명 / 실인원 ${json.headcount}명 / 활성 ${json.active}명`);
json.orgs.forEach((o) => console.log(`  - ${o.org}: 등록 ${o.total} / 실인원 ${o.headcount || "-"} / 명부 ${o.members.length}행 / 참여율합 ${o.manRatio || "-"}%`));
