#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mod_audio_fork 预编译产物重建工具

用途：仅当升级 FreeSWITCH 镜像版本或更换目标 CPU 架构时使用，
      重新编译生成 mod_audio_fork-binary/ 目录下的预编译产物。
      日常部署由 freeswitch部署脚本*.py 直接注入本目录产物，不再执行编译。

使用方法：
    python3 freeswitch编译mod_audio_fork重建工具.py
    前置条件：宿主机已安装 docker 且已拉取并 tag 为 freeswitch:1.10.12
              （部署脚本会自动完成，也可手动执行 docker pull
              swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/safarov/freeswitch:1.10.12
              后 docker tag 为 freeswitch:1.10.12）

产物输出（覆盖写入 mod_audio_fork-binary/ 目录）：
    mod_audio_fork.so          模块本体（x86_64，ubuntu 22.04 编译）
    libwebsockets.so.16        lws 运行时（ubuntu 22.04 版本，真实文件）
    libev.so.4.0.0             lws 依赖（真实文件）
    libuv.so.1.0.0             lws 依赖（真实文件）

编译原理与陷阱（原部署脚本内联编译逻辑的独立版，保持不变）：
    safarov/freeswitch 镜像极度精简（无包管理器、无 FS 源码树、无 bash），
    无法在容器内编译；必须在宿主机 Ubuntu 24.04 的 ubuntu:22.04 编译容器中
    构建（宿主机 glibc 2.39 产物依赖 GLIBC_2.38，FS 容器 Debian 12 仅 2.36
    无法加载；ubuntu:22.04 的 glibc 2.35 低于 FS 容器，产物可正常加载）。
    FS 1.10.12 源码树（GitHub tag tarball）不含 mod_audio_fork（需从 drachtio
    仓库拷入），且 configure 强制要求 spandsp >= 3.0 与 sofia-sip-ua >= 1.13.17
    （均不在源码树内，需先源码编译安装；apt 的 libspandsp-dev 为 2.x 不满足）。
    ★ libs/libteleteon 是 git submodule，GitHub tag tarball 中为空目录，
      需从官方 release tarball（含全部 submodule）提取后补入，否则 switch.h
      编译报 libteletone.h 缺失；容器内 xz 解压有兼容问题（Not found in
      archive），须宿主机提取后 gzip 打包再进容器解压。
    ★ GitHub tag tarball 无 configure（autotools 生成文件），须 bootstrap.sh
      生成后再 configure（同时产出 switch_am_config.h/config.h/modules.mk）。
    ★ FS 通用模块构建规则只编译与模块同名的单源文件（mod_audio_fork.c），
      drachtio 模块还有 lws_glue.cpp/parser.cpp/audio_pipe.cpp，需手动
      gcc/g++ 编译 4 个源文件后链接（链接目标 libfreeswitch.so 取自
      freeswitch:1.10.12 镜像临时容器）。
