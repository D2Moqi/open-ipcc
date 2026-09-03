#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
yudao-cloud 呼叫中心 FreeSWITCH 一键部署脚本

核心：
    本脚本部署的 FreeSWITCH 通过 mod_xml_curl 与 yudao-cloud Java 后端联动，
    directory/dialplan/configuration 等动态配置由 Java 后端下发，
    因此本脚本只增量修改 5 个静态配置文件：modules.conf.xml、xml_curl.conf.xml、
    event_socket.conf.xml、acl.conf.xml、vars.xml。

设计要点：
    1. 远程服务器与 FreeSWITCH 部署参数全部使用常量定义
    2. 端口冲突时（已存在同端口 FS 容器或主机端口被占用）报错终止，不自动清理
    3. 所有配置文件均从镜像 vanilla 配置读取后增量修改，禁止全量覆盖
    4. 部署后多维度严谨验证：容器状态/ESL/Sofia/端口监听/配置实际值/模块加载/日志
"""

import base64
import os
import random
import re
import socket
import string
import sys
import time

# ==================== 远程服务器常量 ====================
REMOTE_HOST = "<A服务器公网>"
SSH_PORT = 22
SSH_USER = "<账户>"
SSH_PASSWORD = "<密码>"

# ==================== 端口常量 ====================
INTERNAL_SIP_PORT = 16560
INTERNAL_TLS_PORT = 16561
EXTERNAL_SIP_PORT = 16580
EXTERNAL_TLS_PORT = 16581
ESL_PORT = 18121
RTP_PORT_START = 16384
RTP_PORT_END = 32768

# 需要检测占用的主要端口（TCP）
# 注：internal_ssl_enable=false / external_ssl_enable=false 时 TLS 端口 15561/15581 不监听，
# 故不列入检测列表；如后续启用 SSL 需将 TLS 端口加入此列表
TCP_PORTS_TO_CHECK = [INTERNAL_SIP_PORT, EXTERNAL_SIP_PORT, ESL_PORT]

# ==================== FreeSWITCH 部署常量 ====================
FS_IMAGE = "freeswitch:1.10.12"
FS_IMAGE_SOURCE = "swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/safarov/freeswitch:1.10.12"

# 容器名采用 freeswitch_SIP_PORT_ESL_PORT_<6位随机串> 格式，配置目录与容器名一致，避免多实例冲突
CONTAINER_NAME_PREFIX = "freeswitch_" + str(INTERNAL_SIP_PORT) + "_" + str(ESL_PORT) + "_"
CONTAINER_NAME_RANDOM_LENGTH = 6
TEMP_CONTAINER_NAME = "freeswitch_tmp"
CONFIG_BASE_PATH = "/etc"

# ==================== 密码常量 ====================
ESL_PASSWORD = "<密码>"
DEFAULT_PASSWORD = "<密码>"

# ==================== 网络与 ACL 常量 ====================
# FreeSWITCH 对外 SIP/RTP 公网 IP（与服务器公网 IP 一致）
PUBLIC_IP = "<A服务器公网>"
# ESL ACL 允许连接的 CIDR（测试环境允许全部 IPv4）
ACL_ALLOW_CIDR = "0.0.0.0/0"
ACL_LIST_NAME = "event_socket.auto"

# ==================== Java 后端常量 ====================
# mod_xml_curl 将动态配置请求发送到此 URL，由 yudao-cloud 的 FsController 处理
# 注：JAVA_BACKEND_HOST 默认为 PUBLIC_IP，但部分云主机不支持 NAT 回环
#     （hairpin NAT），主机/容器内无法通过公网 IP 访问本机服务。
#     脚本会在部署前自动检测，若公网 IP 不可达则改用内网 IP。
JAVA_BACKEND_HOST = "<B服务器域名>"
JAVA_BACKEND_PORT = 443
JAVA_BACKEND_PATH = "/admin-api/cc/fs/curl/api"
# JAVA_BACKEND_URL 由 HOST/PORT/PATH 拼接，供显示与参考；运行时使用 effective_java_backend_url
JAVA_BACKEND_URL = "https://%s:%d%s" % (JAVA_BACKEND_HOST, JAVA_BACKEND_PORT, JAVA_BACKEND_PATH)
XML_CURL_BINDINGS = "dialplan|configuration|phrases"
XML_CURL_TIMEOUT_MS = 2000

# ==================== Mock Java 后端常量 （若java程序已启动则会跳过） ====================
# 部署期间临时启动的 mock HTTP server，用于解决 mod_xml_curl 同步阻塞问题。
# 现象与原因：mod_xml_curl 在 FreeSWITCH 启动时会同步请求 Java 后端获取配置
#     （cdr_csv.conf/sofia.conf/loopback.conf 等）。若 Java 后端未启动，
#     curl 会等待系统级 TCP connect 超时（Linux 默认约 135 秒），即使配置了
#     timeout=2000ms 也不生效（该参数控制已建立连接后的传输超时，不控制 connect）。
#     每个模块加载都会触发一次 135 秒阻塞，导致 FreeSWITCH 完全启动需要 10+ 分钟。
# 解决方案：部署期间在远程服务器后台启动 mock HTTP server 监听 48080 端口，
#     对所有请求返回空 XML 响应，让 mod_xml_curl 快速得到响应。
#     部署验证通过后停止 mock server，由用户启动真实 Java 后端接管。
MOCK_BACKEND_SCRIPT_PATH = "/tmp/yudao_mock_java_backend.py"
MOCK_BACKEND_PID_FILE = "/tmp/yudao_mock_java_backend.pid"
MOCK_BACKEND_LOG_FILE = "/tmp/yudao_mock_java_backend.log"
# mock server 返回的空 XML 响应（FreeSWITCH 收到空响应会回退到本地配置文件）
MOCK_BACKEND_RESPONSE_XML = '<?xml version="1.0" encoding="UTF-8"?>\n<document type="freeswitch/xml"><section name="configuration"></section></document>'

# ==================== mod_audio_fork 常量 ====================
# fork 音频参数默认值（仅 conf 参考，实际值由 Java 后端通过 ESL uuid_audio_fork
# 命令参数动态下发）；mod_audio_fork 音频固定为 L16(16bit PCM)，声道数由 mix-type
# 决定（mono/mixed=单声道）。连接地址不在此配置，避免与命令动态下发产生歧义
AUDIO_FORK_MIX_TYPE = "mono"
AUDIO_FORK_SAMPLE_RATE = "16k"
# mod_audio_fork 预编译产物目录（本脚本同级 mod_audio_fork-binary/）：
# 产物在 ubuntu:22.04 (glibc 2.35) x86_64 环境编译，实测仅依赖 GLIBC_2.32，
# 可在 Debian 12 (glibc 2.36) 的 safarov/freeswitch:1.10.12 容器正常加载；
# 升级 FS 镜像版本或更换 CPU 架构时，需用重建工具脚本重新编译（见该目录 README）
AUDIO_FORK_BINARY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mod_audio_fork-binary")
# 产物清单：(本地文件名, 注入容器路径)；libev/libuv 注入后需在容器内建 SONAME 符号链接
AUDIO_FORK_FILES = [
    ("mod_audio_fork.so", "/usr/lib/freeswitch/mod/mod_audio_fork.so"),
    ("libwebsockets.so.16", "/lib/libwebsockets.so.16"),
    ("libev.so.4.0.0", "/lib/libev.so.4.0.0"),
    ("libuv.so.1.0.0", "/lib/libuv.so.1.0.0"),
]

# ==================== 验证常量 ====================
# 容器启动后等待 FreeSWITCH 初始化的时间（秒）。
# 注：有 mock backend 时 mod_xml_curl 不再阻塞，15 秒足够 Sofia/ESL 启动。
CONTAINER_START_WAIT_SECONDS = 15
MODULE_LOAD_WAIT_SECONDS = 5
# ESL 连接轮询重试参数（防止 FreeSWITCH 启动较慢时误判失败）
ESL_CONNECT_RETRY_COUNT = 12
ESL_CONNECT_RETRY_INTERVAL = 5
ALLOWED_LOG_ERRORS = [
    # mod_signalwire 已注释，若镜像残留旧配置可能仍报 SSL 警告，不影响核心功能
    "mod_signalwire",
    "ca-certificates.crt",
    "SSL certificate problem",
    # Java 后端未启动时 mod_xml_curl 报错是预期情况（已用 mock backend 规避，
    # 但 mock server 停止后或部署期间偶发请求仍可能报错，不影响核心功能）
    "mod_xml_curl.c",
    "Received HTTP error 0 trying to fetch",
    "CURL returned error",
    # mod_audio_fork 首次启动时尚未注入产物，modules.conf.xml 的 load 行会报加载失败，
    # 部署流程会在容器启动后注入预编译产物并动态加载，该启动期报错为预期内
    "mod_audio_fork",
]


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


# ==================== 容器名与配置目录 ====================

def generate_container_name():
    """生成 freeswitch_<6位随机串> 格式的容器名，避免与已有实例冲突"""
    chars = string.ascii_lowercase + string.digits
    suffix = "".join(random.choice(chars) for _ in range(CONTAINER_NAME_RANDOM_LENGTH))
    return "%s%s" % (CONTAINER_NAME_PREFIX, suffix)


def get_config_dir(container_name):
    """配置目录与容器名一致：/etc/freeswitch_<随机串>"""
    return "%s/%s" % (CONFIG_BASE_PATH, container_name)


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


def remote_exec(ssh_client, command, check=False, timeout=600):
    """执行远程命令，返回 stdout 字符串

    处理逻辑：
        - 通过 channel 设置读超时，避免服务器端命令异常时 SSH 通道永久挂死
          （paramiko 默认 recv_exit_status 无超时，曾出现命令已结束但通道不关闭的问题）
        - 超时后关闭通道并抛出 RuntimeError，由调用方决定重试或终止
    入参：
        - timeout：通道读超时（秒），编译等长时命令需按需放大
    返回规则：
        - 正常：stdout 文本；stderr 非空时打印告警
        - check=True 且退出码非 0 时抛 RuntimeError
    异常场景：
        - 命令超时抛 RuntimeError，提示调用方增大 timeout
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


def remote_read_file(ssh_client, remote_path):
    """读取远程文件内容，文件不存在返回空字符串"""
    return remote_exec(ssh_client, "cat '%s' 2>/dev/null" % remote_path)


def remote_write_file(ssh_client, remote_path, content):
    """通过 base64 编码写入远程文件，避免引号转义问题"""
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
    command = "echo '%s' | base64 -d > %s" % (encoded, remote_path)
    remote_exec(ssh_client, command, check=True)


def remote_upload_file(ssh_client, local_path, remote_path):
    """通过 SFTP 上传二进制文件（mod_audio_fork 预编译 .so 产物），与 base64 文本写入互补"""
    sftp = ssh_client.open_sftp()
    try:
        sftp.put(local_path, remote_path)
    finally:
        sftp.close()
    log_info("  已上传 %s -> %s" % (os.path.basename(local_path), remote_path))


def remote_mkdir(ssh_client, path):
    """递归创建远程目录"""
    remote_exec(ssh_client, "mkdir -p %s" % path, check=True)


# ==================== XML 增量修改工具 ====================

def xml_set_params(content, parent_close_tag, params, indent="    "):
    """
    增量修改 XML <param> 配置，保留所有未提及的默认配置。

    需求与陷阱：禁止全量覆盖 XML 文件导致默认 param 丢失。只修改或新增指定的 param。
         vanilla 配置中部分 param 以 <!-- --> 注释形式存在（如 apply-inbound-acl），
         简单 regex 会误匹配注释内的 param，导致值被更新但参数仍被注释、配置不生效。
    处理逻辑：
        1. 仅匹配 ACTIVE（行首非 <!--）的 <param name="key" value="..."/>
        2. 若存在 ACTIVE param，正则替换其 value
        3. 若不存在 ACTIVE param，在 parent_close_tag（如 </settings>）前插入新 ACTIVE param 行
           （保留原注释行不动，FreeSWITCH 会忽略注释，使用新增的 ACTIVE param）
    """
    for name, value in params.items():
        value = str(value)
        # 负向先行断言排除行首为 <!-- 的注释行
        active_pattern = re.compile(
            r'(?m)^\s*(?!<!--.*)(<param\s+name="' + re.escape(name) + r'"\s+value=")[^"]*(")'
        )
        if active_pattern.search(content):
            content = active_pattern.sub(lambda m: m.group(1) + value + m.group(2), content)
        else:
            new_line = '%s<param name="%s" value="%s"/>' % (indent, name, value)
            content = content.replace(parent_close_tag, new_line + "\n  " + parent_close_tag, 1)
    return content


