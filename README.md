# yudao-cloud-cc · IPCC 智能呼叫中心

<div align="center">

**中文** | [English](README.en.md)

官方网站：https://openipcc.wenmoqi.top ｜ 在线演示：https://cc.wenmoqi.top

</div>

---

## 项目简介

基于 **yudao-cloud**（Spring Boot 4.1 + Java 25 + Spring Cloud 2025.1 + Maven 多模块）二次开发的企业级智能呼叫中心，融合 **FreeSWITCH** 通信能力与**可视化 IVR 流程编排**，为企业提供 SIP 软电话接入、坐席管理、智能外呼、AI 语音对话等全场景解决方案。100% 源码开放，支持私有化部署，数据完全自主可控。

## 核心特性

- **可视化 IVR 流程引擎**：状态机驱动、拖拽式编排，9+ 节点类型（start/condition/playback/receive/transfer/hangup/satisfaction/method），流程状态持久化到 Redis。
- **坐席与通话管理**：坐席状态管理、全程自动录音、SIP 软电话、来电弹屏、质检评分与绩效统计。
- **智能外呼**：批量外呼任务、预测式外呼、AI 语音机器人、黑名单管理、多维度数据报表。
- **SIP 代理与通信架构**：SIP over WebSocket B2BUA，13+ 扩展点，会话管理与集群广播。
- **AI 对话与全场景测试**：AI 对话节点接入自研 AI 模块（yudao-module-ai）实现多轮语音交互；配套端到端测试套件覆盖 9 大业务场景，并提供分级并发呼入压测。

## 自研开源组件

| 组件 | 说明 | 仓库 |
|---|---|---|
| **ipcc-sipproxy** | SIP over WebSocket 背靠背用户代理（B2BUA），信令转发、会话管理与集群广播，13 个扩展点与父程序解耦 | https://gitee.com/ipcc-ai/ipcc-sipproxy |
| **ipcc-fs-esl** | Netty 4.x 重写的 FreeSWITCH ESL 客户端，提供 ESL 连接管理、事件路由与分布式监听权协调，不含业务逻辑 | https://gitee.com/ipcc-ai/ipcc-fs-esl |

> TTS/ASR 不走 MRCP：通过 AudioFork 采集纯 PCM 音频流，直连云 SDK（如阿里云 NLS）流式收发，架构更轻、易于横向集群部署。

## 版本说明

- **社区版**（免费开源）：前端完整的呼叫中心流程、可视化 IVR、坐席管理与通话记录、端到端测试脚本等；⚠️ 不含后端服务完整流程代码。
- **企业版**（面议）：社区版全部功能 + AI 对话节点、自动外呼、多租户架构、集群部署、源码交付与一对一技术支持。

## 源码与文档

- 源码仓库：https://gitee.com/ipcc-ai/open-ipcc
- 更多文档与技术资料可在网站「文档中心」查看（技术文档 / 部署文档均实时同步自 Gitee）。

---

## 开发工具

### git

拉取主项目后执行：

```bash
cd yudao-cloud-cc
git submodule update --init --recursive
```

然后使用 IDEA 打开该文件夹。

> 说明：项目由三个独立 Git 仓库（git submodule）组成，各自独立提交与分支。

### IDEA

- 需安装 **Multi-Project Workspace** 插件，用于同时打开前后端多类型项目，便于前后端联动开发。
- 项目加载异常：关闭 IDEA，删除 `.idea` 目录中除 `jb-workspace.xml` 外的文件后重新打开。
- 项目名称展示异常：核对各 git 子项目（前后端工程）分支是否正确。
- 前端 npm 命令不识别：确认 `package.json` 被 IDE 正确识别为 JSON（未识别时右键设置文件类型）。

---

**许可**：社区版基于 Mulan PSL v2 开源协议；企业版一次性买断、源码交付、可私有化部署。
