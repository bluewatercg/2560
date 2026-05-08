TAG = {
    "LACK_VOLUME": "#缺量",
    "HIGH_POSITION": "#高位",
    "SIDEWAYS": "#震荡",
    "NO_BREAKOUT": "#未突破",
    "AGAINST_TREND": "#逆势",
    "WEAK_TREND": "#趋势走弱",
    "NO_CONFIRM": "#未确认",
    "PRICE_AWAY_MA25": "#偏离MA25",
    "MA25_WEAK": "#MA25走弱",
    "DATA_INSUFFICIENT": "#数据不足",
    "COMPLETE_STRUCTURE": "#结构完整",
}


def build_tags(row: dict) -> list[dict]:
    tags = []

    def add(code, tag_type="negative"):
        tags.append({"tag_code": code, "tag_name": TAG[code], "tag_type": tag_type})

    if not row.get("volume_ok") or not row.get("volume_structure_ok"):
        add("LACK_VOLUME")
    if row.get("near_resistance"):
        add("HIGH_POSITION")
    if not row.get("volatility_ok"):
        add("SIDEWAYS")
    if not row.get("breakout_ok"):
        add("NO_BREAKOUT")
    if not row.get("trend_price_ok"):
        add("AGAINST_TREND")
    if not row.get("trend_slope_ok"):
        add("WEAK_TREND")
    if not row.get("pullback_ok") or not row.get("bullish_confirm"):
        add("NO_CONFIRM")
    if not row.get("price_near_ma25"):
        add("PRICE_AWAY_MA25")
    if not row.get("ma25_slope_ok"):
        add("MA25_WEAK")
    if row.get("data_quality_status") != "normal":
        add("DATA_INSUFFICIENT")
    if not tags:
        add("COMPLETE_STRUCTURE", "positive")
    return tags


def structure_status(tags: list[dict]) -> str:
    neg = len([t for t in tags if t.get("tag_type") == "negative"])
    if any(t["tag_code"] == "DATA_INSUFFICIENT" for t in tags):
        return "数据不足"
    if neg == 0:
        return "结构完整"
    if neg <= 2:
        return "部分满足"
    return "明显缺失"


def explain_text(row: dict, tags: list[dict], status: str) -> str:
    names = " ".join([t["tag_name"] for t in tags if t.get("tag_type") == "negative"])

    if status == "结构完整":
        return (
            f"该标的在{row.get('signal_period', '30m')}周期出现2560结构，"
            f"价格接近MA25，MA25趋势正常，量能结构满足，"
            f'当前结构状态为"结构完整"。'
        )

    return f'该标的出现2560相关结构，但存在{names}，当前结构状态为"{status}"。'
