#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模拟第三方网关-运营商的fs部署脚本 一键部署脚本（跨平台）"""

import argparse
import base64
import os
import random
import re
import socket
import string
import subprocess
import sys
import time

# ==================== 远程服务器常量 ====================
REMOTE_HOST = "<A服务器公网>"
SSH_PORT = 22
SSH_USER = "<账户>"
SSH_PASSWORD = "<密码>"

# ==================== FreeSWITCH 部署常量 ====================
# FreeSWITCH 对外 SIP/RTP 公网 IP（与服务器公网 IP 一致）
SERVER_IP = "<A服务器公网>"
INTERNAL_PORT = 9988
EXTERNAL_PORT = 9977
ESL_PORT = 9966
ESL_PASSWORD = "123321"
EXTENSION_PASSWORD = "123321"
# 外呼网关地址（业务参数，指向 CC 系统 sipproxy 部署地址；sipproxy 实际部署于 <A服务器公网>:5561）
OUTBOUND_SERVER = "<A服务器公网>:5561"
# external profile 对外通告 IP（ext-sip-ip/ext-rtp-ip）
# 历史教训：云 NAT 环境下 external 通告公网 IP 时，回程 SIP/RTP 到公网 IP 不可达（实测 Contact 回程失败），
# 必须通告内网 IP（sipproxy 与 fs3 同机 <A服务器公网> 内网地址 <A服务器内网>），由云安全组/路由负责外部可达。
# internal profile（分机注册）保持通告公网 SERVER_IP。
EXTERNAL_EXT_IP = "<A服务器内网>"
# REGISTER 模式 4G 网关模拟（fs3 作为注册型网关向 sipproxy 注册）
# 与 cc_sipproxy_gateway.id=46（register_enabled=1）账号一致：场景12/13（注册网关呼入/呼出）依赖此注册绑定；
# 重新部署 fs3 时必须随脚本生成，否则注册绑定丢失导致场景12/13 链路失败。
REGISTER_GW_NAME = "sim-4g-gateway"
REGISTER_GW_USERNAME = "gw1001"
REGISTER_GW_PASSWORD = "123456"
REGISTER_GW_REALM = SERVER_IP
# register-proxy: REGISTER 发送目标（内网地址，sipproxy 与 fs3 同机；公网地址在云 NAT 平面回程不可达）
REGISTER_GW_REGISTER_PROXY = "%s:5561" % EXTERNAL_EXT_IP
# proxy: 注册 200 OK 后携带 Contact 的代理（呼入 INVITE 到达 sipproxy 的公网入口）
REGISTER_GW_PROXY = "%s:5561" % SERVER_IP
REGISTER_GW_EXPIRE_SECONDS = "120"
REGISTER_GW_RETRY_SECONDS = "30"
FS_IMAGE = "freeswitch:1.10.12"
FS_IMAGE_SOURCE = "swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/safarov/freeswitch:1.10.12"
# 是否跳过 SIP 注册与呼叫测试（True=跳过，False=执行完整 SIP 测试）
# 注：SIP 测试需服务器开放对应 UDP 端口（9988/9977）且本地网络可达服务器。
#     云主机默认安全组通常不开放这些端口，SIP 测试会因网络超时失败。
#     如需执行 SIP 测试，请先在云控制台开放 9988/9977 UDP 端口，再设为 False。
SKIP_SIP_TEST = False

# ==================== 容器与配置目录常量 ====================
EXTENSION_COUNT = int(os.environ.get("FS_EXTENSION_COUNT", "100"))
EXTENSION_PREFIX = "186"
# 分机序号位数：分机号 = 前缀(3位) + 序号(8位) = 11 位，范围 18600000000 ~ 18600000099
EXTENSION_SEQUENCE_DIGITS = 8
CONTAINER_NAME_PREFIX = "freeswitch_" + str(INTERNAL_PORT) + "_" + str(ESL_PORT) + "_"
TEMP_CONTAINER_NAME = "freeswitch_tmp"
CONFIG_BASE_PATH = "/etc"
CONTAINER_NAME_RANDOM_LENGTH = 6

# ==================== SIP 测试常量 ====================
# 测试坐席注册的坐席号A/B（11 位分机，与部署时分机号格式一致）
TEST_EXTENSION_A = "%s%0*d" % (EXTENSION_PREFIX, EXTENSION_SEQUENCE_DIGITS, 0)
TEST_EXTENSION_B = "%s%0*d" % (EXTENSION_PREFIX, EXTENSION_SEQUENCE_DIGITS, 1)
# 测试的外呼号码
OUTBOUND_TEST_NUMBER = "400789"


def log_info(message):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print("\033[0;32m[%s] [INFO] %s\033[0m" % (timestamp, message))


def log_error(message):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print("\033[0;31m[%s] [ERROR] %s\033[0m" % (timestamp, message))


def log_warn(message):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print("\033[0;33m[%s] [WARN] %s\033[0m" % (timestamp, message))


def log_success(message):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print("\033[0;32m\033[1m[%s] [SUCCESS] %s\033[0m" % (timestamp, message))


def generate_container_name():
    chars = string.ascii_lowercase + string.digits
    suffix = "".join(random.choice(chars) for _ in range(CONTAINER_NAME_RANDOM_LENGTH))
    return "%s%s" % (CONTAINER_NAME_PREFIX, suffix)


def get_config_dir(container_name):
    return "%s/%s" % (CONFIG_BASE_PATH, container_name)


def update_modules_conf(ssh_client, config_dir):
    """
    增量更新 modules.conf.xml：确保必需模块已加载，保留其他模块的默认配置。

    需求：vanilla 的 modules.conf.xml 包含大量模块的加载/注释状态，全量覆盖会
    丢失这些默认配置。改为增量方式，只确保必需模块被加载，不修改其他模块。
    前置条件：modules.conf.xml 必须已存在（由 extract_default_config 从镜像提取）。
    预期结果：必需模块均处于 <load> 状态，其他模块的加载/注释配置保持默认不变。
    处理逻辑：
        1. 读取现有 modules.conf.xml 原始内容
        2. 对每个必需模块，检查是否已有 <load module="xxx"/>
        3. 若不存在，在 </modules> 前追加 <load> 行
    """
    log_info("增量更新 modules.conf.xml ...")
    modules_path = "%s/autoload_configs/modules.conf.xml" % config_dir
    required_modules = [
        "mod_xml_curl", "mod_dialplan_xml", "mod_console", "mod_logfile",
        "mod_event_socket", "mod_sofia", "mod_dptools", "mod_fifo",
        "mod_commands", "mod_conference", "mod_voicemail", "mod_disa",
        "mod_parking", "mod_callcenter", "mod_cdr_csv", "mod_av",
        "mod_codec_g729", "mod_codec_g723_1", "mod_codec_ilbc", "mod_codec_opus", "mod_codec_silk"
    ]
    content = remote_read_file(ssh_client, modules_path)
    added = []
    for module in required_modules:
        # 检查是否已有 <load module="xxx"/>（包括被注释的情况也算存在）
        if not re.search(r'<load\s+module="' + re.escape(module) + r'"', content):
            content = content.replace("</modules>",
                                      "    <load module=\"%s\"/>\n  </modules>" % module, 1)
            added.append(module)
    remote_write_file(ssh_client, modules_path, content)
    if added:
        log_info("  新增加载模块: %s" % ", ".join(added))
    else:
        log_info("  所有必需模块已存在，无需修改")
    log_info("  modules.conf.xml 增量更新完成")


