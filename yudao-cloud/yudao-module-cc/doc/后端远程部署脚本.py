#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# =============================================================================
# 后端远程部署脚本（后端远程部署）
# -----------------------------------------------------------------------------
# 功能：
#   1. 本地执行后端打包（mvn package -pl yudao-server -am -DskipTests，增量不含 clean）
#      产物：yudao-server/target/yudao-server.jar
#      （若本地无 mvn，依赖 agent 用 ij-debugger 预打包生成 jar 后跳过本步）
#   2. 通过 SCP 上传至服务器 62.234.191.165（ubuntu）的 /home/ubuntu/cc 目录
#   3. SSH 远程执行 bash deploy.sh deploy 启动服务，并保障 JAVA_OPS 含
#      -Dfile.encoding=UTF-8 以修复中文乱码；实时捕获 nohup.out 应用日志
#   4. 多重验证启动成功：Tomcat 就绪 + Spring 上下文完成 + 进程存活，全部通过后
#      向 startup.log 写入聚合标志「项目启动成功」（真实日志不含该串，由本脚本收口）
#   5. curl 访问 https://cc.wenmoqi.top/admin-api 校验 HTTP 状态 + JSON 结构
#   6. 完整错误处理 + 健康检查重试（最多 5 次，间隔 5 秒）
# 依赖：mvn（可选）、sshpass、scp、ssh、curl
# 说明：脚本单次执行完整部署；稳定性由调用方多次运行本脚本验证。
# =============================================================================
import os
import sys
import time
import subprocess

# ----------------------------- 配置区（按实际修改） -----------------------------
BACKEND_DIR = "/Users/wenjiaqi/Documents/ipcc/yudao-cloud"
MVN_MODULE = "yudao-server"
JAR_PATH = os.path.join(BACKEND_DIR, MVN_MODULE, "target", f"{MVN_MODULE}.jar")
PACKAGE_CMD = ["mvn", "package", "-pl", MVN_MODULE, "-am", "-DskipTests"]

REMOTE_HOST = "62.234.191.165"
REMOTE_PORT = "22"
REMOTE_USER = "ubuntu"
REMOTE_PASS = ""  # 若使用密码登录请填写；推荐配置 SSH 公钥免密（留空）
REMOTE_CC_DIR = "/home/ubuntu/cc"
REMOTE_DEPLOY_SCRIPT = f"{REMOTE_CC_DIR}/deploy.sh"
# deploy.sh 的 start() 将 Spring Boot 真实日志重定向到 nohup.out；
# startup.log 为 deploy.sh 自身的 echo 包装日志 + 本脚本追加的聚合成功标志。
REMOTE_APP_LOG = f"{REMOTE_CC_DIR}/nohup.out"
# 多重验证标志（需全部命中才判定启动成功，避免单一标志误判）
FLAG_TOMCAT = "Tomcat started on port 48080"  # Web 容器就绪（实际日志格式）
FLAG_SPRING = "Started YudaoServerApplication"  # Spring 上下文启动完成
# 聚合成功标志：本脚本在多重验证全部通过后写入 startup.log，供外部判定「项目启动成功」
AGG_SUCCESS_FLAG = "项目启动成功"
REMOTE_SUCCESS_LOG = f"{REMOTE_CC_DIR}/startup.log"

VERIFY_URL = "https://cc.wenmoqi.top/admin-api"
HEALTHY_HTTP_CODE = "200"
CURL_TIMEOUT = 30

HEALTH_MAX_RETRY = 5  # 健康检查最多 5 次
HEALTH_RETRY_INTERVAL = 5  # 间隔 5 秒
START_LOG_WAIT = 120  # 启动日志最长捕获等待（秒，含 stop 等待 + 冷启动）

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


def ssh_exec(remote_cmd):
    """远程执行命令，返回 CompletedProcess。"""
    return run(ssh_base() + [f"{REMOTE_USER}@{REMOTE_HOST}", remote_cmd])


# ----------------------------- 步骤实现（成功返回 True，失败返回 False） -----------------------------
def do_package():
    log(f"==> [1/4] 本地后端打包（{' '.join(PACKAGE_CMD)}）")
    if have_cmd("mvn"):
        r = run(PACKAGE_CMD, timeout=1800, cwd=BACKEND_DIR)
        if r.returncode != 0:
            err(f"后端打包失败，请检查 Maven 构建日志：\n{r.stderr[-2000:]}")
            return False
    else:
        warn("本地未检测到 mvn，跳过 mvn 打包，依赖预生成的 jar（请用 ij-debugger 预打包）。")
    if not os.path.isfile(JAR_PATH):
        err(f"打包产物不存在：{JAR_PATH}（请先用 ij-debugger 执行 Maven 打包生成 jar）")
        return False
    size = os.path.getsize(JAR_PATH) / (1024 * 1024)
    log(f"打包产物就绪：{JAR_PATH}（{size:.1f} MB）")
    return True


def do_upload():
    log(f"==> [2/4] 上传 jar 至 {REMOTE_USER}@{REMOTE_HOST}:{REMOTE_CC_DIR}")
    rp = ssh_exec(f"mkdir -p {REMOTE_CC_DIR} && echo ok")
    if rp.returncode != 0:
        err(f"远程目录准备失败：\n{rp.stderr[-1000:]}")
        return False
    up = scp_base() + [JAR_PATH, f"{REMOTE_USER}@{REMOTE_HOST}:{REMOTE_CC_DIR}/"]
    ru = run(up, timeout=600)
    if ru.returncode != 0:
        err(f"SCP 上传 jar 失败：\n{ru.stderr[-1000:]}")
        return False
    log("上传完成。")
    return True


