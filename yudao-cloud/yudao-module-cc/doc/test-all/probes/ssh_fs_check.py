#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SSH 到 FS 服务器查看关键配置和媒体日志。
使用部署脚本中的 SSH 凭据。
"""
import sys

try:
    import paramiko
except ImportError:
    print("需要 paramiko: pip install paramiko")
    sys.exit(1)

REMOTE_HOST = "<A服务器公网>"
SSH_PORT = 22
SSH_USER = "<账户>"
SSH_PASSWORD = "<密码>"

# 找到当前活动的 FS 容器名（端口 16560/18121 是 fs2）
EXPECTED_PORTS = ["16560", "18121"]


def run(client, cmd, timeout=30):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return out + (("\n[stderr] " + err) if err.strip() else "")


def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"连接 SSH {REMOTE_HOST}:{SSH_PORT} ...")
    client.connect(hostname=REMOTE_HOST, port=SSH_PORT,
                   username=SSH_USER, password=SSH_PASSWORD, timeout=30)
    print("SSH 连接成功")

    # 1. 找到 fs2 容器
    out = run(client, "docker ps --format '{{.Names}}\t{{.Status}}' | grep -i freeswitch")
    print("\n===== FS 容器列表 =====")
    print(out)

    # 找到端口 16560 的容器
    containers = [line.split('\t')[0] for line in out.strip().split('\n') if line.strip()]
    target = None
    for c in containers:
        cinfo = run(client, f"docker inspect --format '{{{{.Config.Cmd}}}} {{{{.HostConfig.PortBindings}}}}' {c}")
        vinfo = run(client,
                    f"docker exec {c} cat /etc/freeswitch/vars.xml 2>/dev/null | grep -E 'internal_sip_port|external_sip_port' | head -5")
        if "16560" in vinfo and "18121" in run(client,
                                               f"docker exec {c} cat /etc/freeswitch/autoload_configs/event_socket.conf.xml 2>/dev/null | grep listen-port"):
            target = c
            break
    # 简化：直接用 docker ps 找
    if not target:
        for c in containers:
            t = run(client, f"docker exec {c} fs_cli -P 18121 -p <密码> -x 'status' 2>/dev/null")
            if "UP" in t:
                target = c
                break
    print(f"\n目标容器: {target}")

    if not target:
        print("未找到目标 FS 容器")
        client.close()
        return

    # 2. 查看 internal.xml 中 WebRTC/DTLS/SRTP 相关配置
    print("\n===== internal.xml 媒体相关配置 =====")
    out = run(client,
              f"docker exec {target} grep -iE 'webrtc|dtls|srtp|rtp-secure|stun|turn|ice|inbound-late-negotiation|inbound-proxy-media|media-mix-inbound-outbound-codecs|liberal|disable-transcoding|inherit-codec' /etc/freeswitch/sip_profiles/internal.xml 2>/dev/null")
    print(out or "(无匹配)")

    print("\n===== external.xml 媒体相关配置 =====")
    out = run(client,
              f"docker exec {target} grep -iE 'webrtc|dtls|srtp|rtp-secure|stun|turn|ice|inbound-late-negotiation|inbound-proxy-media|media-mix-inbound-outbound-codecs|liberal|disable-transcoding|inherit-codec' /etc/freeswitch/sip_profiles/external.xml 2>/dev/null")
    print(out or "(无匹配)")

    # 3. 查看 vars.xml 中的 WebRTC 相关变量
    print("\n===== vars.xml 媒体相关配置 =====")
    out = run(client,
              f"docker exec {target} grep -iE 'rtp_secure|dtls|webrtc|stun|turn|ice|external_rtp|external_sip|local_ip' /etc/freeswitch/vars.xml 2>/dev/null")
    print(out or "(无匹配)")

    # 4. 查看最近的 FS 日志中的媒体错误
    print("\n===== FS 最近日志 (媒体/ICE/DTLS) =====")
    out = run(client,
              f"docker exec {target} tail -500 /var/log/freeswitch/freeswitch.log 2>/dev/null | grep -iE 'ice|dtls|srtp|codec|media|negotiation|rtp|warning|error' | tail -40")
    print(out or "(无匹配)")

    # 5. 查看已加载的模块
    print("\n===== 已加载模块列表（媒体相关）=====")
    out = run(client, f"docker exec {target} fs_cli -P 18121 -p <密码> -x 'module_exists mod_opus'")
    print(f"mod_opus: {out.strip()}")
    out = run(client, f"docker exec {target} fs_cli -P 18121 -p <密码> -x 'module_exists mod_rtc')")
    print(f"mod_rtc: {out.strip()}")

    # 6. 查看 internal profile 完整配置
    print("\n===== sofia status profile internal 完整 =====")
    out = run(client, f"docker exec {target} fs_cli -P 18121 -p <密码> -x 'sofia status profile internal'")
    print(out)

    # 7. 查看 external profile 完整配置
    print("\n===== sofia status profile external 完整 =====")
    out = run(client, f"docker exec {target} fs_cli -P 18121 -p <密码> -x 'sofia status profile external'")
    print(out)

    # 8. 查看当前的活动通道（如果有）
    print("\n===== 当前活动通道 =====")
    out = run(client, f"docker exec {target} fs_cli -P 18121 -p <密码> -x 'show channels'")
    print(out)

    client.close()
    print("\nSSH 连接已关闭")


if __name__ == '__main__':
    main()
