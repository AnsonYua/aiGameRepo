---
name: skill_resource
triggers: [resource]
phase_lock: resource
---

# skill_resource — 資源階段

## 輸出規則
你的回應是 state_diff YAML。使用 **Write** 工具寫入 `/tmp/gcg_skill_output.txt`，再用 **Read** 工具讀回 — 你的回應就是 Read 的結果。

資源階段（CR-2.6）。從資源牌庫部署 1 張資源卡。行動玩家強制執行。

## 流程

1. resource_deck_count > 0 → 部署 1 張（resource_deck_count -= 1, resources.active += 1）
2. resource_deck_count = 0 → 跳過（CR-8.3）

## 輸出

```yaml
state_diff:
  <active_player>:
    resource_deck_count: -1
    resources:
      active: +1
  battle_log:                          # 模板見 ui_templates.md §log_resource
    - "<active_player> deploys a resource"
```