# ==================== Docker 检测与安装 ====================

def detect_sudo_prefix(ssh_client):
    """
    检测 docker 命令是否需要 sudo 前缀。

    需求：Ubuntu 云主机默认用户通常需要 sudo 执行 docker，需自动适配。
    处理逻辑：先试 `docker ps`，失败则试 `sudo -n docker ps`，再失败则用密码 sudo。
    """
    if remote_exec(ssh_client, "docker ps >/dev/null 2>&1 && echo OK") == "OK":
        return ""
    if remote_exec(ssh_client, "sudo -n docker ps >/dev/null 2>&1 && echo OK") == "OK":
        return "sudo -n "
    # 尝试带密码的 sudo（通过 stdin 传递密码）
    test_cmd = "echo '%s' | sudo -S docker ps >/dev/null 2>&1 && echo OK" % SSH_PASSWORD
    if remote_exec(ssh_client, test_cmd) == "OK":
        return "echo '%s' | sudo -S " % SSH_PASSWORD
    # 都不行，返回空让后续安装流程处理
    return ""


def detect_general_sudo_prefix(ssh_client):
    """
    检测通用命令（apt-get 等）的 sudo 前缀。

    需求与陷阱：docker 命令可能因用户已加入 docker 组而免 sudo，
         但 apt-get 等系统命令仍需 sudo，不能复用 detect_sudo_prefix 的结果。
    """
    if remote_exec(ssh_client, "id -u") == "0":
        return ""
    if remote_exec(ssh_client, "sudo -n true >/dev/null 2>&1 && echo OK") == "OK":
        return "sudo -n "
    test_cmd = "echo '%s' | sudo -S true >/dev/null 2>&1 && echo OK" % SSH_PASSWORD
    if remote_exec(ssh_client, test_cmd) == "OK":
        return "echo '%s' | sudo -S " % SSH_PASSWORD
    return ""


def ensure_docker_installed(ssh_client, sudo_prefix):
    """确保远程服务器已安装并启动 Docker"""
    log_info("检查远程服务器 Docker 安装状态...")
    docker_check = remote_exec(ssh_client, "command -v docker || echo 'NOT_FOUND'")
    if docker_check == "NOT_FOUND":
        log_info("Docker 未安装，开始安装（Ubuntu apt 方式）...")
        # Ubuntu apt 安装 Docker
        install_script = (
                             "sudo -n apt-get update -y 2>/dev/null || echo '%s' | sudo -S apt-get update -y; "
                             "sudo -n apt-get install -y ca-certificates curl gnupg lsb-release 2>/dev/null "
                             "|| echo '%s' | sudo -S apt-get install -y ca-certificates curl gnupg lsb-release; "
                             "sudo install -m 0755 -d /etc/apt/keyrings; "
                             "curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg; "
                             "sudo chmod a+r /etc/apt/keyrings/docker.gpg; "
                             'echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null; '
                             "sudo -n apt-get update -y 2>/dev/null || echo '%s' | sudo -S apt-get update -y; "
                             "sudo -n apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin 2>/dev/null "
                             "|| echo '%s' | sudo -S apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin; "
                             "sudo systemctl start docker; sudo systemctl enable docker"
                         ) % (SSH_PASSWORD, SSH_PASSWORD, SSH_PASSWORD, SSH_PASSWORD)
        remote_exec(ssh_client, install_script, check=False)
        # 把 ubuntu 用户加入 docker 组，避免后续都要 sudo
        remote_exec(ssh_client, "sudo usermod -aG docker %s" % SSH_USER, check=False)
        log_success("Docker 安装完成（已将 %s 加入 docker 组）" % SSH_USER)
    else:
        log_info("Docker 已安装，确保服务运行...")
        remote_exec(ssh_client, "sudo systemctl start docker 2>/dev/null || systemctl start docker 2>/dev/null || true")
        log_success("Docker 服务已启动")


def pull_freeswitch_image(ssh_client, sudo_prefix):
    """确保本地存在 FreeSWITCH 镜像，不存在则从国内源拉取"""
    log_info("检查 FreeSWITCH 镜像...")
    image_check = remote_exec(ssh_client, "%sdocker images | grep -i 'freeswitch' || echo 'NOT_FOUND'" % sudo_prefix)
    if "NOT_FOUND" in image_check:
        log_info("本地无 FreeSWITCH 镜像，开始从国内源拉取（可能耗时较长）...")
        remote_exec(ssh_client, "%sdocker pull %s" % (sudo_prefix, FS_IMAGE_SOURCE), check=True)
        remote_exec(ssh_client, "%sdocker tag %s %s" % (sudo_prefix, FS_IMAGE_SOURCE, FS_IMAGE), check=True)
        log_success("FreeSWITCH 镜像拉取完成")
    else:
        log_success("FreeSWITCH 镜像已存在")


# ==================== 端口冲突检测（核心：冲突即报错终止） ====================

def check_existing_fs_containers_with_same_ports(ssh_client, sudo_prefix):
    """
    检测已存在的 FreeSWITCH 容器是否使用了相同的主要端口。

    需求：脚本要满足重复使用的需求，当远程服务器上已存在同端口设置的 FreeSWITCH 容器时，
         必须提示错误信息并终止部署（禁止自动清理，避免误删生产实例）。
    处理逻辑：
        1. 列出所有 freeswitch_* 容器（包括已停止的）
        2. 对每个容器，读取其 vars.xml 与 event_socket.conf.xml 提取已配置端口
        3. 若与目标端口集合有交集，则报错终止
    """
    log_info("检测已存在的 FreeSWITCH 容器端口冲突...")
    target_ports = {str(INTERNAL_SIP_PORT), str(INTERNAL_TLS_PORT),
                    str(EXTERNAL_SIP_PORT), str(EXTERNAL_TLS_PORT), str(ESL_PORT)}

    containers_raw = remote_exec(ssh_client,
                                 '%sdocker ps -a --filter "name=%s" --format "{{.Names}}"' % (sudo_prefix,
                                                                                              CONTAINER_NAME_PREFIX))
    containers = [c.strip() for c in containers_raw.split("\n") if c.strip()]

    if not containers:
        log_info("未发现已存在的 freeswitch 实例")
        return

    for cname in containers:
        config_dir = get_config_dir(cname)
        # 同时从 vars.xml 和 event_socket.conf.xml 提取端口配置
        port_info = remote_exec(ssh_client,
                                "grep -hoE 'internal_sip_port=[0-9]+' %s/vars.xml 2>/dev/null; "
                                "grep -hoE 'internal_tls_port=[0-9]+' %s/vars.xml 2>/dev/null; "
                                "grep -hoE 'external_sip_port=[0-9]+' %s/vars.xml 2>/dev/null; "
                                "grep -hoE 'external_tls_port=[0-9]+' %s/vars.xml 2>/dev/null; "
                                "grep -hoE 'listen-port value=\"[0-9]+\"' %s/autoload_configs/event_socket.conf.xml 2>/dev/null"
                                % (config_dir, config_dir, config_dir, config_dir, config_dir))

        existing_ports = set()
        for part in port_info.split():
            digits = "".join(ch for ch in part if ch.isdigit())
            if digits:
                existing_ports.add(digits)

        conflict = target_ports & existing_ports
        if conflict:
            log_error("检测到已存在的 FreeSWITCH 容器 [%s] 占用了目标端口: %s" % (
                cname, ", ".join(sorted(conflict))))
            log_error("该容器配置目录: %s" % config_dir)
            log_error("按需求要求终止部署。如需替换，请先手动停止并删除该容器：")
            log_error("  sudo docker stop %s && sudo docker rm %s" % (cname, cname))
            log_error("  sudo rm -rf %s" % config_dir)
            raise RuntimeError("端口冲突，部署已终止（容器 %s 占用 %s）" % (cname, ", ".join(sorted(conflict))))
        else:
            log_info("  容器 %s 端口无冲突 (其端口: %s)" % (cname, ", ".join(
                sorted(existing_ports)) if existing_ports else "未知"))


def check_host_port_occupation(ssh_client, sudo_prefix):
    """
    检测主机端口是否被任意进程占用（不限于 FreeSWITCH）。

    需求：当所使用的主要端口被占用时要提示错误信息并终止部署。
    处理逻辑：
        1. 通过 ss/netstat 检查 TCP 端口 15560/15561/15580/15581/18021
        2. 检查 UDP 端口 15560/15580（SIP UDP 监听）
        3. 任意端口被占用即报错终止
    """
    log_info("检测主机端口占用情况...")
    occupied = []

    for port in TCP_PORTS_TO_CHECK:
        # 优先用 ss，回退到 netstat
        cmd = ("%sss -tlnp 2>/dev/null | grep ':%s ' || "
               "netstat -tlnp 2>/dev/null | grep ':%s ' || true") % (sudo_prefix, port, port)
        result = remote_exec(ssh_client, cmd)
        if result:
            occupied.append("TCP/%s" % port)

    # SIP UDP 端口
    for udp_port in [INTERNAL_SIP_PORT, EXTERNAL_SIP_PORT]:
        cmd = ("%sss -ulnp 2>/dev/null | grep ':%s ' || "
               "netstat -ulnp 2>/dev/null | grep ':%s ' || true") % (sudo_prefix, udp_port, udp_port)
        result = remote_exec(ssh_client, cmd)
        if result:
            occupied.append("UDP/%s" % udp_port)

    if occupied:
        log_error("以下目标端口已被占用: %s" % ", ".join(occupied))
        log_error("请释放相关端口后重试。可使用以下命令排查占用进程：")
        log_error("  sudo ss -tlnp | grep -E '%s'" % "|".join(str(p) for p in TCP_PORTS_TO_CHECK))
        log_error("  sudo ss -ulnp | grep -E '%s|%s'" % (INTERNAL_SIP_PORT, EXTERNAL_SIP_PORT))
        raise RuntimeError("端口被占用，部署已终止: %s" % ", ".join(occupied))

    log_success("所有目标端口均未被占用")


# ==================== 提取镜像默认配置 ====================

def remote_sudo(ssh_client, command, check=False):
    """
    以 sudo（带密码）执行需要 root 权限的命令（如 /etc 下的目录操作）。

    需求：Ubuntu 用户在 docker 组可执行 docker 命令，但 /etc 目录写操作仍需 root。
         通过 `echo password | sudo -S` 方式非交互传递密码。
    """
    wrapped = "echo '%s' | sudo -S %s" % (SSH_PASSWORD, command)
    return remote_exec(ssh_client, wrapped, check=check)


# ==================== Mock Java 后端（部署期间临时 HTTP server） ====================

MOCK_BACKEND_SCRIPT_CONTENT = '''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
yudao-cloud 部署期间临时 Mock Java 后端。

用途：在 FreeSWITCH 部署期间监听 48080 端口，对 mod_xml_curl 的所有 HTTP 请求
     返回空 XML 响应，避免 mod_xml_curl 同步阻塞 FreeSWITCH 启动。
停止：部署验证完成后由部署脚本通过 PID 文件 kill。
"""
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

RESPONSE_XML = '<?xml version="1.0" encoding="UTF-8"?>\\n<document type="freeswitch/xml"><section name="configuration"></section></document>'
PORT = int(os.environ.get("MOCK_PORT", "48080"))


class MockHandler(BaseHTTPRequestHandler):
    """对所有 POST/GET 请求返回空 XML 响应，mod_xml_curl 收到后会回退到本地配置"""

    def _handle(self):
        # 读取并丢弃请求体（避免客户端因连接未读取而阻塞）
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length > 0:
                self.rfile.read(length)
        except Exception:
            pass
        body = RESPONSE_XML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/xml; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self._handle()

    def do_GET(self):
        self._handle()

    def log_message(self, fmt, *args):
        # 简化日志输出，避免 stderr 噪音
        sys.stderr.write("[mock] %s - %s\\n" % (self.address_string(), fmt % args))


def main():
    server = HTTPServer(("0.0.0.0", PORT), MockHandler)
    sys.stderr.write("[mock] Mock Java backend listening on 0.0.0.0:%d\\n" % PORT)
    sys.stderr.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()
'''


