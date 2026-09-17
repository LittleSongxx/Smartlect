import { ref } from 'vue';
import { userMemberApi } from '@/api/modules';

export type CommentLevel = { levelCode: number; levelName: string };

/**
 * 评价列表里的会员等级徽章：两个详情页原来各写一份缓存 + 懒加载 + 标签类名，
 * 基线档类名不同（移动端 level-default / PC level-normal），所以按页传入。
 */
export function useCommentLevels(options: { baseClass?: string } = {}) {
  const levels = ref<Record<string, CommentLevel>>({});
  // 同一个用户在途请求只发一次：缓存要等响应回来才写，列表里出现重复行时原来会各发一次
  const pending = new Set<string>();

  const fetchLevel = (userId?: string | number) => {
    const key = String(userId ?? '');
    if (!key || levels.value[key] || pending.has(key)) return;
    pending.add(key);
    userMemberApi.getLevelBadge(key).then((res: any) => {
      if (res?.levelCode != null) {
        levels.value = { ...levels.value, [key]: res };
      }
    }).catch(() => { /* 等级只是装饰信息，取不到就不显示 */ })
      .finally(() => pending.delete(key));
  };

  /** 批量预热（列表渲染前调用），只对还没缓存的用户发请求。 */
  const fetchLevels = (rows: any[] | null | undefined, key = 'userId') => {
    rows?.forEach((row) => {
      const id = row?.[key];
      if (id) fetchLevel(String(id));
    });
  };

  /** 只读缓存；需要"缺失即拉取"的页面自行在调用前 fetchLevel。 */
  const getLevel = (userId?: string | number): CommentLevel | null => {
    const key = String(userId ?? '');
    return (key && levels.value[key]) || null;
  };

  const tagClass = (levelCode: number) => {
    if (levelCode >= 3) return 'level-gold';
    if (levelCode >= 2) return 'level-silver';
    return options.baseClass ?? 'level-default';
  };

  return { levels, fetchLevel, fetchLevels, getLevel, tagClass };
}
