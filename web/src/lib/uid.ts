/** 生成本地唯一 id（用于可编辑名单的本地行标识）。 */
export const uid = () => Math.random().toString(36).slice(2, 10)
