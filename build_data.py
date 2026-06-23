"""
true_result.json(football-data.org 포맷)을 읽어 matches.json, results.json을 재생성한다.

경기 결과가 갱신되면(=true_result.json을 새로 받으면) 이 스크립트만 다시 실행하면
matches.json/results.json이 최신 상태로 갱신된다.

    python3 build_data.py
"""
import json
from pathlib import Path

BASE = Path(__file__).parent
SRC_PATH      = BASE / "true_result.json"
MATCHES_PATH  = BASE / "matches.json"
RESULTS_PATH  = BASE / "results.json"


def main():
    with open(SRC_PATH, encoding="utf-8") as f:
        data = json.load(f)

    matches_out = []
    results_out = {}

    for m in data["matches"]:
        entry = {
            "id":    m["id"],
            "team1": m["homeTeam"]["name"],
            "team2": m["awayTeam"]["name"],
        }
        if m.get("group"):
            entry["group"] = m["group"]
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

    print(f"matches.json 갱신: 경기 {len(matches_out)}개")
    print(f"results.json 갱신: 결과 {len(results_out)}개 (미종료 {len(matches_out) - len(results_out)}개)")


if __name__ == "__main__":
    main()
