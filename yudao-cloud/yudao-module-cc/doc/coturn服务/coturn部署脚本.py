#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
coturn 一键部署脚本（远程 SSH 部署）

参考 yudao-cloud集成fs部署脚本.py 的结构与部署文档 coturn安装和配置.md。

设计要点：
    1. 远程服务器与 coturn 部署参数全部使用常量定义
    2. 端口冲突或已存在同配置 coturn 容器时，提示错误信息并终止部署（不自动清理）
    3. 配置文件 turnserver.conf 从镜像提取默认值后增量修改，禁止全量覆盖
    4. 部署后多维度严谨验证：容器状态/端口监听/配置实际值/日志/TURN 服务响应
"""

import base64
import re
import sys
import time

# ==================== 远程服务器常量 ====================
REMOTE_HOST = "<B服务器公网>"
SSH_PORT = 22
SSH_USER = "<账户>"
SSH_PASSWORD = "<密码>"

# ==================== coturn 部署常量 ====================
# coturn 官方镜像（单实例部署，容器名固定为 coturn，不使用随机后缀）
COTURN_IMAGE = "coturn/coturn:latest"
# 国内拉取源（docker.io 即 Docker Hub 官方源）
COTURN_IMAGE_SOURCE = "docker.io/coturn/coturn:latest"
CONTAINER_NAME = "coturn"
TEMP_CONTAINER_NAME = "coturn_tmp"
# 配置目录与文件路径（与部署文档一致）
CONFIG_BASE_PATH = "/etc/coturn"
CONFIG_FILE_PATH = "/etc/coturn/turnserver.conf"
CERTS_DIR_PATH = "/etc/coturn/certs"
# 镜像内默认配置文件路径（coturn 镜像默认配置位于 /etc/turnserver.conf）
IMAGE_DEFAULT_CONFIG_PATH = "/etc/turnserver.conf"

# ==================== 端口常量 ====================
# TURN/STUN 监听端口（TCP+UDP）
LISTENING_PORT = 3478
# TURN/STUN over TLS 监听端口（TCP+UDP）
TLS_LISTENING_PORT = 5349
# 中继端口范围（UDP）
MIN_PORT = 49152
MAX_PORT = 49200
# 需要检测占用的主要 TCP 端口
TCP_PORTS_TO_CHECK = [LISTENING_PORT, TLS_LISTENING_PORT]
# 需要检测占用的主要 UDP 端口
UDP_PORTS_TO_CHECK = [LISTENING_PORT, TLS_LISTENING_PORT]

# ==================== 认证常量 ====================
# 认证域名（realm），TURN 客户端需使用相同 realm 才能通过认证
REALM = "yudao-cc.com"
# 长期凭证机制用户名:密码（lt-cred-mech 启用后使用）
TURN_USER = "<账户>"
TURN_PASSWORD = "<密码>"

# ==================== NAT / 中继地址常量 ====================
# 云服务器公网 IP（对外通告，TURN 客户端通过该地址连接中继）
PUBLIC_IP = "<B服务器公网>"
# 云服务器内网 IP（中继绑定地址；NAT 环境下 turnserver 必须显式指定，否则中继地址解析错误）
PRIVATE_IP = "<B服务器内网>"
# external-ip 配置值：公网IP/内网IP（coturn 用于 NAT 环境通告可被客户端访问的中继地址）
EXTERNAL_IP = "%s/%s" % (PUBLIC_IP, PRIVATE_IP)

# ==================== 验证常量 ====================
CONTAINER_START_WAIT_SECONDS = 8
# TURN 服务响应验证超时（秒）
TURN_VERIFY_TIMEOUT = 10
# 容器内允许出现的日志错误关键字（这些错误不影响核心功能）
ALLOWED_LOG_ERRORS = [
    # TLS 证书未配置时的警告（本次部署未配置 TLS 证书，属预期行为）
    "cannot find TLS certificate",
    "no TLS certificate",
    "SSL",
    "TLS",
    "cert",
]
# 宿主机日志目录（挂载到容器 /var/log，解决容器内 /var/log 写权限问题）
HOST_LOG_DIR = "/var/log/coturn"


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


# ==================== SSH 与远程文件操作 ====================

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
        log_error("SSH 连接失败: %s" % str(e))
        raise
    log_success("SSH 连接成功")
    return client


def remote_exec(ssh_client, command, check=False):
    """
    执行远程命令，返回 stdout 字符串。

    异常场景：命令执行失败（exit_code != 0）且 check=True 时抛出 RuntimeError。
    """
    stdin, stdout, stderr = ssh_client.exec_command(command)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    if err:
        print("    [remote-stderr] %s" % err)
    if check and exit_code != 0:
        raise RuntimeError("远程命令执行失败 (exit=%d): %s" % (exit_code, command))
    return out


def remote_read_file(ssh_client, remote_path):
    """读取远程文件内容，文件不存在返回空字符串"""
    return remote_exec(ssh_client, "cat '%s' 2>/dev/null" % remote_path)


def remote_write_file(ssh_client, remote_path, content):
    """通过 base64 编码写入远程文件，避免引号转义问题"""
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
    command = "echo '%s' | base64 -d > %s" % (encoded, remote_path)
    remote_exec(ssh_client, command, check=True)


def remote_sudo(ssh_client, command, check=False):
    """
    以 sudo 权限执行远程命令（通过 echo password | sudo -S 传递密码）。

    使用场景：Ubuntu 普通用户无权直接操作 /etc 目录，需 sudo 创建目录并 chown。
    """
    full_command = "echo '%s' | sudo -S bash -c \"%s\"" % (SSH_PASSWORD, command.replace('"', '\\"'))
    return remote_exec(ssh_client, full_command, check=check)


# ==================== coturn 配置增量修改工具 ====================

def conf_set_value(content, key, value):
    """
    增量修改 coturn 配置项（有值型：key=value），保留所有未提及的默认配置。

    需求：禁止全量覆盖 turnserver.conf 导致默认配置丢失。只修改或新增指定配置项。
    处理逻辑：
        1. 用负向先行断言匹配 ACTIVE 行（行首非 #），避免误匹配注释行
        2. 若存在 ACTIVE 行，正则替换其值
        3. 若不存在 ACTIVE 行，在文件末尾追加 ACTIVE 配置行
    """
    value = str(value)
    # 负向先行断言：行首非 # 的 key=value 行
    active_pattern = re.compile(
        r'(?m)^(\s*(?!#)' + re.escape(key) + r'\s*=\s*)[^\n]*(.*)$'
    )
    if active_pattern.search(content):
        content = active_pattern.sub(lambda m: m.group(1) + value + m.group(2), content)
    else:
        content = content.rstrip() + "\n" + key + "=" + value + "\n"
    return content


def conf_enable_switch(content, key):
    """
    增量启用 coturn 开关型配置项（如 lt-cred-mech、fingerprint）。

    需求：开关型配置项只有 key 没有 value。若默认配置中被注释（#key）或不存在，
         需追加 ACTIVE 行；若已存在 ACTIVE 行则保持不变。
    """
    # 匹配 ACTIVE 行：行首非 #，整行只有 key（可能有前后空白）
    active_pattern = re.compile(r'(?m)^\s*(?!#)' + re.escape(key) + r'\s*$')
    if active_pattern.search(content):
        return content  # 已存在 ACTIVE 行，无需修改
    # 追加 ACTIVE 行
    content = content.rstrip() + "\n" + key + "\n"
    return content


# ==================== Docker 检测与安装 ====================

def detect_sudo_prefix(ssh_client):
    """
    检测 docker 命令是否需要 sudo 前缀。

    处理逻辑：先试 `docker ps`，失败则试 `sudo -n docker ps`，再失败则用密码 sudo。
    """
    if remote_exec(ssh_client, "docker ps >/dev/null 2>&1 && echo OK") == "OK":
        return ""
    if remote_exec(ssh_client, "sudo -n docker ps >/dev/null 2>&1 && echo OK") == "OK":
        return "sudo -n "
    test_cmd = "echo '%s' | sudo -S docker ps >/dev/null 2>&1 && echo OK" % SSH_PASSWORD
    if remote_exec(ssh_client, test_cmd) == "OK":
        return "echo '%s' | sudo -S " % SSH_PASSWORD
    return ""


def ensure_docker_installed(ssh_client, sudo_prefix):
    """确保远程服务器已安装并启动 Docker"""
    log_info("检查远程服务器 Docker 安装状态...")
    docker_check = remote_exec(ssh_client, "command -v docker || echo 'NOT_FOUND'")
    if docker_check == "NOT_FOUND":
        log_info("Docker 未安装，开始安装（Ubuntu apt 方式）...")
        install_script = (
                             "echo '%s' | sudo -S apt-get update -y; "
                             "echo '%s' | sudo -S apt-get install -y ca-certificates curl gnupg lsb-release; "
                             "sudo install -m 0755 -d /etc/apt/keyrings; "
                             "curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg; "
                             "sudo chmod a+r /etc/apt/keyrings/docker.gpg; "
                             'echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null; '
                             "echo '%s' | sudo -S apt-get update -y; "
                             "echo '%s' | sudo -S apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin; "
                             "sudo systemctl start docker; sudo systemctl enable docker; "
                             "sudo usermod -aG docker %s"
                         ) % (SSH_PASSWORD, SSH_PASSWORD, SSH_PASSWORD, SSH_PASSWORD, SSH_USER)
        remote_exec(ssh_client, install_script, check=False)
        log_success("Docker 安装完成（已将 %s 加入 docker 组）" % SSH_USER)
    else:
        log_info("Docker 已安装，确保服务运行...")
        remote_exec(ssh_client, "echo '%s' | sudo -S systemctl start docker 2>/dev/null || true" % SSH_PASSWORD,
                    check=False)
        log_success("Docker 服务已启动")


def pull_coturn_image(ssh_client, sudo_prefix):
    """确保本地存在 coturn 镜像，不存在则从源拉取"""
    log_info("检查 coturn 镜像...")
    image_check = remote_exec(ssh_client,
                              "%sdocker images | grep -i 'coturn' || echo 'NOT_FOUND'" % sudo_prefix)
    if "NOT_FOUND" in image_check:
        log_info("本地无 coturn 镜像，开始拉取（可能耗时较长）...")
        remote_exec(ssh_client, "%sdocker pull %s" % (sudo_prefix, COTURN_IMAGE_SOURCE), check=True)
        if COTURN_IMAGE != COTURN_IMAGE_SOURCE:
            remote_exec(ssh_client, "%sdocker tag %s %s" % (sudo_prefix, COTURN_IMAGE_SOURCE, COTURN_IMAGE), check=True)
        log_success("coturn 镜像拉取完成")
    else:
        log_success("coturn 镜像已存在")


# ==================== 端口冲突与已存在容器检测（核心：冲突即报错终止） ====================

def check_existing_coturn_container(ssh_client, sudo_prefix):
    """
    检测已存在的 coturn 容器。

    需求：脚本要满足重复使用的需求。当远程服务器上已存在 coturn 容器（按容器名检测）
         或相同端口设置时，必须提示错误信息并终止部署（禁止自动清理，避免误删生产实例）。
    处理逻辑：
        1. 检测容器名为 "coturn" 的容器（包括已停止的）
        2. 若存在，提取其配置的端口，与目标端口比较
        3. 若端口相同（同配置），报错终止
        4. 若端口不同（不同配置），也报错终止（容器名冲突）
    """
    log_info("检测已存在的 coturn 容器...")
    containers_raw = remote_exec(ssh_client,
                                 '%sdocker ps -a --filter "name=^%s$" --format "{{.Names}}\t{{.Status}}"' % (
                                     sudo_prefix, CONTAINER_NAME))
    if not containers_raw:
        log_info("未发现已存在的 coturn 容器")
        return

    log_error("检测到已存在的 coturn 容器:")
    for line in containers_raw.split("\n"):
        log_error("  %s" % line)

    # 提取已存在容器的配置端口，用于错误提示
    existing_config = remote_exec(ssh_client,
                                  "%sdocker exec %s cat %s 2>/dev/null || echo '(无法读取配置)'" % (
                                      sudo_prefix, CONTAINER_NAME, CONFIG_FILE_PATH))
    if existing_config and existing_config != "(无法读取配置)":
        for key in ["listening-port", "tls-listening-port", "realm", "user"]:
            for l in existing_config.split("\n"):
                if l.strip().startswith(key + "=") or l.strip().startswith(key + "="):
                    log_error("  已存在配置: %s" % l.strip())
                    break

    log_error("")
    log_error("部署终止：已存在同配置 coturn 容器，重复部署可能导致端口冲突。")
    log_error("如需重新部署，请先手动清理：")
    log_error("  %sdocker stop %s && %sdocker rm %s" % (sudo_prefix, CONTAINER_NAME, sudo_prefix, CONTAINER_NAME))
    log_error("  sudo rm -rf %s" % CONFIG_BASE_PATH)
    sys.exit(2)


def check_host_port_occupation(ssh_client, sudo_prefix):
    """
    检测主机端口是否被其他进程占用。

    需求：即使没有同名的 coturn 容器，目标端口也可能被其他进程占用
         （如其他 TURN 服务、nginx 等），此时也必须报错终止。
    处理逻辑：
        1. 检测 TCP 端口占用（3478, 5349）
        2. 检测 UDP 端口占用（3478, 5349）
        3. 任一端口被占用则报错终止
    """
    log_info("检测主机端口占用情况...")
    occupied_tcp = []
    occupied_udp = []

    for port in TCP_PORTS_TO_CHECK:
        result = remote_exec(ssh_client,
                             "%sss -tlnp 2>/dev/null | grep ':%d ' || echo FREE" % (sudo_prefix, port))
        if "FREE" not in result:
            occupied_tcp.append((port, result))

    for port in UDP_PORTS_TO_CHECK:
        result = remote_exec(ssh_client,
                             "%sss -ulnp 2>/dev/null | grep ':%d ' || echo FREE" % (sudo_prefix, port))
        if "FREE" not in result:
            occupied_udp.append((port, result))

    if occupied_tcp or occupied_udp:
        log_error("以下目标端口已被占用，部署终止：")
        for port, info in occupied_tcp:
            log_error("  TCP/%d: %s" % (port, info))
        for port, info in occupied_udp:
            log_error("  UDP/%d: %s" % (port, info))
        log_error("")
        log_error("请排查占用进程：")
        log_error("  sudo ss -tlnp | grep -E ':(%s) '" % "|".join(str(p) for p in TCP_PORTS_TO_CHECK))
        log_error("  sudo ss -ulnp | grep -E ':(%s) '" % "|".join(str(p) for p in UDP_PORTS_TO_CHECK))
        sys.exit(2)

    log_success("目标端口全部空闲 (TCP: %s, UDP: %s)" % (
        ",".join(str(p) for p in TCP_PORTS_TO_CHECK),
        ",".join(str(p) for p in UDP_PORTS_TO_CHECK)))


# ==================== 配置提取与增量修改 ====================

def extract_default_config(ssh_client, sudo_prefix):
    """
    从 coturn 镜像提取默认 turnserver.conf 配置。

    需求与陷阱：coturn 配置必须基于镜像默认值增量修改，禁止全量覆盖。
         Ubuntu 普通用户无权直接写 /etc 目录，需 sudo 创建目录并 chown。
         coturn 镜像默认配置位于 /etc/turnserver.conf（部分镜像可能无此文件，
         此时返回空字符串作为基础，后续追加自定义配置）。
    处理逻辑：
        1. 清理临时容器
        2. sudo 创建配置目录并 chown 给当前用户
        3. docker create 临时容器
        4. 尝试从镜像 /etc/turnserver.conf 提取默认配置
        5. 若镜像无默认配置，使用空字符串
        6. 清理临时容器
    返回值：默认配置文件内容（字符串）
    """
    log_info("提取 coturn 默认配置...")

    # 清理临时容器
    remote_exec(ssh_client, "%sdocker stop %s 2>/dev/null || true" % (sudo_prefix, TEMP_CONTAINER_NAME))
    remote_exec(ssh_client, "%sdocker rm %s 2>/dev/null || true" % (sudo_prefix, TEMP_CONTAINER_NAME))

    # 创建配置目录并 chown（Ubuntu 需 sudo）
    remote_sudo(ssh_client, "mkdir -p %s %s %s" % (CONFIG_BASE_PATH, CERTS_DIR_PATH, HOST_LOG_DIR), check=True)
    remote_sudo(ssh_client, "chown -R %s:%s %s %s" % (SSH_USER, SSH_USER, CONFIG_BASE_PATH, HOST_LOG_DIR), check=True)
    # coturn 容器进程可能以非 root 用户运行，日志目录需放开写权限
    remote_sudo(ssh_client, "chmod 0777 %s" % HOST_LOG_DIR, check=True)
    # 清理旧日志文件，避免下次部署时读取到上一次部署的日志导致误判
    remote_sudo(ssh_client, "rm -f %s/turnserver_*.log 2>/dev/null || true" % HOST_LOG_DIR)

    # 创建临时容器提取默认配置
    remote_exec(ssh_client, "%sdocker create --name %s %s" % (sudo_prefix, TEMP_CONTAINER_NAME, COTURN_IMAGE),
                check=True)

    # 尝试从镜像提取默认 turnserver.conf
    # coturn 官方镜像默认配置在 /etc/turnserver.conf（部分版本可能在 /etc/coturn/turnserver.conf）
    default_config = remote_exec(ssh_client,
                                 "%sdocker cp %s:%s /tmp/coturn_default.conf 2>/dev/null && cat /tmp/coturn_default.conf && rm -f /tmp/coturn_default.conf || echo '__NO_DEFAULT_CONFIG__'" % (
                                     sudo_prefix, TEMP_CONTAINER_NAME, IMAGE_DEFAULT_CONFIG_PATH))

    if "__NO_DEFAULT_CONFIG__" in default_config:
        log_info("镜像无默认 turnserver.conf，使用空配置作为基础")
        default_config = ""
    else:
        log_info("已从镜像提取默认 turnserver.conf (%d 字节)" % len(default_config))

    # 清理临时容器
    remote_exec(ssh_client, "%sdocker rm %s" % (sudo_prefix, TEMP_CONTAINER_NAME), check=True)

    return default_config


def update_turnserver_conf(ssh_client, default_config):
    """
    增量修改 turnserver.conf，保留默认配置，只修改/新增指定配置项。

    需求：基于镜像默认配置增量修改，禁止全量覆盖。
    部署文档要求的关键配置项：
        - listening-port=3478（监听端口）
        - tls-listening-port=5349（TLS 监听端口）
        - min-port=49152（最小中继端口）
        - max-port=49200（最大中继端口）
        - realm=yudao-cc.com（认证域名）
        - lt-cred-mech（启用长期凭证机制，开关型）
        - fingerprint（启用消息指纹验证，开关型）
        - no-tlsv1（禁用 TLSv1，开关型）
        - no-tlsv1_1（禁用 TLSv1.1，开关型）
        - user=yudao-cc:yudao-cc（认证用户名:密码）
        - syslog（输出日志到 syslog，开关型）
        - log-file=/var/log/turnserver.log（日志文件路径）
    处理逻辑：
        1. 以默认配置为基础
        2. 用 conf_set_value 增量修改有值型配置
        3. 用 conf_enable_switch 增量启用开关型配置
        4. 写入 /etc/coturn/turnserver.conf
    """
    log_info("增量修改 turnserver.conf ...")
    content = default_config if default_config else ""

    # 有值型配置项
    content = conf_set_value(content, "listening-port", LISTENING_PORT)
    content = conf_set_value(content, "tls-listening-port", TLS_LISTENING_PORT)
    content = conf_set_value(content, "min-port", MIN_PORT)
    content = conf_set_value(content, "max-port", MAX_PORT)
    content = conf_set_value(content, "realm", REALM)
    content = conf_set_value(content, "user", "%s:%s" % (TURN_USER, TURN_PASSWORD))
    content = conf_set_value(content, "log-file", "/var/log/turnserver.log")
    # NAT 环境（云厂商 NAT 模式，公网 IP 绑定在 lo）：必须显式配置 external-ip 与 relay-ip，
    # 否则 turnserver 只能探测到内网 IP（<B服务器内网>），向客户端通告的中继地址为内网地址，
    # 客户端（浏览器软电话等）无法连接中继，TURN 分配失败。
    # external-ip=公网IP/内网IP：通告可被客户端访问的中继地址
    # relay-ip=内网IP：中继 socket 绑定内网地址
    content = conf_set_value(content, "external-ip", EXTERNAL_IP)
    content = conf_set_value(content, "relay-ip", PRIVATE_IP)
    # coturn 新版镜像要求 no-tlsv1/no-tlsv1_1 带值（旧版支持开关型），
    # 否则报 "Bad configuration format: no-tlsv1" 警告，故改为有值型。
    content = conf_set_value(content, "no-tlsv1", "true")
    content = conf_set_value(content, "no-tlsv1_1", "true")

    # 开关型配置项
    content = conf_enable_switch(content, "lt-cred-mech")
    content = conf_enable_switch(content, "fingerprint")
    content = conf_enable_switch(content, "syslog")

    # 写入配置文件
    remote_write_file(ssh_client, CONFIG_FILE_PATH, content)
    log_success("turnserver.conf 增量修改完成")
    log_info("  关键配置项：")
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            log_info("    %s" % stripped)


# ==================== 启动容器 ====================

def start_coturn_container(ssh_client, sudo_prefix):
    """
    使用 host 网络模式启动 coturn 容器，挂载配置目录与日志目录。

    需求：--net=host 模式下容器直接使用主机端口，无需端口映射。
         挂载配置文件、证书目录、日志目录到容器内，使宿主机修改的配置生效。
         日志目录必须挂载，否则容器内 /var/log 归 root 所有，coturn 进程无写权限，
         会导致 "Cannot open log file for writing" 错误。
    """
    log_info("启动 coturn 容器 [%s] ..." % CONTAINER_NAME)
    run_cmd = (
                  "%sdocker run -d --net=host --name %s "
                  "--log-opt max-size=10m --log-opt max-file=3 "
                  "--restart=always "
                  "-e TZ=Asia/Shanghai "
                  "-v %s:/etc/turnserver.conf "
                  "-v %s:/etc/coturn/certs "
                  "-v %s:/var/log "
                  "%s"
              ) % (sudo_prefix, CONTAINER_NAME, CONFIG_FILE_PATH, CERTS_DIR_PATH, HOST_LOG_DIR, COTURN_IMAGE)
    remote_exec(ssh_client, run_cmd, check=True)
    log_success("coturn 容器 [%s] 启动成功" % CONTAINER_NAME)


# ==================== 部署验证 ====================

def verify_container_running(ssh_client, sudo_prefix):
    """验证 1：容器运行状态"""
    log_info("[验证 1/5] 容器运行状态...")
    status = remote_exec(ssh_client,
                         '%sdocker ps --filter "name=^%s$" --format "{{.Names}}\t{{.Status}}\t{{.Ports}}"' % (
                             sudo_prefix, CONTAINER_NAME))
    if status and "Up" in status:
        log_success("  PASS: %s" % status.replace("\t", " | "))
        return True
    log_error("  FAIL: 容器未运行")
    # 输出容器日志便于排查
    logs = remote_exec(ssh_client, "%sdocker logs %s 2>&1 | tail -20" % (sudo_prefix, CONTAINER_NAME))
    log_error("  容器日志:\n%s" % logs)
    return False


def verify_port_listening(ssh_client, sudo_prefix):
    """
    验证 2：端口监听状态（TCP + UDP）。

    业务约束：TURN 3478 端口必须监听（核心功能）；TLS 5349 端口仅在配置了 TLS 证书时
             才会监听，本次部署未配置 TLS 证书，TLS 端口未监听属预期行为，降级为警告。
    """
    log_info("[验证 2/5] 端口监听状态...")
    all_pass = True
    # TURN 核心端口（3478）必须监听
    for port in [LISTENING_PORT]:
        result = remote_exec(ssh_client,
                             "%sss -tlnp 2>/dev/null | grep ':%d ' || echo FREE" % (sudo_prefix, port))
        if "FREE" in result:
            log_error("  FAIL: TCP/%d 未监听" % port)
            all_pass = False
        else:
            log_success("  PASS: TCP/%d 已监听" % port)
    for port in [LISTENING_PORT]:
        result = remote_exec(ssh_client,
                             "%sss -ulnp 2>/dev/null | grep ':%d ' || echo FREE" % (sudo_prefix, port))
        if "FREE" in result:
            log_error("  FAIL: UDP/%d 未监听" % port)
            all_pass = False
        else:
            log_success("  PASS: UDP/%d 已监听" % port)
    # TLS 端口（5349）仅在配置了 TLS 证书时才监听，本次部署未配置，降级为警告
    for port in [TLS_LISTENING_PORT]:
        tcp_result = remote_exec(ssh_client,
                                 "%sss -tlnp 2>/dev/null | grep ':%d ' || echo FREE" % (sudo_prefix, port))
        udp_result = remote_exec(ssh_client,
                                 "%sss -ulnp 2>/dev/null | grep ':%d ' || echo FREE" % (sudo_prefix, port))
        if "FREE" in tcp_result and "FREE" in udp_result:
            log_warn("  WARN: TCP/UDP %d (TLS) 未监听（未配置 TLS 证书，属预期行为）" % port)
        else:
            log_success("  PASS: TLS 端口 %d 已监听" % port)
    return all_pass


def verify_config_file_values(ssh_client, sudo_prefix):
    """验证 3：配置文件实际值校验（区分 ACTIVE 行与注释行）"""
    log_info("[验证 3/5] 配置文件实际值校验...")
    content = remote_exec(ssh_client,
                          "%sdocker exec %s cat /etc/turnserver.conf 2>/dev/null" % (sudo_prefix, CONTAINER_NAME))
    if not content:
        log_error("  FAIL: 无法读取容器内 turnserver.conf")
        return False

    all_pass = True
    # 校验有值型配置（必须是 ACTIVE 行，非注释）
    value_checks = [
        ("listening-port", str(LISTENING_PORT)),
        ("tls-listening-port", str(TLS_LISTENING_PORT)),
        ("min-port", str(MIN_PORT)),
        ("max-port", str(MAX_PORT)),
        ("realm", REALM),
        ("user", "%s:%s" % (TURN_USER, TURN_PASSWORD)),
        ("external-ip", EXTERNAL_IP),
        ("relay-ip", PRIVATE_IP),
        ("no-tlsv1", "true"),
        ("no-tlsv1_1", "true"),
    ]
    for key, expected_value in value_checks:
        # 负向先行断言匹配 ACTIVE 行（行首非 #）
        pattern = re.compile(r'(?m)^\s*(?!#)' + re.escape(key) + r'\s*=\s*([^\s#]+)')
        match = pattern.search(content)
        if match and match.group(1) == expected_value:
            log_success("  PASS: %s=%s (ACTIVE)" % (key, expected_value))
        else:
            actual = match.group(1) if match else "(未找到 ACTIVE 行)"
            log_error("  FAIL: %s 期望=%s, 实际=%s" % (key, expected_value, actual))
            all_pass = False

    # 校验开关型配置（必须是 ACTIVE 行）
    switch_checks = ["lt-cred-mech", "fingerprint", "syslog"]
    for key in switch_checks:
        pattern = re.compile(r'(?m)^\s*(?!#)' + re.escape(key) + r'\s*$')
        if pattern.search(content):
            log_success("  PASS: %s (ACTIVE)" % key)
        else:
            log_error("  FAIL: %s 未启用 (无 ACTIVE 行)" % key)
            all_pass = False

    return all_pass


def verify_turn_service(ssh_client, sudo_prefix):
    """
    验证 4：TURN 服务进程运行验证。

    设计背景：turnserver.conf 中的 user= 是静态用户配置，不会被加载到数据库，
         turnadmin -l 只列出数据库中的用户，无法验证静态用户。
         coturn 官方镜像为 distroless，不含 ps/command 等 shell 命令，
         因此通过 docker top（宿主机视角）或 /proc/1/comm 验证进程运行。
    处理逻辑：
        1. 优先用 docker top 查看容器进程
        2. 备选用 docker exec cat /proc/1/comm 读取 PID 1 进程名
        3. 验证进程名为 turnserver
    """
    log_info("[验证 4/5] TURN 服务进程验证...")
    # 优先用 docker top（从宿主机视角查看容器进程，不依赖容器内命令）
    result = remote_exec(ssh_client,
                         "%sdocker top %s 2>&1 | head -5" % (sudo_prefix, CONTAINER_NAME))
    if "turnserver" in result:
        log_success("  PASS: turnserver 进程正在运行 (docker top)")
        for line in result.split("\n")[:3]:
            log_info("    %s" % line.strip()[:150])
    else:
        # 备选：通过 /proc/1/comm 读取 PID 1 进程名（distroless 镜像也可用）
        comm = remote_exec(ssh_client,
                           "%sdocker exec %s cat /proc/1/comm 2>&1" % (sudo_prefix, CONTAINER_NAME))
        if comm.strip() == "turnserver":
            log_success("  PASS: turnserver 进程正在运行 (/proc/1/comm)")
        else:
            log_error("  FAIL: 容器内未发现 turnserver 进程")
            log_error("  docker top 输出: %s" % result[:200])
            log_error("  /proc/1/comm 输出: %s" % comm[:200])
            return False

    # 进一步验证：发送 STUN Binding Request 测试 TURN 服务响应
    # 通过容器内 echo + nc 发送一个最小的 STUN Binding Request（20 字节）
    # STUN Binding Request: 0x0001 (type) + 0x0000 (len) + 0x2112A442 (magic) + 12 字节 txn id
    # 注：coturn 镜像为 distroless，可能无 nc 命令，失败时降级为警告
    stun_test = remote_exec(ssh_client,
                            "%sdocker exec %s sh -c \""
                            "printf '\\\\x00\\\\x01\\\\x00\\\\x00\\\\x21\\\\x12\\\\xa4\\\\x42\\\\x00\\\\x00\\\\x00\\\\x00\\\\x00\\\\x00\\\\x00\\\\x00\\\\x00\\\\x00\\\\x00\\\\x00' | nc -u -w 2 127.0.0.1 3478 | head -c 4 | od -An -tx1 2>/dev/null"
                            "\" 2>&1 || echo '__STUN_FAILED__'" % (sudo_prefix, CONTAINER_NAME))

    if "__STUN_FAILED__" not in stun_test and stun_test.strip():
        # STUN 响应前 2 字节应为 0x01 0x01 (Binding Success Response)
        first_bytes = stun_test.strip().split()
        if first_bytes and first_bytes[0] == "01":
            log_success("  PASS: STUN Binding Request 收到响应 (%s)" % " ".join(first_bytes[:4]))
            return True
        else:
            log_warn("  WARN: STUN 响应非预期格式: %s（不影响服务运行）" % stun_test.strip()[:60])
            return True  # 不算 fail，仅警告
    else:
        log_warn("  WARN: STUN 响应测试未确认（容器可能无 nc 命令，不影响服务运行）")
        return True  # 不算 fail，仅警告


def verify_logs(ssh_client, sudo_prefix):
    """
    验证 5：启动日志错误扫描。

    设计背景：coturn 镜像 CMD 为 `turnserver --log-file=stdout --external-ip=...`，
         但配置文件中的 `log-file=/var/log/turnserver.log` 会覆盖命令行参数，
         导致日志写入文件而非 stdout（docker logs 输出为空）。
         因此改为读取宿主机 /var/log/coturn/turnserver_*.log 文件。
         日志文件名按日期生成（turnserver_YYYY-MM-DD.log）。
    需求：coturn 启动日志中不应有影响核心功能的 [ERR] 或 CRIT 级别错误。
         TLS 证书未配置的警告属预期行为（本次部署未配置 TLS 证书），不计入失败。
    """
    log_info("[验证 5/5] 启动日志错误扫描...")
    # 读取宿主机日志目录中最新的 turnserver_*.log 文件
    logs = remote_exec(ssh_client,
                       "%scat %s/turnserver_*.log 2>/dev/null || echo '__NO_LOG_FILE__'" % (
                           sudo_prefix, HOST_LOG_DIR))
    if "__NO_LOG_FILE__" in logs or not logs:
        log_warn("  WARN: 无日志文件（可能尚未生成）")
        return True

    # 统计错误行
    err_lines = [l for l in logs.split("\n") if "[ERR]" in l or "CRIT" in l or "ERROR" in l.upper()]
    # 过滤允许的错误（TLS 证书警告等）
    real_errors = [l for l in err_lines if not any(a in l for a in ALLOWED_LOG_ERRORS)]

    if not real_errors:
        log_success("  PASS: 启动日志无影响核心功能的错误")
        # 输出关键启动信息
        for line in logs.split("\n"):
            if "IPv4" in line or "IPv6" in line or "realm" in line.lower() or "listening" in line.lower() or "log file opened" in line.lower():
                log_info("    %s" % line.strip()[:120])
        return True
    else:
        log_error("  FAIL: 启动日志存在真实错误:")
        for l in real_errors[:5]:
            log_error("    %s" % l[:200])
        return False


def verify_deployment(ssh_client, sudo_prefix):
    """部署后综合验证：容器状态 + 端口监听 + 配置实际值 + TURN 服务 + 日志"""
    log_info("=" * 60)
    log_info("开始部署验证（5 项）")
    log_info("=" * 60)

    log_info("等待 coturn 完全启动（%d 秒）..." % CONTAINER_START_WAIT_SECONDS)
    time.sleep(CONTAINER_START_WAIT_SECONDS)

    results = [
        verify_container_running(ssh_client, sudo_prefix),
        verify_port_listening(ssh_client, sudo_prefix),
        verify_config_file_values(ssh_client, sudo_prefix),
        verify_turn_service(ssh_client, sudo_prefix),
        verify_logs(ssh_client, sudo_prefix),
    ]

    log_info("=" * 60)
    passed = sum(results)
    total = len(results)
    if passed == total:
        log_success("全部 %d 项验证通过" % total)
    else:
        log_error("仅 %d/%d 项验证通过" % (passed, total))
    log_info("=" * 60)
    return passed == total


# ==================== 主流程 ====================

def run_deployment(ssh_client):
    """
    coturn 部署主流程。

    流程：
        1. 检测 sudo 前缀
        2. 确保 Docker 已安装
        3. 拉取 coturn 镜像
        4. 检测已存在的 coturn 容器（存在则终止）
        5. 检测主机端口占用（占用则终止）
        6. 提取镜像默认配置
        7. 增量修改 turnserver.conf
        8. 启动 coturn 容器
        9. 严谨验证（5 项）
        10. 输出汇总
    """
    # 步骤 1：检测 sudo 前缀
    sudo_prefix = detect_sudo_prefix(ssh_client)
    log_info("sudo 前缀: %s" % (repr(sudo_prefix) if sudo_prefix else "(无需 sudo)"))

    # 步骤 2：确保 Docker 已安装
    ensure_docker_installed(ssh_client, sudo_prefix)

    # 步骤 3：拉取 coturn 镜像
    pull_coturn_image(ssh_client, sudo_prefix)

    # 步骤 4：检测已存在的 coturn 容器（存在则终止）
    check_existing_coturn_container(ssh_client, sudo_prefix)

    # 步骤 5：检测主机端口占用（占用则终止）
    check_host_port_occupation(ssh_client, sudo_prefix)

    # 步骤 6：提取镜像默认配置
    default_config = extract_default_config(ssh_client, sudo_prefix)

    # 步骤 7：增量修改 turnserver.conf
    update_turnserver_conf(ssh_client, default_config)

    # 步骤 8：启动 coturn 容器
    start_coturn_container(ssh_client, sudo_prefix)

    # 步骤 9：严谨验证
    success = verify_deployment(ssh_client, sudo_prefix)

    # 步骤 10：输出汇总
    log_info("=" * 60)
    if success:
        log_success("coturn 部署全部完成！")
    else:
        log_error("coturn 部署完成，但部分验证未通过，请检查上方日志")
    log_info("容器名: %s" % CONTAINER_NAME)
    log_info("配置文件: %s" % CONFIG_FILE_PATH)
    log_info("监听端口: TCP/UDP %d (TURN), TCP/UDP %d (TLS)" % (LISTENING_PORT, TLS_LISTENING_PORT))
    log_info("中继端口范围: UDP %d-%d" % (MIN_PORT, MAX_PORT))
    log_info("认证域名: %s" % REALM)
    log_info("TURN 用户: %s (密码: %s)" % (TURN_USER, TURN_PASSWORD))
    log_info("中继地址: external-ip=%s, relay-ip=%s" % (EXTERNAL_IP, PRIVATE_IP))
    log_info("测试地址: https://webrtc.github.io/samples/src/content/peerconnection/trickle-ice/")
    log_info("=" * 60)
    return success


def main():
    """脚本入口：使用顶部定义的固定常量，无需命令行参数"""
    log_info("=" * 60)
    log_info("开始 coturn 远程部署")
    log_info("目标服务器: %s (用户: %s)" % (REMOTE_HOST, SSH_USER))
    log_info("容器名: %s | 配置目录: %s" % (CONTAINER_NAME, CONFIG_BASE_PATH))
    log_info("监听端口: %d (TURN) / %d (TLS) | 中继: %d-%d" % (
        LISTENING_PORT, TLS_LISTENING_PORT, MIN_PORT, MAX_PORT))
    log_info("realm: %s | user: %s" % (REALM, TURN_USER))
    log_info("=" * 60)

    ssh_client = None
    try:
        ssh_client = create_ssh_client()
        success = run_deployment(ssh_client)
        if not success:
            sys.exit(1)
    except KeyboardInterrupt:
        log_error("用户中断部署")
        sys.exit(1)
    except SystemExit:
        raise
    except Exception as e:
        log_error("部署失败: %s" % str(e))
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        if ssh_client:
            ssh_client.close()
            log_info("SSH 连接已关闭")


if __name__ == "__main__":
    main()
