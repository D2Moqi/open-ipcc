#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ESL(Event Socket Library)连接辅助类

需求: 通过ESL协议连接远程FreeSWITCH服务器,用于呼叫中心系统测试
预期结果: 封装常用ESL命令(查询通道/订阅事件/originate/uuid_kill/conference等),供测试脚本调用
处理逻辑: 使用Python socket直接实现ESL协议,不依赖第三方ESL库,避免安装问题

ESL协议说明:
- 基于文本协议,每条命令以两个换行符(\n\n)结尾
- 响应头与body以空行分隔,Content-Length头标识body长度
- 事件以Content-Type: text/event-plain推送,body为key=value格式

连接信息:
- 主机: <B服务器公网>
- 端口: 18021
- 密码: <密码>
"""

import json
import logging
import re
import socket
import time

# 配置日志输出,便于调试ESL交互过程
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger('EslHelper')


class EslHelper:
    """ESL连接辅助类,封装FreeSWITCH ESL命令"""

    def __init__(self, host, port, password):
        """
        初始化ESL连接参数
        :param host: ESL主机地址
        :param port: ESL端口
        :param password: ESL认证密码
        """
        self.host = host
        self.port = int(port)
        self.password = password
        # socket连接对象,connect()成功后赋值
        self.sock = None
        # 接收缓冲区,用于拼接不完整的ESL消息
        self._buffer = b''
        # 是否已订阅事件(订阅后socket会持续收到事件推送)
        self._subscribed = False
        # 事件缓存队列: send_command执行期间收到的事件会被缓存,
        # 供后续 wait_for_event 读取,避免事件被丢弃导致测试脚本超时
        # (典型场景: originate阻塞命令执行期间,CHANNEL_PARK事件先于命令响应到达,
        #  若丢弃则 wait_for_event 永远等不到事件)
        self._event_queue = []

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """
        连接ESL服务器并完成认证
        :return: 连接成功返回True,失败返回False
        处理逻辑:
            1. 建立TCP socket连接
            2. 等待服务器发送"Content-Type: auth/request"
            3. 发送"auth <password>"命令
            4. 验证响应是否为"+OK accepted"
        """
        try:
            # 创建TCP连接,设置10秒连接超时
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(10.0)
            self.sock.connect((self.host, self.port))
            self._buffer = b''
            logger.info('[ESL] TCP连接已建立 %s:%s', self.host, self.port)

            # 等待服务器发送auth/request
            headers = self._read_headers()
            content_type = headers.get('Content-Type', '')
            if content_type != 'auth/request':
                logger.error('[ESL] 期望auth/request,实际收到: %s', content_type)
                return False

            # 发送auth命令进行认证
            self._send_raw('auth {}\n\n'.format(self.password))
            headers = self._read_headers()
            reply = headers.get('Reply-Text', '')
            if reply.startswith('+OK'):
                logger.info('[ESL] 认证成功: %s', reply)
                return True
            else:
                logger.error('[ESL] 认证失败: %s', reply)
                return False
        except Exception as e:
            logger.error('[ESL] 连接异常: %s', e)
            self.sock = None
            return False

    def disconnect(self):
        """
        断开ESL连接
        处理逻辑: 关闭socket并清理状态
        """
        self._subscribed = False
        if self.sock:
            try:
                # 发送exit命令优雅退出
                self._send_raw('exit\n\n')
            except Exception:
                pass
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        self._buffer = b''
        logger.info('[ESL] 连接已断开')

    # ------------------------------------------------------------------
    # 底层协议处理
    # ------------------------------------------------------------------

    def _send_raw(self, data: str):
        """
        发送原始字符串到ESL服务器
        :param data: 待发送的字符串
        处理逻辑: 将字符串编码为UTF-8后通过socket发送
        """
        if not self.sock:
            raise RuntimeError('ESL未连接')
        self.sock.sendall(data.encode('utf-8'))

    def _read_headers(self) -> dict:
        """
        读取ESL响应头(直到空行)
        :return: 头部字典(key -> value)
        处理逻辑:
            1. 从缓冲区读取数据,直到遇到\r\n\r\n或\n\n
            2. 按行解析key: value格式
            3. 未读取完整时继续从socket接收
        """
        while b'\r\n\r\n' not in self._buffer and b'\n\n' not in self._buffer:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError('ESL连接已关闭')
            self._buffer += chunk

        # 兼容\r\n\r\n和\n\n两种分隔符
        if b'\r\n\r\n' in self._buffer:
            header_bytes, sep, self._buffer = self._buffer.partition(b'\r\n\r\n')
        else:
            header_bytes, sep, self._buffer = self._buffer.partition(b'\n\n')

        headers = {}
        for line in header_bytes.decode('utf-8', errors='replace').split('\n'):
            line = line.strip()
            if not line or ':' not in line:
                continue
            key, _, value = line.partition(':')
            headers[key.strip()] = value.strip()
        return headers

    def _read_body(self, length: int) -> str:
        """
        读取指定长度的body内容
        :param length: Content-Length指定的字节数
        :return: body字符串
        处理逻辑: 从缓冲区读取,不足时继续从socket接收
        """
        while len(self._buffer) < length:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError('ESL连接已关闭')
            self._buffer += chunk
        body_bytes = self._buffer[:length]
        self._buffer = self._buffer[length:]
        return body_bytes.decode('utf-8', errors='replace')

    def send_command(self, command: str, timeout: float = 5.0) -> dict:
        """
        发送ESL api命令并等待响应

        :param command: ESL命令(如"show channels"或"originate ...")
        :param timeout: 响应超时时间(秒)
        :return: 响应字典,包含Content-Type/Reply-Text/Body等字段
        处理逻辑:
            1. 以"api <command>\n\n"格式发送
            2. 循环读取消息,跳过断开通知(text/disconnect-notice)
            3. 订阅事件后,事件(text/event-plain)会先于命令响应到达同一socket,
               将这些事件缓存到 _event_queue(而非丢弃),供后续 wait_for_event 读取
            4. 读取到命令响应(command/reply 或 api/response)后,根据Content-Length读取body并返回
        设计说明:
            originate等阻塞命令执行期间,CHANNEL_PARK/CHANNEL_ANSWER等事件会先于
            命令响应到达同一socket。若丢弃这些事件,wait_for_event 将永远等不到事件
            (场景3/7的根因)。缓存到 _event_queue 后,wait_for_event 会优先从队列
            查找匹配事件,找不到再从socket读取,保证事件不丢失。
        """
        if not self.sock:
            raise RuntimeError('ESL未连接')

        # 设置响应超时
        old_timeout = self.sock.gettimeout()
        self.sock.settimeout(timeout)
        try:
            self._send_raw('api {}\n\n'.format(command))
            # 循环读取消息,直到读到命令响应(command/reply 或 api/response)
            # 事件消息会被缓存到 _event_queue,其他非命令响应消息会被跳过
            while True:
                headers = self._read_headers()
                content_type = headers.get('Content-Type', '')

                # 缓存事件消息: 订阅事件后,事件会先于命令响应到达
                # 解析事件body并缓存到队列,供 wait_for_event 读取
                if content_type == 'text/event-plain':
                    content_length = int(headers.get('Content-Length', 0))
                    if content_length > 0:
                        body = self._read_body(content_length)
                        event = self._parse_event_body(body)
                        if event:
                            self._event_queue.append(event)
                            logger.debug('[ESL] send_command 缓存事件: %s, uuid=%s, channel=%s',
                                         event.get('Event-Name', ''),
                                         event.get('Unique-ID', ''),
                                         event.get('Channel-Name', ''))
                    continue

                # 跳过断开通知
                if content_type == 'text/disconnect-notice':
                    content_length = int(headers.get('Content-Length', 0))
                    if content_length > 0:
                        self._read_body(content_length)
                    continue

                # 跳过认证请求(不应出现在命令响应中,但防御性处理)
                if content_type == 'auth/request':
                    continue

                # 命令响应: command/reply 或 api/response
                if content_type in ('command/reply', 'api/response'):
                    content_length = int(headers.get('Content-Length', 0))
                    if content_length > 0:
                        headers['Body'] = self._read_body(content_length)
                    else:
                        headers['Body'] = ''
                    return headers

                # 未知消息类型: 读取body并跳过
                content_length = int(headers.get('Content-Length', 0))
                if content_length > 0:
                    self._read_body(content_length)
                logger.warning('[ESL] send_command 跳过未知消息类型: %s', content_type)
        finally:
            self.sock.settimeout(old_timeout)

    def _parse_event_body(self, body: str) -> dict:
        """
        解析ESL事件body为字典

        :param body: 事件body文本(每行 key=value 或 key: value 格式)
        :return: 事件数据字典
        处理逻辑: 按行解析,同时支持 = 和 : 作为分隔符
        设计说明:
            FS 标准事件格式为 key=value,但某些 FS 实例/版本的事件 body 使用 key: value 格式。
            同时支持两种分隔符,保证兼容性。优先使用 = 分隔符(标准格式),
            若行中无 = 则尝试用 : 分割(非标准格式)。
            注意: 使用第一个分隔符分割,key 中不会包含分隔符。
        """
        event = {}
        for line in body.split('\n'):
            line = line.strip()
            if not line:
                continue
            # 优先使用 = 作为分隔符(标准格式)
            if '=' in line:
                key, _, value = line.partition('=')
            # 回退使用 : 作为分隔符(非标准格式,某些 FS 实例使用)
            elif ':' in line:
                key, _, value = line.partition(':')
            else:
                continue
            event[key.strip()] = value.strip()
        return event

    # ------------------------------------------------------------------
    # 通道查询
    # ------------------------------------------------------------------

    def show_channels(self) -> list:
        """
        查询当前所有通道
        :return: 通道列表,每个通道是字典
        处理逻辑: 发送"show channels as json"命令,解析JSON响应
        预期结果: 返回当前FS上所有活跃通道的列表
        """
        resp = self.send_command('show channels as json')
        body = resp.get('Body', '').strip()
        if not body:
            return []
        try:
            data = json.loads(body)
            # FreeSWITCH返回格式: {"row_count": N, "rows": [...]}
            return data.get('rows', [])
        except json.JSONDecodeError as e:
            logger.error('[ESL] 解析通道JSON失败: %s, body: %s', e, body[:200])
            return []

    def get_channel_count(self) -> int:
        """
        获取当前通道数量
        :return: 通道数量
        处理逻辑: 通过show channels结果统计
        """
        return len(self.show_channels())

    def find_channel_by_number(self, number: str) -> dict:
        """
        根据号码查找通道

        :param number: 电话号码
        :return: 通道信息字典,未找到返回None
        处理逻辑:
            1. 查询所有通道
            2. 在多个可能包含号码的字段中匹配
        字段说明:
            FreeSWITCH `show channels as json` 返回的通道字段命名空间与 ESL 事件不同,
            早期实现只匹配 caller_id_number/callee_id_number,
            但实际 JSON 中字段名为 name(如 "sofia/internal/1001@xxx"),
            且某些情况下 caller_id_number 为空(EARLY 状态或入局 INVITE 未到 ANSWER 阶段),
            需扩展匹配字段并兼容大小写不同的别名。
        """
        channels = self.show_channels()
        for ch in channels:
            # 兼容 show channels JSON 与 ESL 事件两种字段命名
            # show channels JSON: name/caller_id_number/callee_id_number/context/presence_id/callstate
            # ESL 事件: Caller-Caller-ID-Number/Caller-Destination-Number/Channel-Name 等
            fields = [
                'name', 'caller_id_number', 'callee_id_number',
                'context', 'presence_id', 'callstate',
                # 兼容 ESL 事件字段名(连字符格式)
                'Caller-Caller-ID-Number', 'Caller-Destination-Number',
                'Caller-Callee-ID-Number', 'Channel-Name',
                # 兼容小写连字符格式
                'caller-caller-id-number', 'caller-destination-number',
                'channel-name',
            ]
            for field in fields:
                value = str(ch.get(field, ''))
                if value and number in value:
                    return ch
        return None

    # ------------------------------------------------------------------
    # 呼叫控制
    # ------------------------------------------------------------------

    def originate(self, caller: str, callee: str, gateway_id: str = None,
                  task_id: str = None, ivr_flow: str = None) -> str:
        """
        发起originate呼叫(用于模拟外部呼入/自动外呼)
        :param caller: 主叫号码
        :param callee: 被叫号码
        :param gateway_id: 网关ID(可选,出局呼叫时携带,通过sip_h_X-Gateway-Id透传)
        :param task_id: 任务ID(可选,自动外呼时携带)
        :param ivr_flow: IVR流程ID(可选,自动外呼时携带)
        :return: 呼叫UUID(成功)或空字符串(失败)
        处理逻辑:
            1. 构造通道变量集合,在{}中以var=val,var=val格式设置
            2. 根据参数决定呼叫类型:
               - 自动外呼(task_id+ivr_flow): 使用sofia/external/<callee>@<realm>
               - 内部呼叫: 使用user/<callee>
               - 出局呼叫(gateway_id): 使用sofia/external/<callee>
            3. 末尾使用 &park() 保持通道,等待后续业务处理
            4. 发送originate命令,从响应中提取UUID
        命令格式示例:
            originate {task_id=xxx,ivr_flow=yyy}sofia/external/13800001111 &park()
            originate {sip_h_X-Gateway-Id=xxx}user/1002 &park()
        """
        # 构造通道变量集合
        variables = {
            'origination_caller_id_number': caller,
            'origination_caller_id_name': caller,
            'return_ring_ready': 'true',
            'absolute_codec_string': 'PCMA,PCMU',
        }
        # 透传网关ID(用于SIP头X-Gateway-Id识别出局网关)
        if gateway_id:
            variables['sip_h_X-Gateway-Id'] = gateway_id
        # 透传task_id和ivr_flow(供CHANNEL_PARK事件识别自动外呼任务)
        if task_id:
            variables['task_id'] = task_id
        if ivr_flow:
            variables['ivr_flow'] = ivr_flow

        # 拼接变量字符串: {key1=val1,key2=val2}
        var_str = ','.join('{}={}'.format(k, v) for k, v in variables.items())
        var_block = '{' + var_str + '}'

        # 根据参数决定呼叫目标
        if task_id and ivr_flow:
            # 自动外呼: 使用sofia/external profile出局
            destination = 'sofia/external/{}'.format(callee)
        elif gateway_id:
            # 出局呼叫(携带网关ID): 使用sofia/external profile
            destination = 'sofia/external/{}'.format(callee)
        else:
            # 内部呼叫: 使用user/<分机号>
            destination = 'user/{}'.format(callee)

        # 末尾 &park() 保持通道,等待业务侧处理(与Java端EslConstant.PARK一致)
        command = 'originate {}{} &park()'.format(var_block, destination)
        logger.info('[ESL] 发起originate: %s', command)

        resp = self.send_command(command, timeout=30.0)
        body = resp.get('Body', '').strip()
        reply = resp.get('Reply-Text', '')

        # originate响应格式: "+OK <uuid>" 或 "+OK <uuid> <dest>" 或失败"-ERR xxx"
        if body.startswith('+OK'):
            # 提取UUID(OK后的第一个token)
            parts = body.split()
            if len(parts) >= 2:
                uuid = parts[1]
                logger.info('[ESL] originate成功, UUID: %s', uuid)
                return uuid
            return body
        elif reply.startswith('+OK'):
            parts = reply.split()
            if len(parts) >= 2:
                return parts[1]
            return reply
        else:
            logger.error('[ESL] originate失败: body=%s, reply=%s', body, reply)
            return ''

    def uuid_kill(self, uuid: str, ignore_no_channel: bool = True) -> bool:
        """
        挂断指定通道

        :param uuid: 通道UUID
        :param ignore_no_channel: 为 True 时(默认),"No such channel" 错误视为成功
            (通道已自行挂断,uuid_kill 仅作为兜底清理,重复清理不应报错)
        :return: 成功返回True,失败返回False
        处理逻辑:
            1. 发送 "uuid_kill <uuid>" 命令
            2. 检查响应是否为 +OK
            3. 若收到 "-ERR No such channel" 且 ignore_no_channel=True,视为成功
               (场景3 中 IVR 流程结束后 uuid_kill 已挂断的 UUID 是正常 race condition,
                不是真实错误, 仅日志噪音)
        """
        resp = self.send_command('uuid_kill {}'.format(uuid))
        body = resp.get('Body', '').strip()
        reply = resp.get('Reply-Text', '')
        # 成功响应: "+OK" 或 body包含"OK"
        if body.startswith('+OK') or reply.startswith('+OK') or 'OK' in body:
            logger.info('[ESL] uuid_kill成功: %s', uuid)
            return True
        # 兜底清理容忍 "No such channel": 通道已自行挂断,不是真实错误
        if ignore_no_channel and ('No such channel' in body or 'No such channel' in reply):
            logger.info('[ESL] uuid_kill 忽略 No such channel(通道已挂断): %s', uuid)
            return True
        logger.error('[ESL] uuid_kill失败: %s, body=%s', uuid, body)
        return False

    def uuid_hold(self, uuid: str, hold: bool = True) -> bool:
        """
        保持/恢复通道
        :param uuid: 通道UUID
        :param hold: True保持(放等待音),False恢复
        :return: 成功返回True,失败返回False
        处理逻辑: 发送"uuid_hold <on|off> <uuid>"命令
        """
        action = 'on' if hold else 'off'
        resp = self.send_command('uuid_hold {} {}'.format(action, uuid))
        body = resp.get('Body', '').strip()
        reply = resp.get('Reply-Text', '')
        if body.startswith('+OK') or reply.startswith('+OK') or 'OK' in body:
            logger.info('[ESL] uuid_hold %s 成功: %s', action, uuid)
            return True
        logger.error('[ESL] uuid_hold %s 失败: %s, body=%s', action, uuid, body)
        return False

    # ------------------------------------------------------------------
    # 会议管理
    # ------------------------------------------------------------------

    def conference_list(self) -> list:
        """
        查询所有会议
        :return: 会议名称列表
        处理逻辑:
            1. 发送"conference list"命令
            2. 解析响应,每行一个会议(格式: "conf_name member_count")
        """
        resp = self.send_command('conference list')
        body = resp.get('Body', '').strip()
        if not body or body.startswith('-ERR') or 'No active conferences' in body:
            return []
        conferences = []
        for line in body.split('\n'):
            line = line.strip()
            if not line or line.startswith('No active'):
                continue
            # 格式: "conf_name member_count"
            parts = line.split()
            if parts:
                conferences.append(parts[0])
        return conferences

    def conference_list_members(self, conference_name: str) -> list:
        """
        查询指定会议的成员
        :param conference_name: 会议名称
        :return: 成员信息列表,每个成员是字典
        处理逻辑:
            1. 发送"conference <name> list"命令
            2. 解析每行成员信息(字段以分号或空格分隔)
        """
        resp = self.send_command('conference {} list'.format(conference_name))
        body = resp.get('Body', '').strip()
        if not body or body.startswith('-ERR') or 'Conference' not in body and not body:
            return []
        members = []
        for line in body.split('\n'):
            line = line.strip()
            if not line or line.startswith('Conference') or 'members' in line:
                continue
            # 成员行格式: "ID;UUID;CallerID;..."
            # 不同FS版本格式可能不同,这里做兼容处理
            if ';' in line:
                parts = line.split(';')
            else:
                parts = line.split()
            if parts:
                members.append({
                    'raw': line,
                    'id': parts[0] if len(parts) > 0 else '',
                    'uuid': parts[1] if len(parts) > 1 else '',
                    'caller_id': parts[2] if len(parts) > 2 else '',
                })
        return members

    def hangup_all_channels(self):
        """
        挂断所有通道(测试后清理用)

        需求: 测试结束后清理所有残留通话,避免影响后续测试
        预期结果: 所有通道被挂断
        处理逻辑:
          1. 优先使用 hupall 命令批量挂断(单条命令,高效)
          2. 若 hupall 失败,fallback 到逐个 uuid_kill(兼容性兜底)
          3. 记录挂断结果统计
        设计说明: 逐个 uuid_kill 在通道数多时很慢(每条 RTT + sleep),
                  且僵尸通道会返回 "No such channel" 错误;
                  hupall 一次命令挂断所有通道,适合清理场景
        """
        # 优先使用 hupall 批量挂断(normal_clearing cause,一次命令挂断所有)
        resp = self.send_command('hupall normal_clearing')
        body = resp.get('Body', '') + resp.get('Reply-Text', '')
        if '+OK' in body:
            logger.info('[ESL] hupall 批量挂断成功: %s', body.strip())
            return
        logger.warning('[ESL] hupall 失败, fallback 到逐个 uuid_kill: %s', body)

        # fallback: 逐个 uuid_kill(兼容性兜底)
        channels = self.show_channels()
        total = len(channels)
        success = 0
        logger.info('[ESL] 开始逐个挂断通道, 共%d个', total)
        for ch in channels:
            uuid = ch.get('uuid', '')
            if not uuid:
                continue
            if self.uuid_kill(uuid):
                success += 1
        logger.info('[ESL] 挂断完成: 成功%d/总数%d', success, total)

    # ------------------------------------------------------------------
    # 事件订阅与等待
    # ------------------------------------------------------------------

    def subscribe_events(self, events: list):
        """
        订阅事件
        :param events: 事件名列表,如["CHANNEL_PARK", "CHANNEL_ANSWER", "CHANNEL_BRIDGE", "CHANNEL_HANGUP"]
        处理逻辑:
            1. 先发送 "event plain off" 取消之前的所有订阅(避免事件流干扰新订阅)
            2. 再发送 "event plain <EVENT1> <EVENT2>" 订阅新事件
        预期结果: FS开始推送订阅的事件,可通过wait_for_event读取
        注意: "event plain" 是 ESL 协议命令(非 api 命令),不能通过 send_command(会加 api 前缀),
              需直接发送原始命令
        """
        if not events:
            return
        if not self.sock:
            logger.error('[ESL] 订阅事件失败: 未连接')
            return
        old_timeout = self.sock.gettimeout()
        self.sock.settimeout(5.0)
        try:
            # 步骤1: 取消之前的所有订阅,清空事件缓冲区
            self._send_raw('event plain off\n\n')
            off_headers = self._read_headers()
            logger.debug('[ESL] event plain off 响应: %s', off_headers)
            # 读取可能的 body(Content-Length 为 0 时不需要读取)
            off_content_length = int(off_headers.get('Content-Length', 0))
            if off_content_length > 0:
                self._read_body(off_content_length)
            # 清空接收缓冲区中的残留事件
            self._buffer = b''
            # 清空事件缓存队列
            self._event_queue = []

            # 步骤2: 订阅新事件
            event_str = ' '.join(events)
            command = 'event plain {}\n\n'.format(event_str)
            self._send_raw(command)
            headers = self._read_headers()
            logger.debug('[ESL] event plain %s 响应: %s', event_str, headers)
            content_length = int(headers.get('Content-Length', 0))
            if content_length > 0:
                headers['Body'] = self._read_body(content_length)
            else:
                headers['Body'] = ''
            reply = headers.get('Reply-Text', '')
            if reply.startswith('+OK'):
                self._subscribed = True
                logger.info('[ESL] 订阅事件成功: %s, reply=%s', events, reply)
            else:
                logger.error('[ESL] 订阅事件失败: %s, reply=%s, headers=%s',
                             events, reply, headers)
        except Exception as e:
            logger.error('[ESL] 订阅事件异常: %s, events=%s', e, events)
        finally:
            self.sock.settimeout(old_timeout)

    def _read_event(self, timeout: float = 10.0) -> dict:
        """
        读取一个事件(内部方法)
        :param timeout: 读取超时时间
        :return: 事件数据字典(key -> value),非事件消息返回空字典
        处理逻辑:
            1. 读取事件头,验证Content-Type为text/event-plain
            2. 根据Content-Length读取body
            3. 调用 _parse_event_body 解析body中的key=value格式
        """
        old_timeout = self.sock.gettimeout()
        self.sock.settimeout(timeout)
        try:
            headers = self._read_headers()
            content_type = headers.get('Content-Type', '')
            # 跳过非事件消息(如api/response、command/reply)
            if content_type != 'text/event-plain':
                # 如果携带body,读取并丢弃
                content_length = int(headers.get('Content-Length', 0))
                if content_length > 0:
                    self._read_body(content_length)
                return {}
            content_length = int(headers.get('Content-Length', 0))
            body = self._read_body(content_length)
            return self._parse_event_body(body)
        finally:
            self.sock.settimeout(old_timeout)

    def wait_for_event(self, event_name: str, timeout: float = 10.0,
                       match_vars: dict = None) -> dict:
        """
        等待指定事件

        :param event_name: 事件名(如CHANNEL_ANSWER)
        :param timeout: 超时时间(秒)
        :param match_vars: 需要匹配的变量字典(如{'Caller-Caller-ID-Number': '1001'})
        :return: 事件数据字典,超时返回None
        处理逻辑:
            1. 如果未订阅事件,自动订阅ALL事件
            2. 优先从事件缓存队列(_event_queue)查找匹配的事件
               (send_command执行期间缓存的事件,如originate阻塞期间的CHANNEL_PARK)
            3. 队列中找不到时,从socket读取新事件
            4. 超时未匹配返回None
        预期结果: 在超时时间内收到匹配的事件
        设计说明:
            originate等阻塞命令执行期间,事件会先于命令响应到达并被缓存到队列。
            wait_for_event 必须先检查队列,否则会导致事件丢失(场景3/7根因)。
        """
        # 未订阅时自动订阅所有事件
        if not self._subscribed:
            self.subscribe_events(['ALL'])

        start_time = time.time()
        logger.info('[ESL] 等待事件: %s, match_vars=%s, timeout=%s, 缓存事件数=%d',
                    event_name, match_vars, timeout, len(self._event_queue))

        # 步骤1: 优先从事件缓存队列查找匹配的事件
        # (send_command执行期间缓存的事件,避免丢弃导致超时)
        for i, event in enumerate(self._event_queue):
            current_name = event.get('Event-Name', '')
            if current_name != event_name:
                continue
            if match_vars:
                matched = True
                for key, value in match_vars.items():
                    if str(event.get(key, '')) != str(value):
                        matched = False
                        break
                if not matched:
                    continue
            # 匹配成功,从队列移除并返回
            self._event_queue.pop(i)
            logger.info('[ESL] 从缓存队列命中事件: %s', event_name)
            return event

        # 步骤2: 队列中无匹配事件,从socket读取新事件
        while time.time() - start_time < timeout:
            remaining = timeout - (time.time() - start_time)
            if remaining <= 0:
                break
            try:
                event = self._read_event(timeout=remaining)
            except socket.timeout:
                logger.warning('[ESL] 等待事件超时: %s', event_name)
                return None
            except Exception as e:
                logger.error('[ESL] 读取事件异常: %s', e)
                return None

            if not event:
                continue

            # 匹配事件名
            current_name = event.get('Event-Name', '')
            if current_name != event_name:
                # 不匹配的事件缓存到队列,供后续其他 wait_for_event 调用使用
                self._event_queue.append(event)
                continue

            # 匹配指定变量
            if match_vars:
                matched = True
                for key, value in match_vars.items():
                    if str(event.get(key, '')) != str(value):
                        matched = False
                        break
                if not matched:
                    # 不匹配的事件缓存到队列
                    self._event_queue.append(event)
                    continue

            logger.info('[ESL] 收到匹配事件: %s', event_name)
            return event

        logger.warning('[ESL] 等待事件超时: %s', event_name)
        return None


# ----------------------------------------------------------------------
# 主程序入口(用于独立测试ESL连接)
# ----------------------------------------------------------------------
if __name__ == '__main__':
    # ESL连接信息(对齐当前部署环境: <A服务器公网>)
    ESL_HOST = '<A服务器公网>'
    ESL_PORT = 18021
    ESL_PASSWORD = '<密码>'

    helper = EslHelper(ESL_HOST, ESL_PORT, ESL_PASSWORD)
    try:
        if helper.connect():
            # 查询当前通道数量
            count = helper.get_channel_count()
            print('当前通道数量: {}'.format(count))

            # 查询所有会议
            conferences = helper.conference_list()
            print('当前会议列表: {}'.format(conferences))

            # 打印通道详情
            channels = helper.show_channels()
            for ch in channels:
                print('通道: uuid={}, caller={}, callee={}'.format(
                    ch.get('uuid'),
                    ch.get('caller_id_number'),
                    ch.get('callee_id_number')
                ))
        else:
            print('ESL连接失败')
    finally:
        helper.disconnect()
