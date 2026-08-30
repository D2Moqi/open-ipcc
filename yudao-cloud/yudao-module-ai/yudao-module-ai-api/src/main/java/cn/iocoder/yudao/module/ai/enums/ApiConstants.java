package cn.iocoder.yudao.module.ai.enums;

import cn.iocoder.yudao.framework.common.enums.RpcConstants;

/**
 * AI 模块的 API 常量
 *
 * <p>提供 AI 模块对外暴露的 RPC 服务名与 API 前缀，供 Feign 接口
 * （如 {@code AiChatApi}）及服务端安全配置共用。</p>
 *
 * @author cc
 */
public interface ApiConstants {

    /**
     * 服务名（与 application.yaml 的 spring.application.name 一致）
     */
    String NAME = "ai-server";

    /**
     * API 前缀：所有 RPC 端点统一挂在 /rpc-api/ai 下
     */
    String PREFIX = RpcConstants.RPC_API_PREFIX + "/ai";

}