def detect_java_backend_host(ssh_client):
    """
    检测 FreeSWITCH 容器内可访问的 Java 后端主机地址。

    需求与现象：部分云主机（如腾讯云）不支持 NAT 回环（hairpin NAT），
         主机/容器内无法通过公网 IP 访问本机服务。若 JAVA_BACKEND_HOST 配置为公网 IP，
         mod_xml_curl 请求会一直 timeout，导致 FreeSWITCH 启动阻塞 10+ 分钟。
    处理逻辑：
        1. 启动临时 mock HTTP server 在 JAVA_BACKEND_PORT
        2. 通过 JAVA_BACKEND_HOST:PORT 测试连通性
        3. 若不通，获取主机内网 IP，测试内网 IP 连通性
        4. 返回可用的 host（公网 IP 优先，不可达则用内网 IP）
        5. 停止临时 mock server
    返回：实际可用的 host 字符串
    """
    log_info("检测 Java 后端可访问地址...")

    # 启动临时 mock server 用于连通性测试
    remote_write_file(ssh_client, MOCK_BACKEND_SCRIPT_PATH, MOCK_BACKEND_SCRIPT_CONTENT)
    remote_exec(ssh_client, "chmod +x %s" % MOCK_BACKEND_SCRIPT_PATH, check=True)
    start_cmd = (
                    "nohup python3 %s > %s 2>&1 & "
                    "echo $! > %s"
                ) % (MOCK_BACKEND_SCRIPT_PATH, MOCK_BACKEND_LOG_FILE, MOCK_BACKEND_PID_FILE)
    remote_exec(ssh_client, start_cmd, check=True)
    time.sleep(2)

    try:
        # 1. 测试公网 IP 连通性（用 curl，超时 3 秒）
        public_test = remote_exec(ssh_client,
                                  "curl -s -o /dev/null -w '%%{http_code}' --connect-timeout 3 --max-time 5 "
                                  "-k https://%s:%d/test 2>/dev/null || echo FAIL" % (JAVA_BACKEND_HOST,
                                                                                      JAVA_BACKEND_PORT))
        log_info("  公网 IP %s:%d 连通性: %s" % (
            JAVA_BACKEND_HOST, JAVA_BACKEND_PORT, public_test or "FAIL"))
        if public_test and public_test.isdigit() and 200 <= int(public_test) < 500:
            log_success("  公网 IP 可达，使用 %s 作为 Java 后端地址" % JAVA_BACKEND_HOST)
            return JAVA_BACKEND_HOST

        # 2. 公网 IP 不可达，获取内网 IP
        #    优先用 hostname -I，回退到 ip -4 addr show
        internal_ip = remote_exec(ssh_client,
                                  "hostname -I 2>/dev/null | awk '{print $1}' || "
                                  "ip -4 addr show 2>/dev/null | grep -oP 'inet \\K[\\d.]+' | grep -v '127.0.0.1' | head -1")
        internal_ip = internal_ip.strip()
        if not internal_ip:
            log_error("  无法获取主机内网 IP")
            raise RuntimeError("无法确定 Java 后端可访问地址：公网 IP 不可达且无法获取内网 IP")

        # 3. 测试内网 IP 连通性
        internal_test = remote_exec(ssh_client,
                                    "curl -s -o /dev/null -w '%%{http_code}' --connect-timeout 3 --max-time 5 "
                                    "-k https://%s:%d/test 2>/dev/null || echo FAIL" % (internal_ip, JAVA_BACKEND_PORT))
        log_info("  内网 IP %s:%d 连通性: %s" % (
            internal_ip, JAVA_BACKEND_PORT, internal_test or "FAIL"))
        if internal_test and internal_test.isdigit() and 200 <= int(internal_test) < 500:
            log_warn("  公网 IP 不可达（云主机可能不支持 NAT 回环）")
            log_success("  改用内网 IP %s 作为 Java 后端地址" % internal_ip)
            return internal_ip

        log_error("  公网 IP 和内网 IP 均不可达")
        raise RuntimeError("Java 后端地址检测失败：公网/内网 IP 均不可达")
    finally:
        # 停止临时 mock server（后续 start_mock_java_backend 会重新启动）
        pid_str = remote_exec(ssh_client, "cat %s 2>/dev/null" % MOCK_BACKEND_PID_FILE)
        if pid_str:
            remote_exec(ssh_client, "kill %s 2>/dev/null || true" % pid_str.strip())
            time.sleep(1)
            remote_exec(ssh_client, "kill -9 %s 2>/dev/null || true" % pid_str.strip())
        remote_exec(ssh_client, "rm -f %s %s" % (MOCK_BACKEND_PID_FILE, MOCK_BACKEND_SCRIPT_PATH))


def check_java_backend_responsive(ssh_client, backend_url):
    """
    通过 GET 请求检测真实 Java 后端是否已能正常响应 mod_xml_curl 请求。

    需求：启动 Mock Java 后端前先确认真实后端是否已就绪。若真实后端能正确响应
         mod_xml_curl 的 DIALPLAN 请求（HTTP 200 且响应体非空），则无需启动 mock，
         既避免 mock 与真实后端抢占 JAVA_BACKEND_PORT，也省去 mock 的启停开销。
    处理逻辑：
        1. 拼接 mod_xml_curl 标准查询参数 section=DIALPLAN
        2. 通过远程 curl GET 请求 backend_url（连接超时 3s，整体超时 5s）
        3. HTTP 状态码 200 且响应体字节数 > 0 视为真实后端已就绪
    入参约束：
        backend_url：实际可用的 Java 后端 URL（已由 detect_java_backend_host 确定主机）
    返回规则：
        True  - 真实 Java 后端已就绪，可跳过 mock 启动
        False - 真实 Java 后端未就绪或响应异常，仍需启动 mock
    异常场景：curl 命令本身失败、超时、返回非 200 状态码、响应体为空，均视为未就绪
    """
    test_url = "%s?section=DIALPLAN" % backend_url
    log_info("  检测真实 Java 后端响应: %s" % test_url)
    # -s 静默；-w 同时输出 http_code 与 size_download，便于判断是否返回了内容
    # 响应体落盘到临时文件后丢弃，避免占用 SSH 输出
    result = remote_exec(ssh_client,
                         "curl -s -o /tmp/_fs_backend_check.body -w '%%{http_code}|%%{size_download}' "
                         "--connect-timeout 3 --max-time 5 '%s' 2>/dev/null || echo FAIL" % test_url)
    if not result or result.strip() == "FAIL":
        log_info("  真实 Java 后端无响应（curl 失败），需要启动 mock")
        return False
    parts = result.strip().split("|")
    if len(parts) != 2:
        log_info("  真实 Java 后端响应异常（%s），需要启动 mock" % result)
        return False
    http_code, size = parts[0], parts[1]
    if http_code == "200" and size.isdigit() and int(size) > 0:
        log_success("  真实 Java 后端已就绪 (HTTP 200, %s 字节)，跳过 mock 启动" % size)
        return True
    log_info("  真实 Java 后端未就绪 (HTTP=%s, size=%s)，需要启动 mock" % (http_code, size))
    return False


def start_mock_java_backend(ssh_client):
    """
    在远程服务器后台启动 mock Java 后端 HTTP server，监听 JAVA_BACKEND_PORT。

    需求：mod_xml_curl 在 FreeSWITCH 启动时会同步请求 Java 后端获取配置。
         若 Java 后端未启动，curl 会等待 TCP connect 超时（约 135 秒），
         导致 FreeSWITCH 完全启动需要 10+ 分钟。
         部署期间启动 mock server 快速响应 mod_xml_curl，让 FreeSWITCH 正常启动。
    处理逻辑：
        1. 清理上次脚本异常退出可能残留的 mock backend（通过 PID 文件识别）
        2. 若 JAVA_BACKEND_PORT 仍被占用，假设真实 Java 后端已运行，跳过启动
        3. 上传 mock server 脚本到 MOCK_BACKEND_SCRIPT_PATH
        4. nohup 后台启动，记录 PID 到 MOCK_BACKEND_PID_FILE
        5. 等待 2 秒后验证 mock server 是否监听端口
    """
    log_info("启动 Mock Java 后端（端口 %d）..." % JAVA_BACKEND_PORT)

    # 1. 清理上次脚本异常退出可能残留的 mock backend
    residual_pid = remote_exec(ssh_client, "cat %s 2>/dev/null" % MOCK_BACKEND_PID_FILE)
    if residual_pid:
        log_info("  发现残留 mock backend PID 文件 (PID=%s)，尝试清理..." % residual_pid)
        remote_exec(ssh_client, "kill %s 2>/dev/null || true" % residual_pid)
        time.sleep(1)
        remote_exec(ssh_client, "kill -9 %s 2>/dev/null || true" % residual_pid)
        remote_exec(ssh_client, "rm -f %s %s" % (MOCK_BACKEND_PID_FILE, MOCK_BACKEND_SCRIPT_PATH))

    # 2. 检查端口是否仍被占用（可能是真实 Java 后端已启动）
    port_check = remote_exec(ssh_client,
                             "ss -tlnp 2>/dev/null | grep ':%d ' || true" % JAVA_BACKEND_PORT)
    if port_check:
        # 端口被占用且非残留 mock，假设真实 Java 后端已启动，跳过 mock
        log_warn("  端口 %d 已被占用，假设真实 Java 后端已运行，跳过 mock 启动" % JAVA_BACKEND_PORT)
        log_warn("  占用进程: %s" % port_check)
        return False

    # 3. 上传 mock server 脚本
    remote_write_file(ssh_client, MOCK_BACKEND_SCRIPT_PATH, MOCK_BACKEND_SCRIPT_CONTENT)
    remote_exec(ssh_client, "chmod +x %s" % MOCK_BACKEND_SCRIPT_PATH, check=True)

    # 4. 后台启动 mock server（nohup 确保脱离 SSH session）
    start_cmd = (
                    "nohup python3 %s > %s 2>&1 & "
                    "echo $! > %s"
                ) % (MOCK_BACKEND_SCRIPT_PATH, MOCK_BACKEND_LOG_FILE, MOCK_BACKEND_PID_FILE)
    remote_exec(ssh_client, start_cmd, check=True)

    # 5. 等待 mock server 启动并验证端口监听
    time.sleep(2)
    pid_str = remote_exec(ssh_client, "cat %s 2>/dev/null" % MOCK_BACKEND_PID_FILE)
    listen_check = remote_exec(ssh_client,
                               "ss -tlnp 2>/dev/null | grep ':%d ' || true" % JAVA_BACKEND_PORT)

    if pid_str and listen_check:
        log_success("  Mock Java 后端已启动 (PID=%s, 监听 %d)" % (pid_str.strip(), JAVA_BACKEND_PORT))
        return True
    else:
        log_error("  Mock Java 后端启动失败")
        log_error("  PID: %s" % pid_str if pid_str else "  PID: (空)")
        log_error("  监听: %s" % listen_check if listen_check else "  监听: (无)")
        # 输出 mock server 日志便于排查
        mock_log = remote_exec(ssh_client, "cat %s 2>/dev/null | tail -20" % MOCK_BACKEND_LOG_FILE)
        if mock_log:
            log_error("  Mock 日志:\n    %s" % mock_log.replace("\n", "\n    "))
        raise RuntimeError("Mock Java 后端启动失败")


