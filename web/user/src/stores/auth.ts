import { computed, ref } from 'vue';
import { defineStore } from 'pinia';
import { accountApi } from '@/api/modules';
import { DEMO_SHOPPER } from '@/constants/trial';
import { useCartStore } from '@/stores/cart';

function hasUserSession(data: Record<string, any> | null | undefined): data is Record<string, any> {
  return !!data?.userId;
}

export const useAuthStore = defineStore('auth', () => {
  const userInfo = ref<Record<string, any> | null>(null);
  const isLoggedIn = computed(() => !!userInfo.value?.userId);
  const isTrial = computed(() => !!userInfo.value?.trial);
  const isPublishedShopper = computed(() =>
    String(userInfo.value?.email || '').trim().toLowerCase() === DEMO_SHOPPER.email);

  let sessionPromise: Promise<boolean> | null = null;
  let sessionReady = false;

  const loggingOut = ref(false);


  const clearAuth = () => {
    userInfo.value = null;
    sessionReady = false;
    try {
      useCartStore().resetCart();
    } catch {

    }
  };

  const fetchUserInfo = async () => {
    if (!isLoggedIn.value) return;
    userInfo.value = { ...(userInfo.value || {}), ...(await accountApi.getUserInfo()) };
  };

  const login = async (payload: Record<string, unknown>) => {
    const data = await accountApi.login({
      ...payload,
      password: String(payload.password ?? '')
    });
    userInfo.value = data;
    sessionReady = true;
    try {
      await fetchUserInfo();
    } catch {

    }
    try {
      await useCartStore().fetchCartCount();
    } catch {

    }
  };

  const prepareLogoutNavigation = () => {
    loggingOut.value = true;
  };

  const logout = async (silent = false) => {
    if (!silent && isLoggedIn.value) await accountApi.logout();
    clearAuth();
    const { reset } = await import('@/composables/useAgentSession');
    reset();
  };

  const finishLogoutNavigation = () => {
    loggingOut.value = false;
  };

  const ensureSession = (): Promise<boolean> => {
    if (sessionReady && isLoggedIn.value) return Promise.resolve(true);
    if (sessionPromise) return sessionPromise;

    sessionPromise = (async () => {
      try {
        const data = await accountApi.autoLogin();
        if (!hasUserSession(data)) {
          clearAuth();
          return false;
        }
        userInfo.value = data;
        sessionReady = true;
        try {
          await fetchUserInfo();
        } catch {

        }
            return true;
      } catch {
        clearAuth();
        return false;
      }
    })().finally(() => {
      sessionPromise = null;
    });

    return sessionPromise;
  };

  const autoLogin = ensureSession;

  let restorePromise: Promise<void> | null = null;
  const tryRestoreSession = (): Promise<void> => {
    if (sessionReady && isLoggedIn.value) return Promise.resolve();
    if (restorePromise) return restorePromise;
    restorePromise = (async () => {
      try {
        const data = await accountApi.autoLogin();
        if (hasUserSession(data)) {
          userInfo.value = data;
          sessionReady = true;
          try { await fetchUserInfo(); } catch {  }
              }
      } catch {

      } finally {
        restorePromise = null;
      }
    })();
    return restorePromise;
  };

  return {
    userInfo,
    isLoggedIn,
    isTrial,
    isPublishedShopper,
    loggingOut,
    login,
    logout,
    prepareLogoutNavigation,
    finishLogoutNavigation,
    fetchUserInfo,
    autoLogin,
    ensureSession,
    tryRestoreSession
  };
});
