---
kind: design
name: FlowDataContext 引入 variables 作为 IVR 流程变量中枢
source: session
category: adr
---

# FlowDataContext 引入 variables 作为 IVR 流程变量中枢

_来源：cf8c29b → 81b13a1 提交周期内记录的编码计划——内容为规划时意图，实现可能滞后或有出入。_

**状态：** accepted

## 背景
IVR 各节点（Start/Receive/Method/Transfer）之间需要共享上下文数据，但 FlowDataContext 原本没有变量存储；DTMF 回调、条件判断、文本替换等场景都需要跨节点读写数据。

## 决策驱动
- 通话隔离（随 extendedState→Redis 持久化）
- 与前端 nodeOutputs.ts 严格对齐的键约定
- 避免在多处散落临时 Map

## 备选方案
- **在 FlowDataContext 中新增 Map<String,String> variables** — 优点：随状态机实例持久化、天然通话隔离、集中管理所有节点输出
- **使用 Redis 独立 key 存储变量** _（已否决）_ — 优点：可跨调用共享；缺点：增加额外依赖和序列化开销，且当前 per-call 模型不需要跨调用共享

## 决策
在 FlowDataContext 新增 variables 字段并配套 NodeOutputRegistry 与 FlowVariableUtils，统一以「节点类型前缀.key」命名写入，供后续组件通过 ${key} 语法引用。

## 影响
所有节点 Handler 必须通过 putVariable/getVariable 访问变量；新增/删除输出键需同步修改 NodeOutputRegistry 与前端 nodeOutputs.ts，否则 resolve 会静默保留原样。