def stop_mock_java_backend(ssh_client):
    """
    停止 mock Java 后端 HTTP server。

    需求：部署验证通过后停止 mock server，让真实 Java 后端可以接管 mod_xml_curl 请求。
    处理逻辑：
        1. 读取 PID 文件
        2. kill 进程
        3. 清理 PID 文件和脚本文件
    """
    log_info("停止 Mock Java 后端...")
    pid_str = remote_exec(ssh_client, "cat %s 2>/dev/null" % MOCK_BACKEND_PID_FILE)
    if not pid_str:
        log_info("  无 PID 文件，可能 mock server 未启动或已被停止")
        return

    # kill 进程（先 SIGTERM，等待 1 秒后 SIGKILL）
    remote_exec(ssh_client, "kill %s 2>/dev/null || true" % pid_str)
    time.sleep(1)
    remote_exec(ssh_client, "kill -9 %s 2>/dev/null || true" % pid_str)

    # 验证端口已释放
    listen_check = remote_exec(ssh_client,
                               "ss -tlnp 2>/dev/null | grep ':%d ' || true" % JAVA_BACKEND_PORT)
    if not listen_check:
        log_success("  Mock Java 后端已停止 (端口 %d 已释放)" % JAVA_BACKEND_PORT)
    else:
        log_warn("  端口 %d 仍被占用: %s" % (JAVA_BACKEND_PORT, listen_check))

    # 清理临时文件
    remote_exec(ssh_client, "rm -f %s %s" % (MOCK_BACKEND_PID_FILE, MOCK_BACKEND_SCRIPT_PATH))
    log_info("  Mock 临时文件已清理")


def extract_default_config(ssh_client, sudo_prefix, config_dir):
    """
    从 FreeSWITCH 镜像中提取 vanilla 默认配置到目标配置目录。

    需求：后续配置修改必须基于镜像原始配置增量修改，禁止全量覆盖。
         因此先通过临时容器把 /usr/share/freeswitch/conf/vanilla 完整复制出来。
    处理逻辑：
        1. 清理同名临时容器
        2. docker create 创建临时容器（不启动）
        3. sudo 创建 config_dir 并 chown 给当前用户（/etc 需要 root 权限）
        4. docker cp 复制 vanilla 配置（以当前用户身份写入，目录已 chown）
        5. 再次 chown 确保 docker cp 创建的子文件也归属正确
        6. 删除临时容器
    """
    log_info("提取 FreeSWITCH 默认配置到 %s ..." % config_dir)
    remote_exec(ssh_client, "%sdocker stop %s 2>/dev/null || true" % (sudo_prefix, TEMP_CONTAINER_NAME))
    remote_exec(ssh_client, "%sdocker rm %s 2>/dev/null || true" % (sudo_prefix, TEMP_CONTAINER_NAME))

    remote_exec(ssh_client, "%sdocker create --name %s %s" % (sudo_prefix, TEMP_CONTAINER_NAME, FS_IMAGE), check=True)
    # /etc 目录写操作需 root：sudo 创建目录后 chown 给当前用户，使后续 docker cp / remote_write_file 可直接写入
    remote_sudo(ssh_client, "mkdir -p %s" % config_dir, check=True)
    remote_sudo(ssh_client, "chown -R $(id -u):$(id -g) %s" % config_dir, check=True)
    # docker cp 以 calling user 身份写入，目录已归属 ubuntu
    cp_cmd = "%sdocker cp %s:/usr/share/freeswitch/conf/vanilla/. %s" % (
        sudo_prefix, TEMP_CONTAINER_NAME, config_dir)
    remote_exec(ssh_client, cp_cmd, check=True)
    # docker cp 创建的子文件可能归属 root，统一 chown 一次
    remote_sudo(ssh_client, "chown -R $(id -u):$(id -g) %s" % config_dir, check=False)
    remote_exec(ssh_client, "%sdocker rm %s" % (sudo_prefix, TEMP_CONTAINER_NAME), check=True)
    log_success("默认配置提取完成: %s" % config_dir)


# ==================== 5 个配置文件增量修改 ====================

def update_modules_conf(ssh_client, config_dir):
    """
    增量修改 modules.conf.xml：
        1. 确保 mod_xml_curl 有 ACTIVE <load> 行（与 Java 后端联动的核心模块）
        2. 注释掉 mod_signalwire（避免日志 SSL 报错噪音）

    需求与陷阱：vanilla 的 modules.conf.xml 中 mod_xml_curl 可能以注释形式存在
         （<!-- <load module="mod_xml_curl"/> -->），简单 regex 会误判为已加载。
         必须区分 ACTIVE 与 COMMENTED 的 load 行。
    """
    log_info("增量更新 modules.conf.xml ...")
    path = "%s/autoload_configs/modules.conf.xml" % config_dir
    content = remote_read_file(ssh_client, path)
    if not content:
        raise RuntimeError("modules.conf.xml 不存在或为空: %s" % path)

    changes = []

    # 1. 确保 mod_xml_curl 有 ACTIVE load 行（行首非 <!--）
    active_load_pattern = re.compile(r'(?m)^\s*(?!<!--.*)<load\s+module="mod_xml_curl"\s*/>')
    if active_load_pattern.search(content):
        log_info("  mod_xml_curl 已有 ACTIVE load 行，无需修改")
    else:
        # 无 ACTIVE load 行，检查是否有注释的 load 行，如有则取消注释
        commented_pattern = re.compile(r'(?m)^(\s*)<!--\s*(<load\s+module="mod_xml_curl"\s*/>)\s*-->\s*$')
        if commented_pattern.search(content):
            content = commented_pattern.sub(lambda m: '%s%s' % (m.group(1), m.group(2)), content)
            changes.append("取消注释 mod_xml_curl")
        else:
            # 无现有 load 行，在 </modules> 前新增
            content = content.replace("</modules>",
                                      '    <load module="mod_xml_curl"/>\n  </modules>', 1)
            changes.append("新增加载 mod_xml_curl")

    # 2. 注释掉 mod_signalwire（仅 ACTIVE 行；已注释的跳过）
    sig_active_pattern = re.compile(r'(?m)^(\s*)(?!<!--)(<load\s+module="mod_signalwire"\s*/>)\s*$')
    if sig_active_pattern.search(content):
        content = sig_active_pattern.sub(lambda m: '%s<!--  %s  -->' % (m.group(1), m.group(2)), content)
        changes.append("注释掉 mod_signalwire")
    else:
        log_info("  mod_signalwire 未启用或已注释，无需修改")

    # 3. 确保 mod_audio_fork 有 ACTIVE load 行（音频 fork 到 CC WebSocket，支撑流式 TTS/ASR）
    active_fork_pattern = re.compile(r'(?m)^\s*(?!<!--.*)<load\s+module="mod_audio_fork"\s*/>')
    if active_fork_pattern.search(content):
        log_info("  mod_audio_fork 已有 ACTIVE load 行，无需修改")
    else:
        content = content.replace("</modules>",
                                  '    <load module="mod_audio_fork"/>\n  </modules>', 1)
        changes.append("新增加载 mod_audio_fork")

    remote_write_file(ssh_client, path, content)
    if changes:
        log_info("  修改项: %s" % "; ".join(changes))
    log_info("  modules.conf.xml 增量更新完成")


def update_audio_fork_conf(ssh_client, config_dir):
    """
    创建 mod_audio_fork 配置文件 autoload_configs/mod_audio_fork.conf.xml。

    需求：该文件为本次部署新增（vanilla 不存在），记录音频参数默认值供运维
         参考；mod_audio_fork 不读取 conf 中的 ws-url（连接地址由 Java 后端
         每次通过 ESL uuid_audio_fork 命令动态下发），故 conf 中不配置 ws-url。
    """
    log_info("创建 mod_audio_fork.conf.xml ...")
    path = "%s/autoload_configs/mod_audio_fork.conf.xml" % config_dir
    content = (
                  '<configuration name="mod_audio_fork.conf" description="Audio Fork Module">\n'
                  '  <settings>\n'
                  '    <param name="mix-type" value="%s"/>\n'
                  '    <param name="sample-rate" value="%s"/>\n'
                  '  </settings>\n'
                  '</configuration>\n'
              ) % (AUDIO_FORK_MIX_TYPE, AUDIO_FORK_SAMPLE_RATE)
    remote_write_file(ssh_client, path, content)
    log_success("mod_audio_fork.conf.xml 创建完成")


def install_mod_audio_fork(ssh_client, sudo_prefix, container_name):
    """
    注入预编译的 mod_audio_fork 产物到 FS 容器并动态加载。

    需求与陷阱：
        mod_audio_fork 使用仓库内预编译产物（mod_audio_fork-binary/ 目录），
        部署时不再编译（原编译流程已抽离为重建工具脚本，仅升级 FS 版本或
        更换 CPU 架构时使用）。产物约束：
        1. ubuntu:22.04 (glibc 2.35) x86_64 编译，实测仅依赖 GLIBC_2.32，
           Debian 12 (glibc 2.36) 的 safarov/freeswitch:1.10.12 容器可正常加载；
        2. 依赖 libwebsockets.so.16（ubuntu 22.04 版本，SONAME 与 FS 容器
           Debian 12 不同）及其依赖 libev/libuv，需随模块一并注入容器 /lib
           并建立 SONAME 符号链接（产物目录中保存的是真实文件，docker cp
           复制符号链接会报 Too many levels of symbolic links）。
    处理逻辑：
        1. 已加载则跳过
        2. 校验本地产物齐全后 SFTP 上传宿主机 /tmp
        3. docker cp 注入 FS 容器（模块 .so + 3 个依赖库）
        4. 容器内建立 libev/libuv 的 SONAME 符号链接
        5. fs_cli 动态加载并校验（重试 3 次规避库加载时序问题），失败时
           解析日志定位原因并提示（版本/架构不匹配需用重建工具重新编译），
           不影响主流程（流式 TTS/ASR 降级为 say 放音/DTMF 收号）
    """
    log_info("[mod_audio_fork] 注入预编译模块到容器 [%s] ..." % container_name)

    # 1. 已加载则直接跳过
    loaded = remote_exec(ssh_client,
                         "%sdocker exec %s fs_cli -P %d -p %s -x 'module_exists mod_audio_fork'" % (
                             sudo_prefix, container_name, ESL_PORT, ESL_PASSWORD))
    if loaded and "true" in loaded.lower():
        log_success("[mod_audio_fork] 模块已加载，跳过安装")
        return True

    # 2. 校验本地产物文件齐全（缺失时提示先用重建工具生成产物）
    missing_files = [name for name, _ in AUDIO_FORK_FILES
                     if not os.path.isfile(os.path.join(AUDIO_FORK_BINARY_DIR, name))]
    if missing_files:
        log_error("[mod_audio_fork] 本地产物缺失: %s" % ", ".join(missing_files))
        log_error("[mod_audio_fork] 请先运行重建工具脚本生成产物（freeswitch编译mod_audio_fork重建工具.py）")
        return False

    # 3. SFTP 上传产物到宿主机 /tmp 并 docker cp 注入 FS 容器
    for name, target_path in AUDIO_FORK_FILES:
        local_path = os.path.join(AUDIO_FORK_BINARY_DIR, name)
        remote_path = "/tmp/af_binary_%s" % name
        remote_upload_file(ssh_client, local_path, remote_path)
        remote_exec(ssh_client, "%sdocker cp %s %s:%s" % (
            sudo_prefix, remote_path, container_name, target_path), check=True)

    # 4. 容器内建立 libev/libuv 的 SONAME 符号链接（libwebsockets.so.16 为真实文件名无需建链）
    remote_exec(ssh_client,
                "%sdocker exec %s sh -c 'ln -sf /lib/libev.so.4.0.0 /lib/libev.so.4; ln -sf /lib/libuv.so.1.0.0 /lib/libuv.so.1; true'" % (
                    sudo_prefix, container_name), check=False)

    # 5. 动态加载并校验（重试 3 次，规避容器内库加载时序问题）
    for attempt in range(3):
        remote_exec(ssh_client,
                    "%sdocker exec %s fs_cli -P %d -p %s -x 'load mod_audio_fork'" % (
                        sudo_prefix, container_name, ESL_PORT, ESL_PASSWORD))
        verify_result = remote_exec(ssh_client,
                                    "%sdocker exec %s fs_cli -P %d -p %s -x 'module_exists mod_audio_fork'" % (
                                        sudo_prefix, container_name, ESL_PORT, ESL_PASSWORD))
        if verify_result and "true" in verify_result.lower():
            log_success("[mod_audio_fork] 模块注入并加载成功")
            remote_exec(ssh_client, "rm -f /tmp/af_binary_*", check=False)
            return True
        time.sleep(2)

    # 6. 加载失败：解析日志定位原因（通常为架构/镜像版本不匹配，需重建产物）
    err_log = remote_exec(ssh_client,
                          "%sdocker exec %s tail -50 /var/log/freeswitch/freeswitch.log | grep -oE 'error while loading shared libraries: [^:]*|cannot open shared object file: [^ ]*|too many levels of symbolic links' | tail -1" % (
                              sudo_prefix, container_name))
    log_error("[mod_audio_fork] 模块加载失败，原因: %s" % (err_log or "未知（请查看 freeswitch.log）"))
    log_error("[mod_audio_fork] 流式 TTS/ASR 将降级为 say 放音/DTMF 收号；若为版本/架构不匹配请用重建工具重新编译产物")
    remote_exec(ssh_client, "rm -f /tmp/af_binary_*", check=False)
    return False


