package cn.iocoder.yudao.module.ai.api.chat;

import cn.iocoder.yudao.framework.common.pojo.CommonResult;
import cn.iocoder.yudao.module.ai.api.chat.dto.AiChatSendMessageReqDTO;
import cn.iocoder.yudao.module.ai.api.chat.dto.AiChatSendMessageRespDTO;
import cn.iocoder.yudao.module.ai.enums.ApiConstants;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;

/**
 * RPC 服务 - AI 聊天
 *
 * <p>供其它模块（如 IVR AI 对话节点）跨模块调用 AI 对话能力：
 * <ul>
 *   <li>{@link #createConversation}：按聊天角色创建对话，返回会话 ID</li>
 *   <li>{@link #sendMessage}：向指定会话发送消息，返回 AI 回复文本</li>
 * </ul>
 * 多轮对话复用同一会话 ID 保持上下文；AI 调用失败时返回错误码，调用方需自行降级。</p>
 *
 * <p>url 占位符 {@code ${cc.ai.server-url:}}：聚合单体部署时通过
 * {@code AiChatApiImpl} 本地直连（@Primary），该占位符仅 cc-server 独立进程
 * 直连 ai-server 场景使用（如本地联调指向聚合容器 48080）。</p>
 *
 * @author cc
 */
@FeignClient(name = ApiConstants.NAME, url = "${cc.ai.server-url:}") // TODO 芋艿：fallbackFactory =
@Tag(name = "RPC 服务 - AI 聊天")
public interface AiChatApi {

    String PREFIX = ApiConstants.PREFIX + "/chat";

    @PostMapping(PREFIX + "/conversation/create")
    @Operation(summary = "按聊天角色创建 AI 对话")
    @Parameter(name = "roleId", description = "聊天角色编号", required = true, example = "1")
    CommonResult<Long> createConversation(@RequestParam("roleId") Long roleId);

    @PostMapping(PREFIX + "/message/send")
    @Operation(summary = "向 AI 对话发送消息")
    CommonResult<AiChatSendMessageRespDTO> sendMessage(@Valid @RequestBody AiChatSendMessageReqDTO req);

}