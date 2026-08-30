package cn.iocoder.yudao.module.ai.api.chat.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

/**
 * AI 聊天消息发送 Response DTO
 *
 * <p>返回对话编号与 AI 回复文本（{@code reply}），回复文本供调用方
 * 通过 TTS 合成播放。</p>
 *
 * @author cc
 */
@Schema(description = "RPC 调用 - AI 聊天消息发送 Response DTO")
@Data
public class AiChatSendMessageRespDTO {

    @Schema(description = "聊天对话编号（多轮对话复用）", example = "1024")
    private Long conversationId;

    @Schema(description = "AI 回复内容", example = "您好，请问有什么可以帮您？")
    private String reply;

}