#!/usr/bin/env python3
"""validate.py — creation-density 闭环计划七维校验器

输入: 闭环计划 JSON（schema 见 tests/sample_good.json）
  {
    "week": {
      "open_items": 1,                     # 本周在研项数量（>3 = 开题成瘾信号，提示级不拦截）
      "items": [
        {
          "id": "ITEM-1",
          "driver": "real_problem",        # real_problem | passion（热情=FAIL）
          "hit_by": "谁被击中: 具体的人/问题",
          "deliverable": "最小可交付件描述",
          "status": "closed",              # closed | open
          "usage_evidence": "他人使用/接收证据",
          "prompt_template_saved": true    # 是否沉淀 prompt/模板
        }
      ],
      "weekly_closed_count": 2             # 自评闭环数，须 == status=closed 且证据齐的项数
    },
    "time_allocation": {                   # 时间押注
      "judgment_pct": 60,                  # 判断力(问题定义/取舍/负责)时间占比
      "mastery_pct": 20,                   # 熟练度时间占比
      "execution_pct": 20
    },
    "launch": {                            # 创业/付费孵化决策（有则必填）
      "decision": "proceed_single",        # proceed_single | proceed_team | pay_incubator | not_now
      "cost_check": {                      # proceed_team/pay_incubator 时必填且全真
        "funding_monthly_burn": true,      # 月烧钱已填数
        "runway_months": true,             # 跑道已填数
        "opportunity_cost": true,          # 机会成本已填数
        "alternatives_considered": true    # 同类替代方案已对比
      },
      "milestones": {                      # proceed_team 时须全达标
        "m1_deliverables_3plus": true,     # ≥3 个可被他人直接使用的产物
        "m2_active_users_3plus": true,     # ≥3 个主动要的使用者
        "m3_measurable_result": true       # 有可验证数字
      }
    }
  }

七维校验（任一 FAIL → exit 1）：
  D1 问题型选题: 每个 item 的 driver 须为 real_problem 且 hit_by 非空
     （热情驱动/答不出被谁击中 = FAIL）
  D2 交付物强制: 每个 item 的 deliverable 非空（最小可交付件）
  D3 闭环证据: status=closed 的 item 须有 usage_evidence（使用证据）
     —— 无使用证据的"交付"= 自嗨，不算闭环
  D4 计分一致: week.weekly_closed_count 须 == 实际合格闭环数
     （closed 且证据齐的项）；不符 = 口径造假
  D5 时间押注: judgment_pct + mastery_pct + execution_pct == 100
     且 judgment_pct >= execution_pct（判断力时间须 ≥ 执行时间）
     且 mastery_pct <= 30（熟练度不投边际时间）
  D6 创业前置核实: decision ∈ 枚举；proceed_team/pay_incubator 时
     cost_check 四项全 true；proceed_team 另须 milestones M1-M3 全 true
     （先核实成本与机会成本；先单人跑通再组队）
  D7 沉淀纪律: status=closed 的 item 须 prompt_template_saved=true
     （不沉淀 = 密度不复利）

退出码：0=通过 / 1=有缺陷 / 2=文件/格式错误
"""
import json
import sys

DECISIONS = {"proceed_single", "proceed_team", "pay_incubator", "not_now"}
COST_KEYS = ("funding_monthly_burn", "runway_months", "opportunity_cost", "alternatives_considered")
MILESTONE_KEYS = ("m1_deliverables_3plus", "m2_active_users_3plus", "m3_measurable_result")


def fail(checks, code, msg):
    checks.append(("FAIL", code, msg))


def ok(checks, code, msg):
    checks.append(("OK", code, msg))


