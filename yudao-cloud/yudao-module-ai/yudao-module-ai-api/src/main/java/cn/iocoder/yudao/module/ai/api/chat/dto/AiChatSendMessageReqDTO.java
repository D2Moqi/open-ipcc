package cn.iocoder.yudao.module.ai.api.chat.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import lombok.Data;

/**
 * AI 聊天消息发送 Request DTO
 *
 * <p>供其它模块（如 IVR AI 对话节点）通过 {@code AiChatApi} 跨模块调用
 * AI 对话能力时使用；dialogue 内多轮对话复用同一 {@code conversationId} 保持上下文。</p>
 *
 * @author cc
 */
@Schema(description = "RPC 调用 - AI 聊天消息发送 Request DTO")
@Data
public class AiChatSendMessageReqDTO {

    @Schema(description = "聊天对话编号（多轮对话复用同一编号保持上下文）", requiredMode = Schema.RequiredMode.REQUIRED, example = "1024")
    @NotNull(message = "聊天对话编号不能为空")
    private Long conversationId;

    @Schema(description = "聊天内容", requiredMode = Schema.RequiredMode.REQUIRED, example = "你好")
    @NotEmpty(message = "聊天内容不能为空")
    private String content;

}