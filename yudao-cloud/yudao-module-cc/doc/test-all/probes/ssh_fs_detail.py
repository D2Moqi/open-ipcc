#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查看 FS internal.xml 和 external.xml 完整配置，以及 TLS 证书目录。"""
import paramiko
import sys

REMOTE_HOST = "<A服务器公网>"
SSH_USER = "<账户>"
SSH_PASSWORD = "<密码>"


def run(client, cmd):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=30)
    return stdout.read().decode("utf-8", errors="replace")


def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(hostname=REMOTE_HOST, port=22, username=SSH_USER, password=SSH_PASSWORD, timeout=30)

    target = "freeswitch_16560_18121_d8eqta"

    # 1. 查看 internal.xml 完整内容
    print("===== internal.xml (sip_profiles) =====")
    out = run(client, f"docker exec {target} cat /etc/freeswitch/sip_profiles/internal.xml")
    print(out)

    # 2. 查看 external.xml 完整内容
    print("\n===== external.xml (sip_profiles) =====")
    out = run(client, f"docker exec {target} cat /etc/freeswitch/sip_profiles/external.xml")
    print(out)

    # 3. 查看 TLS 证书目录
    print("\n===== TLS 证书目录 =====")
    out = run(client, f"docker exec {target} ls -la /etc/freeswitch/tls/ 2>/dev/null")
    print(out)

    # 4. 查看 vars.xml 中 rtp_secure_media 等配置
    print("\n===== vars.xml 中 rtp_secure_media 相关 =====")
    out = run(client,
              f"docker exec {target} grep -A2 -B2 'rtp_secure\\|dtls\\|webrtc' /etc/freeswitch/vars.xml 2>/dev/null | head -40")
    print(out)

    client.close()


if __name__ == '__main__':
    main()
