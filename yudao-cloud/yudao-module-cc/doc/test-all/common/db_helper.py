# -*- coding: utf-8 -*-
"""
MySQL 数据库校验辅助模块
========================
需求背景:
    基于芋道(yudao-cloud)框架的呼叫中心系统测试脚本辅助模块。
    通过 MySQL 连接远程数据库,验证通话记录、坐席状态、网关/路由配置等数据是否正确。

预期结果:
    提供统一的数据库访问封装,支持查询/校验/清理测试数据等操作。

修复说明:
    对齐当前数据库实际表结构:
    - cc_sys_agent: 使用 name 列(SIP 分机号), password 列(SIP 密码), 无 sip_number/sip_password 列
    - cc_sipproxy_gateway: 重构后新网关表, 使用 username/address/port/auth_type/transport_protocol/status 列
    - cc_call_route: 使用 route_num 列(号码模式), level 列(优先级), status 列(启用状态), flow_id 列(IVR 流程), 无 pattern/priority/gateway_id/enabled 列
    - cc_call_record: 增加 call_type 列(1-IVR/2-出局/3-内部/4-三方/5-双向/6-转接/7-自动外呼)
"""

import pymysql
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

logger = logging.getLogger('DbHelper')


class DbHelper:
    """MySQL 数据库校验辅助类,用于验证通话记录、坐席状态等数据"""

    def __init__(self, host: str, port: int, user: str, password: str, database: str):
        """
        初始化数据库连接配置

        :param host: 数据库主机地址
        :param port: 数据库端口
        :param user: 用户名
        :param password: 密码
        :param database: 数据库名
        """
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        # 数据库连接对象,延迟初始化,connect() 调用后赋值
        self.connection: Optional[pymysql.Connection] = None

    def connect(self) -> bool:
        """
        连接 MySQL 数据库

        :return: 连接成功返回 True,失败返回 False
        """
        try:
            self.connection = pymysql.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                database=self.database,
                charset='utf8mb4',
                cursorclass=pymysql.cursors.DictCursor
            )
            return True
        except Exception:
            self.connection = None
            return False

    def disconnect(self):
        """关闭数据库连接"""
        if self.connection is not None:
            try:
                self.connection.close()
            finally:
                self.connection = None

    def query(self, sql: str, params: tuple = None) -> List[Dict[str, Any]]:
        """
        执行查询 SQL,返回字典列表

        :param sql: SQL 语句
        :param params: 参数元组,用于参数化查询防注入
        :return: 查询结果列表,每行是字典;查询失败返回空列表
        """
        if self.connection is None:
            logger.error("[DB][query] connection is None")
            return []
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(sql, params)
                return cursor.fetchall()
        except Exception as e:
            logger.error("[DB][query] 查询异常: %s, sql=%s, params=%s", e, sql, params)
            # 连接可能已失效,尝试重连一次
            try:
                self.connect()
                with self.connection.cursor() as cursor:
                    cursor.execute(sql, params)
                    return cursor.fetchall()
            except Exception as e2:
                logger.error("[DB][query] 重连后查询仍失败: %s", e2)
                return []

    def execute(self, sql: str, params: tuple = None) -> int:
        """
        执行更新/删除 SQL,返回受影响行数

        :param sql: SQL 语句
        :param params: 参数元组
        :return: 影响行数,失败返回 0
        """
        if self.connection is None:
            return 0
        try:
            with self.connection.cursor() as cursor:
                affected = cursor.execute(sql, params)
                self.connection.commit()
                return affected
        except Exception:
            try:
                self.connection.rollback()
            except Exception:
                pass
            return 0

    # ==================== 通话记录查询 ====================

    def get_call_record_by_call_id(self, call_id: str) -> Optional[Dict]:
        """
        根据 call_id 查询通话记录

        :param call_id: 通话 ID
        :return: 通话记录字典,未找到返回 None
        """
        sql = """
              SELECT id,
                     call_id,
                     caller_number,
                     callee_number,
                     direction,
                     start_time,
                     answer_time,
                     end_time,
                     duration,
                     status,
                     agent_id,
                     gateway_id,
                     call_type,
                     tenant_id,
                     create_time
              FROM cc_call_record
              WHERE call_id = %s
                AND deleted = 0
              LIMIT 1 \
              """
        rows = self.query(sql, (call_id,))
        return rows[0] if rows else None

    def get_recent_call_records(self, limit: int = 10, agent_id: int = None) -> List[Dict]:
        """
        查询最近的通话记录

        :param limit: 返回数量,默认 10
        :param agent_id: 坐席 ID 过滤(可选)
        :return: 通话记录列表
        """
        if agent_id is not None:
            sql = """
                  SELECT id,
                         call_id,
                         caller_number,
                         callee_number,
                         direction,
                         start_time,
                         answer_time,
                         end_time,
                         duration,
                         status,
                         agent_id,
                         gateway_id,
                         call_type,
                         create_time
                  FROM cc_call_record
                  WHERE deleted = 0
                    AND agent_id = %s
                  ORDER BY start_time DESC
                  LIMIT %s \
                  """
            return self.query(sql, (agent_id, limit))
        else:
            sql = """
                  SELECT id,
                         call_id,
                         caller_number,
                         callee_number,
                         direction,
                         start_time,
                         answer_time,
                         end_time,
                         duration,
                         status,
                         agent_id,
                         gateway_id,
                         call_type,
                         create_time
                  FROM cc_call_record
                  WHERE deleted = 0
                  ORDER BY start_time DESC
                  LIMIT %s \
                  """
            return self.query(sql, (limit,))

    def get_call_records_by_time_range(self, start_time: datetime, end_time: datetime) -> List[Dict]:
        """
        按时间范围查询通话记录

        :param start_time: 开始时间
        :param end_time: 结束时间
        :return: 通话记录列表
        """
        sql = """
              SELECT id,
                     call_id,
                     caller_number,
                     callee_number,
                     direction,
                     start_time,
                     answer_time,
                     end_time,
                     duration,
                     status,
                     agent_id,
                     gateway_id,
                     call_type,
                     create_time
              FROM cc_call_record
              WHERE deleted = 0
                AND start_time >= %s
                AND start_time <= %s
              ORDER BY start_time ASC \
              """
        return self.query(sql, (start_time, end_time))

    def count_call_records_since(self, start_time: datetime) -> int:
        """
        统计指定时间后的通话记录数(用于验证新通话是否生成记录)

        :param start_time: 开始时间
        :return: 记录数
        """
        sql = """
              SELECT COUNT(*) AS cnt
              FROM cc_call_record
              WHERE deleted = 0
                AND create_time >= %s \
              """
        rows = self.query(sql, (start_time,))
        if not rows:
            return 0
        return int(rows[0].get('cnt', 0))

    def verify_call_record_exists(self, call_id: str, caller: str = None,
                                  callee: str = None, direction: str = None,
                                  call_type: int = None) -> bool:
        """
        验证通话记录是否存在并匹配条件

        :param call_id: 通话 ID
        :param caller: 主叫号码(可选校验)
        :param callee: 被叫号码(可选校验)
        :param direction: 呼叫方向(incoming/outgoing)
        :param call_type: 通话类型(1-IVR/2-出局/3-内部/4-三方/5-双向/6-转接/7-自动外呼)
        :return: 验证通过返回 True
        """
        record = self.get_call_record_by_call_id(call_id)
        if record is None:
            return False
        if caller is not None and str(record.get('caller_number', '')) != str(caller):
            return False
        if callee is not None and str(record.get('callee_number', '')) != str(callee):
            return False
        if direction is not None and str(record.get('direction', '')) != str(direction):
            return False
        if call_type is not None and int(record.get('call_type', 0)) != int(call_type):
            return False
        return True

    # ==================== 坐席信息查询 ====================

    def get_agent_by_sip_number(self, sip_number: str) -> Optional[Dict]:
        """
        根据 SIP 号码查询坐席信息

        需求: 通过 SIP 分机号定位坐席(对应 cc_sys_agent.name 列)。
        :param sip_number: SIP 号码(对应 name 列)
        :return: 坐席信息字典
        """
        sql = """
              SELECT id,
                     user_id,
                     name,
                     password,
                     domain,
                     status,
                     online_status,
                     tenant_id
              FROM cc_sys_agent
              WHERE name = %s
                AND deleted = 0
              LIMIT 1 \
              """
        rows = self.query(sql, (sip_number,))
        return rows[0] if rows else None

    def get_agent_online_status(self, sip_number: str) -> int:
        """
        查询坐席在线状态

        :param sip_number: SIP 号码
        :return: 在线状态(0 离线/1 就绪/2 忙碌)
        """
        agent = self.get_agent_by_sip_number(sip_number)
        if agent is None:
            return 0
        return int(agent.get('online_status', 0))

    def update_agent_online_status(self, sip_number: str, status: int) -> bool:
        """
        更新坐席在线状态(测试前重置用)

        :param sip_number: SIP 号码
        :param status: 在线状态(0 离线/1 就绪/2 忙碌)
        :return: 成功返回 True
        """
        sql = """
              UPDATE cc_sys_agent
              SET online_status = %s,
                  update_time   = NOW()
              WHERE name = %s
                AND deleted = 0 \
              """
        affected = self.execute(sql, (status, sip_number))
        return affected > 0

    def reset_agent_status(self, sip_number: str) -> bool:
        """
        重置坐席状态为离线(测试前清理用)

        :param sip_number: SIP 号码
        :return: 成功返回 True
        """
        return self.update_agent_online_status(sip_number, 0)

    # ==================== 网关查询 ====================

    def get_all_gateways(self) -> List[Dict]:
        """
        查询所有外部网关(type=2)

        :return: 网关列表
        """
        sql = """
              SELECT id,
                     name,
                     username,
                     password,
                     auth_address,
                     address,
                     port,
                     auth_type,
                     transport_protocol,
                     type,
                     external_line_number,
                     tenant_id,
                     status
              FROM cc_sipproxy_gateway
              WHERE deleted = 0
                AND type = 2
              ORDER BY id ASC \
              """
        return self.query(sql)

    def get_gateway_by_name(self, name: str) -> Optional[Dict]:
        """
        根据名称查询网关

        :param name: 网关名称
        :return: 网关信息字典
        """
        sql = """
              SELECT id,
                     name,
                     username,
                     password,
                     auth_address,
                     address,
                     port,
                     auth_type,
                     transport_protocol,
                     type,
                     external_line_number,
                     tenant_id,
                     status
              FROM cc_sipproxy_gateway
              WHERE name = %s
                AND deleted = 0
              LIMIT 1 \
              """
        rows = self.query(sql, (name,))
        return rows[0] if rows else None

    def get_gateway_by_id(self, gateway_id: int) -> Optional[Dict]:
        """
        根据 ID 查询网关

        :param gateway_id: 网关 ID
        :return: 网关信息字典
        """
        sql = """
              SELECT id,
                     name,
                     username,
                     password,
                     auth_address,
                     address,
                     port,
                     auth_type,
                     transport_protocol,
                     type,
                     external_line_number,
                     tenant_id,
                     status
              FROM cc_sipproxy_gateway
              WHERE id = %s
                AND deleted = 0
              LIMIT 1 \
              """
        rows = self.query(sql, (gateway_id,))
        return rows[0] if rows else None

    # ==================== 路由查询 ====================

    def get_all_routes(self) -> List[Dict]:
        """
        查询所有启用的呼叫路由(status=1)

        :return: 路由列表,按 level 升序(数字越小优先级越高)
        """
        sql = """
              SELECT id,
                     name,
                     route_num,
                     type,
                     level,
                     status,
                     flow_id,
                     tenant_id
              FROM cc_call_route
              WHERE deleted = 0
                AND status = 1
              ORDER BY level ASC, id ASC \
              """
        return self.query(sql)

    def get_route_by_pattern(self, pattern: str) -> Optional[Dict]:
        """
        根据号码模式查询路由(精确匹配 route_num)

        :param pattern: 号码模式
        :return: 路由信息字典
        """
        sql = """
              SELECT id,
                     name,
                     route_num,
                     type,
                     level,
                     status,
                     flow_id,
                     tenant_id
              FROM cc_call_route
              WHERE route_num = %s
                AND deleted = 0
              LIMIT 1 \
              """
        rows = self.query(sql, (pattern,))
        return rows[0] if rows else None

    def get_routes_by_type(self, route_type: int) -> List[Dict]:
        """
        根据路由类型查询路由

        :param route_type: 路由类型(1-呼入/2-呼出)
        :return: 路由列表
        """
        sql = """
              SELECT id,
                     name,
                     route_num,
                     type,
                     level,
                     status,
                     flow_id,
                     tenant_id
              FROM cc_call_route
              WHERE deleted = 0
                AND type = %s
                AND status = 1
              ORDER BY level ASC, id ASC \
              """
        return self.query(sql, (route_type,))

    # ==================== FS 配置查询 ====================

    def get_all_fs_configs(self) -> List[Dict]:
        """
        查询所有 FS 实例配置

        :return: FS 配置列表
        """
        sql = """
              SELECT id,
                     name,
                     `group`,
                     ip,
                     port,
                     transport_protocol,
                     esl_port,
                     password,
                     status,
                     out_time,
                     tenant_id
              FROM cc_fs_config
              WHERE deleted = 0
              ORDER BY id ASC \
              """
        return self.query(sql)

    def get_fs_config_by_name(self, name: str) -> Optional[Dict]:
        """
        根据名称查询 FS 实例配置

        :param name: FS 实例名称
        :return: FS 配置字典
        """
        sql = """
              SELECT id,
                     name,
                     `group`,
                     ip,
                     port,
                     esl_port,
                     password,
                     status,
                     out_time,
                     tenant_id
              FROM cc_fs_config
              WHERE name = %s
                AND deleted = 0
              LIMIT 1 \
              """
        rows = self.query(sql, (name,))
        return rows[0] if rows else None

    # ==================== 测试数据清理 ====================

    def cleanup_test_data(self, before_time: datetime):
        """
        清理测试数据(删除指定时间后的通话记录)

        :param before_time: 删除此时间之后的记录
        """
        sql = """
              DELETE
              FROM cc_call_record
              WHERE create_time > %s \
              """
        self.execute(sql, (before_time,))

    def reset_all_agents_offline(self) -> int:
        """
        重置所有坐席为离线状态(测试前清理用)

        :return: 受影响行数
        """
        sql = """
              UPDATE cc_sys_agent
              SET online_status = 0,
                  update_time   = NOW()
              WHERE deleted = 0 \
              """
        return self.execute(sql)