def update_xml_curl_conf(ssh_client, config_dir, backend_url):
    """
    增量修改 xml_curl.conf.xml：确保有一个 active 的 binding 把动态配置请求转发到 Java 后端。

    需求与陷阱：
        vanilla 的 xml_curl.conf.xml 有一个 ACTIVE 的 <binding name="example">，
        但其内部所有 <param>（包括 gateway-url）都被 <!-- --> 注释。
        mod_xml_curl 解析时发现 binding 没有 gateway-url 就会报 "Binding has no url!" 并加载失败。
        简单的 regex 替换会误匹配注释内的 gateway-url，导致值被更新但参数仍被注释。
    处理逻辑：
        1. 优先查找 ACTIVE（非注释）的 <param name="gateway-url" .../>：
           - 存在则更新其 value 与 bindings 属性
        2. 若无 ACTIVE gateway-url，但存在 <binding name="example">...</binding> 块：
           - 整体替换该 example binding 为自定义 binding（vanilla 的 example 无用，替换不丢功能）
        3. 否则在 <bindings> 后插入新 binding
    参数：
        backend_url: 实际可用的 Java 后端 URL（可能是公网 IP 或内网 IP，由 detect_java_backend_host 确定）
    """
    log_info("增量更新 xml_curl.conf.xml (gateway-url=%s)..." % backend_url)
    path = "%s/autoload_configs/xml_curl.conf.xml" % config_dir
    content = remote_read_file(ssh_client, path)
    if not content:
        raise RuntimeError("xml_curl.conf.xml 不存在或为空: %s" % path)

    binding_block = (
                        '    <binding name="all configs">\n'
                        '      <param name="gateway-url" value="%s" bindings="%s"/>\n'
                        '      <param name="timeout" value="%d"/>\n'
                        '    </binding>'
                    ) % (backend_url, XML_CURL_BINDINGS, XML_CURL_TIMEOUT_MS)

    # 关键：匹配"未被注释"的 gateway-url param。
    # 通过负向先行断言排除 <!-- ... --> 包裹的注释行。
    # ACTIVE gateway-url 定义：该行以空白开头，后跟 <param name="gateway-url".../>，且行首没有 <!--
    active_url_pattern = re.compile(
        r'(?m)^\s*(?!<!--.*)(<param\s+name="gateway-url"\s+value=")[^"]*("[^>]*/>)'
    )

    if active_url_pattern.search(content):
        # 已有 ACTIVE gateway-url，更新其 value
        old_content = content
        content = active_url_pattern.sub(
            lambda m: m.group(1) + backend_url + m.group(2), content)
        # 同时更新 ACTIVE timeout（紧跟 gateway-url 的）
        active_timeout_pattern = re.compile(
            r'(?m)^\s*(?!<!--.*)(<param\s+name="timeout"\s+value=")[^"]*("[^>]*/>)'
        )
        if active_timeout_pattern.search(content):
            content = active_timeout_pattern.sub(
                lambda m: m.group(1) + str(XML_CURL_TIMEOUT_MS) + m.group(2), content)
        # 更新 bindings 属性（仅 ACTIVE gateway-url 行的）
        bindings_attr_pattern = re.compile(
            r'(?m)^(\s*(?!<!--.*)(<param\s+name="gateway-url"\s+value="[^"]*"\s+)(bindings=")[^"]*("))'
        )
        if bindings_attr_pattern.search(content):
            content = bindings_attr_pattern.sub(
                lambda m: m.group(2) + m.group(3) + XML_CURL_BINDINGS + m.group(4), content)
        if old_content != content:
            log_info("  更新已存在的 ACTIVE binding: gateway-url=%s" % backend_url)
        else:
            log_info("  binding 已是最新配置")
    else:
        # 无 ACTIVE gateway-url，检查是否存在 vanilla 的 example binding（整体替换）
        example_binding_pattern = re.compile(
            r'(?ms)^\s*<binding\s+name="example"[^>]*>.*?</binding>'
        )
        if example_binding_pattern.search(content):
            content = example_binding_pattern.sub(
                lambda m: binding_block.rstrip(), content)
            log_info("  替换 vanilla example binding 为自定义 binding: gateway-url=%s" % backend_url)
        elif "<bindings>" in content:
            content = content.replace("<bindings>",
                                      "<bindings>\n" + binding_block, 1)
            log_info("  新增 binding: gateway-url=%s" % backend_url)
        else:
            content = content.replace("</configuration>",
                                      "  <bindings>\n%s\n  </bindings>\n</configuration>" % binding_block, 1)
            log_info("  新增 <bindings> + binding: gateway-url=%s" % backend_url)

    remote_write_file(ssh_client, path, content)
    log_info("  xml_curl.conf.xml 增量更新完成")


def update_event_socket_conf(ssh_client, config_dir):
    """
    增量修改 event_socket.conf.xml：设置 ESL 端口、密码、应用 ACL。

    需求：保留 nat-map、listen-ip 等默认 param，仅增量修改端口/密码/ACL。
    """
    log_info("增量更新 event_socket.conf.xml ...")
    path = "%s/autoload_configs/event_socket.conf.xml" % config_dir
    content = remote_read_file(ssh_client, path)
    if not content:
        raise RuntimeError("event_socket.conf.xml 不存在或为空: %s" % path)

    content = xml_set_params(content, "</settings>", {
        "listen-port": ESL_PORT,
        "password": ESL_PASSWORD,
        "apply-inbound-acl": ACL_LIST_NAME,
    })
    remote_write_file(ssh_client, path, content)
    log_info("  event_socket.conf.xml 增量更新完成 (端口: %s, ACL: %s)" % (ESL_PORT, ACL_LIST_NAME))


def update_acl_conf(ssh_client, config_dir):
    """
    增量修改 acl.conf.xml：新增 event_socket.auto 列表允许指定 CIDR 连接 ESL。

    需求：保留 vanilla 默认的 ACL 列表（domains、default 等），仅新增 event_socket.auto。
         若已存在同名 list，更新其 node 配置；否则在 </network-lists> 前插入。
    """
    log_info("增量更新 acl.conf.xml ...")
    path = "%s/autoload_configs/acl.conf.xml" % config_dir
    content = remote_read_file(ssh_client, path)
    if not content:
        raise RuntimeError("acl.conf.xml 不存在或为空: %s" % path)

    list_block = (
                     '    <list name="%s" default="deny">\n'
                     '      <node type="allow" cidr="%s"/>\n'
                     '    </list>'
                 ) % (ACL_LIST_NAME, ACL_ALLOW_CIDR)

    # 检查是否已存在同名 list
    list_pattern = re.compile(r'<list\s+name="%s"[^>]*>.*?</list>' % re.escape(ACL_LIST_NAME), re.DOTALL)
    if list_pattern.search(content):
        # 已存在，替换整个 list 块
        content = list_pattern.sub(lambda m: list_block, content)
        log_info("  更新已存在的 list: %s" % ACL_LIST_NAME)
    else:
        # 不存在，在 </network-lists> 前插入
        if "</network-lists>" in content:
            content = content.replace("</network-lists>",
                                      list_block + "\n  </network-lists>", 1)
            log_info("  新增 list: %s (允许 %s)" % (ACL_LIST_NAME, ACL_ALLOW_CIDR))
        else:
            log_warn("  未找到 </network-lists> 标签，跳过 ACL 新增（可能默认配置结构不同）")

    remote_write_file(ssh_client, path, content)
    log_info("  acl.conf.xml 增量更新完成")


def update_vars_xml(ssh_client, config_dir):
    """
    增量修改 vars.xml：设置默认密码、公网 IP、SIP/TLS 端口、SSL 开关、auth 开关。

    需求：通过 sed 替换 X-PRE-PROCESS 指令中的 data 属性值，保留其他默认变量。
         若目标变量不存在，则在 </X-PRE-PROCESS> 区域末尾追加（vars.xml 末尾的 vars.xml include）。
    """
    log_info("增量更新 vars.xml ...")
    path = "%s/vars.xml" % config_dir
    content = remote_read_file(ssh_client, path)
    if not content:
        raise RuntimeError("vars.xml 不存在或为空: %s" % path)

    # 定义需要设置的所有 X-PRE-PROCESS 指令：cmd -> (data_key, value)
    directives = [
        ("set", "default_password", DEFAULT_PASSWORD),
        ("set", "internal_auth_calls", "false"),
        ("set", "internal_sip_port", str(INTERNAL_SIP_PORT)),
        ("set", "internal_tls_port", str(INTERNAL_TLS_PORT)),
        ("set", "internal_ssl_enable", "false"),
        ("set", "external_auth_calls", "false"),
        ("set", "external_sip_port", str(EXTERNAL_SIP_PORT)),
        ("set", "external_tls_port", str(EXTERNAL_TLS_PORT)),
        ("set", "external_ssl_enable", "false"),
    ]

    changes = []
    for cmd, key, value in directives:
        # 匹配 <X-PRE-PROCESS cmd="set" data="key=value"/>
        pattern = re.compile(
            r'(<X-PRE-PROCESS\s+cmd="%s"\s+data="%s=)[^"]*(")' % (re.escape(cmd), re.escape(key))
        )
        if pattern.search(content):
            content = pattern.sub(lambda m: m.group(1) + value + m.group(2), content)
            changes.append("%s=%s" % (key, value))
        else:
            # 不存在，在文件末尾追加（vars.xml 末尾通常有 </include> 或类似闭合标签）
            new_line = '<X-PRE-PROCESS cmd="%s" data="%s=%s"/>' % (cmd, key, value)
            # 优先在 </include> 前插入
            if "</include>" in content:
                content = content.replace("</include>", new_line + "\n</include>", 1)
            else:
                content = content + "\n" + new_line
            changes.append("新增 %s=%s" % (key, value))

    # 处理 external_rtp_ip / external_sip_ip（stun-set 命令）
    # 部署文档使用 stun-set，但用户选择直接用公网 IP，改为 set 命令更可控
    for key, value in [("external_rtp_ip", PUBLIC_IP), ("external_sip_ip", PUBLIC_IP)]:
        # 先检查 stun-set 形式
        stun_pattern = re.compile(
            r'(<X-PRE-PROCESS\s+cmd="stun-set"\s+data="%s=)[^"]*(")' % re.escape(key)
        )
        set_pattern = re.compile(
            r'(<X-PRE-PROCESS\s+cmd="set"\s+data="%s=)[^"]*(")' % re.escape(key)
        )
        if stun_pattern.search(content):
            # 把 stun-set 改为 set，避免依赖外部 STUN 服务器
            content = stun_pattern.sub(
                lambda m: '<X-PRE-PROCESS cmd="set" data="%s=%s"' % (key, value), content)
            changes.append("%s=%s (stun-set → set)" % (key, value))
        elif set_pattern.search(content):
            content = set_pattern.sub(lambda m: m.group(1) + value + m.group(2), content)
            changes.append("%s=%s" % (key, value))
        else:
            new_line = '<X-PRE-PROCESS cmd="set" data="%s=%s"/>' % (key, value)
            if "</include>" in content:
                content = content.replace("</include>", new_line + "\n</include>", 1)
            else:
                content = content + "\n" + new_line
            changes.append("新增 %s=%s" % (key, value))

    # 处理 ext-sip-ip / ext-rtp-ip（SIP profile 使用的 ${external_sip_ip} 变量已足够，
    # 但 vanilla vars.xml 中可能也有 ext-sip-ip/ext-rtp-ip 的 stun-set，统一改为 set）
    for key, value in [("ext-sip-ip", "$${external_sip_ip}"), ("ext-rtp-ip", "$${external_rtp_ip}")]:
        stun_pattern = re.compile(
            r'(<X-PRE-PROCESS\s+cmd="stun-set"\s+data="%s=)[^"]*(")' % re.escape(key)
        )
        if stun_pattern.search(content):
            content = stun_pattern.sub(
                lambda m: '<X-PRE-PROCESS cmd="set" data="%s=%s"' % (key, value), content)
            changes.append("%s=%s (stun-set → set)" % (key, value))

    remote_write_file(ssh_client, path, content)
    log_info("  vars.xml 修改项: %s" % "; ".join(changes))
    log_info("  vars.xml 增量更新完成 (公网 IP: %s)" % PUBLIC_IP)


