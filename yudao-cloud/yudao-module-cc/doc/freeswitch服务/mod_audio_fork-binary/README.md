# mod_audio_fork 预编译产物

FreeSWITCH `mod_audio_fork` 模块的预编译二进制产物，供部署脚本直接注入 FS 容器， **部署时不再编译**
（原编译流程抽离为 [重建工具](../freeswitch编译mod_audio_fork重建工具.py)，仅升级/换架构时使用）。

## 产物清单

| 文件                  | 注入位置                   | 说明                                                                        |
|-----------------------|----------------------------|-----------------------------------------------------------------------------|
| `mod_audio_fork.so`   | `/usr/lib/freeswitch/mod/` | 模块本体                                                                    |
| `libwebsockets.so.16` | `/lib/`                    | lws 运行时（ubuntu 22.04 版本，SONAME 与 FS 容器 Debian 12 不同，必须注入） |
| `libev.so.4.0.0`      | `/lib/`                    | lws 依赖，容器内需建 `libev.so.4` 符号链接                                  |
| `libuv.so.1.0.0`      | `/lib/`                    | lws 依赖，容器内需建 `libuv.so.1` 符号链接                                  |

## 编译环境与版本约束

- **编译容器**：`ubuntu:22.04`（glibc 2.35）， **x86_64** 架构
- **目标容器**：`safarov/freeswitch:1.10.12`（Debian 12，glibc 2.36），必须为 x86_64
- **FS 基座**：FreeSWITCH 1.10.12（产物链接 `libfreeswitch.so.1`，升级 FS 版本需重新编译）
- **模块源码**：drachtio-freeswitch-modules main 分支 `mod_audio_fork`
- **编译依赖**：spandsp3（freeswitch/spandsp 固定 commit `0d2e6ac6`）、sofia-sip v1.13.17、libteleteon（FS release tarball）

## 兼容性验证

- 产物仅要求 `GLIBC_2.32`（readelf 实测），低于 Debian 12 的 2.36，可正常加载
- 动态依赖（NEEDED）：`libfreeswitch.so.1`、`libwebsockets.so.16`、`libstdc++.so.6`、`libgcc_s.so.1`、`libc.so.6`（后三者 Debian
  12 容器自带）

## 来源

导出自已部署服务器 `<A服务器公网>` 的 FS 容器 `freeswitch_15560_18021_clpqzc`（`module_exists mod_audio_fork` 返回
true，运行 26 小时健康），与现网实际加载的产物一致（两个已部署容器文件 SHA 相同）。

## 使用约束

1. 目标服务器必须为 **x86_64** 架构（`uname -m` 验证），arm64 需重建
2. FS 容器镜像必须为 **safarov/freeswitch:1.10.12**，更换版本需重建
3. 升级 FS 版本或更换架构时，运行重建工具重新编译后替换本目录文件
