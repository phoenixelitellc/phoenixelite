from typing import List, Dict
def graduation_urgency_weight(class_level: str) -> float:
    return {"freshman":0.2,"sophomore":0.4,"junior":0.7,"senior":1.0}.get((class_level or "").lower(),0.5)
def calculate_recruiting_propensity(players: List[Dict], decay: float = 0.6) -> float:
    if not players: return 1.0
    need = 1.0 / (1.0 + float(len(players)) / 10.0)
    return round(need, 3)
def final_match_score(school_propensity: float, class_level: str, alpha: float = 0.7) -> float:
    urgency = graduation_urgency_weight(class_level)
    return round((alpha*school_propensity + (1-alpha)*urgency) * 100.0, 1)