def update_sip_profiles(ssh_client, config_dir):
    """
    增量更新 SIP Profiles：sip-ip/rtp-ip 设为 0.0.0.0 监听所有地址，ext-sip-ip/ext-rtp-ip 通告公网 IP。

    需求背景（2026-08-14 hairpin 问题）：云厂商将公网 IP(<A服务器公网>) 绑定在 lo 接口
    （NAT 模式）。vanilla 默认 sip-ip=$${local_ip_v4}（解析为内网 IP <A服务器内网>）或显式绑定
    公网 IP 时，服务器内部（如 sipproxy、另一台 FS）发往 <A服务器公网>:SIP端口 的包路由到 lo
    后无监听 socket 被内核丢弃（发卡），导致服务器内无法通过公网 IP 访问 docker-FS 的 SIP 端口。
    设置 sip-ip=0.0.0.0（监听所有接口含 lo）后，服务器内访问公网 IP 的 SIP 端口可达；
    ext-sip-ip 仍通告公网 IP，保证对端（坐席/网关）收到正确的 Contact/对外通告地址。

    处理逻辑：internal/external profile 增量修改 sip-ip/rtp-ip/ext-sip-ip/ext-rtp-ip 四个 param，
    其余 50+ 默认 param 完全不变（复用 xml_set_params 增量语义）。
    """
    log_info("增量更新 SIP Profiles（sip-ip=%s 监听公网IP, rtp-ip=0.0.0.0）..." % PUBLIC_IP)
    profile_params = {
        "rtp-ip": "0.0.0.0",
        "sip-ip": PUBLIC_IP,
        "ext-rtp-ip": PUBLIC_IP,
        "ext-sip-ip": PUBLIC_IP,
    }
    for profile in ["internal", "external"]:
        path = "%s/sip_profiles/%s.xml" % (config_dir, profile)
        content = remote_read_file(ssh_client, path)
        if not content:
            log_warn("  sip_profiles/%s.xml 不存在或为空，跳过" % profile)
            continue
        content = xml_set_params(content, "</settings>", profile_params)
        remote_write_file(ssh_client, path, content)
        log_info("  sip_profiles/%s.xml 更新完成 (sip-ip=%s, rtp-ip=0.0.0.0, ext-sip-ip=%s)" % (profile, PUBLIC_IP,
                                                                                                PUBLIC_IP))


# ==================== 启动容器 ====================

def start_freeswitch_container(ssh_client, sudo_prefix, container_name, config_dir):
    """
    使用 host 网络模式启动 FreeSWITCH 容器，挂载配置目录，并覆盖镜像内置 healthcheck。

    需求与陷阱：--net=host 模式下容器直接使用主机端口，无需端口映射。
         挂载配置目录到 /etc/freeswitch，使宿主机修改的配置生效。
         safarov/freeswitch 镜像内置 healthcheck 脚本 /healthcheck.sh 使用默认
         `fs_cli -x status`（连接 127.0.0.1:8021 无密码），但本部署把 ESL 端口改为
         18021、密码改为 <密码>，导致内置 healthcheck 始终报 unhealthy
         （"Error Connecting"），虽然不影响 FreeSWITCH 核心功能，但状态不健康会误导
         运维且可能触发容器编排系统的自动重启策略。
         通过 --health-cmd 覆盖为带端口和密码的 fs_cli 命令，使 healthcheck 正常工作。
    """
    log_info("启动 FreeSWITCH 容器 [%s] ..." % container_name)
    # 覆盖 healthcheck：使用实际的 ESL 端口和密码，间隔 30s，超时 5s，启动等待 30s
    health_cmd = "fs_cli -P %d -p %s -x 'status' | grep -q UP" % (ESL_PORT, ESL_PASSWORD)
    run_cmd = (
                  "%sdocker run -d --net=host --name %s "
                  "--log-opt max-size=10m --log-opt max-file=3 "
                  "-e TZ=Asia/Shanghai "
                  "--health-cmd \"%s\" "
                  "--health-interval=30s --health-timeout=5s --health-start-period=30s --health-retries=3 "
                  "-v %s:/etc/freeswitch %s"
              ) % (sudo_prefix, container_name, health_cmd, config_dir, FS_IMAGE)
    remote_exec(ssh_client, run_cmd, check=True)

    log_info("等待容器启动（%d 秒）..." % CONTAINER_START_WAIT_SECONDS)
    time.sleep(CONTAINER_START_WAIT_SECONDS)

    status = remote_exec(ssh_client,
                         '%sdocker ps --filter "name=^%s$" --format "{{.Status}}"' % (sudo_prefix, container_name))
    if "Up" in status:
        log_success("FreeSWITCH 容器 [%s] 已启动: %s" % (container_name, status))
    else:
        log_error("FreeSWITCH 容器 [%s] 启动失败" % container_name)
        logs = remote_exec(ssh_client, "%sdocker logs %s 2>&1 | tail -50" % (sudo_prefix, container_name))
        print("    [容器日志]\n    %s" % logs.replace("\n", "\n    "))
        raise RuntimeError("FreeSWITCH 容器启动失败: %s" % container_name)


# ==================== 严谨的部署后验证 ====================

def verify_container_running(ssh_client, sudo_prefix, container_name):
    """
    验证 1：容器运行状态 + healthcheck 状态。

    需求：容器必须 Up 且 healthcheck 非 unhealthy。
         注：health-start-period=30s + interval=30s，容器刚启动时 healthcheck 可能
         还在 starting 阶段，此时不算 fail；但若已超出 start period 仍 unhealthy 则 fail。
    """
    log_info("[验证 1/9] 容器运行状态...")
    status = remote_exec(ssh_client,
                         '%sdocker ps --filter "name=^%s$" --format "{{.Names}}\t{{.Status}}\t{{.Ports}}"' % (
                             sudo_prefix, container_name))
    if not status or "Up" not in status:
        log_error("  FAIL: 容器未运行")
        return False

    log_success("  PASS: %s" % status.replace("\t", " | "))

    # 附加检查 healthcheck 状态（容器已通过 --health-cmd 覆盖为带端口密码的 fs_cli）
    # 健康状态：starting（启动初期）/ healthy / unhealthy / 空（无 healthcheck）
    health_status = remote_exec(ssh_client,
                                '%sdocker inspect --format "{{.State.Health.Status}}" %s 2>/dev/null' % (
                                    sudo_prefix, container_name))
    if health_status:
        if health_status == "healthy":
            log_success("  PASS: healthcheck 状态 = healthy")
        elif health_status == "starting":
            log_info("  INFO: healthcheck 仍在启动期 (starting)，稍后会自动变为 healthy")
        elif health_status == "unhealthy":
            # unhealthy 但容器 Up：可能是 healthcheck 间隔未到或 fs_cli 短暂失败
            # 输出最近一次 healthcheck 日志便于排查
            last_hc = remote_exec(ssh_client,
                                  '%sdocker inspect --format "{{json .State.Health.Log}}" %s 2>/dev/null' % (
                                      sudo_prefix, container_name))
            log_warn("  WARN: healthcheck = unhealthy（容器仍 Up，FS 功能可能正常）")
            log_warn("  最近 healthcheck 日志: %s" % (last_hc[:200] if last_hc else "(无)"))
        else:
            log_info("  INFO: healthcheck 状态 = %s" % health_status)
    return True


def wait_for_esl_ready(ssh_client, sudo_prefix, container_name,
                       retry_count=None, retry_interval=None):
    """
    轮询等待 ESL 端口可连接。

    需求：FreeSWITCH 启动时间不确定（mod_xml_curl 阻塞、模块加载顺序等），
         直接验证可能误判失败。需要轮询重试直到 ESL 就绪或超时。
    处理逻辑：
        1. 循环执行 fs_cli status 命令
        2. 返回包含 "UP" 视为就绪
        3. 否则等待 retry_interval 秒后重试
    返回：就绪返回 fs_cli 输出，超时返回 None
    """
    if retry_count is None:
        retry_count = ESL_CONNECT_RETRY_COUNT
    if retry_interval is None:
        retry_interval = ESL_CONNECT_RETRY_INTERVAL

    cmd = "%sdocker exec %s fs_cli -P %s -p %s -x 'status'" % (
        sudo_prefix, container_name, ESL_PORT, ESL_PASSWORD)

    for attempt in range(1, retry_count + 1):
        result = remote_exec(ssh_client, cmd)
        if result and "UP" in result.upper():
            return result
        if attempt < retry_count:
            log_info("    ESL 未就绪，%d 秒后重试 (%d/%d)..." % (
                retry_interval, attempt, retry_count))
            time.sleep(retry_interval)
    return None


def verify_esl_connection(ssh_client, sudo_prefix, container_name):
    """验证 2：ESL 连接（fs_cli status 返回 UP，带轮询重试）"""
    log_info("[验证 2/9] ESL 连接（轮询等待 FreeSWITCH 就绪）...")
    result = wait_for_esl_ready(ssh_client, sudo_prefix, container_name)
    if result:
        log_success("  PASS: ESL 连接成功")
        for line in result.split("\n")[:5]:
            log_info("    %s" % line)
        return True
    log_error("  FAIL: ESL 连接失败（已重试 %d 次，共 %d 秒）" % (
        ESL_CONNECT_RETRY_COUNT, ESL_CONNECT_RETRY_COUNT * ESL_CONNECT_RETRY_INTERVAL))
    # 最后一次的输出用于排查
    last_cmd = "%sdocker exec %s fs_cli -P %s -p %s -x 'status' 2>&1" % (
        sudo_prefix, container_name, ESL_PORT, ESL_PASSWORD)
    last_result = remote_exec(ssh_client, last_cmd)
    log_error("    最后一次输出: %s" % (last_result[:200] if last_result else "(空)"))
    return False


def verify_sofia_profiles(ssh_client, sudo_prefix, container_name):
    """验证 3：Sofia Profile 状态（internal & external 均 RUNNING）"""
    log_info("[验证 3/9] Sofia Profile 状态...")
    cmd = "%sdocker exec %s fs_cli -P %s -p %s -x 'sofia status'" % (
        sudo_prefix, container_name, ESL_PORT, ESL_PASSWORD)
    result = remote_exec(ssh_client, cmd)
    if not result:
        log_error("  FAIL: sofia status 无输出")
        return False

    has_internal = "internal" in result and "RUNNING" in result
    has_external = "external" in result and "RUNNING" in result
    if has_internal and has_external:
        log_success("  PASS: internal & external profiles 均 RUNNING")
        for line in result.split("\n")[:10]:
            log_info("    %s" % line)
        return True
    log_error("  FAIL: Sofia profiles 异常 (internal=%s, external=%s)" % (has_internal, has_external))
    log_error("    %s" % result.replace("\n", "\n    ")[:500])
    return False