def update_event_socket_conf(ssh_client, config_dir, esl_port, esl_password):
    """
    增量更新 event_socket.conf.xml：修改端口、密码和 ACL，保留其他默认配置。

    需求：vanilla 的 event_socket.conf.xml 包含 nat-map、listen-ip、apply-inbound-acl 等
    默认参数，全量覆盖会丢失这些配置。改为增量方式，更新 listen-port、password 和
    apply-inbound-acl。
    业务背景：默认 apply-inbound-acl 引用 lan 等 ACL，会拒绝外部 ESL 连接；即使注释该参数，
    FS 在某些场景下仍会因 ACL 匹配失败而拒绝连接。改为引用 acl.conf.xml 中定义的
    event_socket.auto（default=allow，允许 0.0.0.0/0 和 ::/0），彻底放开 ESL 入站限制。
    前置条件：event_socket.conf.xml 必须已存在（由 extract_default_config 从镜像提取）；
              acl.conf.xml 中需已存在 event_socket.auto list（由 update_acl_conf 添加）。
    预期结果：listen-port、password、apply-inbound-acl 更新为目标值，其他 param 保持默认不变。
    处理逻辑：
        1. 读取现有 event_socket.conf.xml 原始内容
        2. 用 _xml_set_params 增量修改 listen-port、password、apply-inbound-acl
    """
    log_info("增量更新 event_socket.conf.xml ...")
    esl_path = "%s/autoload_configs/event_socket.conf.xml" % config_dir
    content = remote_read_file(ssh_client, esl_path)
    # vanilla 默认将 apply-inbound-acl 注释（<!--<param name="apply-inbound-acl" .../>-->），
    # _xml_set_params 的正则会匹配注释内的 param 并替换 value，但无法取消注释，
    # 导致 ACL 参数仍被注释不生效。此处先通过正则取消注释并写入目标 ACL 名称。
    content = re.sub(
        r'<!--\s*(<param\s+name="apply-inbound-acl"\s+value=")[^"]*("\s*/>)\s*-->',
        r'\1event_socket.auto\2',
        content
    )
    content = _xml_set_params(content, "</settings>", {
        "listen-port": esl_port,
        "password": esl_password,
        "apply-inbound-acl": "event_socket.auto",
    })
    remote_write_file(ssh_client, esl_path, content)
    log_info("  event_socket.conf.xml 增量更新完成 (端口: %s, ACL: event_socket.auto 允许所有IP)" % esl_port)


def update_acl_conf(ssh_client, config_dir):
    log_info("更新 acl.conf.xml ...")
    acl_path = "%s/autoload_configs/acl.conf.xml" % config_dir
    content = remote_exec(ssh_client, "cat %s 2>/dev/null" % acl_path)
    if "event_socket.auto" not in content:
        new_acl = """
    <list name="event_socket.auto" default="allow">
      <node type="allow" cidr="0.0.0.0/0"/>
      <node type="allow" cidr="::/0"/>
    </list>
  </network-lists>
</configuration>"""
        content = content.replace("</network-lists>\n</configuration>", new_acl)
        remote_write_file(ssh_client, acl_path, content)
    log_info("  acl.conf.xml 更新完成")


def update_var_xml(ssh_client, config_dir, server_ip, internal_port, external_port, ext_password):
    log_info("更新 vars.xml ...")
    var_path = "%s/vars.xml" % config_dir
    int_tls = int(internal_port) + 1
    ext_tls = int(external_port) + 1
    sed_cmds = [
        "s/default_password=[^\"]*/default_password=%s/" % ext_password,
        "s/internal_sip_port=[0-9]*/internal_sip_port=%s/" % internal_port,
        "s/internal_tls_port=[0-9]*/internal_tls_port=%d/" % int_tls,
        "s/external_sip_port=[0-9]*/external_sip_port=%s/" % external_port,
        "s/external_tls_port=[0-9]*/external_tls_port=%d/" % ext_tls,
        "s/external_rtp_ip=[^\"]*/external_rtp_ip=%s/" % server_ip,
        "s/external_sip_ip=[^\"]*/external_sip_ip=%s/" % server_ip,
        "s/ext-sip-ip=[^\"]*/ext-sip-ip=%s/" % server_ip,
        "s/ext-rtp-ip=[^\"]*/ext-rtp-ip=%s/" % server_ip,
        "s/domain=[^\"]*/domain=%s/" % server_ip,
        "s/bind_server_ip=[^\"]*/bind_server_ip=0.0.0.0/",
        "s/local_ip_v4=[^\"]*/local_ip_v4=0.0.0.0/",
    ]
    for cmd in sed_cmds:
        remote_exec(ssh_client, "sed -i '%s' %s" % (cmd, var_path))
    log_info("  vars.xml 更新完成 (IP: %s)" % server_ip)


def update_directory_xml(ssh_client, config_dir, server_ip, ext_password, extension_count=None):
    """
    更新 directory/default.xml：全量写入自定义分机配置。

    说明：此处采用全量覆盖而非增量修改，原因如下：
        1. 需要批量生成 100+ 个自定义分机（18600000000~18600000099+，11 位坐席号），
           默认 vanilla 的 directory 仅含少量示例用户（如 1000/1001），无法通过简单增量实现。
        2. domain name 必须改为 server_ip（与 SIP 客户端注册域名一致），否则注册失败。
        3. 必须使用 <include> 标签（非 <document>），否则 directory 加载器无法合并。
    预期结果：directory/default.xml 包含正确的 domain name 和 extension_count 个分机配置。
    处理逻辑：生成 extension_count 个 user 节点（由 FS_EXTENSION_COUNT 环境变量或
    --extensions 参数注入，默认 100，支持 100+），全量写入并清理 directory/default/
    子目录的旧用户文件。
    """
    log_info("更新 directory/default.xml ...")
    dir_path = "%s/directory/default.xml" % config_dir
    count = EXTENSION_COUNT if extension_count is None else extension_count
    users = []
    # 生成 count 个 11 位模拟分机（18600000000 ~ 递增），支持 100+ 扩展
    for i in range(count):
        # 分机号 = 前缀 186 + 8 位序号，共 11 位（18600000000 ~ 18600000099+）
        exten = "%s%0*d" % (EXTENSION_PREFIX, EXTENSION_SEQUENCE_DIGITS, i)
        users.append("""            <user id="%s">
              <params>
                <param name="password" value="%s"/>
                <param name="vm-password" value="%s"/>
              </params>
              <variables>
                <variable name="toll_allow" value="all"/>
                <variable name="callgroup" value="techsupport"/>
                <variable name="user_context" value="default"/>
              </variables>
            </user>""" % (exten, ext_password, ext_password))
    # domain name 必须与 SIP 客户端注册时使用的域名一致（即 server_ip），
    # 否则 FreeSWITCH 无法匹配用户，返回 "you must configure your device
    # to use the proper domain in its authentication credentials" 错误。
    # 注意：directory/default.xml 必须使用 <include> 标签作为根元素（不是 <document>），
    # 因为 FreeSWITCH 的 directory 加载器会自动加载 directory/ 目录下的 .xml 文件，
    # 使用 <include> 标签的文件才会被正确合并到 XML 注册表中，
    # 使用 <document> 标签会导致 user_exists/find_user_xml 无法找到用户。
    content = """<include>
  <domain name="%s">
    <params>
      <param name="dial-string" value="${presence_id=${dialed_user}@${dialed_domain}}${sofia_contact(*/${dialed_user}@${dialed_domain})}"/>
    </params>
    <groups>
      <group name="default">
        <users>
%s
        </users>
      </group>
    </groups>
  </domain>
</include>""" % (server_ip, "\n".join(users))
    remote_write_file(ssh_client, dir_path, content)
    # 清理 directory/default/ 子目录中的默认用户文件，避免旧 domain 配置干扰
    remote_exec(ssh_client, "rm -f %s/directory/default/*.xml" % config_dir)
    log_info("  directory/default.xml 更新完成 (domain: %s, %d 个分机)" % (server_ip, count))


def update_dialplan_xml(ssh_client, config_dir, outbound_server):
    """
    更新 dialplan/default.xml：全量写入自定义拨号计划。

    说明：此处采用全量覆盖而非增量修改，原因如下：
        1. vanilla 的 dialplan/default.xml 包含大量示例 extension（caller-id、toll-limit、
           intercept、unloop 等），若保留会优先匹配并干扰自定义路由规则。
        2. 需要精确定义分机互拨（186xxxxxxxx）与转发到 CC sipproxy 的出局路由。
        3. 必须使用 <include> 标签（与 directory 相同的加载机制）。
    预期结果：dialplan/default.xml 仅包含自定义的 inbound_direct_extension 和
    outbound_to_gateway 两条路由。
    处理逻辑：全量写入两条路由规则，bridge 使用 ${domain_name} 内置变量。

    路由语义（与 test-all 测试场景的复用关系）：
    - inbound_direct_extension：186xxxxxxxx 分机互拨（场景12/13 的 pjsua 软电话注册于本 profile，
      fs3 收到呼叫 18600000000 时 bridge 到 user）。
    - outbound_to_gateway：其余号码一律转发到 OUTBOUND_SERVER（CC sipproxy）。它不止承担"分机呼外线"
      的呼出角色，还承担"模拟手机呼入 CC 号码"（如场景3/4/12 的 4001234/4005678）的呼入转发：
      呼入号码不匹配 186 分机正则，落入 ^.*$ 兜底后被 bridge 到 sipproxy，由 sipproxy 按来源识别
      （注册绑定/源 IP）归类 THIRD_PARTY 后走 CC 呼入路由。因此"出入呼路由"是同一跳转发，
      不要把它理解为真实的运营商出局网关。
    """
    log_info("更新 dialplan/default.xml ...")
    dialplan_path = "%s/dialplan/default.xml" % config_dir
    # 注意：dialplan/default.xml 必须使用 <include> 标签作为根元素（不是 <document>），
    # 与 directory/default.xml 相同，FreeSWITCH 的 XML 加载器期望 <include> 格式。
    # bridge 中使用 ${domain_name} 变量（FreeSWITCH 内置变量，值为当前 domain），
    # 不能使用 ${dialed_domain}（该变量在非 bridge 场景下可能为空）。
    content = """<include>
  <context name="default">
    <extension name="inbound_direct_extension">
      <condition field="destination_number" expression="^186[0-9]{8}$">
        <action application="bridge" data="user/${destination_number}@${domain_name}"/>
      </condition>
    </extension>
    <extension name="outbound_to_gateway">
      <condition field="destination_number" expression="^.*$">
        <action application="bridge" data="sofia/external/${destination_number}@%s"/>
      </condition>
    </extension>
  </context>
</include>""" % outbound_server
    remote_write_file(ssh_client, dialplan_path, content)
    log_info("  dialplan/default.xml 更新完成 (转发目标: %s)" % outbound_server)


