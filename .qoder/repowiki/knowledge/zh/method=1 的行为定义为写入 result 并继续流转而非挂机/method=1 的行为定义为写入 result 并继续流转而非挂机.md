---
kind: design
name: method=1 的行为定义为写入 result 并继续流转而非挂机
source: session
category: adr
---

# method=1 的行为定义为写入 result 并继续流转而非挂机

_来源：cf8c29b → 81b13a1 提交周期内记录的编码计划——内容为规划时意图，实现可能滞后或有出入。_

**状态：** accepted

## 背景
方法节点 method=1 的字面含义是挂断电话，但与场景1拓扑矛盾——流程需要继续走到判断器2再转坐席，字面挂机会导致测试无法通过。

## 决策驱动
- 与业务场景拓扑一致
- 用户已确认裁决
- 保持与后续判断器的衔接

## 备选方案
- **字面挂机（hangup）** _（已否决）_ — 优点：符合 method 字面语义；缺点：流程到不了转坐席，场景1无法通过
- **写入非空 result 并触发 next** — 优点：满足场景1拓扑要求，可被下游判断器消费

## 决策
method=1 将写入 variables['<nodeId>.result'] = 'success' 并触发 next 继续流转，不挂断电话；未定义 method 时降级为写空结果并触发 next。

## 影响
下游判断器可通过读取 result 做分支决策；若未来需要真正的挂断行为需新增 method 值或属性。