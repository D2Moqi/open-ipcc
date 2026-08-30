package cn.iocoder.yudao.module.ai.controller.admin.model.vo.chatRole;

import io.swagger.v3.oas.annotations.media.Schema;
import lombok.Data;

/**
 * AI 聊天角色精简 Response VO
 *
 * <p>供 IVR 设计器等公共场景下拉选择使用，仅暴露编号/名称/分类，
 * 不携带角色设定等敏感细节。</p>
 *
 * @author cc
 */
@Schema(description = "管理后台 - AI 聊天角色精简 Response VO")
@Data
public class AiChatRoleSimpleRespVO {

    @Schema(description = "编号", requiredMode = Schema.RequiredMode.REQUIRED, example = "1024")
    private Long id;

    @Schema(description = "角色名称", requiredMode = Schema.RequiredMode.REQUIRED, example = "客服")
    private String name;

    @Schema(description = "角色分类", example = "创作")
    private String category;

}