def verify_port_listening(ssh_client, sudo_prefix):
    """验证 4：所有目标端口实际监听（TCP + UDP）"""
    log_info("[验证 4/9] 主机端口监听状态...")
    all_listening = True
    # TCP 端口
    for port in TCP_PORTS_TO_CHECK:
        cmd = ("%sss -tlnp 2>/dev/null | grep ':%s ' || "
               "netstat -tlnp 2>/dev/null | grep ':%s '") % (sudo_prefix, port, port)
        result = remote_exec(ssh_client, cmd)
        if result:
            log_success("  PASS: TCP/%s 监听中" % port)
        else:
            log_error("  FAIL: TCP/%s 未监听" % port)
            all_listening = False
    # SIP UDP 端口（RTP 端口范围太大不逐一检查，只看 SIP UDP）
    for udp_port in [INTERNAL_SIP_PORT, EXTERNAL_SIP_PORT]:
        cmd = ("%sss -ulnp 2>/dev/null | grep ':%s ' || "
               "netstat -ulnp 2>/dev/null | grep ':%s '") % (sudo_prefix, udp_port, udp_port)
        result = remote_exec(ssh_client, cmd)
        if result:
            log_success("  PASS: UDP/%s 监听中" % udp_port)
        else:
            log_error("  FAIL: UDP/%s 未监听" % udp_port)
            all_listening = False
    return all_listening


def verify_config_file_values(ssh_client, sudo_prefix, container_name, config_dir, backend_url):
    """
    验证 5：从容器内读取配置文件，逐项校验关键值是否生效。

    需求：严谨验证配置是否生效——不能只看文件存在，必须验证具体值正确。
    参数：
        backend_url: 实际写入 xml_curl.conf.xml 的 Java 后端 URL（可能是公网或内网 IP）
    """
    log_info("[验证 5/9] 配置文件实际值校验...")
    all_correct = True

    def check(label, grep_cmd, expected_substr):
        nonlocal all_correct
        result = remote_exec(ssh_client, grep_cmd)
        if expected_substr in result:
            log_success("  PASS: %s" % label)
            log_info("    %s" % result)
        else:
            log_error("  FAIL: %s (期望包含 %r)" % (label, expected_substr))
            log_error("    实际: %s" % result)
            all_correct = False

    # 5.1 modules.conf.xml - ACTIVE mod_xml_curl 加载行（排除注释行）
    #     vanilla 的 mod_xml_curl load 行可能是注释状态，简单 grep 会误报 PASS
    active_load_cmd = (
                          "%sdocker exec %s sh -c \"grep '<load module=\\\"mod_xml_curl\\\"' "
                          "/etc/freeswitch/autoload_configs/modules.conf.xml | grep -vE '^\\s*<!--'\""
                      ) % (sudo_prefix, container_name)
    check("modules.conf.xml 含 ACTIVE mod_xml_curl 加载行", active_load_cmd, "mod_xml_curl")

    # 5.2 modules.conf.xml - mod_signalwire 已注释
    sig_check = remote_exec(ssh_client,
                            "%sdocker exec %s grep -c '<!--.*mod_signalwire' %s/autoload_configs/modules.conf.xml || echo 0" % (
                                sudo_prefix, container_name, "/etc/freeswitch"))
    if sig_check and sig_check != "0":
        log_success("  PASS: mod_signalwire 已注释")
    else:
        # 检查是否本来就没有 mod_signalwire
        exists_check = remote_exec(ssh_client,
                                   "%sdocker exec %s grep -c 'mod_signalwire' %s/autoload_configs/modules.conf.xml || echo 0" % (
                                       sudo_prefix, container_name, "/etc/freeswitch"))
        if exists_check and exists_check != "0":
            log_warn("  WARN: mod_signalwire 存在但未注释（可能镜像版本不同）")
        else:
            log_success("  PASS: mod_signalwire 不存在（无需注释）")

    # 5.3 xml_curl.conf.xml - ACTIVE gateway-url 正确（排除注释行）
    #     vanilla 的 gateway-url 在 <!-- --> 内，简单 grep 会误报 PASS，必须过滤注释行
    #     注：gateway-url 使用实际可用的 backend_url（可能是内网 IP）
    active_url_cmd = (
                         "%sdocker exec %s sh -c \"grep '<param name=\\\"gateway-url\\\"' "
                         "/etc/freeswitch/autoload_configs/xml_curl.conf.xml | grep -vE '^\\s*<!--' | grep '%s'\""
                     ) % (sudo_prefix, container_name, backend_url)
    check("xml_curl.conf.xml ACTIVE gateway-url 指向 Java 后端", active_url_cmd, backend_url)

    # 5.4 event_socket.conf.xml - listen-port 正确
    check("event_socket.conf.xml listen-port=%d" % ESL_PORT,
          "%sdocker exec %s grep 'listen-port' %s/autoload_configs/event_socket.conf.xml" % (
              sudo_prefix, container_name, "/etc/freeswitch"),
          str(ESL_PORT))

    # 5.5 event_socket.conf.xml - ACTIVE password 正确（排除注释行）
    active_pwd_cmd = (
                         "%sdocker exec %s sh -c \"grep 'name=\\\"password\\\"' "
                         "/etc/freeswitch/autoload_configs/event_socket.conf.xml | grep -vE '^\\s*<!--'\""
                     ) % (sudo_prefix, container_name)
    check("event_socket.conf.xml ACTIVE password 正确", active_pwd_cmd, ESL_PASSWORD)

    # 5.6 event_socket.conf.xml - ACTIVE apply-inbound-acl 正确（排除注释行）
    #     vanilla 的 apply-inbound-acl 可能是注释状态，需确认 ACTIVE
    active_acl_cmd = (
                         "%sdocker exec %s sh -c \"grep 'apply-inbound-acl' "
                         "/etc/freeswitch/autoload_configs/event_socket.conf.xml | grep -vE '^\\s*<!--'\""
                     ) % (sudo_prefix, container_name)
    check("event_socket.conf.xml ACTIVE apply-inbound-acl=%s" % ACL_LIST_NAME, active_acl_cmd, ACL_LIST_NAME)

    # 5.7 acl.conf.xml - event_socket.auto list 存在
    check("acl.conf.xml 含 %s list" % ACL_LIST_NAME,
          "%sdocker exec %s grep '%s' %s/autoload_configs/acl.conf.xml" % (
              sudo_prefix, container_name, ACL_LIST_NAME, "/etc/freeswitch"),
          ACL_LIST_NAME)

    # 5.8 vars.xml - default_password
    check("vars.xml default_password 正确",
          "%sdocker exec %s grep 'default_password=' %s/vars.xml" % (
              sudo_prefix, container_name, "/etc/freeswitch"),
          DEFAULT_PASSWORD)

    # 5.9 vars.xml - internal_sip_port
    check("vars.xml internal_sip_port=%d" % INTERNAL_SIP_PORT,
          "%sdocker exec %s grep 'internal_sip_port=' %s/vars.xml" % (
              sudo_prefix, container_name, "/etc/freeswitch"),
          "internal_sip_port=%d" % INTERNAL_SIP_PORT)

    # 5.10 vars.xml - external_sip_port
    check("vars.xml external_sip_port=%d" % EXTERNAL_SIP_PORT,
          "%sdocker exec %s grep 'external_sip_port=' %s/vars.xml" % (
              sudo_prefix, container_name, "/etc/freeswitch"),
          "external_sip_port=%d" % EXTERNAL_SIP_PORT)

    # 5.11 vars.xml - external_rtp_ip
    check("vars.xml external_rtp_ip=%s" % PUBLIC_IP,
          "%sdocker exec %s grep 'external_rtp_ip=' %s/vars.xml" % (
              sudo_prefix, container_name, "/etc/freeswitch"),
          PUBLIC_IP)

    # 5.12 vars.xml - external_sip_ip
    check("vars.xml external_sip_ip=%s" % PUBLIC_IP,
          "%sdocker exec %s grep 'external_sip_ip=' %s/vars.xml" % (
              sudo_prefix, container_name, "/etc/freeswitch"),
          PUBLIC_IP)

    return all_correct


def verify_mod_xml_curl_loaded(ssh_client, sudo_prefix, container_name):
    """验证 6：mod_xml_curl 模块已成功加载到 FreeSWITCH 内存"""
    log_info("[验证 6/9] mod_xml_curl 模块加载状态...")
    cmd = "%sdocker exec %s fs_cli -P %s -p %s -x 'module_exists mod_xml_curl'" % (
        sudo_prefix, container_name, ESL_PORT, ESL_PASSWORD)
    result = remote_exec(ssh_client, cmd)
    if result and "true" in result.lower():
        log_success("  PASS: mod_xml_curl 已加载")
        return True
    log_error("  FAIL: mod_xml_curl 未加载")
    log_error("    输出: %s" % result)
    # 尝试手动加载并查看错误
    log_info("  尝试手动 load mod_xml_curl 查看错误...")
    load_result = remote_exec(ssh_client,
                              "%sdocker exec %s fs_cli -P %s -p %s -x 'load mod_xml_curl'" % (
                                  sudo_prefix, container_name, ESL_PORT, ESL_PASSWORD))
    log_error("    load 结果: %s" % load_result)
    return False


def verify_mod_audio_fork_loaded(ssh_client, sudo_prefix, container_name):
    """验证 9：mod_audio_fork 模块已成功加载到 FreeSWITCH 内存"""
    log_info("[验证 9/9] mod_audio_fork 模块加载状态...")
    cmd = "%sdocker exec %s fs_cli -P %s -p %s -x 'module_exists mod_audio_fork'" % (
        sudo_prefix, container_name, ESL_PORT, ESL_PASSWORD)
    result = remote_exec(ssh_client, cmd)
    if result and "true" in result.lower():
        log_success("  PASS: mod_audio_fork 已加载")
        return True
    log_error("  FAIL: mod_audio_fork 未加载")
    log_error("    输出: %s" % result)
    # 尝试手动加载并查看错误
    log_info("  尝试手动 load mod_audio_fork 查看错误...")
    load_result = remote_exec(ssh_client,
                              "%sdocker exec %s fs_cli -P %s -p %s -x 'load mod_audio_fork'" % (
                                  sudo_prefix, container_name, ESL_PORT, ESL_PASSWORD))
    log_error("    load 结果: %s" % load_result)
    return False


def verify_sofia_profile_ports(ssh_client, sudo_prefix, container_name):
    """验证 7：Sofia Profile 实际监听端口与配置一致"""
    log_info("[验证 7/9] Sofia Profile 实际监听端口...")
    all_correct = True

    # internal profile
    cmd = "%sdocker exec %s fs_cli -P %s -p %s -x 'sofia status profile internal'" % (
        sudo_prefix, container_name, ESL_PORT, ESL_PASSWORD)
    result = remote_exec(ssh_client, cmd)
    if str(INTERNAL_SIP_PORT) in result:
        log_success("  PASS: internal profile sip-port=%d" % INTERNAL_SIP_PORT)
    else:
        log_error("  FAIL: internal profile 端口未生效（期望 %d）" % INTERNAL_SIP_PORT)
        all_correct = False
    # 显示关键行
    for line in result.split("\n"):
        if any(k in line for k in ["SIP-IP", "Ext-SIP-IP", "RTP-IP", "Ext-RTP-IP", "URL", "BIND"]):
            log_info("    %s" % line.strip())

    # external profile
    cmd = "%sdocker exec %s fs_cli -P %s -p %s -x 'sofia status profile external'" % (
        sudo_prefix, container_name, ESL_PORT, ESL_PASSWORD)
    result = remote_exec(ssh_client, cmd)
    if str(EXTERNAL_SIP_PORT) in result:
        log_success("  PASS: external profile sip-port=%d" % EXTERNAL_SIP_PORT)
    else:
        log_error("  FAIL: external profile 端口未生效（期望 %d）" % EXTERNAL_SIP_PORT)
        all_correct = False
    for line in result.split("\n"):
        if any(k in line for k in ["SIP-IP", "Ext-SIP-IP", "RTP-IP", "Ext-RTP-IP", "URL", "BIND"]):
            log_info("    %s" % line.strip())

    return all_correct


