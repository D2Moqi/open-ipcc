#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# =============================================================================
# 前端远程部署脚本（前端远程部署）
# -----------------------------------------------------------------------------
# 功能：
#   1. 本地执行前端生产构建（pnpm build:prod -> 产物 dist-prod/）
#   2. 通过 SCP 上传至服务器 <B服务器公网>（root）的 /opt/cc/web 目录（网站根目录）
#   3. 通过 curl 访问 https://<B服务器域名>/ 验证部署（HTTP 200 + 关键字）
#   4. 完整错误处理 + 验证超时重试机制（单轮内最多 6 次）
# 依赖：pnpm、sshpass、scp、ssh、curl（均通过 subprocess 调用系统命令）
# 说明：脚本单次执行完整部署；稳定性由调用方多次运行本脚本验证。
# =============================================================================
import os
import subprocess
import sys
import time

# ----------------------------- 配置区（按实际修改） -----------------------------
FRONTEND_DIR = "<本地项目根路径>/yudao-ui-admin-vue3"
DIST_DIR = os.path.join(FRONTEND_DIR, "dist-prod")  # build:prod 模式 VITE_OUT_DIR=dist-prod
BUILD_CMD = ["pnpm", "build:prod"]

REMOTE_HOST = "<B服务器公网>"
REMOTE_PORT = "22"
REMOTE_USER = "<账户>"
REMOTE_PASS = "<密码>"
REMOTE_WEB_DIR = "/opt/cc/web"

VERIFY_URL = "https://<B服务器域名>/"
EXPECTED_KEYWORD = "<title"  # 部署成功标志：页面含 <title 标签；可按需替换业务关键字
HEALTHY_HTTP_CODE = "200"

VERIFY_MAX_RETRY = 6  # 验证阶段单轮内最多重试次数
VERIFY_RETRY_INTERVAL = 5  # 验证重试间隔（秒）
CURL_TIMEOUT = 30  # curl 单次超时（秒）

SSH_OPTS = ["-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null"]


# ----------------------------- 通用函数 -----------------------------
def ts():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def log(msg):
    print(f"\033[32m[{ts()} INFO]\033[0m {msg}", flush=True)


def warn(msg):
    print(f"\033[33m[{ts()} WARN]\033[0m {msg}", flush=True)


def err(msg):
    print(f"\033[31m[{ts()} ERROR]\033[0m {msg}", flush=True)


def die(msg):
    err(msg)
    sys.exit(1)


def have_cmd(name):
    return subprocess.run(["command", "-v", name], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


def require_cmd(name):
    if not have_cmd(name):
        die(f"缺少必需命令：{name}，请先安装。")


def run(cmd, timeout=None, cwd=None):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, timeout=timeout, cwd=cwd)


def ssh_base():
    if REMOTE_PASS:
        return ["sshpass", "-p", REMOTE_PASS, "ssh"] + SSH_OPTS + ["-p", REMOTE_PORT]
    return ["ssh"] + SSH_OPTS + ["-p", REMOTE_PORT]


def scp_base():
    if REMOTE_PASS:
        return ["sshpass", "-p", REMOTE_PASS, "scp"] + SSH_OPTS + \
            ["-P", REMOTE_PORT, "-o", "ConnectTimeout=15", "-o", "ServerAliveInterval=30"]
    return ["scp"] + SSH_OPTS + ["-P", REMOTE_PORT, "-o", "ConnectTimeout=15",
                                 "-o", "ServerAliveInterval=30"]


# ----------------------------- 步骤实现（成功返回 True，失败返回 False） -----------------------------
def do_build():
    log("==> [1/3] 本地构建前端（pnpm build:prod）")
    if not os.path.isdir(FRONTEND_DIR):
        err(f"前端目录不存在：{FRONTEND_DIR}")
        return False
    r = run(BUILD_CMD, timeout=1800, cwd=FRONTEND_DIR)
    if r.returncode != 0:
        err(f"前端构建失败，请检查构建日志：\n{r.stderr[-2000:]}")
        return False
    if not os.path.isdir(DIST_DIR):
        err(f"构建产物目录不存在：{DIST_DIR}")
        return False
    file_count = sum(len(files) for _, _, files in os.walk(DIST_DIR))
    if file_count == 0:
        err(f"构建产物为空：{DIST_DIR}")
        return False
    log(f"构建成功，产物文件数：{file_count}")
    return True


def do_upload():
    log(f"==> [2/3] 上传产物至 {REMOTE_USER}@{REMOTE_HOST}:{REMOTE_WEB_DIR}")
    prep = ssh_base() + [f"{REMOTE_USER}@{REMOTE_HOST}",
                         f"mkdir -p {REMOTE_WEB_DIR} && rm -rf {REMOTE_WEB_DIR}/* "
                         f"{REMOTE_WEB_DIR}/.[!.]* 2>/dev/null; echo ok"]
    rp = run(prep)
    if rp.returncode != 0:
        err(f"远程目录准备失败：\n{rp.stderr[-1000:]}")
        return False
    up = scp_base() + ["-r", f"{DIST_DIR}/.", f"{REMOTE_USER}@{REMOTE_HOST}:{REMOTE_WEB_DIR}/"]
    ru = run(up, timeout=600)
    if ru.returncode != 0:
        err(f"SCP 上传失败：\n{ru.stderr[-1000:]}")
        return False
    log("上传完成。")
    return True


def do_verify():
    log(f"==> [3/3] 验证部署 {VERIFY_URL}")
    for attempt in range(1, VERIFY_MAX_RETRY + 1):
        log(f"验证尝试 {attempt}/{VERIFY_MAX_RETRY} ...")
        r = run(["curl", "-ksSL", "--max-time", str(CURL_TIMEOUT),
                 "-w", "\n__HTTP_CODE__:%{http_code}", VERIFY_URL], timeout=CURL_TIMEOUT + 10)
        out = r.stdout
        parts = out.rsplit("\n__HTTP_CODE__:", 1)
        http_code = parts[1].strip() if len(parts) == 2 else ""
        content = parts[0]
        if http_code == HEALTHY_HTTP_CODE and EXPECTED_KEYWORD in content:
            log(f"部署验证成功：HTTP={http_code}，命中关键字『{EXPECTED_KEYWORD}』")
            return True
        warn(f"验证未通过：HTTP={http_code or 'NA'}，关键字命中={content.count(EXPECTED_KEYWORD)}")
        if attempt < VERIFY_MAX_RETRY:
            time.sleep(VERIFY_RETRY_INTERVAL)
    return False


# ----------------------------- 主流程 -----------------------------
def main():
    log("========== 前端远程部署开始 ==========")
    require_cmd("pnpm")
    require_cmd("scp")
    require_cmd("ssh")
    require_cmd("curl")
    if REMOTE_PASS and not have_cmd("sshpass"):
        die("未安装 sshpass，请先安装（macOS: brew install hudochenkov/sshpass/sshpass）。")

    # 单次部署：构建 + 上传 + 验证（多轮稳定性由调用方多次执行脚本验证）
    if do_build() and do_upload() and do_verify():
        log("========== 前端远程部署成功完成 ==========")
        sys.exit(0)
    die("========== 前端远程部署失败 ==========")


if __name__ == "__main__":
    main()
