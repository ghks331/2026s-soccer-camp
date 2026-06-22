"""
app.py — 월드컵 예측 CSV 리더보드
"""
import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

# ── 설정 ──────────────────────────────────────────────────────────────────────
MATCHES_PATH    = Path(__file__).parent / "matches.json"
RESULTS_PATH    = Path(__file__).parent / "results.json"
SUBMISSIONS_DIR = Path(__file__).parent / "submissions"
SUBMISSIONS_DIR.mkdir(exist_ok=True)

SUBMISSION_COLS = ["match_id", "pred_team1", "pred_team2", "team1_prob", "team2_prob"]
REQUIRED_COLS   = set(SUBMISSION_COLS)
MEDALS = {0: "🥇", 1: "🥈", 2: "🥉"}

st.set_page_config(
    page_title="⚽ 월드컵 예측 리더보드",
    page_icon="⚽",
    layout="wide",
)

st.markdown("""
<style>
.block-container { padding-top: 1.5rem; max-width: 1100px; }
.score-pill {
    display: inline-block;
    border: 1px solid rgba(128,128,128,0.3);
    border-radius: 8px;
    padding: 10px 14px;
    margin: 4px;
    text-align: center;
    min-width: 90px;
}
.score-pill .sp-emoji { font-size: 20px; }
.score-pill .sp-label { font-size: 12px; color: gray; margin-top: 2px; }
.score-pill .sp-value { font-size: 22px; font-weight: 700; margin-top: 2px; }
.team-row {
    display: flex; align-items: center; gap: 12px;
    padding: 10px 4px; border-bottom: 1px solid rgba(128,128,128,0.2);
}
</style>
""", unsafe_allow_html=True)


# ── 세션 상태 초기화 ──────────────────────────────────────────────────────────
if "open_team" not in st.session_state:
    st.session_state.open_team = None


# ── 데이터 로드 ───────────────────────────────────────────────────────────────
@st.cache_data
def load_matches():
    with open(MATCHES_PATH, encoding="utf-8") as f:
        data = json.load(f)
    matches = []
    for rnd in data["rounds"]:
        for m in rnd["matches"]:
            m["round"] = rnd["round"]
            matches.append(m)
    return matches, {m["id"]: m for m in matches}