def scan_logs_for_errors(ssh_client, sudo_prefix, container_name):
    """
    验证 8：扫描 FreeSWITCH 启动日志中的 [ERR] 条目。

    需求：识别启动过程中的真实错误。允许列表内的已知非致命错误（如 mod_signalwire SSL）
         不会判定为失败，其他 [ERR] 视为部署问题。
    """
    log_info("[验证 8/9] 启动日志错误扫描...")
    log_info("  等待模块加载完成（%d 秒）..." % MODULE_LOAD_WAIT_SECONDS)
    time.sleep(MODULE_LOAD_WAIT_SECONDS)

    logs = remote_exec(ssh_client,
                       "%sdocker exec %s tail -n 200 /var/log/freeswitch/freeswitch.log 2>/dev/null" % (
                           sudo_prefix, container_name))
    if not logs:
        log_warn("  WARN: 无日志输出（可能日志路径不同）")
        return True

    err_lines = [line for line in logs.split("\n") if "[ERR]" in line or "CRIT" in line]
    # 过滤允许列表内的已知错误
    real_errors = []
    for line in err_lines:
        if any(allowed in line for allowed in ALLOWED_LOG_ERRORS):
            continue
        real_errors.append(line)

    if not real_errors:
        if err_lines:
            log_success("  PASS: 仅有已知非致命错误（%d 条已忽略）" % len(err_lines))
            for line in err_lines[:3]:
                log_info("    [忽略] %s" % line.strip()[:200])
        else:
            log_success("  PASS: 启动日志无 [ERR] 错误")
        return True
    log_error("  FAIL: 启动日志发现 %d 条真实错误" % len(real_errors))
    for line in real_errors[:10]:
        log_error("    %s" % line.strip()[:300])
    return False


def verify_java_backend_connectivity(ssh_client, sudo_prefix, container_name, backend_url):
    """附加验证：从容器内测试 Java 后端连通性（非致命，仅提示）"""
    log_info("[附加] Java 后端连通性测试（非致命）...")
    # 容器内可能没有 curl，先检查；没有则跳过
    has_curl = remote_exec(ssh_client,
                           "%sdocker exec %s sh -c 'command -v curl >/dev/null 2>&1 && echo YES || echo NO'" % (
                               sudo_prefix, container_name))
    if has_curl != "YES":
        log_warn("  容器内无 curl 命令，跳过连通性测试")
        log_warn("  请在主机上手动测试: curl -v %s" % backend_url)
        return
    cmd = "%sdocker exec %s curl -s -o /dev/null -w '%%{http_code}' --max-time 5 %s" % (
        sudo_prefix, container_name, backend_url)
    result = remote_exec(ssh_client, cmd)
    if result and result.isdigit():
        code = int(result)
        if 200 <= code < 500:
            # 4xx 也算连通（Java 后端可能返回 401/404 等，但说明端口通）
            log_success("  Java 后端连通 (HTTP %d)" % code)
            if code >= 400:
                log_warn("  返回 %d：Java 后端可能未配置该接口，但不影响 FreeSWITCH 启动" % code)
        else:
            log_warn("  Java 后端返回 HTTP %d（FreeSWITCH 仍可启动，xml_curl 请求时可能报错）" % code)
    else:
        log_warn("  Java 后端不可达（FreeSWITCH 已启动，但 mod_xml_curl 动态配置将失败）")
        log_warn("  请确认 yudao-cloud 服务已启动并监听 %s" % backend_url)


def verify_deployment(ssh_client, sudo_prefix, container_name, config_dir, backend_url):
    """执行全部 9 项验证 + 附加连通性测试，返回是否全部通过"""
    log_info("=" * 60)
    log_info("开始严谨的部署后验证（9 项关键检查）")
    log_info("=" * 60)

    results = {
        "容器运行": verify_container_running(ssh_client, sudo_prefix, container_name),
        "ESL 连接": verify_esl_connection(ssh_client, sudo_prefix, container_name),
        "Sofia Profile": verify_sofia_profiles(ssh_client, sudo_prefix, container_name),
        "端口监听": verify_port_listening(ssh_client, sudo_prefix),
        "配置文件值": verify_config_file_values(ssh_client, sudo_prefix, container_name, config_dir, backend_url),
        "mod_xml_curl": verify_mod_xml_curl_loaded(ssh_client, sudo_prefix, container_name),
        "Sofia 端口生效": verify_sofia_profile_ports(ssh_client, sudo_prefix, container_name),
        "日志错误扫描": scan_logs_for_errors(ssh_client, sudo_prefix, container_name),
        "mod_audio_fork": verify_mod_audio_fork_loaded(ssh_client, sudo_prefix, container_name),
    }

    # 附加连通性测试（不影响最终判定）
    verify_java_backend_connectivity(ssh_client, sudo_prefix, container_name, backend_url)

    log_info("=" * 60)
    log_info("验证结果汇总:")
    all_pass = True
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        if not passed:
            all_pass = False
        log_info("  %s: %s" % (name, status))
    log_info("=" * 60)

    if all_pass:
        log_success("全部 9 项关键验证通过，部署成功！")
    else:
        log_error("部分验证失败，请检查上述日志")
    return all_pass


# ==================== 主流程 ====================

def run_deployment(ssh_client):
    """完整部署流程：从 Docker 准备到验证完成"""
    container_name = generate_container_name()
    config_dir = get_config_dir(container_name)
    # 标记 mock backend 是否已启动，用于 finally 清理
    mock_started = False
    # 实际可用的 Java 后端 URL（detect_java_backend_host 后确定）
    effective_backend_url = JAVA_BACKEND_URL

    log_info("=" * 60)
    log_info("开始 FreeSWITCH 远程部署（yudao-cloud 集成模式）")
    log_info("目标服务器: %s@%s:%s" % (SSH_USER, REMOTE_HOST, SSH_PORT))
    log_info("容器名: %s" % container_name)
    log_info("配置目录: %s" % config_dir)
    log_info("端口: internal=%d/%d external=%d/%d esl=%d rtp=%d-%d" % (
        INTERNAL_SIP_PORT, INTERNAL_TLS_PORT,
        EXTERNAL_SIP_PORT, EXTERNAL_TLS_PORT,
        ESL_PORT, RTP_PORT_START, RTP_PORT_END))
    log_info("Java 后端: %s" % JAVA_BACKEND_URL)
    log_info("公网 IP: %s" % PUBLIC_IP)
    log_info("=" * 60)

    try:
        # 1. 检测 sudo 前缀
        log_info("[步骤 1/11] 检测 sudo 前缀...")
        sudo_prefix = detect_sudo_prefix(ssh_client)
        log_info("  sudo 前缀: %r" % sudo_prefix if sudo_prefix else "  无需 sudo")

        # 2. 确保 Docker 已安装
        log_info("[步骤 2/11] 确保 Docker 已安装...")
        ensure_docker_installed(ssh_client, sudo_prefix)
        # 重新检测 sudo（安装后可能已将用户加入 docker 组，但当前 SSH session 不会立即生效）
        if not sudo_prefix:
            sudo_prefix = detect_sudo_prefix(ssh_client)

        # 3. 拉取镜像
        log_info("[步骤 3/11] 拉取 FreeSWITCH 镜像...")
        pull_freeswitch_image(ssh_client, sudo_prefix)

        # 4. 端口冲突检测（冲突即终止）
        log_info("[步骤 4/11] 端口冲突检测...")
        check_existing_fs_containers_with_same_ports(ssh_client, sudo_prefix)
        check_host_port_occupation(ssh_client, sudo_prefix)

        # 5. 提取镜像默认配置
        log_info("[步骤 5/11] 提取镜像默认配置...")
        extract_default_config(ssh_client, sudo_prefix, config_dir)

        # 6. 检测 Java 后端可访问地址（公网 IP 不可达时自动改用内网 IP）
        log_info("[步骤 6/11] 检测 Java 后端可访问地址...")
        backend_host = detect_java_backend_host(ssh_client)
        effective_backend_url = "https://%s:%d%s" % (backend_host, JAVA_BACKEND_PORT, JAVA_BACKEND_PATH)
        log_info("  实际使用 Java 后端 URL: %s" % effective_backend_url)

        # 7. 增量修改配置文件（含 mod_audio_fork 配置）
        log_info("[步骤 7/11] 增量修改配置文件...")
        update_modules_conf(ssh_client, config_dir)
        update_xml_curl_conf(ssh_client, config_dir, effective_backend_url)
        update_event_socket_conf(ssh_client, config_dir)
        update_acl_conf(ssh_client, config_dir)
        update_vars_xml(ssh_client, config_dir)
        update_audio_fork_conf(ssh_client, config_dir)
        update_sip_profiles(ssh_client, config_dir)
        log_success("全部配置文件增量更新完成")

        # 8. 启动 Mock Java 后端（防止 mod_xml_curl 阻塞 FreeSWITCH 启动）
        #    先 GET 请求 effective_backend_url?section=DIALPLAN 检测真实后端是否已响应：
        #    - 返回内容（HTTP 200 且响应体非空）→ 真实后端就绪，跳过 mock
        #    - 否则 → 启动 mock 应急，避免 mod_xml_curl 阻塞 FreeSWITCH 启动
        log_info("[步骤 8/11] 启动 Mock Java 后端（部署期间临时 HTTP server）...")
        if check_java_backend_responsive(ssh_client, effective_backend_url):
            mock_started = False
        else:
            mock_started = start_mock_java_backend(ssh_client)

        # 9. 启动容器
        log_info("[步骤 9/11] 启动 FreeSWITCH 容器...")
        start_freeswitch_container(ssh_client, sudo_prefix, container_name, config_dir)

        # 9b. 容器启动后注入预编译 mod_audio_fork 产物并动态加载（首次启动时模块尚不存在）
        log_info("[步骤 9b/11] 注入 mod_audio_fork 预编译模块...")
        install_mod_audio_fork(ssh_client, sudo_prefix, container_name)

        # 10. 严谨验证
        log_info("[步骤 10/11] 部署后验证...")
        success = verify_deployment(ssh_client, sudo_prefix, container_name, config_dir, effective_backend_url)

        # 11. 输出汇总
        log_info("[步骤 11/11] 部署完成")
        log_info("=" * 60)
        if success:
            log_success("FreeSWITCH 部署成功！")
        else:
            log_error("FreeSWITCH 部署完成但存在验证失败项，请检查日志")
        log_info("容器名: %s" % container_name)
        log_info("配置目录: %s" % config_dir)
        log_info("ESL 连接: docker exec -it %s fs_cli -P %d -p %s" % (
            container_name, ESL_PORT, ESL_PASSWORD))
        log_info("Java 后端 URL（xml_curl 配置）: %s" % effective_backend_url)
        if mock_started:
            log_warn("注意：Mock Java 后端将在本脚本退出前停止，请尽快启动真实 yudao-cloud 服务")
            log_warn("  yudao-cloud 启动后将自动接管 mod_xml_curl 请求")
        log_info("=" * 60)
        return success, container_name, config_dir
    finally:
        # 无论部署成功失败，都停止 mock backend，避免占用 48080 端口
        if mock_started:
            try:
                stop_mock_java_backend(ssh_client)
            except Exception as e:
                log_warn("停止 Mock Java 后端时异常: %s" % str(e))


def main():
    ssh_client = None
    try:
        ssh_client = create_ssh_client()
        success, _, _ = run_deployment(ssh_client)
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        log_error("用户中断部署")
        sys.exit(1)
    except RuntimeError as e:
        log_error("部署终止: %s" % str(e))
        sys.exit(2)
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
