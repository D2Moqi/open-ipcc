/**
 * IVR 流程节点相关工具函数
 * 提供节点ID生成等辅助功能
 */

/**
 * 生成指定长度的随机数字字符串
 * 在 IVR 流程设计中主要用于生成临时节点ID或其他需要唯一标识符的场景
 * @param length - 要生成的随机字符串长度
 * @returns 指定长度的随机数字字符串
 */
export function generateRandomString(length: number) {
  // 初始化结果字符串
  let result = ''
  // 定义可用于生成随机字符串的字符集（仅包含数字）
  const characters = '0123456789'
  // 获取字符集长度，用于随机索引计算
  const charactersLength = characters.length
  
  // 循环生成指定长度的随机字符串
  for (let i = 0; i < length; i++) {
    // 随机选择字符集中的一个字符并追加到结果字符串中
    // Math.random() 生成0-1之间的随机数
    // Math.floor() 将结果向下取整，确保获得有效的字符索引
    result += characters.charAt(Math.floor(Math.random() * charactersLength))
  }
  
  // 返回生成的随机字符串
  return result
}
