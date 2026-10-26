"""Deterministic two-sided matching against explicitly synthetic inventory and buyer leads."""
from __future__ import annotations

import math
import re

from engine import extract_rules, qualify

MODELS = {
    "卡罗拉": ("丰田", "轿车", "燃油"), "凯美瑞": ("丰田", "轿车", "燃油"),
    "雅阁": ("本田", "轿车", "燃油"), "思域": ("本田", "轿车", "燃油"),
    "轩逸": ("日产", "轿车", "燃油"), "速腾": ("大众", "轿车", "燃油"),
    "高尔夫": ("大众", "两厢车", "燃油"), "Model 3": ("特斯拉", "轿车", "纯电"),
    "Model Y": ("特斯拉", "SUV", "纯电"), "宋PLUS": ("比亚迪", "SUV", "插混"),
    "宝马3系": ("宝马", "轿车", "燃油"), "奥迪A4": ("奥迪", "轿车", "燃油"),
}


def car(id, model, city, price, year, mileage, status="在售"):
    brand, body, energy = MODELS[model]
    return dict(id=id, brand=brand, model=model, city=city, price=price, year=year, mileage=mileage, body=body, energy=energy, status=status, synthetic=True)


INVENTORY = [
    car("V001", "卡罗拉", "北京", 12.6, 2022, 3.2),
    car("V002", "卡罗拉", "北京", 10.8, 2020, 5.6),
    car("V003", "轩逸", "北京", 9.6, 2021, 4.1),
    car("V004", "凯美瑞", "北京", 15.8, 2021, 4.5),
    car("V005", "雅阁", "北京", 14.6, 2020, 6.1),
    car("V006", "卡罗拉", "上海", 11.9, 2021, 3.9),
    car("V007", "宋PLUS", "上海", 16.5, 2023, 2.1),
    car("V008", "宋PLUS", "深圳", 15.6, 2022, 4.0),
    car("V009", "Model 3", "深圳", 17.8, 2022, 3.8),
    car("V010", "Model 3", "苏州", 17.2, 2021, 5.0),
    car("V011", "高尔夫", "杭州", 9.5, 2019, 7.5),
    car("V012", "思域", "广州", 13.8, 2022, 2.9),
    car("V013", "轩逸", "南京", 11.2, 2022, 2.5),
    car("V014", "速腾", "长沙", 10.6, 2020, 6.3),
    car("V015", "卡罗拉", "北京", 11.0, 2021, 4.0, "已售"),
    car("V016", "卡罗拉", "北京", 11.5, 2021, 4.2, "已预订"),
]


def direction(text):
    sell = bool(re.search(r"卖车|出售|想卖|卖掉|出手|置换", text))
    buy = bool(re.search(r"买车|购车|想买|想看|看车|求购", text))
    return "both" if sell and buy else "sell" if sell else "buy"


def number(value, label, low, high, optional=False):
    if value is None or value == "":
        if optional:
            return None
        raise ValueError(f"请填写{label}")
    if isinstance(value, bool):
        raise ValueError(f"{label}须为数字")
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label}须为数字") from None
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{label}须在{low}至{high}之间")
    return value


def validate_query(data):
    if data.get("direction") not in {"buy", "sell"}:
        raise ValueError("请选择买车或卖车")
    out = {"direction": data["direction"]}
    for key, label, required in [("city", "城市", True), ("preference", "车型偏好", False), ("model", "车辆型号", data["direction"] == "sell")]:
        value = data.get(key, "")
        if not isinstance(value, str) or len(value) > 80 or (required and not value.strip()):
            raise ValueError(f"请正确填写{label}")
        out[key] = value.strip()
    if re.search(r"不要|不考虑|排除|不买", out["preference"]):
        raise ValueError("请把车型偏好写成正向条件，例如“轿车”或“本田”，排除条件暂需人工确认")
    text = data.get("text", "")
    if not isinstance(text, str) or len(text) > 4000:
        raise ValueError("需求描述最多4000字")
    out["text"] = text.strip()
    if out["text"]:
        detected = direction(out["text"])
        if detected == "both":
            raise ValueError("描述同时包含买卖或置换，请拆成买车和卖车两次匹配")
        if (detected == "sell" and out["direction"] == "buy") or (detected == "buy" and re.search(r"买车|购车|想买|求购", out["text"]) and out["direction"] == "sell"):
            raise ValueError("描述与所选买卖方向不一致，请切换入口或修改描述")
    if out["direction"] == "buy":
        out["budget_min"] = number(data.get("budget_min", 0), "预算下限", 0, 1000)
        out["budget_max"] = number(data.get("budget_max"), "预算上限", 0.01, 1000)
        if out["budget_min"] > out["budget_max"]:
            raise ValueError("预算下限不能高于上限")
        out["year_min"] = number(data.get("year_min"), "最早上牌年份", 1990, 2026, True)
        out["mileage_max"] = number(data.get("mileage_max"), "最高里程", 0, 100, True)
        if type(data.get("nationwide", False)) is not bool:
            raise ValueError("异地选项须为布尔值")
        out["nationwide"] = data.get("nationwide", False)
    else:
        if out["model"] not in MODELS:
            raise ValueError("请选择列表中的车辆型号")
        out["price"] = number(data.get("price"), "期望售价", 0.01, 1000)
        out["year"] = number(data.get("year"), "上牌年份", 1990, 2026)
        if not out["year"].is_integer():
            raise ValueError("上牌年份须为整数")
        out["year"] = int(out["year"])
        out["mileage"] = number(data.get("mileage"), "行驶里程", 0, 100)
    return out


