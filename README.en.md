# yudao-cloud-cc · IPCC Intelligent Call Center

<div align="center">

[中文](README.md) | **English**

Official Website: https://openipcc.wenmoqi.top ｜ Live Demo: https://cc.wenmoqi.top

</div>

---

## Overview

An enterprise-grade intelligent call center built on top of **yudao-cloud** (Spring Boot 4.1 + Java 25 + Spring Cloud 2025.1 + Maven multi-module), combining **FreeSWITCH** communication capabilities with **visual IVR flow orchestration**. It provides full-scenario solutions including SIP softphone access, agent management, intelligent outbound dialing, and AI voice conversation. 100% open source, supports private deployment, and keeps your data fully under your control.

## Key Features

- **Visual IVR Flow Engine**: state-machine driven, drag-and-drop orchestration, 9+ node types (start/condition/playback/receive/transfer/hangup/satisfaction/method), with flow state persisted in Redis.
- **Agent & Call Management**: agent status management, full automatic call recording, SIP softphone, call pop-up, quality inspection and performance statistics.
- **Intelligent Outbound**: batch outbound tasks, predictive dialing, AI voice bot, blacklist management, and multi-dimensional reports.
- **SIP Proxy & Communication Architecture**: SIP over WebSocket B2BUA, 13+ extension points, session management and cluster broadcast.
- **AI Dialogue & Full-Scenario Testing**: AI dialogue nodes integrate the self-developed AI module (yudao-module-ai) for multi-turn voice interaction; a bundled end-to-end test suite covers 9 business scenarios, plus tiered concurrent inbound stress testing.

## Self-Developed Open Source Components

| Component | Description | Repository |
|---|---|---|
| **ipcc-sipproxy** | SIP over WebSocket back-to-back user agent (B2BUA) with signaling forwarding, session management and cluster broadcast; decoupled via 13 extension points | https://gitee.com/ipcc-ai/ipcc-sipproxy |
| **ipcc-fs-esl** | FreeSWITCH ESL client rewritten on Netty 4.x, providing ESL connection management, event routing and distributed listener coordination, with no business logic | https://gitee.com/ipcc-ai/ipcc-fs-esl |

> TTS/ASR without MRCP: AudioFork captures pure PCM audio and streams it directly to cloud SDKs (e.g., Alibaba Cloud NLS), making the architecture lighter and easier to scale horizontally.

## Editions

- **Community Edition** (Free, Open Source): complete front-end call center flows, visual IVR, agent management and call records, end-to-end test scripts, etc.; ⚠️ does not include the complete back-end flow code.
- **Enterprise Edition** (Negotiable): everything in Community plus AI dialogue nodes, automatic outbound, multi-tenancy, cluster deployment, source code delivery and 1-on-1 technical support.

## Source & Documentation

- Source Repository: https://gitee.com/ipcc-ai/open-ipcc
- For the full documentation set, visit the "Documentation Center" on the website (both technical documentation and deployment documentation are synced in real time from Gitee).

---

## Development Tools

### git

After pulling the main project:

```bash
cd yudao-cloud-cc
git submodule update --init --recursive
```

Then open the folder with IDEA.

> Note: this project consists of three independent Git repositories (git submodules), each committed and branched separately.

### IDEA

- Install the **Multi-Project Workspace** plugin to open multiple front-end/back-end project types at once for coordinated development.
- If the project fails to load: close IDEA, delete files under `.idea` except `jb-workspace.xml`, then reopen.
- If project names display incorrectly: verify each submodule's branch (`yudao-cloud` keeps two parallel branches: `master-jdk25-cc` / `master-jdk17-cc`).
- If front-end npm commands are not recognized: make sure `package.json` is recognized as JSON (right-click to set the file type if needed).

---

**License**: Community Edition is licensed under Mulan PSL v2; Enterprise Edition is a one-time purchase with source code delivery and supports private deployment.
