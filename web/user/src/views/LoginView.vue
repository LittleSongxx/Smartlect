<template>
  <section class="auth-page ignore login-page"><form class="auth-card login-panel" @submit.prevent="mode === 'register' ? register() : login()">
    <div class="auth-brand">
      <div class="auth-brand-text">
        <p class="eyebrow">Smartlect · 智选商城</p>
        <h1>{{ mode === 'register' ? '创建账号，开始选购' : '欢迎回来' }}</h1>
        <p class="brand-tip">{{ mode === 'register' ? '公开演示已关闭自行注册。' : '作品集试用只能逛店和问导购，不能下单或改资料。' }}</p>
      </div>
    </div>
    <div class="auth-form">
      <label class="field">邮箱<input v-model="email" type="email" autocomplete="username" required maxlength="150" /></label>
      <label v-if="mode === 'register'" class="field">昵称<input v-model="nickName" maxlength="20" required /></label>
      <label class="field">密码<input v-model="password" type="password" :autocomplete="mode === 'register' ? 'new-password' : 'current-password'" required /></label>
      <label v-if="!usingTrial" class="field">图片验证码<div class="captcha-row"><input v-model="code" autocomplete="off" required maxlength="10" /><button type="button" class="captcha-button" aria-label="刷新验证码" @click="captcha"><img v-if="captchaImage" :src="captchaImage" alt="登录验证码，点击刷新" /><span v-else>加载验证码</span></button></div></label>
      <p v-if="notice" class="notice" role="status">{{ notice }}</p>
      <p v-if="error" class="notice error" role="alert">{{ error }}</p>
      <button class="submit-btn" type="submit" :disabled="busy || (!usingTrial && !key)">{{ busy ? (mode === 'register' ? '正在注册…' : '正在登录…') : (mode === 'register' ? '注册' : '登录') }}</button>
      <div v-if="mode === 'login'" class="trial-box">
        <p class="trial-title">作品集试用（只读）</p>
        <p>邮箱 <code>{{ TRIAL_VISITOR.email }}</code></p>
        <p>密码 <code>{{ TRIAL_VISITOR.password }}</code></p>
        <p class="trial-note">账密已填好，点登录即可。不能下单、加购、改密、改地址或注册新号。</p>
      </div>
      <div class="auth-footer">
        <button v-if="PUBLIC_REGISTER_ENABLED" type="button" class="muted-link" @click="toggleMode">{{ mode === 'register' ? '已有账号？去登录' : '没有账号？注册' }}</button>
        <RouterLink v-if="mode === 'login'" class="muted-link" to="/forgot-password">找回密码</RouterLink>
        <button type="button" class="guest-link" @click="openAgent()">继续以访客身份咨询 →</button>
      </div>
    </div>
  </form></section>