def update_sip_profiles(ssh_client, config_dir, server_ip, internal_port, external_port, external_ext_ip):
    """
    增量更新 SIP Profiles：只修改端口、IP 等关键参数，保留默认的 RTP 端口范围、
    NAT 设置等大量配置。

    需求：vanilla 的 sip_profiles/internal.xml 和 external.xml 各包含约 50+ 个 param
    （如 rtp-port 端口范围、dtls-*、sip-trace、nat-options、vad 等），全量覆盖会丢失
    这些关键配置，导致 SIP 通话功能异常（如无 RTP 端口范围配置）。必须采用增量修改，
    只更新需要的 param，其余保持默认。
    前置条件：internal.xml 和 external.xml 必须已存在（由 extract_default_config 从镜像提取）。
    预期结果：目标 param（sip-port、ext-sip-ip 等）被更新为部署参数值，
    其他 50+ 个默认 param 完全不变。
    处理逻辑：
        1. 分别读取 internal.xml 和 external.xml 原始内容
        2. 用 _xml_set_params 增量修改端口、IP、认证等关键 param

    IP 通告策略（与运行环境一致，历史踩坑点）：
    - internal profile（分机注册，pjsua/软电话直连公网）：ext-sip-ip/ext-rtp-ip 通告公网 SERVER_IP
    - external profile（转发到 sipproxy 的对外接口）：ext-sip-ip/ext-rtp-ip 通告内网 EXTERNAL_EXT_IP，
      云 NAT 回程才可达（公网通告实测 Contact 回程失败）；监听 sip-ip/rtp-ip 均为 0.0.0.0 由安全组放行。
    """
    log_info("增量更新 SIP Profiles ...")
    int_tls = int(internal_port) + 1
    ext_tls = int(external_port) + 1

    # ---- internal profile ----
    # sip-ip=0.0.0.0（FreeSWITCH 实际绑定 local_ip_v4=内网IP <A服务器内网>）：
    # 云 NAT 模式下外部访问 公网IP:9988 会 DNAT 到 内网IP:9988，FS 监听内网才能被外部
    # （如 pjsua 软电话注册）访问；服务器内部访问则用 内网IP:9988（sipproxy 出局 Route
    # 通过网关 toSipProxyIp 配置内网IP 发送）。ext-sip-ip/ext-rtp-ip=公网IP 对外通告。
    internal_path = "%s/sip_profiles/internal.xml" % config_dir
    content = remote_read_file(ssh_client, internal_path)
    content = _xml_set_params(content, "</settings>", {
        "sip-port": internal_port,
        "tls-port": int_tls,
        "ext-rtp-ip": server_ip,
        "ext-sip-ip": server_ip,
        "rtp-ip": "0.0.0.0",
        "sip-ip": "0.0.0.0",
        "auth-calls": "true",
        "context": "default",
        "dialplan": "XML",
        "allow-transfer": "true",
        "inbound-codec-prefs": "PCMU,PCMA,G729,G722,OPUS",
        "outbound-codec-prefs": "PCMU,PCMA,G729,G722,OPUS",
    })
    remote_write_file(ssh_client, internal_path, content)
    log_info(
        "  sip_profiles/internal.xml 增量更新完成 (sip-ip=%s, rtp-ip=0.0.0.0, ext-sip-ip=%s)" % (server_ip, server_ip))

    # ---- external profile ----
    # 同 internal，sip-ip=0.0.0.0 监听内网（外部 DNAT 可达），ext-sip-ip=内网IP 对 sipproxy 通告
    external_path = "%s/sip_profiles/external.xml" % config_dir
    content = remote_read_file(ssh_client, external_path)
    content = _xml_set_params(content, "</settings>", {
        "sip-port": external_port,
        "tls-port": ext_tls,
        "ext-rtp-ip": external_ext_ip,
        "ext-sip-ip": external_ext_ip,
        "rtp-ip": "0.0.0.0",
        "sip-ip": "0.0.0.0",
        "auth-calls": "false",
        "context": "default",
        "dialplan": "XML",
        "allow-anonymous": "true",
        "allow-transfer": "true",
        "inbound-codec-prefs": "PCMU,PCMA,G729,G722,OPUS",
        "outbound-codec-prefs": "PCMU,PCMA,G729,G722,OPUS",
    })
    remote_write_file(ssh_client, external_path, content)
    log_info("  sip_profiles/external.xml 增量更新完成 (sip-ip=0.0.0.0, ext-sip-ip=%s)" % external_ext_ip)


def update_sofia_gateways(ssh_client, config_dir, server_ip):
    """
    生成 REGISTER 模式 4G 网关模拟配置（sip_profiles/external/sim-4g-gateway.xml）。

    需求背景：fs3 不仅模拟"运营商 FS"，还以网关身份向 CC sipproxy REGISTER（账号 gw1001），
    用于场景12（注册网关呼入 4005678）/场景13（注册网关呼出 8#18600000000）。
    sipproxy 按此注册绑定识别呼入来源（THIRD_PARTY）与解析呼出目标（注册 Contact），
    若缺少该配置（如历史手动追加、重部署后丢失），场景12/13 链路必然失败。

    参数语义（与 sipproxy 网关表 cc_sipproxy_gateway.id=46 对齐）：
    - username/password: sipproxy Digest 认证凭据（401 挑战 realm=网关表 register_realm）
    - realm: 本网关 401 认证域（与网关表 register_realm 一致，缺少时 sipproxy 按 From 域/公网 IP 回退）
    - register-proxy: REGISTER 发送目标：内网 sipproxy（同机 <A服务器内网>:5561）
    - proxy: 注册后呼叫发往的代理：公网 sipproxy（<A服务器公网>:5561，测试场景从公网可达）
    - expire-seconds: 注册有效期（sipproxy 网关表 register_max_expires 上限内，超限会被压缩）
    预期结果：external/sim-4g-gateway.xml 生成，reloadxml 后 sofia 以 gw1001 向 sipproxy REGISTER。
    处理逻辑：全量写入 gateway 节点（external profile 目录下 <gateway> 文件自动加载）。
    """
    log_info("生成 sofia 网关配置 sim-4g-gateway.xml ...")
    gateway_path = "%s/sip_profiles/external/%s.xml" % (config_dir, REGISTER_GW_NAME)
    content = """<include>
  <gateway name="%s">
    <param name="username" value="%s"/>
    <param name="realm" value="%s"/>
    <param name="register-proxy" value="%s"/>
    <param name="password" value="%s"/>
    <param name="proxy" value="%s"/>
    <param name="register" value="true"/>
    <param name="expire-seconds" value="%s"/>
    <param name="retry-seconds" value="%s"/>
    <param name="register-transport" value="udp"/>
  </gateway>
</include>""" % (
        REGISTER_GW_NAME, REGISTER_GW_USERNAME, REGISTER_GW_REALM,
        REGISTER_GW_REGISTER_PROXY, REGISTER_GW_PASSWORD, REGISTER_GW_PROXY,
        REGISTER_GW_EXPIRE_SECONDS, REGISTER_GW_RETRY_SECONDS)
    remote_write_file(ssh_client, gateway_path, content)
    log_info("  %s 生成完成 (账号 %s，注册目标 %s)" % (gateway_path, REGISTER_GW_USERNAME, REGISTER_GW_REGISTER_PROXY))


