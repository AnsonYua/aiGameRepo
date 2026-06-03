---
name: skill_resource
triggers: [resource]
phase_lock: resource
---

# skill_resource

## 輸出規則
你的回覆是 state_diff YAML。用 **Write** 工具寫入 `/tmp/gcg_skill_output.txt`，用 **Read** 工具讀回，你的回覆就是 Read 的結果。

Resource phase (CR-2.6). Deploy 1 resource card from resource deck. Active player must do this.

## Flow

1. resource_deck_count > 0 → deploy 1 (resource_deck_count -= 1, resources.active += 1)
2. resource_deck_count = 0 → skip (CR-8.3)

## Output

```yaml
state_diff:
  <active_player>:
    resource_deck_count: -1
    resources:
      active: +1
  battle_log:                          # 模板見 ui_templates.md §log_resource
    - "<active_player> deploys a resource"
```
