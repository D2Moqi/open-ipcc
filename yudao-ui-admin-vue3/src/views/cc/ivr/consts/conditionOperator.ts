/**
 * IVR 判断器条件操作符常量
 * 涵盖空值判断、包含判断、等值比较、大小比较、长度比较、布尔判断共 18 种操作符
 */
export const CONDITION_OPERATOR = {
  IS_EMPTY: 'IS_EMPTY',
  IS_NOT_EMPTY: 'IS_NOT_EMPTY',
  CONTAINS: 'CONTAINS',
  NOT_CONTAINS: 'NOT_CONTAINS',
  EQ: 'EQ',
  NE: 'NE',
  GT: 'GT',
  GTE: 'GTE',
  LT: 'LT',
  LTE: 'LTE',
  LENGTH_EQ: 'LENGTH_EQ',
  LENGTH_NE: 'LENGTH_NE',
  LENGTH_GT: 'LENGTH_GT',
  LENGTH_GTE: 'LENGTH_GTE',
  LENGTH_LT: 'LENGTH_LT',
  LENGTH_LTE: 'LENGTH_LTE',
  IS_TRUE: 'IS_TRUE',
  IS_NOT_TRUE: 'IS_NOT_TRUE'
} as const

/**
 * 操作符 → 输入框类型映射
 * none：无需输入比较值（空值/布尔判断类）
 * text：文本输入框（包含/等值/不等判断类）
 * number：数字输入框（大小/长度比较类）
 */
export const OPERATOR_INPUT_TYPE: Record<string, 'none' | 'text' | 'number'> = {
  IS_EMPTY: 'none',
  IS_NOT_EMPTY: 'none',
  CONTAINS: 'text',
  NOT_CONTAINS: 'text',
  EQ: 'text',
  NE: 'text',
  GT: 'number',
  GTE: 'number',
  LT: 'number',
  LTE: 'number',
  LENGTH_EQ: 'number',
  LENGTH_NE: 'number',
  LENGTH_GT: 'number',
  LENGTH_GTE: 'number',
  LENGTH_LT: 'number',
  LENGTH_LTE: 'number',
  IS_TRUE: 'none',
  IS_NOT_TRUE: 'none'
}