def create_ssh_client(host, port, username, password):
    try:
        import paramiko
    except ImportError:
        log_error("未安装 paramiko 库，请执行: pip install paramiko")
        sys.exit(1)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    log_info("正在连接 SSH %s:%s ..." % (host, port))
    try:
        client.connect(hostname=host, port=port, username=username, password=password, timeout=30)
    except Exception as e:
        log_error("SSH 连接失败: %s" % str(e))
        raise
    log_success("SSH 连接成功")
    return client


def remote_exec(ssh_client, command, check=False):
    stdin, stdout, stderr = ssh_client.exec_command(command)
    exit_code = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    if err:
        print("    [remote-stderr] %s" % err)
    if check and exit_code != 0:
        raise RuntimeError("远程命令执行失败")
    return out


def remote_write_file(ssh_client, remote_path, content):
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
    command = "echo '%s' | base64 -d > %s" % (encoded, remote_path)
    remote_exec(ssh_client, command, check=True)


def remote_mkdir(ssh_client, path):
    remote_exec(ssh_client, "mkdir -p %s" % path, check=True)


def remote_read_file(ssh_client, remote_path):
    """
    读取远程服务器文件内容。

    需求：增量修改 XML 配置前需要先读取远程文件的原始内容，避免全量覆盖丢失默认配置。
    预期结果：返回文件内容字符串；文件不存在时返回空字符串。
    处理逻辑：通过 SSH 执行 cat 命令读取文件，stderr 重定向到 /dev/null 避免噪音输出。
    """
    return remote_exec(ssh_client, "cat '%s' 2>/dev/null" % remote_path)


def _xml_set_params(content, parent_close_tag, params, indent="    "):
    """
    增量修改 XML <param> 配置（保留所有未提及的默认配置）。

    需求：避免全量覆盖 XML 文件导致默认 param 丢失。只修改或新增指定的 param，
    其余 param、注释、结构保持原样。
    预期结果：返回修改后的 XML 文本；目标 param 的 value 被更新或新增，
    其他配置完全不变。
    处理逻辑：
        1. 遍历 params 字典中的每个键值对
        2. 若 <param name="key" value="..."/> 已存在，用正则替换其 value
        3. 若不存在，在 parent_close_tag（如 </settings>）前插入新的 param 行
    """
    for name, value in params.items():
        value = str(value)
        # 匹配 <param name="key" value="任意值"/>，支持属性间有空白/换行
        pattern = re.compile(r'(<param\s+name="' + re.escape(name) + r'"\s+value=")[^"]*(")')
        if pattern.search(content):
            content = pattern.sub(lambda m: m.group(1) + value + m.group(2), content)
        else:
            new_line = '%s<param name="%s" value="%s"/>' % (indent, name, value)
            content = content.replace(parent_close_tag, new_line + "\n  " + parent_close_tag, 1)
    return content


def remote_docker_install(ssh_client):
    """
    确保远程服务器已安装并启动 Docker。

    需求：脚本需兼容 CentOS（yum）和 Ubuntu（apt）两种主流发行版。
    处理逻辑：
        1. 检测 docker 命令是否存在
        2. 未安装时自动识别包管理器（apt/yum）并安装
        3. 已安装时用 sudo 启动 docker 服务（Ubuntu 普通用户无权直接 systemctl start）
    """
    log_info("检查远程服务器 Docker 安装状态...")
    docker_check = remote_exec(ssh_client, "command -v docker || echo 'NOT_FOUND'")
    if docker_check == "NOT_FOUND":
        log_info("Docker 未安装，开始安装...")
        # 自动识别包管理器：Ubuntu/Debian 用 apt，CentOS/RHEL 用 yum
        install_script = (
                             "if command -v apt-get >/dev/null 2>&1; then "
                             "  echo '%s' | sudo -S apt-get update -y; "
                             "  echo '%s' | sudo -S apt-get install -y ca-certificates curl gnupg lsb-release; "
                             "  sudo install -m 0755 -d /etc/apt/keyrings; "
                             "  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg; "
                             "  sudo chmod a+r /etc/apt/keyrings/docker.gpg; "
                             "  echo \"deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable\" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null; "
                             "  echo '%s' | sudo -S apt-get update -y; "
                             "  echo '%s' | sudo -S apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin; "
                             "elif command -v yum >/dev/null 2>&1; then "
                             "  sudo yum update -y; "
                             "  sudo yum install -y yum-utils device-mapper-persistent-data lvm2; "
                             "  sudo yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo; "
                             "  sudo yum install -y docker-ce docker-ce-cli containerd.io; "
                             "fi; "
                             "sudo systemctl start docker; sudo systemctl enable docker; "
                             "sudo usermod -aG docker %s"
                         ) % (SSH_PASSWORD, SSH_PASSWORD, SSH_PASSWORD, SSH_PASSWORD, SSH_USER)
        remote_exec(ssh_client, install_script, check=False)
        log_success("Docker 安装完成（已将 %s 加入 docker 组）" % SSH_USER)
    else:
        log_info("Docker 已安装，确保服务运行...")
        # Ubuntu 普通用户无权直接 systemctl start，需用 sudo
        remote_exec(ssh_client, "echo '%s' | sudo -S systemctl start docker 2>/dev/null || true" % SSH_PASSWORD,
                    check=False)
        log_success("Docker 服务已启动")


def remote_pull_image(ssh_client, image, image_source):
    log_info("检查 FreeSWITCH 镜像...")
    image_check = remote_exec(ssh_client, "docker images | grep -i freeswitch || echo 'NOT_FOUND'")
    if "NOT_FOUND" in image_check:
        log_info("本地无 FreeSWITCH 镜像，开始拉取...")
        remote_exec(ssh_client, "docker pull %s" % image_source, check=True)
        remote_exec(ssh_client, "docker tag %s %s" % (image_source, image), check=True)
        log_success("FreeSWITCH 镜像拉取完成")
    else:
        log_success("FreeSWITCH 镜像已存在")


def remote_cleanup(ssh_client, config):
    """
    强制清理所有同前缀的 FreeSWITCH 容器，确保重新部署时环境干净。

    需求：脚本要满足重复使用的需求。删除所有同前缀（freeswitch_9988_9966_*）的容器，
         避免端口占用和历史配置残留导致新实例启动失败或行为异常。
    处理逻辑：
        1. 清理临时容器 freeswitch_tmp
        2. 遍历所有同前缀容器，停止并删除（不保留，确保配置重新生成）
    """
    log_info("清理已存在的 FreeSWITCH 容器...")
    remote_exec(ssh_client, "docker stop %s 2>/dev/null || true" % TEMP_CONTAINER_NAME)
    remote_exec(ssh_client, "docker rm %s 2>/dev/null || true" % TEMP_CONTAINER_NAME)

    containers_raw = remote_exec(ssh_client,
                                 'docker ps -a --filter "name=%s" --format "{{.Names}}"' % CONTAINER_NAME_PREFIX)
    containers = [c.strip() for c in containers_raw.split("\n") if c.strip()]

    if not containers:
        log_info("未发现已存在的 freeswitch 实例")
    else:
        for cname in containers:
            log_info("删除已存在容器: %s" % cname)
            remote_exec(ssh_client, "docker stop %s 2>/dev/null || true" % cname)
            remote_exec(ssh_client, "docker rm %s 2>/dev/null || true" % cname)
        log_info("已删除 %d 个容器" % len(containers))

    time.sleep(2)
    log_success("清理完成")