"""

import os
import socket
import sys
import time

# ==================== 远程服务器常量 ====================
REMOTE_HOST = "62.234.191.165"
SSH_PORT = 22
SSH_USER = "ubuntu"
SSH_PASSWORD = "Moqi147852369"

# ==================== 编译版本常量（与原部署脚本保持一致，改动需同步） ====================
FS_IMAGE = "freeswitch:1.10.12"
# FreeSWITCH 源码包（GitHub tag v1.10.12，作为编译基座；注意源码树不含 mod_audio_fork）
FS_SOURCE_TARBALL_URL = "https://codeload.github.com/signalwire/freeswitch/tar.gz/refs/tags/v1.10.12"
# drachtio mod_audio_fork 模块源码（拷入 FS 源码树 src/mod/applications/ 后随 FS 构建体系编译）
MOD_AUDIO_FORK_TARBALL_URL = "https://codeload.github.com/mdslaney/drachtio-freeswitch-modules/tar.gz/refs/heads/main"
# FS 1.10.12 configure 的强制基座依赖（均不在 FS 源码树内，需先源码编译安装）：
#   - spandsp3：configure 要求 spandsp >= 3.0，apt 的 libspandsp-dev 为 2.x（pc 版本 0.0.6）不满足，
#     且其 spandsp.pc 位于 /usr/lib/x86_64-linux-gnu/pkgconfig，搜索优先级高于新装的
#     /usr/lib/pkgconfig/spandsp.pc(3.0.0) 会造成遮蔽，因此构建前必须移除 libspandsp-dev；
#     spandsp3 取自 freeswitch/spandsp 仓库的稳定 commit（社区验证与 FS 1.10.x 配套）
#   - sofia-sip：configure 要求 sofia-sip-ua >= 1.13.17，FS 1.10.12 源码树不再内置
SPANDSP3_TARBALL_URL = "https://codeload.github.com/freeswitch/spandsp/tar.gz/0d2e6ac65e0e8f53d652665a743015a88bf048d4"
SOFIA_SIP_TARBALL_URL = "https://codeload.github.com/freeswitch/sofia-sip/tar.gz/refs/tags/v1.13.17"
# FS 官方 release tarball（含全部 git submodule，如 libs/libteleteon；GitHub tag tarball 中 submodule 为空目录）
FS_RELEASE_TARBALL_URL = "https://files.freeswitch.org/releases/freeswitch/freeswitch-1.10.12.-release.tar.xz"

# 产物输出目录（本脚本同级 mod_audio_fork-binary/，与部署脚本 AUDIO_FORK_BINARY_DIR 一致）
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mod_audio_fork-binary")
# 产物清单（与部署脚本 AUDIO_FORK_FILES 一致）
OUTPUT_FILES = ["mod_audio_fork.so", "libwebsockets.so.16", "libev.so.4.0.0", "libuv.so.1.0.0"]

# 编译容器名（与原部署脚本一致，避免与部署残留冲突）
BUILD_CONTAINER = "fs-build-2204"


# ==================== 日志工具 ====================

def log_info(message):
    """输出普通信息，绿色"""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print("\033[0;32m[%s] [INFO] %s\033[0m" % (timestamp, message))


def log_warn(message):
    """输出警告信息，黄色"""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print("\033[0;33m[%s] [WARN] %s\033[0m" % (timestamp, message))


def log_error(message):
    """输出错误信息，红色"""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print("\033[0;31m[%s] [ERROR] %s\033[0m" % (timestamp, message))


def log_success(message):
    """输出成功信息，绿色加粗"""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print("\033[0;32m\033[1m[%s] [SUCCESS] %s\033[0m" % (timestamp, message))


# ==================== SSH 与远程执行 ====================

def create_ssh_client():
    """创建 SSH 客户端，连接远程服务器"""
    try:
        import paramiko
    except ImportError:
        log_error("未安装 paramiko 库，请执行: pip install paramiko")
        sys.exit(1)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    log_info("正在连接 SSH %s:%s ..." % (REMOTE_HOST, SSH_PORT))
    try:
        client.connect(hostname=REMOTE_HOST, port=SSH_PORT,
                       username=SSH_USER, password=SSH_PASSWORD, timeout=30)
    except Exception as e:
        log_error("SSH 连接失败: %s" % e)
        sys.exit(1)
    log_success("SSH 连接成功")
    return client


def remote_exec(ssh_client, command, check=False, timeout=600):
    """执行远程命令，返回 stdout 字符串

    处理逻辑：
        - 通过 channel 设置读超时，避免服务器端命令异常时 SSH 通道永久挂死
        - 超时后关闭通道并抛出 RuntimeError，由调用方决定重试或终止
    入参：
        - timeout：通道读超时（秒），编译等长时命令需按需放大
    返回规则：
        - 正常：stdout 文本；stderr 非空时打印告警
        - check=True 且退出码非 0 时抛 RuntimeError
    """
    stdin, stdout, stderr = ssh_client.exec_command(command)
    stdout.channel.settimeout(timeout)
    try:
        exit_code = stdout.channel.recv_exit_status()
    except socket.timeout:
        stdout.channel.close()
        raise RuntimeError("远程命令执行超时 (%ds): %s" % (timeout, command[:200]))
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    if err:
        print("    [remote-stderr] %s" % err)
    if check and exit_code != 0:
        raise RuntimeError("远程命令执行失败 (exit=%d): %s" % (exit_code, command))
    return out


def remote_write_file(ssh_client, remote_path, content):
    """通过 base64 编码写入远程文件，避免引号转义问题"""
    import base64
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
    command = "echo '%s' | base64 -d > %s" % (encoded, remote_path)
    remote_exec(ssh_client, command, check=True)


def detect_general_sudo_prefix(ssh_client):
    """
    检测通用命令（apt-get 等）的 sudo 前缀。

    需求与陷阱：docker 命令可能因用户已加入 docker 组而免 sudo，
         但 apt-get 等系统命令仍需 sudo，不能复用 docker 的 sudo 检测结果。
    """
    if remote_exec(ssh_client, "id -u") == "0":
        return ""
    if remote_exec(ssh_client, "sudo -n true >/dev/null 2>&1 && echo OK") == "OK":
        return "sudo -n "
    test_cmd = "echo '%s' | sudo -S true >/dev/null 2>&1 && echo OK" % SSH_PASSWORD
    if remote_exec(ssh_client, test_cmd) == "OK":
        return "echo '%s' | sudo -S " % SSH_PASSWORD
    return ""


# ==================== 编译编排 ====================

def generate_build_scripts():
    """生成宿主机编排脚本与容器内 5 个分步脚本（沿用原部署脚本内联逻辑）"""
    host_script = """#!/bin/sh