def load_results() -> dict:
    if not RESULTS_PATH.exists():
        return {}
    with open(RESULTS_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return {str(k): v for k, v in data.get("results", {}).items()}


def load_submissions() -> dict[str, list[dict]]:
    """팀별 제출 기록: {team: [{ts, df}, ...]} 시간순"""
    team_subs: dict[str, list] = {}
    for team_dir in sorted(SUBMISSIONS_DIR.iterdir()):
        if not team_dir.is_dir():
            continue
        history = []
        for f in sorted(team_dir.glob("*.csv")):
            try:
                df = pd.read_csv(f)
                if REQUIRED_COLS.issubset(df.columns):
                    history.append({"ts": f.stem, "df": df})
            except Exception:
                pass
        if history:
            team_subs[team_dir.name] = history
    return team_subs


def fmt_ts(ts: str) -> str:
    try:
        return datetime.strptime(ts, "%Y%m%d_%H%M%S").strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ts


# ── 채점 ─────────────────────────────────────────────────────────────────────
def get_winner(team1: int, team2: int) -> str:
    """'1' = team1 승, '2' = team2 승, 'D' = 무승부"""
    if team1 > team2: return "1"
    elif team1 < team2: return "2"
    return "D"


def calc_score(pred_team1: int, pred_team2: int,
               real_team1: int, real_team2: int) -> dict:
    team1_exact    = pred_team1 == real_team1
    team2_exact    = pred_team2 == real_team2
    real_result    = get_winner(real_team1, real_team2)
    result_correct = get_winner(pred_team1, pred_team2) == real_result
    is_draw        = real_result == "D"

    if team1_exact and team2_exact:
        label = "🤝 무승부 + 두 팀 점수" if is_draw else "🎯 승패 + 두 팀 점수"
        return {"pts": 10, "label": label}
    elif (team1_exact or team2_exact) and result_correct:
        label = "🤝 무승부 + 한 팀 점수" if is_draw else "✅ 승패 + 한 팀 점수"
        return {"pts": 6, "label": label}
    elif team1_exact or team2_exact:
        return {"pts": 3, "label": "⭕ 한 팀 점수만 (승패 틀림)"}
    elif result_correct:
        label = "🤝 무승부만" if is_draw else "🔵 승패만"
        return {"pts": 1, "label": label}
    return {"pts": 0, "label": "❌ 모두 틀림"}


def score_df(df: pd.DataFrame, results: dict) -> tuple[int, list[dict]]:
    total, details = 0, []
    for _, row in df.iterrows():
        mid = str(int(row["match_id"]))
        if mid not in results:
            continue
        r = results[mid]
        real_team1, real_team2 = r["team1_score"], r["team2_score"]
        pred_team1, pred_team2 = int(row["pred_team1"]), int(row["pred_team2"])

        base = calc_score(pred_team1, pred_team2, real_team1, real_team2)

        total += base["pts"]
        details.append({
            "match_id":   int(mid),
            "pred_team1": pred_team1,
            "pred_team2": pred_team2,
            "team1_prob": float(row["team1_prob"]),
            "team2_prob": float(row["team2_prob"]),
            **base,
        })
    return total, details


def make_cnt(details: list[dict]) -> dict:
    cnt = {10: 0, 6: 0, 3: 0, 1: 0, 0: 0}
    for d in details:
        cnt[d["pts"]] += 1
    return cnt


def detail_table(details: list[dict], match_map: dict, results: dict) -> pd.DataFrame:
    rows = []
    for d in details:
        m = match_map.get(d["match_id"], {})
        r = results.get(str(d["match_id"]), {})
        rows.append({
            "경기":     f"{m.get('team1','?')} vs {m.get('team2','?')}",
            "예측":     f"{d['pred_team1']} - {d['pred_team2']}",
            "실제":     f"{r.get('team1_score','?')} - {r.get('team2_score','?')}",
            "항목":     d["label"],
            "점수":     d["pts"],
            "예측 확률": f"{d['team1_prob']:.0%} / {d['team2_prob']:.0%}",
        })
    return pd.DataFrame(rows)


def highlight_pts(row):
    styles = {
        10: "background-color:#1e4620;color:#a5d6a7",
        6:  "background-color:#3e2a00;color:#ffcc80",
        3:  "background-color:#3e2c00;color:#fff59d",
        1:  "background-color:#0d2a4a;color:#90caf9",
        0:  "background-color:#3e1010;color:#ef9a9a",
    }
    return [styles.get(row["점수"], "")] * len(row)


def pills_html(cnt: dict) -> str:
    items = [
        ("🎯", "10점", cnt[10]),
        ("✅", "6점",  cnt[6]),
        ("⭕", "3점",  cnt[3]),
        ("🔵", "1점",  cnt[1]),
        ("❌", "0점",  cnt[0]),
    ]
    inner = "".join(
        f"<div class='score-pill'>"
        f"<div class='sp-emoji'>{e}</div>"
        f"<div class='sp-label'>{l}</div>"
        f"<div class='sp-value'>{n}회</div>"
        f"</div>"
        for e, l, n in items
    )
    return f"<div style='display:flex;gap:10px;margin:10px 0;flex-wrap:wrap'>{inner}</div>"


# ── 데이터 준비 ───────────────────────────────────────────────────────────────
matches, match_map = load_matches()
results            = load_results()
all_subs           = load_submissions()

leaderboard: list[dict] = []
for team, history in all_subs.items():
    total, details = score_df(history[-1]["df"], results)
    cnt = make_cnt(details)
    leaderboard.append({
        "team":        team,
        "score":       total,
        "scored":      len(details),
        "submissions": len(history),
        "details":     details,
        "history":     history,
        "cnt":         cnt,
    })

# 동점 시 tiebreaker: 10점 횟수 → 6점 → 3점 → 1점 순으로 우선순위
leaderboard.sort(
    key=lambda r: (-r["score"], -r["cnt"][10], -r["cnt"][6], -r["cnt"][3], -r["cnt"][1])
)


# ════════════════════════════════════════════════════════════════════════════
# 상단 헤더 — 채점 기준 + 순위 요약
# ════════════════════════════════════════════════════════════════════════════
st.title("⚽ 월드컵 예측 리더보드")

with st.expander("📋 점수 채점 기준 보기", expanded=True):
    ca, cb, cc, cd, ce = st.columns(5)
    def _crit(col, emoji, pts, cond, ex):
        col.markdown(
            f"<div style='text-align:center;font-size:26px'>{emoji}</div>"
            f"<div style='text-align:center;font-size:20px;font-weight:700'>{pts}</div>"
            f"<div style='text-align:center;font-size:12px;margin-top:4px'>{cond}</div>"
            f"<div style='text-align:center;font-size:11px;color:gray;margin-top:3px'>{ex}</div>",
            unsafe_allow_html=True,
        )
    _crit(ca, "🎯", "10점", "승패(무승부 포함) +<br><b>두 팀</b> 점수", "예) 2-1 / 실제 2-1")
    _crit(cb, "✅", "6점",  "승패(무승부 포함) +<br><b>한 팀</b> 점수", "예) 2-0 / 실제 2-1")
    _crit(cc, "⭕", "3점",  "한 팀 점수만<br>(승패 틀림)",            "예) 2-1 / 실제 2-2")
    _crit(cd, "🔵", "1점",  "승패(무승부 포함)만",                    "예) 1-0 / 실제 3-0")
    _crit(ce, "❌", "0점",  "승패·점수<br>모두 틀림",                 "예) 1-0 / 실제 0-2")

st.divider()

# 상위 팀 요약 카드
if leaderboard:
    hero_cols = st.columns(min(len(leaderboard), 4))
    for i, row in enumerate(leaderboard[:4]):
        medal = MEDALS.get(i, f"{i+1}위")
        with hero_cols[i]:
            st.metric(
                label=f"{medal}  {row['team']}",
                value=f"{row['score']}점",
                delta=f"제출 {row['submissions']}회 · {row['scored']}경기",
                delta_color="off",
            )

st.divider()


# ── 탭 ───────────────────────────────────────────────────────────────────────
tab_board, tab_upload = st.tabs([
    "🏆 리더보드", "📤 CSV 업로드",
])


# ════════════════════════════════════════════════════════════════════════════
# 탭 1: 리더보드 — session_state 토글로 상세 보기 (rerun 후에도 열린 상태 유지)
# ════════════════════════════════════════════════════════════════════════════
with tab_board:
    col_h, col_btn = st.columns([5, 1])
    with col_h:
        st.subheader("🏆 전체 순위")
        st.caption(
            f"채점 완료: {len(results)} / {len(matches)}경기  ·  "
            f"참가 팀: {len(leaderboard)}팀  ·  "
            f"동점 시 10점 → 6점 → 3점 → 1점 횟수 순 우선"
        )
    with col_btn:
        st.markdown("<div style='padding-top:26px'>", unsafe_allow_html=True)
        if st.button("🔄 새로고침", key="refresh"):
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)

    if not leaderboard:
        st.info("아직 제출된 예측이 없어요.")
    else:
        max_score = max(r["score"] for r in leaderboard) or 1

        for i, row in enumerate(leaderboard):
            medal     = MEDALS.get(i, f"{i+1}위")
            team      = row["team"]
            score     = row["score"]
            is_open   = st.session_state.open_team == team

            # ── 순위 행 ──────────────────────────────────────────────
            c_rank, c_team, c_bar, c_score, c_btn = st.columns([0.5, 2, 3.5, 1, 1.2])

            c_rank.markdown(
                f"<div style='font-size:24px;padding-top:6px'>{medal}</div>",
                unsafe_allow_html=True,
            )
            with c_team:
                st.markdown(f"**{team}**")
                st.caption(f"제출 {row['submissions']}회 · {row['scored']}경기 채점")

            with c_bar:
                st.markdown("<div style='margin-top:14px'>", unsafe_allow_html=True)
                st.progress(score / max_score)
                st.markdown("</div>", unsafe_allow_html=True)

            c_score.markdown(
                f"<div style='font-size:20px;font-weight:700;padding-top:8px;text-align:right'>"
                f"{score}점</div>",
                unsafe_allow_html=True,
            )

            btn_label = "▲ 닫기" if is_open else "▼ 상세"
            if c_btn.button(btn_label, key=f"toggle_{team}"):
                # 같은 팀 다시 클릭 → 닫기 / 다른 팀 → 열기
                st.session_state.open_team = None if is_open else team
                st.rerun()

            # ── 상세 패널 (열린 팀만 표시) ───────────────────────────
            if is_open:
                with st.container():
                    st.markdown(
                        f"<div style='margin-left:8px;padding:12px 16px;"
                        f"border-left:3px solid rgba(128,128,128,0.4)'>",
                        unsafe_allow_html=True,
                    )

                    # 최신 제출 채점표
                    st.markdown(
                        f"**최신 제출 채점 결과**  "
                        f"<span style='color:gray;font-size:12px'>"
                        f"{fmt_ts(row['history'][-1]['ts'])}</span>",
                        unsafe_allow_html=True,
                    )

                    details = row["details"]
                    if not details:
                        st.caption("채점 가능한 경기가 없어요. results.json에 결과가 입력되면 반영됩니다.")
                    else:
                        df_show = detail_table(details, match_map, results)
                        st.dataframe(
                            df_show.style.apply(highlight_pts, axis=1),
                            use_container_width=True,
                            hide_index=True,
                        )
                        st.markdown(pills_html(row["cnt"]), unsafe_allow_html=True)

                    # 제출 히스토리
                    history = row["history"]
                    if len(history) > 1:
                        st.divider()
                        st.markdown("**제출 기록**")
                        hist_rows = []
                        prev_score = None
                        for idx, entry in enumerate(history):
                            h_score, _ = score_df(entry["df"], results)
                            if prev_score is None:
                                change = "—"
                            else:
                                diff   = h_score - prev_score
                                change = f"▲ {diff}점" if diff > 0 else (f"▼ {abs(diff)}점" if diff < 0 else "–")
                            hist_rows.append({
                                "회차":      f"{idx+1}차",
                                "제출 시각": fmt_ts(entry["ts"]),
                                "점수":      h_score,
                                "변화":      change,
                                "비고":      "← 현재" if idx == len(history) - 1 else "",
                            })
                            prev_score = h_score

                        st.dataframe(
                            pd.DataFrame(hist_rows),
                            use_container_width=True,
                            hide_index=True,
                        )

                    st.markdown("</div>", unsafe_allow_html=True)

            st.markdown("---")


