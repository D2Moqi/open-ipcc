package cn.iocoder.yudao.module.ai.api.chat;

import cn.hutool.core.util.StrUtil;
import cn.iocoder.yudao.framework.common.pojo.CommonResult;
import cn.iocoder.yudao.module.ai.api.chat.dto.AiChatSendMessageReqDTO;
import cn.iocoder.yudao.module.ai.api.chat.dto.AiChatSendMessageRespDTO;
import cn.iocoder.yudao.module.ai.controller.admin.chat.vo.conversation.AiChatConversationCreateMyReqVO;
import cn.iocoder.yudao.module.ai.controller.admin.chat.vo.message.AiChatMessageSendReqVO;
import cn.iocoder.yudao.module.ai.controller.admin.chat.vo.message.AiChatMessageSendRespVO;
import cn.iocoder.yudao.module.ai.service.chat.AiChatConversationService;
import cn.iocoder.yudao.module.ai.service.chat.AiChatMessageService;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.annotation.Resource;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Primary;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.RestController;

import static cn.iocoder.yudao.framework.common.pojo.CommonResult.success;

/**
 * RPC 服务 - AI 聊天 {@link AiChatApi} 实现
 *
 * <p>供 IVR AI 对话节点等其它模块跨模块调用 AI 对话能力。
 * IVR 场景无登录态，创建对话与发送消息统一使用固定系统用户
 * （配置项 {@code cc.ai.system-user-id}），保证 {@code sendMessage}
 * 内部 conversation.userId 归属校验通过。</p>
 *
 * <p>标注 @Primary：聚合单体部署（yudao-server 单进程包含 ai-server）时
 * Feign 客户端因无注册中心不可用，容器内注入 {@link AiChatApi} 需优先
 * 本本地实现直连（无网络跳数）；分布式部署时本类不在调用方容器，
 * Feign 代理正常生效。</p>
 *
 * @author cc
 */
@Tag(name = "RPC 服务 - AI 聊天")
@RestController
@Validated
@Primary // 由于聚合单体中 AiChatApi 存在 Feign 代理 Bean，必须声明为 @Primary Bean 保证本地直连
public class AiChatApiImpl implements AiChatApi {

    @Resource
    private AiChatConversationService chatConversationService;
    @Resource
    private AiChatMessageService chatMessageService;

    /**
     * IVR 等无人值守场景固定使用的系统用户编号（可配置化，默认 1）
     */
    @Value("${cc.ai.system-user-id:1}")
    private Long systemUserId;

    @Override
    public CommonResult<Long> createConversation(Long roleId) {
        // 按聊天角色创建对话；会话归属固定系统用户，供后续 sendMessage 归属校验与上下文加载
        Long conversationId = chatConversationService.createChatConversationMy(
                new AiChatConversationCreateMyReqVO().setRoleId(roleId), systemUserId);
        return success(conversationId);
    }

    @Override
    public CommonResult<AiChatSendMessageRespDTO> sendMessage(AiChatSendMessageReqDTO req) {
        // 携带上下文(true)发送：AI 回复基于会话内历史消息，保证多轮对话延续性
        AiChatMessageSendRespVO resp = chatMessageService.sendMessage(
                new AiChatMessageSendReqVO().setConversationId(req.getConversationId())
                        .setContent(req.getContent()).setUseContext(true), systemUserId);
        String reply = resp != null && resp.getReceive() != null
                ? StrUtil.nullToDefault(resp.getReceive().getContent(), "") : "";
        return success(new AiChatSendMessageRespDTO().setConversationId(req.getConversationId()).setReply(reply));
    }

}