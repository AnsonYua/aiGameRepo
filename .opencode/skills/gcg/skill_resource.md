---
name: skill_resource
triggers: [resource]
phase_lock: resource
---

# skill_resource

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
  battle_log:
    - "<active_player> deploys a resource"
```
