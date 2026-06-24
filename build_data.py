"""
group_stage_result.json(football-data.org 포맷, 조별리그+토너먼트 전체 104경기 구조)을
기본 골격으로 matches.json, results.json을 재생성한다.

true_result.json이 같은 폴더에 있으면, 그 안의 경기들(id 기준)로 status/score를
덮어쓴다 — true_result.json은 보통 더 최신 스냅샷이지만 조별리그 경기 전체를
다 담고 있지 않을 수 있어서, "전체 구조는 group_stage_result.json, 최신 결과는
true_result.json"으로 합치는 방식이다.

경기 결과가 갱신되면(=true_result.json을 새로 받으면) 이 스크립트만 다시 실행하면
matches.json/results.json이 최신 상태로 갱신된다.

    python3 build_data.py

주의: 16강(Round of 32) 이후 토너먼트 경기는 조별리그 결과가 나오기 전까지
homeTeam/awayTeam이 비어있다(대진 미정). 이런 경기는 matches.json에서 제외하고,
조별리그가 끝나 대진이 확정된 뒤 다시 실행하면 자동으로 추가된다.
"""
import json
from pathlib import Path

BASE = Path(__file__).parent
SRC_PATH       = BASE / "group_stage_result.json"
OVERRIDE_PATH  = BASE / "true_result.json"
MATCHES_PATH   = BASE / "matches.json"
RESULTS_PATH   = BASE / "results.json"

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
    matches_by_id = {m["id"]: m for m in data["matches"]}

    updated = 0
    if OVERRIDE_PATH.exists():
        with open(OVERRIDE_PATH, encoding="utf-8") as f:
            override = json.load(f)
        for om in override["matches"]:
            if om["id"] in matches_by_id:
                # matches_by_id의 값은 data["matches"] 원소에 대한 참조라서,
                # 여기서 갱신하면 data 자체도 같이 최신화된다.
                matches_by_id[om["id"]]["status"] = om["status"]
                matches_by_id[om["id"]]["score"]  = om["score"]
                updated += 1
        print(f"true_result.json 기준 {updated}경기 결과를 최신으로 덮어씀")

        # group_stage_result.json 자체도 병합된 최신 상태로 다시 저장한다.
        # load_group_standings()가 이 파일을 직접 읽으므로, 안 그러면 조별리그
        # 순위표가 true_result.json 갱신 이전의 옛 결과로 계속 멈춰 있게 된다.
        if "resultSet" in data:
            data["resultSet"]["played"] = sum(
                1 for m in matches_by_id.values() if m["status"] == "FINISHED"
            )
        with open(SRC_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    matches_out = []
    results_out = {}
    skipped_tbd = 0

    for m in matches_by_id.values():
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
