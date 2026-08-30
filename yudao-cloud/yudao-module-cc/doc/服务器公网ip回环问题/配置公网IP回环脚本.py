import paramiko
import time

REMOTE_HOST = '62.234.191.165'
SSH_USER = 'ubuntu'
SSH_PASSWORD = 'Moqi147852369'
PUBLIC_IP = '62.234.191.165'


def ssh_exec_command(client, command, sudo=False, timeout=60):
    if sudo:
        command = f"sudo -S -p '' {command}"

    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)

    if sudo:
        stdin.write(f"{SSH_PASSWORD}\n")
        stdin.flush()

    stdout.channel.set_combine_stderr(True)
    output = stdout.read().decode('utf-8', errors='ignore').strip()

    return output


def main():
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(REMOTE_HOST, username=SSH_USER, password=SSH_PASSWORD, timeout=30)

        print("=" * 60)
        print("1. 检查当前回环接口配置")
        print("=" * 60)
        output = ssh_exec_command(client, "ip addr show lo")
        print(output)
        print()

        if PUBLIC_IP in output:
            print(f"✓ 公网IP {PUBLIC_IP} 已绑定到回环接口")
        else:
            print(f"✗ 公网IP {PUBLIC_IP} 未绑定到回环接口，需要配置")
            print()

            print("=" * 60)
            print("2. 创建启动脚本")
            print("=" * 60)
            script_content = "#!/bin/bash\n/sbin/ip addr add " + PUBLIC_IP + "/32 dev lo 2>/dev/null || true"
            ssh_exec_command(client,
                             "printf '" + script_content + "' | sudo tee /usr/local/bin/add-loopback-ip.sh > /dev/null",
                             sudo=True)
            ssh_exec_command(client, "sudo chmod +x /usr/local/bin/add-loopback-ip.sh", sudo=True)
            output = ssh_exec_command(client, "cat /usr/local/bin/add-loopback-ip.sh")
            print(output)
            print("✓ 启动脚本创建成功")
            print()

            print("=" * 60)
            print("3. 创建systemd服务文件")
            print("=" * 60)
            service_content = "[Unit]\nDescription=Add public IP to loopback interface\nAfter=network.target\n\n[Service]\nType=oneshot\nExecStart=/usr/local/bin/add-loopback-ip.sh\n\n[Install]\nWantedBy=multi-user.target"
            ssh_exec_command(client,
                             "printf '" + service_content + "' | sudo tee /etc/systemd/system/loopback-ip.service > /dev/null",
                             sudo=True)
            output = ssh_exec_command(client, "cat /etc/systemd/system/loopback-ip.service")
            print(output)
            print("✓ systemd服务文件创建成功")
            print()

            print("=" * 60)
            print("4. 启用并启动服务")
            print("=" * 60)
            output = ssh_exec_command(client, "sudo systemctl daemon-reload", sudo=True)
            if output:
                print(f"daemon-reload: {output}")

            output = ssh_exec_command(client, "sudo systemctl enable loopback-ip", sudo=True)
            print(f"enable: {output}")

            output = ssh_exec_command(client, "sudo systemctl start loopback-ip", sudo=True)
            if output:
                print(f"start: {output}")
            else:
                print("✓ 服务启动成功")
            print()

        print("=" * 60)
        print("5. 验证IP配置")
        print("=" * 60)
        output = ssh_exec_command(client, "ip addr show lo")
        print(output)
        print()

        if PUBLIC_IP in output:
            print("✓ IP绑定成功")
        else:
            print("✗ IP绑定失败")
            client.close()
            return

        print("=" * 60)
        print("6. 测试ping")
        print("=" * 60)
        output = ssh_exec_command(client, f"ping -c 4 {PUBLIC_IP}")
        print(output)
        print()

        if "0% packet loss" in output:
            print("✓ ping测试成功")
        else:
            print("✗ ping测试失败")

        print("=" * 60)
        print("7. 测试telnet")
        print("=" * 60)
        try:
            output = ssh_exec_command(client, f"timeout 2 telnet {PUBLIC_IP} 22 || echo 'telnet closed'")
            print(output)
            if "Connected" in output or "SSH" in output:
                print("✓ telnet测试成功")
            else:
                print("✗ telnet测试失败")
        except Exception as e:
            print(f"telnet测试异常: {e}")
        print()

        print("=" * 60)
        print("8. 服务状态检查")
        print("=" * 60)
        output = ssh_exec_command(client, "systemctl status loopback-ip")
        print(output)
        print()

        if "enabled" in output and "SUCCESS" in output:
            print("✓ 服务状态正常")
        else:
            print("✗ 服务状态异常")

        client.close()
        print()
        print("=" * 60)
        print("配置完成！")
        print("=" * 60)

    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