</template>
<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { errorText, javaGet, javaPost, loadSession } from '@/api/client';
import { useAgentSession } from '@/composables/useAgentSession';
import { bindVisitor } from '@/api/traffic';
import { safeNext } from '@/utils/navigation';
import { useOpenAgent } from '@/composables/useOpenAgent';
import { useAuthStore } from '@/stores/auth';
import { PUBLIC_REGISTER_ENABLED, TRIAL_VISITOR } from '@/constants/trial';
const PASSWORD = /^(?=.*\d)(?=.*[a-zA-Z])[\da-zA-Z~!@#$%^&*_]{8,18}$/;
const email = ref(TRIAL_VISITOR.email); const password = ref<string>(TRIAL_VISITOR.password); const nickName = ref(''); const code = ref(''); const key = ref(''); const captchaImage = ref('');
const usingTrial = computed(() => mode.value === 'login'
  && email.value.trim().toLowerCase() === TRIAL_VISITOR.email
  && password.value === TRIAL_VISITOR.password);
const busy = ref(false); const error = ref(''); const notice = ref(''); const mode = ref<'login' | 'register'>('login');
const router = useRouter(); const route = useRoute(); const authStore = useAuthStore();
const { conversationId, reset, restore } = useAgentSession();
const { openAgent } = useOpenAgent();
async function captcha() {
  try { const result = await javaGet('/account/checkCode'); key.value = result.checkCodeKey; captchaImage.value = result.checkCode; code.value = ''; }
  catch (reason) { error.value = errorText(reason); }
}
function toggleMode() {
  if (!PUBLIC_REGISTER_ENABLED) return;
  mode.value = mode.value === 'login' ? 'register' : 'login';
  error.value = ''; notice.value = ''; password.value = ''; void captcha();
}
watch(usingTrial, (trial) => {
  if (!trial && !key.value) void captcha();
});
async function register() {
  if (busy.value) return;
  if (!PASSWORD.test(password.value)) { error.value = '密码需 8–18 位，并同时包含字母和数字。'; return; }
  busy.value = true; error.value = ''; notice.value = '';
  try {
    await javaPost('/account/register', {
      email: email.value, nickName: nickName.value.trim(), registerPassword: password.value,
      checkCodeKey: key.value, checkCode: code.value,
    });
    password.value = ''; mode.value = 'login'; notice.value = '注册成功，请登录。';
    await captcha();
  } catch (reason) { error.value = errorText(reason); await captcha(); }
  finally { busy.value = false; }
}
async function login() {
  if (busy.value) return; busy.value = true; error.value = ''; notice.value = '';
  const previousConversation = conversationId.value;
  try {
    const data = await javaPost('/account/login', {
      email: email.value,
      password: password.value,
      checkCodeKey: usingTrial.value ? '' : key.value,
      checkCode: usingTrial.value ? '' : code.value,
    });
    password.value = '';
    if (data?.userId) authStore.userInfo = data;
    await loadSession();
    const binding = await bindVisitor();
    reset();
    if (binding?.bound && previousConversation && binding.conversation_ids.includes(previousConversation)) await restore(previousConversation);
    await router.replace(safeNext(route.query.next || route.query.redirect, '/'));
  } catch (reason) { error.value = errorText(reason); if (!usingTrial.value) await captcha(); }
  finally { busy.value = false; }
}
onMounted(() => { if (!usingTrial.value) void captcha(); });
</script>
<style scoped lang="scss">
@use '@/styles/variables' as *;

.auth-page.ignore {
  box-sizing: border-box;
  width: 100%;
  max-width: 440px;
  display: flex;
  justify-content: center;
}

.auth-card {
  width: 100%;
  background: $color-card;
  border-radius: 16px;
  border: 1px solid $color-border-light;
  box-shadow: $shadow-card-hover;
  overflow: hidden;
}

.auth-brand {
  padding: 28px 28px 22px;
  background: linear-gradient(135deg, $color-primary 0%, $color-primary-hover 100%);
  color: #fff;
}

.eyebrow {
  margin: 0 0 8px;
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: rgba(255, 255, 255, 0.78);
}

h1 {
  margin: 0 0 8px;
  font-size: 26px;
  line-height: 1.3;
  color: #fff;
}

.brand-tip {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: rgba(255, 255, 255, 0.82);
}

.auth-form {
  display: flex;
  flex-direction: column;
  padding: 24px 28px 8px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
  margin: 0 0 16px;
  font-size: 13px;
  color: $color-text-body;
}

.field input {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid $color-border;
  border-radius: 12px;
  padding: 12px 14px;
  color: $color-text-title;
  background: #fff;
}

.captcha-row {
  display: flex;
  align-items: stretch;
  gap: 12px;
}

.captcha-row input {
  flex: 1;
  min-width: 0;
}

.captcha-button {
  flex: 0 0 148px;
  width: 148px;
  height: 48px;
  padding: 0;
  overflow: hidden;
  border: 1px solid $color-border;
  border-radius: 12px;
  background: $color-bg-subtle;
}

.captcha-button img,
.captcha-button span {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.captcha-button span {
  display: grid;
  place-items: center;
  font-size: 12px;
  color: $color-text-muted;
}

.notice {
  margin: 0 0 14px;
  padding: 12px 14px;
  border-radius: 12px;
  border: 1px solid $color-success-border;
  background: $color-success-soft;
  color: #24553a;
  font-size: 13px;
}

.notice.error {
  border-color: $color-error-border;
  background: $color-error-soft;
  color: #8a1c14;
}

.submit-btn {
  width: 100%;
  margin: 4px 0 8px;
  padding: 12px 16px;
  border: 0;
  border-radius: 12px;
  background: $color-primary;
  color: #fff;
  font-weight: 600;
}

.submit-btn:disabled {
  opacity: 0.48;
}

.auth-footer {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 8px 0 24px;
}

.muted-link,
.guest-link {
  border: 0;
  background: transparent;
  color: $color-primary;
  padding: 0;
  text-align: left;
  font-size: 13px;
}

.guest-link {
  color: $color-text-muted;
}

.trial-box {
  margin: 4px 0 16px;
  padding: 12px 14px;
  border-radius: 12px;
  border: 1px dashed $color-border;
  background: $color-bg-subtle;
  font-size: 13px;
  line-height: 1.6;
  color: $color-text-body;
}

.trial-title {
  margin: 0 0 6px;
  font-weight: 600;
  color: $color-text-title;
}

.trial-box p {
  margin: 0 0 4px;
}

.trial-box code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.trial-note {
  color: $color-text-muted;
}
</style>