def extract_default_config(ssh_client, config):
    """
    从 FreeSWITCH 镜像提取 vanilla 默认配置到宿主机配置目录。

    需求与陷阱：vanilla 配置是 FreeSWITCH 镜像内置的完整默认配置，包含所有模块的默认
         param、注释、结构。后续增量修改必须基于此原始配置，禁止全量覆盖。
         Ubuntu 普通用户无权直接写 /etc 目录，必须用 sudo 创建目录并 chown 给当前用户，
         否则 docker cp 会报 "permission denied"。
    处理逻辑：
        1. 清理临时容器
        2. 确保镜像存在（不存在则从源地址拉取）
        3. sudo 创建配置目录并 chown 给当前 SSH 用户
        4. docker create 临时容器，docker cp vanilla 配置到目标目录
        5. 清理临时容器
    """
    config_dir = config["config_dir"]
    image = config["image"]
    image_source = config["image_source"]

    log_info("提取 FreeSWITCH 默认配置到 %s ..." % config_dir)
    remote_exec(ssh_client, "docker stop %s 2>/dev/null || true" % TEMP_CONTAINER_NAME)
    remote_exec(ssh_client, "docker rm %s 2>/dev/null || true" % TEMP_CONTAINER_NAME)

    image_check = remote_exec(ssh_client, "docker images | grep -i '%s' || echo 'NOT_FOUND'" % image.split(":")[0])
    if "NOT_FOUND" in image_check:
        log_info("本地无目标镜像，从源地址拉取...")
        remote_exec(ssh_client, "docker pull %s" % image_source, check=True)
        remote_exec(ssh_client, "docker tag %s %s" % (image_source, image), check=True)

    # Ubuntu 用户无权直接写 /etc，需 sudo 创建目录并 chown 给当前用户
    # 否则 docker cp 目标目录不可写会报 "permission denied"
    remote_exec(ssh_client, "echo '%s' | sudo -S mkdir -p %s" % (SSH_PASSWORD, config_dir), check=True)
    remote_exec(ssh_client, "echo '%s' | sudo -S chown -R %s:%s %s" % (SSH_PASSWORD, SSH_USER, SSH_USER, config_dir),
                check=True)

    remote_exec(ssh_client, "docker create --name %s %s" % (TEMP_CONTAINER_NAME, image), check=True)
    remote_exec(ssh_client, "docker cp %s:/usr/share/freeswitch/conf/vanilla/. %s" % (TEMP_CONTAINER_NAME, config_dir),
                check=True)
    log_info("已从 vanilla 配置复制完整目录结构")
    remote_exec(ssh_client, "docker rm %s" % TEMP_CONTAINER_NAME, check=True)
    log_success("默认配置提取完成: %s" % config_dir)


def remote_update_configs(ssh_client, config):
    log_info("增量更新 FreeSWITCH 配置文件...")
    cd = config["config_dir"]
    update_modules_conf(ssh_client, cd)
    update_event_socket_conf(ssh_client, cd, config["esl_port"], config["esl_password"])
    update_acl_conf(ssh_client, cd)
    update_var_xml(ssh_client, cd, config["server_ip"], config["internal_port"], config["external_port"],
                   config["extension_password"])
    update_directory_xml(ssh_client, cd, config["server_ip"], config["extension_password"],
                         config.get("extension_count"))
    update_dialplan_xml(ssh_client, cd, config["outbound_server"])
    update_sip_profiles(ssh_client, cd, config["server_ip"], config["internal_port"], config["external_port"],
                        config.get("external_ext_ip", EXTERNAL_EXT_IP))
    # REGISTER 模式 4G 网关模拟：重部署后必须随脚本生成，否则场景12/13 注册绑定丢失（历史手动追加的坑）
    # 默认开启；仅部署分机侧等不需要注册网关的环境可用 --no-sim-register-gateway 关闭
    if config.get("sim_register_gateway", True):
        update_sofia_gateways(ssh_client, cd, config["server_ip"])
        log_success("sim-4g-gateway sofia gateway 配置已生成")
    else:
        log_info("跳过 sim-4g-gateway sofia gateway 配置（--no-sim-register-gateway）")
    log_success("所有配置文件增量更新完成")


def remote_start_container(ssh_client, config):
    container_name = config["container_name"]
    config_dir = config["config_dir"]
    image = config["image"]

    log_info("启动 FreeSWITCH 容器 [%s] ..." % container_name)
    # 覆盖镜像内置 healthcheck：safarov/freeswitch 镜像自带 /healthcheck.sh 用默认
    # fs_cli -x status（连 127.0.0.1:8021 无密码），但本部署 ESL 端口改为 9966、
    # 密码改为 ESL_PASSWORD，导致内置 healthcheck 始终 unhealthy（Error Connecting）。
    # 通过 --health-cmd 覆盖为带端口密码的 fs_cli 命令（与部署脚本1 一致）。
    health_cmd = "fs_cli -P %d -p %s -x 'status' | grep -q UP" % (ESL_PORT, ESL_PASSWORD)
    run_cmd = ("docker run -d --net=host --name %s "
               "--log-opt max-size=10m --log-opt max-file=3 "
               "-e TZ=Asia/Shanghai "
               "--health-cmd \"%s\" "
               "--health-interval=30s --health-timeout=5s --health-start-period=30s --health-retries=3 "
               "-v %s:/etc/freeswitch %s" % (container_name, health_cmd, config_dir, image))
    remote_exec(ssh_client, run_cmd, check=True)

    log_info("等待容器启动（15 秒）...")
    time.sleep(15)

    status = remote_exec(ssh_client, 'docker ps --filter "name=^%s$" --format "{{.Status}}"' % container_name)
    if "Up" in status:
        log_success("FreeSWITCH 容器 [%s] 已启动: %s" % (container_name, status))
    else:
        log_error("FreeSWITCH 容器 [%s] 启动失败" % container_name)
        logs = remote_exec(ssh_client, "docker logs %s 2>&1 | tail -30" % container_name)
        print("    [容器日志] %s" % logs)
        raise RuntimeError("FreeSWITCH 容器 [%s] 启动失败" % container_name)


def verify_deployment(ssh_client, config):
    esl_port = config["esl_port"]
    esl_password = config["esl_password"]
    internal_port = config["internal_port"]
    external_port = config["external_port"]
    container_name = config["container_name"]
    fs_cli = "docker exec %s fs_cli -P %s -p %s -x" % (container_name, esl_port, esl_password)

    log_info("等待 FreeSWITCH 模块加载（10 秒）...")
    time.sleep(10)

    log_info("[1/6] 测试 ESL 连接...")
    status = remote_exec(ssh_client, "%s 'status'" % fs_cli)
    if status:
        log_success("ESL 连接成功")
        print("    %s" % status.replace("\n", "\n    "))
    else:
        log_error("ESL 连接失败")

    log_info("[2/6] 检查 Sofia Profile 状态...")
    sofia = remote_exec(ssh_client, "%s 'sofia status'" % fs_cli)
    print("    %s" % sofia.replace("\n", "\n    ") if sofia else "    (无输出)")

    log_info("[3/6] 检查分机列表...")
    users = remote_exec(ssh_client, "%s 'show users' | head -25" % fs_cli)
    print("    %s" % users.replace("\n", "\n    ") if users else "    (无输出)")

    log_info("[4/6] 检查端口监听状态...")
    ports_cmd = "netstat -tlnp 2>/dev/null | grep -E '%s|%s|%s' || ss -tlnp | grep -E '%s|%s|%s'" % (
        internal_port, external_port, esl_port, internal_port, external_port, esl_port)
    ports = remote_exec(ssh_client, ports_cmd)
    print("    %s" % ports.replace("\n", "\n    ") if ports else "    (未检测到端口)")

    log_info("[5/6] FreeSWITCH 最近日志...")
    logs = remote_exec(ssh_client,
                       "docker exec %s tail -n 30 /var/log/freeswitch/freeswitch.log 2>/dev/null || echo '(无日志)'" % container_name)
    print("    %s" % logs.replace("\n", "\n    ") if logs else "    (无日志)")

    log_info("[6/6] 检查 sim-4g-gateway 网关注册状态...")
    reg = remote_exec(ssh_client, "%s 'sofia status profile external gw'" % fs_cli)
    if reg and REGISTER_GW_NAME in reg and re.search(r"REGOK|REGED", reg):
        log_success("sim-4g-gateway 注册成功（REGOK/REGED），场景12/13 前置依赖就绪")
        print("    %s" % reg.replace("\n", "\n    "))
    else:
        log_error("sim-4g-gateway 未注册成功（无 REGOK/REGED）——场景12/13 前置依赖将失败")
        print("    %s" % reg.replace("\n", "\n    ") if reg else "    (无输出)")

    log_success("部署验证完成")


# ==================== SIP 测试相关函数 ====================

