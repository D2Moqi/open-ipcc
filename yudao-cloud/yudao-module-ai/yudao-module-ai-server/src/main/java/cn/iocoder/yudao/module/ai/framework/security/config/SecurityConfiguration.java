package cn.iocoder.yudao.module.ai.framework.security.config;

import cn.iocoder.yudao.framework.security.config.AuthorizeRequestsCustomizer;
import cn.iocoder.yudao.module.ai.enums.ApiConstants;
import cn.hutool.core.util.StrUtil;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configurers.AuthorizeHttpRequestsConfigurer;

/**
 * AI 模块的 Security 配置
 */
@Configuration(proxyBeanMethods = false, value = "aiSecurityConfiguration")
public class SecurityConfiguration {

    @Value("${spring.ai.mcp.server.sse-endpoint:/sse}")
    private String mcpSseEndpoint;
    @Value("${spring.ai.mcp.server.sse-message-endpoint:/mcp/message}")
    private String mcpSseMessageEndpoint;
    @Value("${spring.ai.mcp.server.streamable-http-endpoint:/mcp}")
    private String mcpStreamableHttpEndpoint;

    @Bean("aiAuthorizeRequestsCustomizer")
    public AuthorizeRequestsCustomizer authorizeRequestsCustomizer() {
        return new AuthorizeRequestsCustomizer() {

            @Override
            public void customize(AuthorizeHttpRequestsConfigurer<HttpSecurity>.AuthorizationManagerRequestMatcherRegistry registry) {
                if (StrUtil.isNotBlank(mcpSseEndpoint)) {
                    registry.requestMatchers(mcpSseEndpoint).permitAll();
                }
                if (StrUtil.isNotBlank(mcpSseMessageEndpoint)) {
                    registry.requestMatchers(mcpSseMessageEndpoint).permitAll();
                }
                if (StrUtil.isNotBlank(mcpStreamableHttpEndpoint)) {
                    registry.requestMatchers(mcpStreamableHttpEndpoint).permitAll();
                }
                // RPC 端点放行：供其它模块（如 IVR AI 对话节点）经 Feign 跨进程调用。
                // 注意：AI 对话 sendMessage 每次调用产生真实模型费用，匿名放行存在被
                // 直连端口滥用消耗 token 的风险——与 system 模块 RPC 放行惯例一致，
                // 依赖部署侧网络隔离/网关内网策略收敛该风险，勿暴露到公网
                registry.requestMatchers(ApiConstants.PREFIX + "/**").permitAll();
            }

        };
    }

}
