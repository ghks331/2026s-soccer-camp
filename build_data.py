"""
group_stage_result.json(football-data.org 포맷, 조별리그+토너먼트 전체 104경기)을
읽어 matches.json, results.json을 재생성한다.

경기 결과가 갱신되면(=group_stage_result.json을 새로 받으면) 이 스크립트만 다시
실행하면 matches.json/results.json이 최신 상태로 갱신된다.

    python3 build_data.py

주의: 16강(Round of 32) 이후 토너먼트 경기는 조별리그 결과가 나오기 전까지
homeTeam/awayTeam이 비어있다(대진 미정). 이런 경기는 matches.json에서 제외하고,
조별리그가 끝나 대진이 확정된 뒤 다시 실행하면 자동으로 추가된다.
"""
import json
from pathlib import Path

BASE = Path(__file__).parent
SRC_PATH      = BASE / "group_stage_result.json"
MATCHES_PATH  = BASE / "matches.json"
RESULTS_PATH  = BASE / "results.json"

# group_stage_result.json의 stage 값 -> 제출 CSV의 type 컬럼 표기값
STAGE_LABEL = {
    "GROUP_STAGE":    "Group Stage",
    "LAST_32":        "Round of 32",
    "LAST_16":        "Round of 16",
    "QUARTER_FINALS": "Quarterfinal",
    "SEMI_FINALS":    "Semifinal",
    "THIRD_PLACE":    "Third Place",
    "FINAL":          "Final",
}


def main():
    with open(SRC_PATH, encoding="utf-8") as f:
        data = json.load(f)

    matches_out = []
    results_out = {}
    skipped_tbd = 0

    for m in data["matches"]:
        home, away = m["homeTeam"].get("name"), m["awayTeam"].get("name")
        if not home or not away:
            skipped_tbd += 1  # 대진 미정 토너먼트 슬롯 — 아직 받을 수 없음
            continue

        stage_label = STAGE_LABEL.get(m["stage"], m["stage"])
        group = m.get("group")
        if group and m["stage"] == "GROUP_STAGE":
            # 조별리그는 어느 조인지까지 type에 묶어서 표기: "Group Stage(A)"
            stage_label = f"{stage_label}({group[len('GROUP_'):]})"

        entry = {
            "id":    m["id"],
            "team1": home,
            "team2": away,
            "type":  stage_label,
        }
        if group:
            entry["group"] = group
        matches_out.append(entry)

        if m["status"] == "FINISHED":
            ft = m["score"]["fullTime"]
            results_out[str(m["id"])] = {
                "team1_score": ft["home"],
                "team2_score": ft["away"],
            }

    with open(MATCHES_PATH, "w", encoding="utf-8") as f:
        json.dump({"matches": matches_out}, f, ensure_ascii=False, indent=2)

    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump({"results": results_out}, f, ensure_ascii=False, indent=2)

    print(f"matches.json 갱신: 경기 {len(matches_out)}개 (대진 미정으로 제외 {skipped_tbd}개)")
    print(f"results.json 갱신: 결과 {len(results_out)}개 (미종료 {len(matches_out) - len(results_out)}개)")


if __name__ == "__main__":
    main()