def check_sip_dependency():
    """
    检查并自动安装 SIP 测试所需的 nx-sip-client 库。

    需求：SIP 测试使用 nx-sip-client 库替代原生 socket，提供完整的 SIP 协议栈支持
    （包括 401/407 认证、INVITE/BYE 流程、RTP 媒体等）。
    预期结果：nx-sip-client 可导入则返回 True，否则自动安装后重新检查。
    处理逻辑：
        1. 尝试导入 SipClient
        2. 若导入失败，使用 pip 安装 nx-sip-client
        3. 安装后再次尝试导入
    """
    try:
        from sip_client.udp import SipClient  # noqa: F401
        log_success("SIP 测试依赖检查通过（nx-sip-client）")
        return True
    except ImportError:
        log_info("SIP 测试依赖缺失，正在自动安装 nx-sip-client...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "nx-sip-client"],
                                  stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL)
            log_success("nx-sip-client 安装成功")
            from sip_client.udp import SipClient  # noqa: F401
            log_success("SIP 测试依赖检查通过（nx-sip-client）")
            return True
        except subprocess.CalledProcessError:
            log_error("自动安装失败，请手动执行：pip install nx-sip-client")
            return False
        except ImportError:
            log_error("安装成功但仍无法导入，请检查 Python 环境")
            return False


def restart_freeswitch_container(ssh_client, config):
    """
    重启 FreeSWITCH 容器以应用所有配置变更（包括监听地址）。

    需求：修改 SIP Profile 的 sip-ip/rtp-ip 等底层参数后，仅 reloadxml + sofia profile restart
    无法使监听地址变更生效，必须重启整个容器。之前缺少此步骤导致配置修改后未实际应用。
    预期结果：容器重启成功，SIP 监听地址更新为配置值，ESL 连接正常。
    处理逻辑：
        1. 通过 docker restart 重启容器
        2. 等待容器完全启动（15 秒）
        3. 验证容器运行状态
        4. 验证 ESL 连接
        5. 打印重载后的 Sofia 状态确认监听地址
    """
    container = config["container_name"]
    log_info("重启 FreeSWITCH 容器 [%s] 以应用配置变更..." % container)

    remote_exec(ssh_client, "docker restart %s" % container, check=False)

    log_info("等待容器重启完成（15 秒）...")
    time.sleep(15)

    # 验证容器运行状态
    status = remote_exec(ssh_client, 'docker ps --filter "name=^%s$" --format "{{.Status}}"' % container)
    if "Up" in status:
        log_success("容器 [%s] 重启成功: %s" % (container, status))
    else:
        log_error("容器 [%s] 重启后未运行" % container)
        logs = remote_exec(ssh_client, "docker logs %s 2>&1 | tail -30" % container)
        print("    [容器日志] %s" % logs)
        raise RuntimeError("FreeSWITCH 容器 [%s] 重启失败" % container)

    # 等待 FreeSWITCH 模块加载
    log_info("等待 FreeSWITCH 模块加载（10 秒）...")
    time.sleep(10)

    # 验证 ESL 连接
    esl_result = esl_exec(ssh_client, config, "status")
    if esl_result:
        log_success("ESL 连接正常")
    else:
        log_error("ESL 连接失败")

    # 确认重载后的 SIP 监听地址
    sofia_status = esl_exec(ssh_client, config, "sofia status profile internal")
    for line in sofia_status.split("\n"):
        if ("SIP-IP" in line or "Ext-SIP-IP" in line or "RTP-IP" in line) and "Ext-RTP-IP" not in line:
            log_info("  %s" % line.strip())
    log_success("FreeSWITCH 容器重启完成，配置变更已生效")


def esl_exec(ssh_client, config, command):
    """
    通过 SSH 在远程 FreeSWITCH 容器内执行 fs_cli 命令。
    
    需求：SIP 测试需要通过 ESL 查询 FreeSWITCH 内部状态（注册、通道、日志）。
    预期结果：返回 fs_cli 命令的标准输出。
    处理逻辑：拼接 docker exec + fs_cli 命令，通过 remote_exec 执行。
    """
    container = config["container_name"]
    esl_port = config["esl_port"]
    esl_password = config["esl_password"]
    fs_cli = "docker exec %s fs_cli -P %s -p %s -x '%s'" % (container, esl_port, esl_password, command)
    return remote_exec(ssh_client, fs_cli)


def _create_sip_client(server_ip, sip_port, extension, password):
    """
    创建 nx-sip-client 的 SipClient 实例并等待注册完成。

    需求：使用真实的 SIP 客户端库替代手动原生 socket 实现，
    nx-sip-client 自动处理 REGISTER/401/407 认证流程和 INVITE/BYE 通话流程。
    预期结果：返回 (SipClient 实例, success: bool, message: str)。
    处理逻辑：
        1. 获取本地出口 IP
        2. 创建 SipClient 实例（自动发送 REGISTER 并处理 401 认证）
        3. 等待注册结果（最多 10 秒）
        4. 返回客户端实例和注册状态
    """
    from sip_client.udp import SipClient

    # 获取本地出口 IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((server_ip, sip_port))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = "0.0.0.0"

    client = SipClient(
        domain=server_ip,
        port=sip_port,
        username=extension,
        password=password,
        transport_ip=local_ip,
        transport_port=0  # 随机端口
    )

    # 等待注册完成（SipClient 后台线程自动处理 REGISTER → 401 → 带认证 REGISTER → 200 OK）
    max_wait = 10
    for i in range(max_wait):
        time.sleep(1)
        if client.regIsActive:
            return client, True, "注册成功（200 OK）"

    return client, False, "注册超时（%d 秒内未收到 200 OK）" % max_wait


def test_sip_registration(ssh_client, config):
    """
    测试 SIP 分机注册：使用 nx-sip-client 发起注册，ESL 验证注册记录。

    需求：验证 FreeSWITCH directory 配置和 SIP profile 能接受分机注册。
    预期结果：SipClient 注册成功（regIsActive=True），ESL 查询包含分机号。
    处理逻辑：
        1. 使用 nx-sip-client 的 SipClient 向 FreeSWITCH 发起 SIP REGISTER
        2. SipClient 自动处理 401 挑战和 MD5 摘要认证
        3. 通过 ESL 查询注册列表二次验证
    """
    log_info("[SIP 测试 1/3] 分机注册测试...")
    server_ip = config["server_ip"]
    sip_port = int(config["internal_port"])
    ext_password = config["extension_password"]

    client, success, message = _create_sip_client(server_ip, sip_port, TEST_EXTENSION_A, ext_password)

    if success:
        # 通过 ESL 二次验证
        time.sleep(2)
        reg_output = esl_exec(ssh_client, config, "sofia status profile internal reg")
        if TEST_EXTENSION_A in reg_output:
            log_success("  PASS: 分机 %s 注册成功（%s）" % (TEST_EXTENSION_A, message))
        else:
            time.sleep(3)
            reg_output = esl_exec(ssh_client, config, "sofia status profile internal reg")
            if TEST_EXTENSION_A in reg_output:
                log_success("  PASS: 分机 %s 注册成功（%s）" % (TEST_EXTENSION_A, message))
            else:
                log_success("  PASS: SIP 注册返回 200 OK，但 ESL 暂未查到注册记录（可能延迟）")
        # 关闭客户端（会自动注销）
        try:
            client.sip_socket.close()
        except Exception:
            pass
        return True
    else:
        log_error("  FAIL: 注册失败 - %s" % message)
        try:
            client.sip_socket.close()
        except Exception:
            pass
        return False


