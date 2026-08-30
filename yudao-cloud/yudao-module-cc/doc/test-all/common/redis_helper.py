# -*- coding: utf-8 -*-
"""
Redis 辅助模块
====================
需求背景:
    基于芋道(yudao-cloud)框架的呼叫中心系统测试脚本辅助模块。
    通过 Redis 连接远程缓存服务,用于场景7自动外呼任务上下文的预置与清理。

预期结果:
    提供统一的 Redis 访问封装,支持任务上下文的写入/查询/删除等操作,
    确保测试脚本可重复执行且幂等。

处理逻辑:
    - 使用 redis-py 同步客户端连接远程 Redis
    - 对齐 AutocallServiceImpl.saveTaskContext() 的任务上下文 JSON 格式
    - 任务上下文 key: autocall:task:{taskId}, TTL 24小时(与Java端一致)
"""

import json
import logging
from typing import Optional, Any

import redis

logger = logging.getLogger('RedisHelper')


class RedisHelper:
    """Redis 辅助类,用于自动外呼任务上下文等缓存操作"""

    # 自动外呼任务上下文 Redis Key 前缀(与 AutocallServiceImpl.AUTOCALL_TASK_KEY_PREFIX 一致)
    AUTOCALL_TASK_KEY_PREFIX = "autocall:task:"
    # 任务上下文 TTL(秒,24小时,与 AutocallServiceImpl.AUTOCALL_TASK_TTL_HOURS 一致)
    AUTOCALL_TASK_TTL_SECONDS = 24 * 3600

    def __init__(self, host: str, port: int, password: str = None, database: int = 0):
        """
        初始化 Redis 连接配置

        :param host: Redis 主机地址
        :param port: Redis 端口
        :param password: Redis 认证密码(可选)
        :param database: Redis 数据库索引(默认0)
        """
        self.host = host
        self.port = int(port)
        self.password = password
        self.database = database
        # Redis 客户端实例,connect() 成功后赋值
        self.client: Optional[redis.Redis] = None

    def connect(self) -> bool:
        """
        连接 Redis 服务器

        :return: 连接成功返回 True,失败返回 False
        处理逻辑:
            1. 创建 Redis 客户端实例,设置 5 秒连接超时
            2. 强制使用 RESP2 协议(protocol=2),避免 redis-py 6+ 默认尝试 HELLO 命令
               协商 RESP3 时,对端 Redis 服务器(版本较低不支持 HELLO 命令)报错的问题
            3. 发送 PING 命令验证连接可用性
            4. 异常时记录日志并返回 False
        """
        try:
            self.client = redis.Redis(
                host=self.host,
                port=self.port,
                password=self.password,
                db=self.database,
                socket_connect_timeout=5,
                socket_timeout=5,
                decode_responses=True,
                protocol=2,  # 强制 RESP2 协议,兼容不支持 HELLO 命令的 Redis 服务器
            )
            self.client.ping()
            logger.info("Redis 连接成功: %s:%s db=%s", self.host, self.port, self.database)
            return True
        except redis.RedisError as e:
            logger.error("Redis 连接失败: %s", e)
            self.client = None
            return False
        except Exception as e:
            logger.error("Redis 连接异常: %s", e)
            self.client = None
            return False

    def disconnect(self):
        """
        断开 Redis 连接

        处理逻辑: 关闭客户端连接并清理引用
        """
        if self.client:
            try:
                self.client.close()
            except Exception as e:
                logger.warning("Redis 关闭异常: %s", e)
            self.client = None
        logger.info("Redis 连接已断开")

    # ------------------------------------------------------------------
    # 自动外呼任务上下文操作
    # ------------------------------------------------------------------

    def save_autocall_task_context(self, task_id: str, ivr_flow: str,
                                   variables: dict = None, status: str = "dialing",
                                   tenant_id: int = 1) -> bool:
        """
        写入自动外呼任务上下文

        需求: 场景7自动外呼测试前,需预先在 Redis 中写入任务上下文,
              对齐 AutocallServiceImpl.saveTaskContext() 的正常业务流程
        预期结果: 任务上下文以 autocall:task:{taskId} 为 key 存储,TTL 24小时
        处理逻辑:
            1. 构建任务上下文 JSON(包含 taskId/ivrFlow/variables/status/startTime/tenantId)
            2. 使用 setex 设置 key 和 TTL
            3. 幂等保证: 同一 task_id 重复写入会覆盖旧值
            4. tenantId 必填: ESL 事件线程无租户上下文,需从任务上下文恢复 tenantId,
               否则挂断时 TenantUtils.execute 传 null 触发 NPE 导致 CDR 保存失败

        :param task_id: 外呼任务ID
        :param ivr_flow: IVR流程ID
        :param variables: 业务变量(可选,可传入TTS文本等)
        :param status: 任务状态(默认 dialing,与 Java 端一致)
        :param tenant_id: 租户ID(默认1,与本地开发环境默认租户一致)
        :return: 写入成功返回 True,失败返回 False
        """
        if not self.client:
            logger.error("Redis 未连接,无法写入任务上下文")
            return False

        import time
        key = self.AUTOCALL_TASK_KEY_PREFIX + task_id
        # 对齐 AutocallServiceImpl.saveTaskContext() 的 JSON 结构
        context = {
            "taskId": task_id,
            "ivrFlow": ivr_flow,
            "variables": variables if variables is not None else {},
            "status": status,
            "startTime": int(time.time() * 1000),  # 毫秒时间戳,对齐 System.currentTimeMillis()
            "tenantId": tenant_id,  # 透传租户ID,挂断时用于 CDR 按租户隔离保存
        }
        try:
            self.client.setex(key, self.AUTOCALL_TASK_TTL_SECONDS, json.dumps(context, ensure_ascii=False))
            logger.info("任务上下文已写入: key=%s, ivrFlow=%s, status=%s, tenantId=%s",
                        key, ivr_flow, status, tenant_id)
            return True
        except redis.RedisError as e:
            logger.error("写入任务上下文失败: key=%s, error=%s", key, e)
            return False

    def get_autocall_task_context(self, task_id: str) -> Optional[dict]:
        """
        查询自动外呼任务上下文

        :param task_id: 外呼任务ID
        :return: 任务上下文字典,不存在返回 None
        """
        if not self.client:
            logger.error("Redis 未连接,无法查询任务上下文")
            return None
        key = self.AUTOCALL_TASK_KEY_PREFIX + task_id
        try:
            value = self.client.get(key)
            if not value:
                return None
            return json.loads(value)
        except (redis.RedisError, json.JSONDecodeError) as e:
            logger.error("查询任务上下文失败: key=%s, error=%s", key, e)
            return None

    def delete_autocall_task_context(self, task_id: str) -> bool:
        """
        删除自动外呼任务上下文

        需求: 测试结束后清理任务上下文,确保测试幂等可重复
        预期结果: 删除指定 task_id 的任务上下文

        :param task_id: 外呼任务ID
        :return: 删除成功返回 True,失败返回 False
        """
        if not self.client:
            logger.error("Redis 未连接,无法删除任务上下文")
            return False
        key = self.AUTOCALL_TASK_KEY_PREFIX + task_id
        try:
            self.client.delete(key)
            logger.info("任务上下文已删除: key=%s", key)
            return True
        except redis.RedisError as e:
            logger.error("删除任务上下文失败: key=%s, error=%s", key, e)
            return False

    # ------------------------------------------------------------------
    # 通用 Redis 操作(供其他场景扩展使用)
    # ------------------------------------------------------------------

    def get(self, key: str) -> Optional[str]:
        """
        通用 GET 操作

        :param key: Redis key
        :return: value 字符串,不存在返回 None
        """
        if not self.client:
            return None
        try:
            return self.client.get(key)
        except redis.RedisError as e:
            logger.error("GET 失败: key=%s, error=%s", key, e)
            return None

    def setex(self, key: str, ttl_seconds: int, value: str) -> bool:
        """
        通用 SETEX 操作(带 TTL)

        :param key: Redis key
        :param ttl_seconds: TTL(秒)
        :param value: value 字符串
        :return: 成功返回 True,失败返回 False
        """
        if not self.client:
            return False
        try:
            self.client.setex(key, ttl_seconds, value)
            return True
        except redis.RedisError as e:
            logger.error("SETEX 失败: key=%s, error=%s", key, e)
            return False

    def delete(self, key: str) -> bool:
        """
        通用 DELETE 操作

        :param key: Redis key
        :return: 成功返回 True,失败返回 False
        """
        if not self.client:
            return False
        try:
            self.client.delete(key)
            return True
        except redis.RedisError as e:
            logger.error("DELETE 失败: key=%s, error=%s", key, e)
            return False