def _remote_grep_count(pattern, logfile):
    """远程 grep -c，返回命中计数（无命中或文件不存在返回 0）。"""
    rg = ssh_exec(f"grep -c '{pattern}' {logfile} 2>/dev/null || echo 0")
    try:
        return int(rg.stdout.strip())
    except ValueError:
        return 0


def do_start():
    log("==> [3/4] 远程执行 bash deploy.sh deploy 并捕获启动日志")
    # 保障：确保服务器 deploy.sh 的 JAVA_OPS 含 -Dfile.encoding=UTF-8，修复中文乱码
    # （重复运行幂等，已注入则跳过）
    fix = (f"cd {REMOTE_CC_DIR} && if ! grep -q 'file.encoding=UTF-8' deploy.sh; then "
           f"sed -i 's|JAVA_OPS=\\\"-Xms512m|JAVA_OPS=\\\"-Dfile.encoding=UTF-8 -Xms512m|' "
           f"deploy.sh && echo INJECTED; else echo ALREADY_PRESENT; fi")
    rf = ssh_exec(fix)
    if rf.returncode != 0:
        warn(f"修复中文乱码编码参数失败（不影响继续）：{rf.stderr[-500:]}")
    else:
        log(f"中文编码参数保障：{rf.stdout.strip()}")

    # 清空旧的应用日志，避免追加模式误判历史启动标志
    start_cmd = (f"cd {REMOTE_CC_DIR} && : > {REMOTE_APP_LOG} && "
                 f"nohup bash deploy.sh deploy "
                 f"> {REMOTE_SUCCESS_LOG} 2>&1 &")
    rs = ssh_exec(start_cmd)
    if rs.returncode != 0:
        err(f"远程启动命令执行失败：\n{rs.stderr[-1000:]}")
        return False

    # 多重验证：需同时满足全部条件才判定启动成功
    #   (1) Web 容器就绪：Tomcat started on port 48080
    #   (2) Spring 上下文完成：Started YudaoServerApplication
    #   (3) 进程存活：yudao-server.jar 进程存在
    log(f"多重验证应用启动（最长 {START_LOG_WAIT}s）："
        f"Tomcat 就绪 + Spring 上下文 + 进程存活")
    waited = 0
    flags = {"tomcat": False, "spring": False, "proc": False}
    while waited < START_LOG_WAIT:
        if not flags["tomcat"]:
            flags["tomcat"] = _remote_grep_count(FLAG_TOMCAT, REMOTE_APP_LOG) > 0
        if not flags["spring"]:
            flags["spring"] = _remote_grep_count(FLAG_SPRING, REMOTE_APP_LOG) > 0
        if not flags["proc"]:
            flags["proc"] = ssh_exec(
                "pgrep -f yudao-server.jar >/dev/null 2>&1 && echo 1 || echo 0"
            ).stdout.strip() == "1"
        if flags["tomcat"] and flags["spring"] and flags["proc"]:
            log(f"多重验证全部通过：Tomcat✔ Spring✔ 进程✔ ✅")
            # 全部通过后写入聚合成功标志，供外部/后续据「项目启动成功」判定
            ssh_exec(f"echo '[deploy] {AGG_SUCCESS_FLAG}' >> {REMOTE_SUCCESS_LOG}")
            return True
        time.sleep(3)
        waited += 3
        if waited % 15 == 0:
            log(f"  进度 {waited}s：Tomcat={flags['tomcat']} Spring={flags['spring']} 进程={flags['proc']}")
    warn(f"在 {START_LOG_WAIT}s 内未通过多重验证：{flags}，输出末尾应用日志：")
    tail = ssh_exec(f"tail -n 40 {REMOTE_APP_LOG} 2>/dev/null")
    print(tail.stdout)
    return False


def do_health_check():
    log(f"==> [4/4] 健康检查与 API 校验 {VERIFY_URL}")
    for attempt in range(1, HEALTH_MAX_RETRY + 1):
        log(f"健康检查 {attempt}/{HEALTH_MAX_RETRY} ...")
        r = run(["curl", "-ksSL", "--max-time", str(CURL_TIMEOUT),
                 "-w", "\n__HTTP_CODE__:%{http_code}", VERIFY_URL], timeout=CURL_TIMEOUT + 10)
        out = r.stdout
        parts = out.rsplit("\n__HTTP_CODE__:", 1)
        http_code = parts[1].strip() if len(parts) == 2 else ""
        content = parts[0].strip()
        is_json = content[:1] in ("{", "[")
        if http_code == HEALTHY_HTTP_CODE and is_json:
            log(f"健康检查成功：HTTP={http_code}，返回 JSON 结构正常 ✅")
            log(f"响应摘要：{content[:240]}")
            return True
        warn(f"健康检查未通过：HTTP={http_code or 'NA'}，JSON 结构命中={1 if is_json else 0}")
        if attempt < HEALTH_MAX_RETRY:
            time.sleep(HEALTH_RETRY_INTERVAL)
    return False


# ----------------------------- 主流程 -----------------------------
def main():
    log("========== 后端远程部署开始 ==========")
    require_cmd("scp")
    require_cmd("ssh")
    require_cmd("curl")
    if REMOTE_PASS and not have_cmd("sshpass"):
        die("未安装 sshpass，请先安装（macOS: brew install hudochenkov/sshpass/sshpass），"
            "或配置 SSH 公钥免密后留空 REMOTE_PASS。")

    # 单次部署：打包 + 上传 + 启动 + 校验（多轮稳定性由调用方多次执行脚本验证）
    if do_package() and do_upload() and do_start() and do_health_check():
        log("========== 后端远程部署成功完成 ==========")
        sys.exit(0)

    die("========== 后端远程部署失败 ==========")
    die(f"========== 后端远程部署在 {TEST_ROUNDS} 轮内均失败 ==========")


if __name__ == "__main__":
    main()