CT=%s
# 1. 宿主机下载源码包（断点续传循环，gzip 完整性校验不通过则继续重试）
for spec in "fs-src.tar.gz|%s" "dfm.tar.gz|%s" "spandsp3.tar.gz|%s" "sofia-sip.tar.gz|%s" "fs-release.tar.xz|%s"; do
  fname=${spec%%|*}
  url=${spec##*|}
  if [ "${fname##*.}" = "xz" ]; then
    if ! xz -t /tmp/$fname 2>/dev/null; then
      for i in $(seq 1 30); do
        curl -sSL --connect-timeout 15 -C - -o /tmp/$fname "$url" && break
        sleep 3
      done
      xz -t /tmp/$fname 2>/dev/null || { echo "ERR: $fname 下载不完整"; exit 1; }
    fi
  else
    if ! gzip -t /tmp/$fname 2>/dev/null; then
      for i in $(seq 1 30); do
        curl -sSL --connect-timeout 15 -C - -o /tmp/$fname "$url" && break
        sleep 3
      done
      gzip -t /tmp/$fname 2>/dev/null || { echo "ERR: $fname 下载不完整"; exit 1; }
    fi
  fi
done
# 1.5 宿主机从官方 release tarball 提取 libteleteon（源码树目录名为 libteletone，
#      git submodule；容器内 xz 解压有兼容问题（Not found in archive），gzip 无此问题）
#      幂等判断：gzip 完整性 + 包内含 libteletone.h，防坏包残留
if ! (gzip -t /tmp/libteleteon-rel.tar.gz 2>/dev/null && tar tzf /tmp/libteleteon-rel.tar.gz 2>/dev/null | grep -q "src/libteletone.h"); then
  rm -rf /tmp/libteleteon-rel && mkdir -p /tmp/libteleteon-rel
  tar xJf /tmp/fs-release.tar.xz -C /tmp/libteleteon-rel freeswitch-1.10.12.-release/libs/libteletone 2>/dev/null
  mv /tmp/libteleteon-rel/freeswitch-1.10.12.-release/libs/libteletone /tmp/libteleteon-rel/libteleteon
  tar czf /tmp/libteleteon-rel.tar.gz -C /tmp/libteleteon-rel libteleteon
  rm -rf /tmp/libteleteon-rel
  gzip -t /tmp/libteleteon-rel.tar.gz 2>/dev/null || { echo "ERR: libteleteon 提取失败"; exit 1; }
fi
# 2. 启动 ubuntu:22.04 编译容器（挂载 /tmp 到 /hosttmp）
docker rm -f $CT >/dev/null 2>&1 || true
docker run -d --name $CT -v /tmp:/hosttmp ubuntu:22.04 sleep infinity >/dev/null || { echo "ERR: 编译容器启动失败（镜像拉取可能失败）"; exit 1; }
# 3. 容器内分步执行（脚本文件方式，无引号嵌套问题）
docker exec $CT bash /hosttmp/af_apt.sh || { echo "ERR: 编译容器依赖安装失败"; exit 1; }
docker exec $CT bash /hosttmp/af_spandsp.sh || { echo "ERR: spandsp3 编译失败"; exit 1; }
docker exec $CT bash /hosttmp/af_sofia.sh || { echo "ERR: sofia-sip 编译失败"; exit 1; }
docker exec $CT bash /hosttmp/af_prepare.sh || { echo "ERR: 源码准备失败"; exit 1; }
docker exec $CT bash /hosttmp/af_build.sh || { echo "ERR: mod_audio_fork 编译失败"; exit 1; }
# 4. 收集产物（编译容器保留：依赖注入阶段还需从其内部取 lws/ev/uv 库）
docker cp $CT:/hosttmp/fs-src/freeswitch-1.10.12/src/mod/applications/mod_audio_fork/mod_audio_fork.so /tmp/mod_audio_fork_2204.so
[ -f /tmp/mod_audio_fork_2204.so ] || { echo "ERR: 未找到 mod_audio_fork.so"; exit 4; }
echo "SO_PATH=/tmp/mod_audio_fork_2204.so"
echo "BUILD_OK"
""" % (BUILD_CONTAINER, FS_SOURCE_TARBALL_URL, MOD_AUDIO_FORK_TARBALL_URL,
       SPANDSP3_TARBALL_URL, SOFIA_SIP_TARBALL_URL, FS_RELEASE_TARBALL_URL)

    # 容器内脚本 1：apt 编译依赖
    apt_script = """#!/bin/bash
set -e
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq build-essential pkg-config libtool libtool-bin autoconf automake libpcre3-dev libedit-dev uuid-dev zlib1g-dev libssl-dev libwebsockets-dev libsndfile1-dev libspeex-dev libspeexdsp-dev libldns-dev libtiff5-dev libjpeg-dev libsqlite3-dev libcurl4-openssl-dev nasm xz-utils curl
"""
    # 容器内脚本 2：spandsp3（FS configure 要求 spandsp >= 3.0，apt 源无满足版本的包）
    spandsp_script = """#!/bin/bash
set -e
rm -rf /hosttmp/spandsp3b && mkdir -p /hosttmp/spandsp3b
tar xzf /hosttmp/spandsp3.tar.gz -C /hosttmp/spandsp3b --strip-components=1
cd /hosttmp/spandsp3b
./bootstrap.sh -j >/dev/null 2>&1
./configure --with-pic --prefix=/usr >/dev/null 2>&1
make -j4 >/dev/null 2>&1
make install >/dev/null 2>&1
ldconfig
"""
    # 容器内脚本 3：sofia-sip（FS configure 要求 sofia-sip-ua >= 1.13.17，源码树不内置）
    sofia_script = """#!/bin/bash
set -e
rm -rf /hosttmp/sofia-sipb && mkdir -p /hosttmp/sofia-sipb
tar xzf /hosttmp/sofia-sip.tar.gz -C /hosttmp/sofia-sipb --strip-components=1
cd /hosttmp/sofia-sipb
./bootstrap.sh >/dev/null 2>&1
./configure --prefix=/usr >/dev/null 2>&1
make -j4 >/dev/null 2>&1
make install >/dev/null 2>&1
ldconfig
"""
    # 容器内脚本 4：解压 FS 源码 + 补 libteleteon（宿主机 gzip 打包）+ 拷入模块
    #                 + bootstrap 生成 configure + configure 生成 switch_am_config.h
    prepare_script = """#!/bin/bash
set -e
rm -rf /hosttmp/fs-src && mkdir -p /hosttmp/fs-src
tar xzf /hosttmp/fs-src.tar.gz -C /hosttmp/fs-src
# libteleteon 是 git submodule，tag tarball 中为空目录；宿主机已从官方 release tarball 提取并打包为 gzip
rm -rf /hosttmp/fs-src/freeswitch-1.10.12/libs/libteleteon
mkdir -p /hosttmp/fs-src/freeswitch-1.10.12/libs/libteleteon
tar xzf /hosttmp/libteleteon-rel.tar.gz -C /hosttmp/fs-src/freeswitch-1.10.12/libs/libteleteon --strip-components=1
[ -f /hosttmp/fs-src/freeswitch-1.10.12/libs/libteleteon/src/libteletone.h ] || { echo "ERR: libteletone 头文件缺失"; exit 1; }
mkdir -p /hosttmp/dfm-src
tar xzf /hosttmp/dfm.tar.gz -C /hosttmp/dfm-src
cp -r /hosttmp/dfm-src/drachtio-freeswitch-modules-main/modules/mod_audio_fork /hosttmp/fs-src/freeswitch-1.10.12/src/mod/applications/
# modules.conf 精简为仅编译 mod_audio_fork；bootstrap 生成 configure，再 configure 生成 switch_am_config.h/config.h/modules.mk
cd /hosttmp/fs-src/freeswitch-1.10.12
printf 'applications/mod_audio_fork\\n' > modules.conf
./bootstrap.sh -j > /tmp/af_bootstrap.log 2>&1 || { echo "ERR: bootstrap 失败"; tail -10 /tmp/af_bootstrap.log; exit 1; }
./configure --prefix=/usr > /tmp/af_configure.log 2>&1 || { echo "ERR: configure 失败"; tail -10 /tmp/af_configure.log; exit 1; }
[ -f /hosttmp/fs-src/freeswitch-1.10.12/src/include/switch_am_config.h ] || { echo "ERR: switch_am_config.h 未生成"; exit 1; }
echo PREPARE_OK
"""
    # 容器内脚本 5：手动编译 4 个源文件（FS 通用规则只编译同名 .c，须手动编译全部源文件）
    build_script_inner = """#!/bin/bash
set -e
FS=/hosttmp/fs-src/freeswitch-1.10.12
cd $FS/src/mod/applications/mod_audio_fork
INC="-I$FS/src/include -I$FS -I."
for d in $FS/libs/*/src/include $FS/libs/*/include $FS/libs/*/src $FS/libs/apr/include; do
  [ -d "$d" ] && INC="$INC -I$d"
done
gcc -fPIC -c mod_audio_fork.c $INC -DHAVE_CONFIG_H -o mod_audio_fork.o
g++ -fPIC -std=c++11 -c lws_glue.cpp $INC -DHAVE_CONFIG_H -o lws_glue.o
g++ -fPIC -std=c++11 -c parser.cpp $INC -DHAVE_CONFIG_H -o parser.o
g++ -fPIC -std=c++11 -c audio_pipe.cpp $INC -DHAVE_CONFIG_H -o audio_pipe.o
g++ -shared -o mod_audio_fork.so mod_audio_fork.o lws_glue.o parser.o audio_pipe.o -L/hosttmp -l:libfreeswitch.so.1.0.0 $(pkg-config --libs libwebsockets) -lpthread -ldl -lssl -lcrypto
[ -f mod_audio_fork.so ] || { echo "ERR: 链接失败"; exit 1; }
"""
    return host_script, apt_script, spandsp_script, sofia_script, prepare_script, build_script_inner


def collect_libs(ssh_client, apt_sudo):
    """从编译容器收集 3 个运行时依赖库到宿主机 /tmp（docker cp 跟随符号链接复制真实文件）"""
    libs = ["libwebsockets.so.16", "libev.so.4.0.0", "libuv.so.1.0.0"]
    for lib in libs:
        real = remote_exec(ssh_client,
                           "docker exec %s sh -c 'ls /usr/lib/x86_64-linux-gnu/%s 2>/dev/null || ls /lib/x86_64-linux-gnu/%s 2>/dev/null' 2>/dev/null || ls /tmp/%s 2>/dev/null || true" % (
                               BUILD_CONTAINER, lib, lib, lib))
        if not real:
            log_warn("编译容器与宿主机均未找到 %s，跳过" % lib)
            continue
        real_path = real.split("\n")[0].strip()
        remote_exec(ssh_client, "%sdocker cp %s:%s /tmp/af_lib_%s" % (
            apt_sudo, BUILD_CONTAINER, real_path, lib), check=True)
        log_info("  已收集依赖库: %s" % lib)


def main():
    ssh_client = create_ssh_client()
    try:
        # 1. 检测 sudo 前缀（docker 与 apt 分别检测）
        log_info("检测 sudo 前缀...")
        apt_sudo = detect_general_sudo_prefix(ssh_client)
        docker_sudo = apt_sudo
        if not docker_sudo and remote_exec(ssh_client, "sudo -n docker ps >/dev/null 2>&1 && echo OK") == "OK":
            docker_sudo = "sudo -n "
        log_info("  apt sudo: %r, docker sudo: %r" % (apt_sudo, docker_sudo))

        # 2. 宿主机安装 xz-utils/curl（编译/解压依赖）
        log_info("检查宿主机 xz-utils/curl ...")
        remote_exec(ssh_client,
                    "%sapt-get install -y -qq xz-utils curl >/dev/null 2>&1 || true" % apt_sudo)

        # 3. 从 freeswitch:1.10.12 镜像临时容器取 libfreeswitch.so（模块链接目标）
        log_info("从 FS 镜像取 libfreeswitch.so.1.0.0（模块链接目标）...")
        remote_exec(ssh_client, "%sdocker rm -f fs-lib-tmp >/dev/null 2>&1 || true" % docker_sudo, check=False)
        remote_exec(ssh_client, "%sdocker create --name fs-lib-tmp %s >/dev/null" % (docker_sudo, FS_IMAGE), check=True)
        remote_exec(ssh_client,
                    "%sdocker cp fs-lib-tmp:/usr/lib/libfreeswitch.so.1.0.0 /tmp/libfreeswitch.so.1.0.0" % docker_sudo,
                    check=True)
        remote_exec(ssh_client, "%sdocker rm -f fs-lib-tmp >/dev/null 2>&1 || true" % docker_sudo, check=False)

        # 4. 写入 6 个构建脚本并执行
        host_script, apt_script, spandsp_script, sofia_script, prepare_script, build_script_inner = generate_build_scripts()
        remote_write_file(ssh_client, "/tmp/af_host.sh", host_script)
        remote_write_file(ssh_client, "/tmp/af_apt.sh", apt_script)
        remote_write_file(ssh_client, "/tmp/af_spandsp.sh", spandsp_script)
        remote_write_file(ssh_client, "/tmp/af_sofia.sh", sofia_script)
        remote_write_file(ssh_client, "/tmp/af_prepare.sh", prepare_script)
        remote_write_file(ssh_client, "/tmp/af_build.sh", build_script_inner)
        remote_exec(ssh_client, "chmod +x /tmp/af_*.sh", check=False)

        # 5. 执行编译（首次 15-30 分钟，视网络与宿主机性能）
        log_info("容器编译中（首次可能需 15-30 分钟）...")
        build_out = remote_exec(ssh_client,
                                "%ssh /tmp/af_host.sh 2>&1 | tail -60" % docker_sudo, timeout=2400)
        log_info("编译输出:\n    %s" % (build_out or "(空)").replace("\n", "\n    "))
        if not build_out or "BUILD_OK" not in build_out:
            log_error("容器编译失败，未生成产物")
            return 1

        # 6. 收集产物（模块 .so + 3 个依赖库）到宿主机 /tmp
        collect_libs(ssh_client, docker_sudo)

        # 7. 下载产物到本地 mod_audio_fork-binary/ 目录
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        sftp = ssh_client.open_sftp()
        try:
            remote_sources = {
                "mod_audio_fork.so": "/tmp/mod_audio_fork_2204.so",
                "libwebsockets.so.16": "/tmp/af_lib_libwebsockets.so.16",
                "libev.so.4.0.0": "/tmp/af_lib_libev.so.4.0.0",
                "libuv.so.1.0.0": "/tmp/af_lib_libuv.so.1.0.0",
            }
            for name, remote_path in remote_sources.items():
                local_path = os.path.join(OUTPUT_DIR, name)
                sftp.get(remote_path, local_path)
                log_success("  已下载 %s (%d bytes) -> %s" % (
                    name, os.path.getsize(local_path), local_path))
        finally:
            sftp.close()

        # 8. 清理宿主机编译环境（编译容器与临时文件）
        remote_exec(ssh_client, "%sdocker rm -f %s >/dev/null 2>&1 || true" % (docker_sudo, BUILD_CONTAINER),
                    check=False)
        remote_exec(ssh_client,
                    "rm -f /tmp/af_*.sh /tmp/af_lib_* /tmp/mod_audio_fork_2204.so /tmp/libfreeswitch.so.1.0.0",
                    check=False)
        log_success("重建完成，产物已更新到 mod_audio_fork-binary/，可直接使用部署脚本注入 FS 容器")
        return 0
    finally:
        ssh_client.close()
        log_info("SSH 连接已关闭")


if __name__ == "__main__":
    sys.exit(main())