def validate(plan):
    checks = []
    week = plan.get("week") or {}
    items = week.get("items")
    if not isinstance(items, list) or not items:
        fail(checks, "D0", "week.items 必须是非空数组")
        return checks

    qualified_closed = 0
    for i, it in enumerate(items):
        where = f"items[{i}]({it.get('id', '?')})"

        # D1 问题型选题
        if it.get("driver") != "real_problem":
            fail(checks, "D1", f"{where}: driver={it.get('driver')!r}——热情驱动禁止立项，须 real_problem")
        elif not str(it.get("hit_by") or "").strip():
            fail(checks, "D1", f"{where}: hit_by 缺失——答不出被哪个具体的人/真实问题击中")
        else:
            ok(checks, "D1", f"{where}: 问题型选题")

        # D2 交付物强制
        if not str(it.get("deliverable") or "").strip():
            fail(checks, "D2", f"{where}: deliverable 缺失——无限期状态须转成有交付物的任务")
        else:
            ok(checks, "D2", f"{where}: 最小可交付件已定义")

        closed = it.get("status") == "closed"
        # D3 闭环证据
        evidence = str(it.get("usage_evidence") or "").strip()
        if closed and not evidence:
            fail(checks, "D3", f"{where}: status=closed 但无使用证据——交付自嗨，不算闭环")
        if closed and evidence:
            qualified_closed += 1
            ok(checks, "D3", f"{where}: 闭环证据齐全")

        # D7 沉淀纪律
        if closed and it.get("prompt_template_saved") is not True:
            fail(checks, "D7", f"{where}: 已闭环但未沉淀 prompt/模板——密度不复利")
        elif closed:
            ok(checks, "D7", f"{where}: 已沉淀")

    # D4 计分一致
    claimed = week.get("weekly_closed_count")
    if claimed != qualified_closed:
        fail(checks, "D4", f"weekly_closed_count={claimed!r} != 实际合格闭环数 {qualified_closed}——口径造假")
    else:
        ok(checks, "D4", f"计分一致（{qualified_closed} 个合格闭环）")

    # D5 时间押注
    ta = plan.get("time_allocation") or {}
    jp = ta.get("judgment_pct")
    mp = ta.get("mastery_pct")
    ep = ta.get("execution_pct")
    if not all(isinstance(x, (int, float)) for x in (jp, mp, ep)):
        fail(checks, "D5", f"time_allocation 不完整: {ta!r}")
    else:
        if jp + mp + ep != 100:
            fail(checks, "D5", f"时间占比之和 {jp + mp + ep} != 100")
        if jp < ep:
            fail(checks, "D5", f"judgment_pct={jp} < execution_pct={ep}——判断力时间须 ≥ 执行时间")
        if mp > 30:
            fail(checks, "D5", f"mastery_pct={mp} > 30——熟练度不投边际时间（会被 AI 平权）")
        if jp >= ep and mp <= 30 and jp + mp + ep == 100:
            ok(checks, "D5", f"时间押注合规（判断力 {jp}% ≥ 执行 {ep}%，熟练度 {mp}% ≤ 30）")

    # D6 创业前置核实
    launch = plan.get("launch")
    if launch:
        dec = launch.get("decision")
        if dec not in DECISIONS:
            fail(checks, "D6", f"launch.decision 非法: {dec!r}")
        else:
            cost = launch.get("cost_check") or {}
            if dec in ("proceed_team", "pay_incubator"):
                bad = [k for k in COST_KEYS if cost.get(k) is not True]
                if bad:
                    fail(checks, "D6", f"decision={dec} 但成本核实未填: {bad}——先核实成本与机会成本，别照单全收")
                else:
                    ok(checks, "D6", "成本核实四项已填")
            if dec == "proceed_team":
                ms = launch.get("milestones") or {}
                bad_m = [k for k in MILESTONE_KEYS if ms.get(k) is not True]
                if bad_m:
                    fail(checks, "D6", f"proceed_team 但里程碑未达标: {bad_m}——单人先跑通（M1-M3）再组队")
                else:
                    ok(checks, "D6", "组队里程碑 M1-M3 全达标")
            if dec not in ("proceed_team", "pay_incubator"):
                ok(checks, "D6", f"decision={dec}，成本/里程碑核实豁免")
    else:
        ok(checks, "D6", "无创业决策，D6 豁免")

    return checks


def main():
    if len(sys.argv) != 2:
        print("usage: python validate.py plan.json", file=sys.stderr)
        return 2
    try:
        with open(sys.argv[1], encoding="utf-8") as f:
            plan = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"ERROR: 无法读取/解析: {e}", file=sys.stderr)
        return 2
    if not isinstance(plan, dict):
        print("ERROR: 顶层必须是 JSON 对象", file=sys.stderr)
        return 2

    checks = validate(plan)
    fails = [c for c in checks if c[0] == "FAIL"]
    for status, code, msg in checks:
        if status == "FAIL":
            print(f"[{code}] FAIL {msg}")
    print(f"== {len(checks) - len(fails)} OK / {len(fails)} FAIL ==")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
