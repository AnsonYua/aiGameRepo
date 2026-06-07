---
id: low-base-defense
triggers:
  keywords:
    - "基地：EX-BASE | AP|HP：0|1"
    - "基地：EX-BASE | AP|HP：0|0"
    - "AP|HP：0|1"
    - "基地被破壞"
    - "對手基地：無"
---

# 低基地防守技能

基地低 HP 或已摧毀時，先檢查對手下回合攻擊者。

防守優先序：

1. 能部署或重建基地就先考慮基地。
2. 能部署 active Blocker 就考慮阻擋者。
3. 能移除、橫置或削弱對手攻擊者就先處理攻擊者。
4. 只有高 HP 但沒有 Blocker、也沒有中和攻擊者效果的 Unit，不算保護基地或盾牌。
