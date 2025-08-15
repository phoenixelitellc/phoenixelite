from typing import List, Dict
from datetime import datetime
def calculate_graduation_year(class_level: str, now=None) -> int:
    if not class_level: return datetime.utcnow().year
    if now is None: now = datetime.utcnow()
    month, year, fall = now.month, now.year, now.month >= 8
    cl = (class_level or "").strip().lower()
    if cl == "senior":    return year + 1 if fall else year
    if cl == "junior":    return year + 2 if fall else year + 1
    if cl == "sophomore": return year + 3 if fall else year + 2
    if cl == "freshman":  return year + 4 if fall else year + 3
    return year
def graduation_urgency_weight(class_level: str) -> float:
    return {"freshman":0.2,"sophomore":0.4,"junior":0.7,"senior":1.0}.get((class_level or "").lower(),0.5)
def calculate_recruiting_propensity(players: List[Dict], decay: float = 0.6) -> float:
    if not players: return 1.0
    need = 1.0 / (1.0 + float(len(players)) / 10.0)
    return round(need, 3)
def final_match_score(school_propensity: float, class_level: str, alpha: float = 0.7) -> float:
    urgency = graduation_urgency_weight(class_level)
    return round((alpha*school_propensity + (1-alpha)*urgency) * 100.0, 1)