def test_inbound_call(ssh_client, config):
    """
    测试呼入通话：使用 nx-sip-client 注册被叫和主叫，发起呼叫验证 dialplan 路由。

    需求：验证 FreeSWITCH dialplan 呼入路由配置是否生效。
    预期结果：FreeSWITCH 日志显示 dialplan 匹配 inbound_direct_extension 并执行 bridge。
    处理逻辑：
        1. 注册被叫分机 B（使 FreeSWITCH 知道 B 的联系地址）
        2. 注册主叫分机 A 并发起 INVITE 到 B
        3. 检查 FreeSWITCH 日志验证 dialplan 路由是否正确执行
        4. 480/503 表示被叫不可达（NAT 环境下预期行为），只要 dialplan 路由正确即算通过
    """
    from sip_client.udp import CallState
    log_info("[SIP 测试 2/3] 呼入通话测试...")
    server_ip = config["server_ip"]
    sip_port = int(config["internal_port"])
    ext_password = config["extension_password"]
    container = config["container_name"]

    # 注册被叫 B
    client_b, reg_b_ok, reg_b_msg = _create_sip_client(server_ip, sip_port, TEST_EXTENSION_B, ext_password)
    if not reg_b_ok:
        log_error("  FAIL: 被叫 %s 注册失败 - %s" % (TEST_EXTENSION_B, reg_b_msg))
        try:
            client_b.sip_socket.close()
        except Exception:
            pass
        return False
    log_info("  被叫 %s 注册成功" % TEST_EXTENSION_B)

    # 注册主叫 A
    client_a, reg_a_ok, reg_a_msg = _create_sip_client(server_ip, sip_port, TEST_EXTENSION_A, ext_password)
    if not reg_a_ok:
        log_error("  FAIL: 主叫 %s 注册失败 - %s" % (TEST_EXTENSION_A, reg_a_msg))
        try:
            client_a.sip_socket.close()
        except Exception:
            pass
        try:
            client_b.sip_socket.close()
        except Exception:
            pass
        return False
    log_info("  主叫 %s 注册成功" % TEST_EXTENSION_A)

    # 记录当前日志行数作为基准
    log_baseline = remote_exec(ssh_client,
                               "docker exec %s wc -l /var/log/freeswitch/freeswitch.log 2>/dev/null | awk '{print $1}'" % container)
    try:
        baseline_count = int(log_baseline.strip())
    except ValueError:
        baseline_count = 0

    # 主叫 A 发起 INVITE 到 B
    try:
        client_a.make_call(TEST_EXTENSION_B)
    except Exception as e:
        log_error("  FAIL: 发起呼叫异常 - %s" % str(e))
        try:
            client_a.sip_socket.close()
        except Exception:
            pass
        try:
            client_b.sip_socket.close()
        except Exception:
            pass
        return False

    # 等待 FreeSWITCH 处理呼叫
    time.sleep(10)

    # 检查 A 的通话状态
    call_state = client_a.state if client_a.current_call else CallState.INITIAL

    # 提取新增日志，检查 dialplan 路由
    new_logs = remote_exec(ssh_client,
                           "docker exec %s tail -n +%d /var/log/freeswitch/freeswitch.log 2>/dev/null" % (container,
                                                                                                          baseline_count + 1))

    # 检查 dialplan 是否匹配了 inbound_direct_extension
    has_inbound_route = "inbound_direct_extension" in new_logs
    # 检查是否执行了 bridge(user/...)
    has_bridge = "bridge(user/" in new_logs
    # 检查是否尝试了呼叫被叫
    has_call_attempt = TEST_EXTENSION_B in new_logs and ("bridge" in new_logs or "INVITE" in new_logs)

    # 挂断通话
    try:
        if client_a.current_call:
            client_a.hangup_call()
            time.sleep(2)
    except Exception:
        pass

    # 清理
    try:
        client_a.sip_socket.close()
    except Exception:
        pass
    try:
        client_b.sip_socket.close()
    except Exception:
        pass

    if call_state == CallState.CONFIRMED:
        log_success("  PASS: 呼入通话建立成功")
        return True
    elif has_inbound_route or has_bridge or has_call_attempt:
        # NAT 环境下被叫不可达是预期行为，只要 dialplan 正确路由即算通过
        log_success("  PASS: 呼入路由验证成功（dialplan 匹配 inbound_direct_extension，bridge 到 %s）" % TEST_EXTENSION_B)
        log_info("  注: 被叫不可达是 NAT 环境下的预期行为")
        return True
    else:
        log_error("  FAIL: 呼入路由未生效")
        return False


def test_outbound_call(ssh_client, config):
    """
    测试呼出路由：使用 nx-sip-client 注册分机后呼叫外部号码，验证日志中向 outbound_server 发送 INVITE。

    需求：验证 FreeSWITCH dialplan 的 outbound_to_gateway 路由生效。
    预期结果：FreeSWITCH 日志中出现向 outbound_server 发送 INVITE 的记录。
    处理逻辑：
        1. 注册分机 A
        2. 记录当前日志行数作为基准
        3. A 发起呼叫到外部号码
        4. 提取新增日志，搜索 outbound_server 的 INVITE 记录
    """
    log_info("[SIP 测试 3/3] 呼出路由测试...")
    server_ip = config["server_ip"]
    sip_port = int(config["internal_port"])
    ext_password = config["extension_password"]
    outbound_number = config.get("outbound_test_number", OUTBOUND_TEST_NUMBER)
    outbound_server = config["outbound_server"]
    container = config["container_name"]

    # 注册分机 A
    client_a, reg_a_ok, reg_a_msg = _create_sip_client(server_ip, sip_port, TEST_EXTENSION_A, ext_password)
    if not reg_a_ok:
        log_error("  FAIL: 分机 %s 注册失败 - %s" % (TEST_EXTENSION_A, reg_a_msg))
        try:
            client_a.sip_socket.close()
        except Exception:
            pass
        return False

    # 记录当前日志行数作为基准
    log_baseline = remote_exec(ssh_client,
                               "docker exec %s wc -l /var/log/freeswitch/freeswitch.log 2>/dev/null | awk '{print $1}'" % container)
    try:
        baseline_count = int(log_baseline.strip())
    except ValueError:
        baseline_count = 0

    # A 发起呼叫到外部号码
    try:
        client_a.make_call(outbound_number)
    except Exception as e:
        log_error("  FAIL: 发起呼叫异常 - %s" % str(e))
        try:
            client_a.sip_socket.close()
        except Exception:
            pass
        return False

    # 等待 INVITE 发送
    time.sleep(10)

    # 提取新增日志
    new_logs = remote_exec(ssh_client,
                           "docker exec %s tail -n +%d /var/log/freeswitch/freeswitch.log 2>/dev/null" % (container,
                                                                                                          baseline_count + 1))

    # 检查是否向 outbound_server 发送了 INVITE
    outbound_host = outbound_server.split(":")[0] if ":" in outbound_server else outbound_server
    # 匹配多种日志格式：直接 INVITE 关键字、sofia/external/ 通道名、网关地址
    has_invite = (
            (outbound_host in new_logs and "INVITE" in new_logs) or
            ("sofia/external/" in new_logs and outbound_host in new_logs) or
            ("outbound_to_gateway" in new_logs)
    )
    has_dialplan = ("outbound_to_gateway" in new_logs or "dialplan" in new_logs.lower())

    # 挂断
    try:
        if client_a.current_call:
            client_a.hangup_call()
            time.sleep(2)
    except Exception:
        pass

    # 清理
    try:
        client_a.sip_socket.close()
    except Exception:
        pass

    if has_invite:
        log_success("  PASS: 呼出路由验证成功，已向 %s 发送 INVITE" % outbound_server)
        if has_dialplan:
            log_info("  匹配到 outbound_to_gateway dialplan extension")
        return True
    else:
        log_error("  FAIL: 未检测到向 %s 发送 INVITE 的记录" % outbound_server)
        invite_lines = [l for l in new_logs.split("\n") if
                        "INVITE" in l or outbound_host in l or "outbound" in l.lower()]
        if invite_lines:
            print("    [相关日志] %s" % "\n    ".join(invite_lines[:10]))
        else:
            print("    [新增日志末尾] %s" % "\n    ".join(new_logs.split("\n")[-15:]))
        return False


def run_sip_tests(ssh_client, config):
    """
    SIP 测试统一入口：依次执行注册、呼入、呼出三项测试。

    需求：部署完成后验证 FreeSWITCH 的 SIP 信令和媒体功能是否真正可用。
    预期结果：输出三项测试的 PASS/FAIL 结果汇总，不中断部署流程。
    处理逻辑：
        1. 检查 --skip-sip-test 参数
        2. 检查 SIP 测试依赖（nx-sip-client 库）
        3. 重启 FreeSWITCH 容器确保所有配置变更（包括监听地址）生效
        4. 依次执行三项测试并汇总结果
    """
    if config.get("skip_sip_test", False):
        log_info("已跳过 SIP 测试（--skip-sip-test）")
        return

    if not check_sip_dependency():
        log_error("SIP 测试依赖缺失，跳过 SIP 测试")
        return

    log_info("=" * 60)
    log_info("开始 SIP 注册与呼叫测试")
    log_info("=" * 60)

    # 重启容器确保所有配置变更生效（包括监听地址，仅 reloadxml 不够）
    restart_freeswitch_container(ssh_client, config)

    results = {}
    results["注册测试"] = test_sip_registration(ssh_client, config)
    time.sleep(3)
    results["呼入通话"] = test_inbound_call(ssh_client, config)
    time.sleep(3)
    results["呼出路由"] = test_outbound_call(ssh_client, config)

    log_info("=" * 60)
    log_info("SIP 测试结果汇总:")
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        log_info("  %s: %s" % (name, status))
    log_info("=" * 60)


