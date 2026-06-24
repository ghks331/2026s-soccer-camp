"""
app.py — 월드컵 예측 CSV 리더보드
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

KST = timezone(timedelta(hours=9))  # 배포 서버는 보통 UTC라 명시적으로 한국 시간 사용

# ── 설정 ──────────────────────────────────────────────────────────────────────
MATCHES_PATH      = Path(__file__).parent / "matches.json"
RESULTS_PATH      = Path(__file__).parent / "results.json"
GROUP_STAGE_PATH  = Path(__file__).parent / "group_stage_result.json"
SUBMISSIONS_DIR   = Path(__file__).parent / "submissions"
SUBMISSIONS_DIR.mkdir(exist_ok=True)

SUBMISSION_COLS = ["team1", "team2", "team1_score", "team2_score", "team1_prob", "team2_prob", "type"]
REQUIRED_COLS   = set(SUBMISSION_COLS)
MEDALS = {0: "🥇", 1: "🥈", 2: "🥉"}

TEAM_OPTIONS = ["1팀: 에스파", "2팀: 국한기", "3팀: 골", "4팀: 레알"]

VIEW_BOARD  = "🏆 리더보드"
VIEW_UPLOAD = "📤 CSV 업로드"

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
if "flash" not in st.session_state:
    st.session_state.flash = None
if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0
if "active_view" not in st.session_state:
    st.session_state.active_view = VIEW_BOARD
if "view_widget_key" not in st.session_state:
    st.session_state.view_widget_key = 0

# rerun으로 넘어온 제출 완료 메시지를 한 번만 띄움 (rerun 직전 st.success는 화면 갱신과
# 동시에 사라지므로, session_state에 저장해 다음 실행 시 toast로 보여준다)
if st.session_state.flash:
    st.toast(st.session_state.flash, icon="✅")
    st.session_state.flash = None
    # 제출 직후 스크롤을 맨 위로 강제 이동 — 이게 없으면 탭은 리더보드로 바뀌어도
    # 스크롤 위치가 그대로 남아 새 탭의 중간/끝부분에 멈춰서 "아무 변화 없는" 것처럼 보임
    st.iframe(
        """<script>
        try { window.parent.scrollTo({top: 0, behavior: 'instant'}); } catch (e) {}
        try { window.parent.document.querySelector('[data-testid="stMain"]').scrollTo(0, 0); } catch (e) {}
        </script>""",
        height=1,  # st.iframe은 height=0을 허용하지 않음 (양의 정수/'stretch'/'content'만 가능)
    )


# ── 데이터 로드 ───────────────────────────────────────────────────────────────
def load_matches():
    with open(MATCHES_PATH, encoding="utf-8") as f:
        data = json.load(f)
    matches = data["matches"]
    return matches, {m["id"]: m for m in matches}


def _norm(name: str) -> str:
    return str(name).strip().casefold()


def build_match_lookup(matches: list[dict]) -> dict:
    """(team1, team2) 정규화 이름 쌍 -> (match_id, swapped) 매핑.
    CSV에 팀 순서가 반대로 들어와도 매칭되도록 양방향으로 등록한다."""
    lookup = {}
    for m in matches:
        a, b = _norm(m["team1"]), _norm(m["team2"])
        lookup[(a, b)] = (m["id"], False)
        lookup[(b, a)] = (m["id"], True)
    return lookup


def load_results() -> dict:
    if not RESULTS_PATH.exists():
        return {}
    with open(RESULTS_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return {str(k): v for k, v in data.get("results", {}).items()}


def load_group_standings() -> dict[str, list[dict]]:
    """조별리그 경기 결과로 조별 순위표(경기/승/무/패/득점/실점/득실차/승점)를 계산.
    승점 -> 득실차 -> 다득점 -> 팀명 순으로 정렬 (상대 전적·페어플레이 등 세부 타이브레이커는 생략)."""
    if not GROUP_STAGE_PATH.exists():
        return {}
    with open(GROUP_STAGE_PATH, encoding="utf-8") as f:
        data = json.load(f)

    groups: dict[str, dict[str, dict]] = {}
    for m in data["matches"]:
        if m["stage"] != "GROUP_STAGE" or not m.get("group"):
            continue
        g = group_label(m["group"])
        teams = groups.setdefault(g, {})
        home, away = m["homeTeam"]["name"], m["awayTeam"]["name"]
        for name in (home, away):
            teams.setdefault(name, {
                "team": name, "p": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0,
            })
        if m["status"] != "FINISHED":
            continue
        hs, as_ = m["score"]["fullTime"]["home"], m["score"]["fullTime"]["away"]
        th, ta = teams[home], teams[away]
        th["p"] += 1; ta["p"] += 1
        th["gf"] += hs; th["ga"] += as_
        ta["gf"] += as_; ta["ga"] += hs
        if hs > as_:
            th["w"] += 1; ta["l"] += 1
        elif hs < as_:
            ta["w"] += 1; th["l"] += 1
        else:
            th["d"] += 1; ta["d"] += 1

    standings = {}
    for g, teams in groups.items():
        rows = list(teams.values())
        for r in rows:
            r["gd"]  = r["gf"] - r["ga"]
            r["pts"] = r["w"] * 3 + r["d"]
        rows.sort(key=lambda r: (-r["pts"], -r["gd"], -r["gf"], r["team"]))
        standings[g] = rows
    return standings


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
        label = "⭕ 한 팀 점수만 (무승부 예측 틀림)" if is_draw else "⭕ 한 팀 점수만 (승패 틀림)"
        return {"pts": 3, "label": label}
    elif result_correct:
        label = "🤝 무승부만" if is_draw else "🔵 승패만"
        return {"pts": 1, "label": label}
    return {"pts": 0, "label": "❌ 모두 틀림"}


def score_df(df: pd.DataFrame, results: dict, match_lookup: dict) -> tuple[int, list[dict], int, list[dict]]:
    """팀 이름(team1, team2)으로 경기를 찾아 채점한다. 조별리그(type이 "Group Stage"로
    시작하는 행, 조는 무관)만 채점 대상으로 삼는다 — 조별리그에서 만난 두 팀이
    토너먼트에서 다시 만날 수 있어, 이름만으로는 어느 단계 경기인지 구분이 안 되기
    때문이다. 토너먼트 단계 행과, 매칭되는 경기가 없는 행은 모두 unmatched로
    집계하고 건너뛴다.

    한 행의 값이 깨져 있어도(빈 칸, 숫자가 아닌 값 등) 그 행만 건너뛰고 나머지는
    정상 채점한다 — 한 팀의 입력 오류가 전체 리더보드를 죽이면 안 되기 때문이다.
    문제가 있었던 행은 invalid_rows에 어떤 경기·어떤 문제였는지 기록해 반환한다."""
    total, details, unmatched = 0, [], 0
    invalid_rows: list[dict] = []
    for _, row in df.iterrows():
        team1, team2 = row.get("team1", "?"), row.get("team2", "?")

        if not str(row.get("type", "")).strip().lower().startswith("group stage"):
            unmatched += 1
            continue

        hit = match_lookup.get((_norm(team1), _norm(team2)))
        if hit is None:
            unmatched += 1
            continue

        mid, swapped = hit
        mid = str(mid)
        if mid not in results:
            continue
        r = results[mid]
        real_team1, real_team2 = r["team1_score"], r["team2_score"]

        try:
            if not swapped:
                pred_team1, pred_team2 = int(row["team1_score"]), int(row["team2_score"])
                prob1, prob2           = float(row["team1_prob"]), float(row["team2_prob"])
            else:  # CSV에 팀 순서가 반대로 적혀 있던 경우 -> 점수도 맞춰서 뒤집어 비교
                pred_team1, pred_team2 = int(row["team2_score"]), int(row["team1_score"])
                prob1, prob2           = float(row["team2_prob"]), float(row["team1_prob"])
        except (TypeError, ValueError) as e:
            invalid_rows.append({"team1": team1, "team2": team2, "error": str(e)})
            continue

        base = calc_score(pred_team1, pred_team2, real_team1, real_team2)

        total += base["pts"]
        details.append({
            "match_id":   int(mid),
            "pred_team1": pred_team1,
            "pred_team2": pred_team2,
            "team1_prob": prob1,
            "team2_prob": prob2,
            **base,
        })
    return total, details, unmatched, invalid_rows


def make_cnt(details: list[dict]) -> dict:
    cnt = {10: 0, 6: 0, 3: 0, 1: 0, 0: 0}
    for d in details:
        cnt[d["pts"]] += 1
    return cnt


def group_label(group: str | None) -> str:
    if group and group.startswith("GROUP_"):
        return f"{group[len('GROUP_'):]}조"
    return "조 정보 없음"


def detail_table(details: list[dict], match_map: dict, results: dict) -> pd.DataFrame:
    rows = []
    for d in details:
        m = match_map.get(d["match_id"], {})
        r = results.get(str(d["match_id"]), {})
        rows.append({
            "조":       group_label(m.get("group")),
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
        10: "background-color:#e8f5e9;color:#1b5e20",
        6:  "background-color:#fff3e0;color:#e65100",
        3:  "background-color:#fffde7;color:#8d6e00",
        1:  "background-color:#e3f2fd;color:#0d47a1",
        0:  "background-color:#ffebee;color:#b71c1c",
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
match_lookup        = build_match_lookup(matches)
results            = load_results()
all_subs           = load_submissions()

leaderboard: list[dict] = []
for team, history in all_subs.items():
    # 한 팀의 제출 파일이 깨져 있어도(예상 못 한 형태의 값 등) 그 팀만 "오류" 상태로
    # 표시하고 다른 팀의 리더보드는 정상 작동해야 한다 — 한 팀 문제로 전체가
    # 죽으면 안 되므로 팀 단위로 예외를 격리한다.
    try:
        total, details, unmatched, invalid_rows = score_df(history[-1]["df"], results, match_lookup)
        cnt = make_cnt(details)
        leaderboard.append({
            "team":         team,
            "score":        total,
            "scored":       len(details),
            "submissions":  len(history),
            "details":      details,
            "history":      history,
            "cnt":          cnt,
            "invalid_rows": invalid_rows,
            "error":        None,
        })
    except Exception as e:
        leaderboard.append({
            "team":         team,
            "score":        0,
            "scored":       0,
            "submissions":  len(history),
            "details":      [],
            "history":      history,
            "cnt":          {10: 0, 6: 0, 3: 0, 1: 0, 0: 0},
            "invalid_rows": [],
            "error":        str(e),
        })

# 동점 시 tiebreaker: 10점 횟수 → 6점 → 3점 → 1점 순으로 우선순위.
# 오류가 있는 팀은 항상 맨 뒤로 보낸다.
def _rank_key(r):
    return (r["error"] is not None, -r["score"], -r["cnt"][10], -r["cnt"][6], -r["cnt"][3], -r["cnt"][1])

leaderboard.sort(key=_rank_key)

# 순위 계산: 동점이면 같은 순위, 다음 순위는 동점자 수만큼 건너뜀 (예: 1,1,3,4)
ranks: list[int] = []
prev_key, prev_rank = None, 0
for i, row in enumerate(leaderboard):
    k = _rank_key(row)
    if k != prev_key:
        prev_rank = i + 1
        prev_key = k
    ranks.append(prev_rank)


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

# ════════════════════════════════════════════════════════════════════════════
# 조별리그 순위 — 탭과 무관하게 항상 보이도록 채점 기준 바로 다음에 배치
# ════════════════════════════════════════════════════════════════════════════
st.subheader("📊 조별리그 순위")
standings = load_group_standings()
if not standings:
    st.info("group_stage_result.json이 없어요. 조별리그 데이터를 먼저 추가해주세요.")
else:
    group_names = sorted(standings.keys())
    selected_group = st.selectbox("조 선택", group_names, key="group_select")

    rows = standings[selected_group]
    table_df = pd.DataFrame([
        {
            "순위":  i + 1,
            "팀":    r["team"],
            "경기":  r["p"],
            "승":    r["w"],
            "무":    r["d"],
            "패":    r["l"],
            "득점":  r["gf"],
            "실점":  r["ga"],
            "득실차": r["gd"],
            "승점":  r["pts"],
        }
        for i, r in enumerate(rows)
    ])

    st.dataframe(
        table_df,
        width="stretch",
        hide_index=True,
    )
    st.caption("16강 진출권 = 조 1·2위 · 승점 → 득실차 → 다득점 순으로 순위 결정")

st.divider()

# 상위 팀 요약 카드
if leaderboard:
    hero_cols = st.columns(min(len(leaderboard), 4))
    for i, row in enumerate(leaderboard[:4]):
        medal = MEDALS.get(ranks[i] - 1, f"{ranks[i]}위")
        with hero_cols[i]:
            st.metric(
                label=f"{medal}  {row['team']}",
                value=f"{row['score']}점",
                delta=f"제출 {row['submissions']}회 · {row['scored']}경기",
                delta_color="off",
            )

st.divider()


# ── 탭 ───────────────────────────────────────────────────────────────────────
# st.tabs()는 명시적으로 어느 탭을 보여줄지 제어할 수 없고, st.rerun() 호출 시
# 탭을 초기 탭으로 되돌리는 동작도 안정적이지 않았다. segmented_control로
# 대체했는데 두 가지 함정이 있었다:
#  1) key를 직접 쓰면 "위젯이 인스턴스화된 뒤에는 같은 run에서
#     session_state[key]를 못 바꾼다"는 제약에 걸림 (StreamlitAPIException이
#     try/except에 조용히 흡수되고 있었음)
#  2) key 없이 default만 쓰면, 사용자가 위젯을 한 번이라도 직접 클릭한 뒤로는
#     위젯 자체의 "마지막 클릭 상태"가 default보다 우선시되어 강제 전환이 무시됨
# uploader_key와 같은 패턴으로, 강제 전환할 때마다 위젯의 key 자체를 바꿔서
# "완전히 새로운 위젯"으로 재마운트시켜야 default가 다시 적용된다.
_selected_view = st.segmented_control(
    "화면 선택", [VIEW_BOARD, VIEW_UPLOAD],
    key=f"view_select_{st.session_state.view_widget_key}",
    default=st.session_state.active_view, label_visibility="collapsed",
)
if _selected_view is not None:
    st.session_state.active_view = _selected_view


# ════════════════════════════════════════════════════════════════════════════
# 화면 1: 리더보드 — session_state 토글로 상세 보기 (rerun 후에도 열린 상태 유지)
# ════════════════════════════════════════════════════════════════════════════
if st.session_state.active_view == VIEW_BOARD:
    col_h, col_btn = st.columns([5, 1])
    with col_h:
        st.subheader("🏆 전체 순위")
        st.caption(
            f"채점 완료: {len(results)} / {len(matches)}경기 "
            f"(현재 받을 수 있는 최대 점수: **{len(results) * 10}점**)  ·  "
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
            has_error = row["error"] is not None
            medal     = "⚠️" if has_error else MEDALS.get(ranks[i] - 1, f"{ranks[i]}위")
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
                if has_error:
                    st.caption("⚠️ 제출 파일에 문제가 있어요 — 상세 보기에서 확인하세요")
                else:
                    st.caption(f"제출 {row['submissions']}회 · {row['scored']}경기 채점")

            with c_bar:
                st.markdown("<div style='margin-top:14px'>", unsafe_allow_html=True)
                st.progress(0 if has_error else score / max_score)
                st.markdown("</div>", unsafe_allow_html=True)

            c_score.markdown(
                f"<div style='font-size:20px;font-weight:700;padding-top:8px;text-align:right'>"
                f"{'오류' if has_error else f'{score}점'}</div>",
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
                        "<div style='margin-left:8px;padding:12px 16px;"
                        "border-left:3px solid rgba(128,128,128,0.4)'>",
                        unsafe_allow_html=True,
                    )

                    # 최신 제출 채점표
                    st.markdown(
                        f"**최신 제출 채점 결과**  "
                        f"<span style='color:gray;font-size:12px'>"
                        f"{fmt_ts(row['history'][-1]['ts'])}</span>",
                        unsafe_allow_html=True,
                    )

                    if row["error"] is not None:
                        st.error(
                            f"이 팀의 최신 제출 파일을 채점하는 중 오류가 발생했습니다:\n\n"
                            f"`{row['error']}`\n\n"
                            f"CSV의 `team1_score`/`team2_score`/`team1_prob`/`team2_prob` 값이 "
                            f"비어있거나 숫자가 아닌 행이 있는지 확인해주세요."
                        )

                    invalid_rows = row.get("invalid_rows") or []
                    if invalid_rows:
                        st.warning(
                            f"⚠️ 값이 잘못돼 채점에서 제외된 행 {len(invalid_rows)}개:\n\n"
                            + "\n".join(
                                f"- {r['team1']} vs {r['team2']} ({r['error']})"
                                for r in invalid_rows
                            )
                        )

                    details = row["details"]
                    if row["error"] is not None:
                        pass
                    elif not details:
                        st.caption("채점 가능한 경기가 없어요. results.json에 결과가 입력되면 반영됩니다.")
                    else:
                        df_show = detail_table(details, match_map, results)
                        st.markdown(pills_html(row["cnt"]), unsafe_allow_html=True)

                        # 조별로 테이블을 나눠서 표시 (A조 -> ... -> L조 -> 조 정보 없음)
                        groups = sorted(
                            df_show["조"].unique(),
                            key=lambda g: (g == "조 정보 없음", g),
                        )
                        for g in groups:
                            st.markdown(f"**{g}**")
                            g_df = df_show[df_show["조"] == g].drop(columns=["조"])
                            st.dataframe(
                                g_df.style.apply(highlight_pts, axis=1),
                                width="stretch",
                                hide_index=True,
                            )

                    # 제출 히스토리
                    history = row["history"]
                    if len(history) > 1:
                        st.divider()
                        st.markdown("**제출 기록**")
                        hist_rows = []
                        prev_score = None
                        for idx, entry in enumerate(history):
                            # 과거 제출 회차 하나가 깨져 있어도 그 회차만 "오류"로
                            # 표시하고 나머지 회차/팀에는 영향이 없게 격리한다
                            try:
                                h_score, _, _, _ = score_df(entry["df"], results, match_lookup)
                            except Exception:
                                h_score = None

                            if h_score is None:
                                change = "⚠️ 오류"
                            elif prev_score is None:
                                change = "—"
                            else:
                                diff   = h_score - prev_score
                                change = f"▲ {diff}점" if diff > 0 else (f"▼ {abs(diff)}점" if diff < 0 else "–")
                            hist_rows.append({
                                "회차":      f"{idx+1}차",
                                "제출 시각": fmt_ts(entry["ts"]),
                                "점수":      h_score if h_score is not None else "오류",
                                "변화":      change,
                                "비고":      "← 현재" if idx == len(history) - 1 else "",
                            })
                            if h_score is not None:
                                prev_score = h_score

                        st.dataframe(
                            pd.DataFrame(hist_rows),
                            width="stretch",
                            hide_index=True,
                        )

                    st.markdown("</div>", unsafe_allow_html=True)

            st.markdown("---")


# ════════════════════════════════════════════════════════════════════════════
# 화면 2: CSV 업로드
# ════════════════════════════════════════════════════════════════════════════
elif st.session_state.active_view == VIEW_UPLOAD:
    st.subheader("📤 예측 CSV 업로드")
    st.caption(
        "필수 컬럼: `team1`, `team2`, `team1_score`, `team2_score`, `team1_prob`, `team2_prob`, `type`  "
        "(팀 이름으로 경기를 찾아 채점합니다 — team1/team2 순서가 바뀌어도 매칭됩니다. "
        "아직 치르지 않았거나 목록에 없는 경기 행은 조용히 채점에서 제외됩니다. "
        "확률은 0~1 사이 값, 둘의 합이 1을 넘지 않아야 함)  "
        "— 같은 팀 이름으로 다시 제출하면 기록이 누적됩니다."
    )

    template_df = pd.DataFrame([
        {"team1": m["team1"], "team2": m["team2"],
         "team1_score": 0, "team2_score": 0, "team1_prob": 0.5, "team2_prob": 0.5,
         "type": ""}
        for m in matches
    ])

    col_tbl, col_dl = st.columns([3, 1])
    with col_tbl:
        st.dataframe(template_df, width="stretch", hide_index=True)
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

    # st.form으로 감싸서, 팀 선택·파일 선택 자체로는 재실행이 일어나지 않고
    # "제출하기"를 눌렀을 때 한 번만 재실행되도록 한다
    with st.form("upload_form"):
        team_name = st.selectbox(
            "팀 이름", TEAM_OPTIONS, index=None, placeholder="팀을 선택해주세요",
        )
        uploaded  = st.file_uploader(
            "예측 CSV 파일", type=["csv"],
            key=f"uploader_{st.session_state.uploader_key}",
        )
        submitted = st.form_submit_button("🚀 제출하기", type="primary", width="stretch")

    if submitted:
        if not team_name:
            st.error("팀을 선택해주세요.")
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
                    ts = datetime.now(KST).strftime("%Y%m%d_%H%M%S")
                    df[SUBMISSION_COLS].to_csv(
                        team_dir / f"{ts}.csv", index=False
                    )

                    _, _, unmatched, invalid_rows = score_df(df, results, match_lookup)
                    msg = f"{team_name} 제출 완료! ({len(df)}경기)"
                    if unmatched:
                        msg += f" — 팀 이름을 못 찾은 행 {unmatched}개는 채점에서 제외됩니다."
                    if invalid_rows:
                        bad = ", ".join(f"{r['team1']} vs {r['team2']}" for r in invalid_rows[:3])
                        more = f" 등 {len(invalid_rows)}건" if len(invalid_rows) > 3 else ""
                        msg += f" — 점수/확률 값이 잘못된 행({bad}{more})은 채점에서 제외됩니다."

                    # rerun 직후에도 보이도록 메시지를 session_state에 남기고,
                    # 업로더 key를 바꿔 파일 선택 상태를 초기화한다
                    st.session_state.flash = msg
                    st.session_state.uploader_key += 1
                    # 리더보드는 항상 전부 접힌 상태로 시작
                    st.session_state.open_team = None
                    # 화면을 명시적으로 리더보드로 전환. 위젯을 새 key로 재마운트해야
                    # (사용자가 이미 CSV 업로드를 클릭해둔 상태에서도) default가 적용된다
                    st.session_state.active_view = VIEW_BOARD
                    st.session_state.view_widget_key += 1
                    st.rerun()
            except Exception as e:
                st.error(f"파일 읽기 실패: {e}")