def preference_fits(preference, vehicle):
    """Named models are alternatives; brand, body, energy remain constraints when explicit."""
    pref = preference.strip().lower()
    if not pref:
        return True, []
    matched_models = [m for m in MODELS if m.lower() in pref]
    brands = [b for b in {v[0] for v in MODELS.values()} if b.lower() in pref]
    bodies = [b for b in ["suv", "轿车", "两厢车", "mpv"] if b in pref]
    energies = [e for e in ["燃油", "纯电", "插混"] if e in pref]
    if "新能源" in pref or ("电车" in pref and "燃油" not in pref):
        energies = list(set(energies + ["纯电", "插混"]))
    recognized = matched_models or brands or bodies or energies
    if not recognized:
        return None, [f"暂不支持解析偏好“{preference}”，请改用具体车型、品牌、SUV/轿车或能源类型"]
    if matched_models and vehicle["model"] not in matched_models:
        return False, []
    if brands and vehicle["brand"] not in brands:
        return False, []
    if bodies and vehicle["body"].lower() not in bodies:
        return False, []
    if energies and vehicle["energy"] not in energies:
        return False, []
    return True, []


def parse_request(text, selected_direction):
    if not isinstance(text, str) or not 2 <= len(text.strip()) <= 4000:
        raise ValueError("请填写2至4000字的需求")
    if selected_direction not in {"buy", "sell"}:
        raise ValueError("请选择买车或卖车")
    text = text.strip()
    profile = extract_rules(text)
    detected = direction(text)
    flags = list(profile["flags"])
    result = {"city": profile["city"], "preference": profile["vehicle"], "evidence": profile["evidence"], "direction": detected, "flags": flags}
    if detected == "both":
        flags.append("置换或买卖混合需求，请拆成两次匹配")
    elif detected != selected_direction and (detected == "sell" or re.search(r"买车|购车|想买|求购", text)):
        flags.append("描述与所选买卖方向不同，请先确认")
    # Preserve all recognized vehicle/brand/type preferences rather than first-model-only extraction.
    prefs = [m for m in MODELS if m.lower() in text.lower()]
    if not prefs:
        prefs = [b for b in sorted({v[0] for v in MODELS.values()}) if b in text]
    if prefs:
        generic = [v for v in ["SUV", "轿车", "两厢车", "MPV", "新能源", "纯电", "插混", "燃油"] if v.lower() in text.lower()]
        result["preference"] = " / ".join(prefs + generic)
    if re.search(r"不要|不考虑|排除|不买", text):
        flags.append("包含排除条件，请人工确认正向车型偏好")
    if selected_direction == "buy":
        result.update(budget_min=profile["budget_min"], budget_max=profile["budget_max"])
        year = re.search(r"(20\d{2})年(?:以后|之后|起|及以后|以上)", text)
        mileage = re.search(r"(\d+(?:\.\d+)?)万公里(?:以内|以下)", text)
        result["year_min"] = int(year[1]) if year else None
        result["mileage_max"] = float(mileage[1]) if mileage else None
    else:
        result["model"] = prefs[0] if len(prefs) == 1 and prefs[0] in MODELS else None
        year = re.search(r"(20\d{2})年", text)
        mileage = re.search(r"(\d+(?:\.\d+)?)万公里", text)
        price = re.search(r"(?:想卖|售价|卖价|期望|卖)[为是到：:\s]*(\d+(?:\.\d+)?)万", text)
        result.update(year=int(year[1]) if year else None, mileage=float(mileage[1]) if mileage else None, price=float(price[1]) if price else None)
    return result


