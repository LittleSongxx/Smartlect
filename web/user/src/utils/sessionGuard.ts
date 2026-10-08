import { ElMessageBox } from 'element-plus';
import router from '@/router';
import { loadSession } from '@/api/client';

// 身份失效分两类，引导完全不同：
//   NEEDS_LOGIN —— 确实需要登录态才能继续（未登录点下单、登录已过期）→ 弹窗引导去登录页
//   VISITOR_STALE —— 访客凭证过期，服务端已按新访客重新签发 → 静默重建会话，
//                    不该把一个本来就能逛能问客服的访客赶去登录
const NEEDS_LOGIN = new Set(['login_required', 'user_required', 'invalid_session']);
const VISITOR_STALE = new Set(['invalid_visitor', 'ambiguous_session_cookie']);

let prompting = false;

/**
 * 提示需要登录并引导去登录页。组件里发现「未登录就点了要登录的操作」时直接调用，
 * 省得每个入口各写一遍跳转——登录后按 redirect 回到原处（或指定落点）。
 */
export function promptLogin(redirect?: string) {
  const current = router.currentRoute.value;
  if (prompting || current.path === '/login') {
    return;
  }
  const target = redirect || current.fullPath;
  prompting = true;
  ElMessageBox.confirm('当前操作需要登录，登录后会自动回到这一页。', '请先登录', {
    confirmButtonText: '去登录',
    cancelButtonText: '留在此页',
    type: 'warning',
    distinguishCancelAndClose: true,
    closeOnClickModal: false,
  })
    .then(() => router.push({ path: '/login', query: { redirect: target } }))
    .catch(() => undefined)
    .finally(() => { prompting = false; });
}

/** 统一接管身份失效：需要登录的弹窗引导，访客凭证过期的静默重建。 */
export function installSessionGuard() {
  window.addEventListener('smartlect:identity-changed', (event) => {
    const reason = (event as CustomEvent<{ reason?: string }>).detail?.reason ?? '';
    if (VISITOR_STALE.has(reason)) {
      void loadSession().catch(() => undefined);
      return;
    }
    // 401 但没带原因码时同样按「需要登录」处理，避免用户停在没有任何提示的错误上
    if (NEEDS_LOGIN.has(reason) || reason === '') {
      promptLogin();
    }
  });
}
