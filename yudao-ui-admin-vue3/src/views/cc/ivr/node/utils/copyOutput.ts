/**
 * IVR 节点输出值剪贴板复制工具
 *
 * 背景：
 * 各组件（start/receive/method/transfer）的输出值（如 `${caller}`、`${result}`）
 * 需要被用户复制到后续组件的文本内容中作为变量引用。
 * 复制逻辑四处复用，统一收敛到本工具，避免重复实现。
 *
 * 兼容性策略：
 * 1. 优先使用标准 Clipboard API（navigator.clipboard.writeText，需安全上下文）；
 * 2. 不可用或失败时（如 http 非安全上下文、iframe 权限受限），
 *    降级为临时 textarea + document.execCommand('copy') 兜底。
 */

/**
 * 复制文本到系统剪贴板
 *
 * @param text - 待复制的文本内容（如 `${caller}`）
 * @returns 复制是否成功
 */
export async function copyTextToClipboard(text: string): Promise<boolean> {
  // 1. 优先标准 Clipboard API
  if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch (e) {
      console.warn('Clipboard API 复制失败，尝试降级方案', e)
    }
  }
  // 2. 降级：临时 textarea + execCommand（不阻断主流程，失败仅记录日志）
  try {
    const textarea = document.createElement('textarea')
    textarea.value = text
    textarea.setAttribute('readonly', '')
    textarea.style.position = 'fixed'
    textarea.style.left = '-9999px'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    const success = document.execCommand('copy')
    document.body.removeChild(textarea)
    return success
  } catch (e) {
    console.error('复制到剪贴板失败', e)
    return false
  }
}