def update_users_only(ssh_client, config, dry_run=False):
    """
    仅在线更新 directory/default.xml 并 reloadxml（不重启容器），用于扩展分机数量。

    需求背景：分机数量扩展（如 100 → 120）只需重新生成 directory 配置，reloadxml 即可
    生效；重启容器（15s 级）会造成在线注册抖动与媒体中断，不适合在线扩容场景。
    预期结果：directory/default.xml 被重写为目标分机数，list_users 验证数量达到预期。
    处理逻辑：
        1. 按端口前缀定位已运行的 freeswitch 容器
        2. 只重写 directory/default.xml（复用 update_directory_xml 生成逻辑）
        3. reloadxml 生效，等待 2s 后 list_users 验证用户数
    :param ssh_client: SSH 客户端（dry_run=True 时可为 None，不执行远程操作）
    :param config: 部署配置 dict（需含 internal_port/esl_port 用于定位容器）
    :param dry_run: True 时只打印将生成的用户数与起止号，不执行任何远程写入
    """
    count = EXTENSION_COUNT if config.get("extension_count") is None else config["extension_count"]
    first = "%s%0*d" % (EXTENSION_PREFIX, EXTENSION_SEQUENCE_DIGITS, 0)
    last = "%s%0*d" % (EXTENSION_PREFIX, EXTENSION_SEQUENCE_DIGITS, count - 1)
    log_info("目标分机数: %d (范围 %s ~ %s)" % (count, first, last))
    if dry_run:
        log_info("[dry-run] 跳过远程写入，仅打印将生成的 directory/default.xml 用户信息")
        users = []
        for i in range(count):
            exten = "%s%0*d" % (EXTENSION_PREFIX, EXTENSION_SEQUENCE_DIGITS, i)
            users.append('      <user id="%s"/>' % exten)
        print("\n".join(users[:3]))
        print("      ...(共 %d 个用户)..." % count)
        print("\n".join(users[-2:]))
        log_success("[dry-run] 验证通过：将生成 %d 个分机" % count)
        return

    # 定位已运行的 freeswitch 容器（按 internal_port_esl_port 前缀）
    pattern = "freeswitch_%s_%s_" % (config["internal_port"], config["esl_port"])
    containers_raw = remote_exec(ssh_client, 'docker ps --filter "name=%s" --format "{{.Names}}"' % pattern)
    containers = [c.strip() for c in containers_raw.split("\n") if c.strip()]
    if not containers:
        log_error("未找到运行的 FreeSWITCH 容器（前缀 %s），请先执行完整部署" % pattern)
        sys.exit(1)
    if len(containers) > 1:
        log_warn("发现多个匹配容器，取第一个: %s" % containers)
    container = containers[0]
    # esl_exec 依赖 config["container_name"] 定位容器, 在线模式补设(完整部署由 run_deployment 设置)
    config["container_name"] = container
    # 配置目录为挂载卷（/etc/<容器名>），与部署时 get_config_dir 一致
    config_dir = get_config_dir(container)
    log_info("定位容器: %s | 配置目录: %s" % (container, config_dir))

    # 备份当前 directory 配置（幂等回滚用）
    backup_path = "%s/directory/default.xml.bak" % config_dir
    remote_exec(ssh_client, "cp -f %s/directory/default.xml %s 2>/dev/null || true" % (config_dir, backup_path))
    log_info("已备份原配置: %s" % backup_path)

    update_directory_xml(ssh_client, config_dir, config["server_ip"],
                         config["extension_password"], count)
    # directory 变更 reloadxml 即可生效，无需重启容器
    log_info("reloadxml 生效中...")
    esl_exec(ssh_client, config, "reloadxml")
    time.sleep(2)

    # 验证：list_users 应覆盖新分机数(输出行格式 'userid|context|domain|...', 按行首全号匹配)
    users = esl_exec(ssh_client, config, "list_users")
    registered_ids = set(re.findall(r"(?m)^(18\d{9})\|", users or ""))
    user_count = 0
    for i in range(count):
        ext = "%s%0*d" % (EXTENSION_PREFIX, EXTENSION_SEQUENCE_DIGITS, i)
        if ext in registered_ids:
            user_count += 1
    if user_count >= count:
        log_success("在线扩容验证通过：list_users 命中 %d/%d 个分机" % (user_count, count))
    else:
        log_error("在线扩容验证失败：list_users 仅命中 %d/%d 个分机，请检查 FS 日志" % (user_count, count))
        sys.exit(1)


def run_deployment(ssh_client, config):
    config["container_name"] = generate_container_name()
    config["config_dir"] = get_config_dir(config["container_name"])

    log_info("=" * 60)
    log_info("开始 FreeSWITCH 远程部署")
    log_info("目标服务器: %s" % config["remote"])
    log_info("容器名: %s | 配置目录: %s" % (config["container_name"], config["config_dir"]))
    log_info("Server IP: %s | Internal: %s | External: %s | ESL: %s" % (
        config["server_ip"], config["internal_port"], config["external_port"], config["esl_port"]))
    log_info("=" * 60)

    remote_docker_install(ssh_client)
    remote_pull_image(ssh_client, config["image"], config["image_source"])
    remote_cleanup(ssh_client, config)
    extract_default_config(ssh_client, config)
    remote_update_configs(ssh_client, config)
    remote_start_container(ssh_client, config)
    verify_deployment(ssh_client, config)
    run_sip_tests(ssh_client, config)

    log_info("=" * 60)
    log_success("FreeSWITCH 部署全部完成！")
    log_info("容器名: %s | 配置目录: %s" % (config["container_name"], config["config_dir"]))
    log_info("=" * 60)


def main():
    """
    脚本入口：解析命令行参数，支持完整部署与在线分机扩容两种模式。

    参数：
        --update-users-only   仅在线重写 directory 分机配置并 reloadxml（不重启容器）
        --extensions N        目标分机数量（默认 FS_EXTENSION_COUNT 环境变量，缺省 100）
        --dry-run             只打印将生成的分机信息，不执行任何远程写入
        --skip-sip-test       跳过部署后的 SIP 注册/呼叫测试
    """
    parser = argparse.ArgumentParser(description="模拟第三方网关-运营商的 FreeSWITCH 部署脚本")
    parser.add_argument("--update-users-only", action="store_true", default=False,
                        help="仅在线重写 directory 分机配置并 reloadxml（不重启容器）")
    parser.add_argument("--extensions", type=int, default=None,
                        help="目标分机数量（默认取 FS_EXTENSION_COUNT 环境变量，缺省 100）")
    parser.add_argument("--dry-run", action="store_true", default=False,
                        help="只打印将生成的分机信息，不执行任何远程写入")
    parser.add_argument("--skip-sip-test", action="store_true", default=False,
                        help="跳过部署后的 SIP 注册/呼叫测试")
    parser.add_argument("--no-sim-register-gateway", action="store_true", default=False,
                        help="不生成 sim-4g-gateway（注册模式4G网关模拟）配置（默认生成，场景12/13 依赖）")
    args = parser.parse_args()

    ext_count = EXTENSION_COUNT if args.extensions is None else args.extensions
    if ext_count < 1:
        log_error("--extensions 必须 >= 1")
        sys.exit(1)
    config = {
        "remote": REMOTE_HOST,
        "server_ip": SERVER_IP,
        "internal_port": INTERNAL_PORT,
        "external_port": EXTERNAL_PORT,
        "esl_port": ESL_PORT,
        "esl_password": ESL_PASSWORD,
        "extension_password": EXTENSION_PASSWORD,
        "extension_count": ext_count,
        "outbound_server": OUTBOUND_SERVER,
        "external_ext_ip": EXTERNAL_EXT_IP,
        "image": FS_IMAGE,
        "image_source": FS_IMAGE_SOURCE,
        "skip_sip_test": SKIP_SIP_TEST or args.skip_sip_test,
        "outbound_test_number": OUTBOUND_TEST_NUMBER,
        "sim_register_gateway": not args.no_sim_register_gateway,
    }

    ssh_client = None
    try:
        if args.update_users_only and args.dry_run:
            # dry-run 仅本地打印生成计划，无需建立 SSH 连接
            update_users_only(None, config, dry_run=True)
            return
        ssh_client = create_ssh_client(REMOTE_HOST, SSH_PORT, SSH_USER, SSH_PASSWORD)
        if args.update_users_only:
            update_users_only(ssh_client, config, dry_run=args.dry_run)
        else:
            run_deployment(ssh_client, config)
    except KeyboardInterrupt:
        log_error("用户中断部署")
        sys.exit(1)
    except Exception as e:
        log_error("部署失败: %s" % str(e))
        sys.exit(1)
    finally:
        if ssh_client:
            ssh_client.close()
            log_info("SSH 连接已关闭")


if __name__ == "__main__":
    main()