def match_buy(query, inventory=None):
    inventory = INVENTORY if inventory is None else inventory
    results, rejected, warnings = [], [], []
    for vehicle in inventory:
        reasons, failures = [], []
        if vehicle["status"] != "在售":
            failures.append("非在售车源")
        if not query["nationwide"] and vehicle["city"] != query["city"]:
            failures.append("城市不符")
        if not query["budget_min"] <= vehicle["price"] <= query["budget_max"]:
            failures.append("价格超出预算区间")
        fits, messages = preference_fits(query["preference"], vehicle)
        warnings.extend(messages)
        if fits is not True:
            failures.append("车型偏好不符或无法识别")
        if query["year_min"] and vehicle["year"] < query["year_min"]:
            failures.append("上牌年份不符")
        if query["mileage_max"] is not None and vehicle["mileage"] > query["mileage_max"]:
            failures.append("里程超限")
        if failures:
            rejected.append({"id": vehicle["id"], "reasons": failures})
            continue
        reasons.extend([f"{vehicle['price']}万，在预算内", "同城" if vehicle["city"] == query["city"] else "异地车源"])
        if query["preference"]:
            reasons.append("车型偏好符合")
        if query["year_min"]:
            reasons.append(f"{vehicle['year']}年上牌，符合年限")
        if query["mileage_max"] is not None:
            reasons.append(f"{vehicle['mileage']}万公里，符合里程")
        results.append({"id": vehicle["id"], "kind": "vehicle", "vehicle": vehicle, "reasons": reasons})
    # Explicit ordering; no invented probability or ungrounded 'AI match score'.
    results.sort(key=lambda r: (r["vehicle"]["city"] != query["city"], -r["vehicle"]["year"], r["vehicle"]["mileage"], r["vehicle"]["price"], r["id"]))
    return {"direction": "buy", "query": query, "matches": results, "excluded": rejected, "warnings": sorted(set(warnings)), "order": "同城优先，其次上牌年份新、里程低、价格低", "total_scanned": len(inventory)}


def match_sell(query, leads):
    vehicle = car("SELLER", query["model"], query["city"], query["price"], query["year"], query["mileage"])
    results, rejected = [], []
    for lead in leads:
        failures = []
        text = lead["text"]
        if direction(text) != "buy":
            failures.append("非单一买车需求")
        if lead["status"] in {"rejected", "won", "lost", "failed"}:
            failures.append("已结束或分析失败的线索")
        # Use the stored evidence-grounded profile if present, otherwise derive a local baseline.
        stored = lead.get("result")
        profile = stored["profile"] if stored and "profile" in stored else extract_rules(text)
        decision = qualify(profile, text)
        if decision["priority"] in {"C", "D"}:
            failures.append("暂无购车计划或拒绝联系")
        if profile["flags"]:
            failures.append("需求存在歧义")
        if not profile["city"] or profile["city"] != query["city"]:
            failures.append("城市不符或未明确")
        if profile["budget_max"] is None or not (profile["budget_min"] <= query["price"] <= profile["budget_max"]):
            failures.append("期望售价不在买家预算内或预算未明确")
        # Prefer richer parsing for buyer constraints so seller matching cannot ignore mileage/year.
        parsed = parse_request(text, "buy")
        preference = parsed["preference"] or ""
        fits, messages = preference_fits(preference, vehicle)
        if fits is not True:
            failures.append("买家车型偏好不符或无法识别")
        if parsed.get("year_min") and query["year"] < parsed["year_min"]:
            failures.append("不符合买家年限要求")
        if parsed.get("mileage_max") is not None and query["mileage"] > parsed["mileage_max"]:
            failures.append("超出买家里程要求")
        if failures:
            rejected.append({"id": lead["id"], "reasons": failures})
            continue
        reasons = ["同城买家", f"售价{query['price']}万在买家预算内"]
        reasons.append("车型偏好符合" if preference else "买家未明确车型，需确认")
        if not parsed.get("year_min"):
            reasons.append("年限接受度待确认")
        if parsed.get("mileage_max") is None:
            reasons.append("里程接受度待确认")
        results.append({"id": lead["id"], "kind": "buyer", "buyer": {"id": lead["id"], "name": lead["name"], "channel": lead["channel"], "status": lead["status"], "text": text, "profile": profile, "priority": decision["priority"]}, "reasons": reasons, "confirmation_needed": not preference or parsed.get("year_min") is None or parsed.get("mileage_max") is None})
    results.sort(key=lambda r: (r["buyer"]["priority"] != "A", r["confirmation_needed"], r["buyer"]["name"]))
    return {"direction": "sell", "query": query, "vehicle": vehicle, "matches": results, "excluded": rejected, "warnings": [], "order": "需求明确的买家优先；未说明的车龄、里程仍需确认", "total_scanned": len(leads)}