# ════════════════════════════════════════════════════════════════════════════
# 탭 2: CSV 업로드
# ════════════════════════════════════════════════════════════════════════════
with tab_upload:
    st.subheader("📤 예측 CSV 업로드")
    st.caption(
        "필수 컬럼: `match_id`, `pred_team1`, `pred_team2`, `team1_prob`, `team2_prob`  "
        "(확률은 0~1 사이 값, 둘의 합이 1을 넘지 않아야 함)  "
        "— 같은 팀 이름으로 다시 제출하면 기록이 누적됩니다."
    )

    template_df = pd.DataFrame([
        {"match_id": m["id"], "team1": m["team1"], "team2": m["team2"],
         "pred_team1": 0, "pred_team2": 0, "team1_prob": 0.5, "team2_prob": 0.5}
        for m in matches
    ])

    col_tbl, col_dl = st.columns([3, 1])
    with col_tbl:
        st.dataframe(template_df, use_container_width=True, hide_index=True)
    with col_dl:
        st.download_button(
            "📥 빈 템플릿",
            template_df[SUBMISSION_COLS].to_csv(index=False),
            file_name="template.csv",
            mime="text/csv",
        )
        example_path = Path(__file__).parent / "example_submission.csv"
        if example_path.exists():
            st.download_button(
                "📥 예시 파일",
                example_path.read_bytes(),
                file_name="example_submission.csv",
                mime="text/csv",
            )

    st.divider()

    team_name = st.text_input("팀 이름", placeholder="예) TeamAlpha").strip()
    uploaded  = st.file_uploader("예측 CSV 파일", type=["csv"])

    if st.button("🚀 제출하기", type="primary", use_container_width=True):
        if not team_name:
            st.error("팀 이름을 입력해주세요.")
        elif not uploaded:
            st.error("CSV 파일을 선택해주세요.")
        else:
            try:
                df      = pd.read_csv(uploaded)
                missing = REQUIRED_COLS - set(df.columns)
                if missing:
                    st.error(f"필수 컬럼 누락: {missing}")
                else:
                    team_dir = SUBMISSIONS_DIR / team_name
                    team_dir.mkdir(exist_ok=True)
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    df[SUBMISSION_COLS].to_csv(
                        team_dir / f"{ts}.csv", index=False
                    )
                    st.success(f"✅ **{team_name}** 제출 완료! ({len(df)}경기)")
                    st.rerun()
            except Exception as e:
                st.error(f"파일 읽기 실패: {e}")
