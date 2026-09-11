<template>
  <main class="login-page"><div class="login-panel">
    <section class="panel-brand"><p class="eyebrow">SMARTLECT</p><h1>商家工作台</h1><p>把投放事实、授权范围和客服跟进放在同一张工作台上。</p><ul><li>活动、素材与库存</li><li>稳定授权与累计预算</li><li>知识与人工客服</li></ul><span class="badge">本地模拟经营</span></section>
    <section class="panel-form"><form @submit.prevent="login"><h2>管理员登录</h2><p class="muted">使用管理员账号和图片验证码进入当前店铺。</p>
      <label>账号<input v-model="form.account" required autocomplete="username" maxlength="150"></label>
      <label>密码<input v-model="form.password" required type="password" autocomplete="current-password"></label>
      <label>图片验证码<div class="captcha-row"><input v-model="form.checkCode" required autocomplete="off" maxlength="10"><button type="button" aria-label="刷新验证码" @click="captcha" :disabled="busy"><img v-if="captchaInfo.checkCode" :src="captchaInfo.checkCode" alt="登录验证码"><span v-else>加载验证码</span></button></div></label>
      <p v-if="error" role="alert" class="notice error">{{ error }}</p><button class="primary wide" type="submit" :disabled="busy || !captchaInfo.checkCodeKey">{{ busy ? '正在登录…' : '登录' }}</button>
    </form></section>
  </div></main>
</template>
<script setup>
import { onMounted, reactive, ref } from 'vue';
import { javaPost, loadSession, errorText } from '../api/client';
const form = reactive({ account: '', password: '', checkCode: '' });
const captchaInfo = ref({}); const busy = ref(false); const error = ref('');
async function captcha() {
  try { captchaInfo.value = await javaPost('/account/checkCode'); form.checkCode = ''; }
  catch (reason) { error.value = errorText(reason); }
}
async function login() {
  if (busy.value) return; busy.value = true; error.value = '';
  try { await javaPost('/account/login', { ...form, checkCodeKey: captchaInfo.value.checkCodeKey }); form.password = ''; await loadSession(); }
  catch (reason) { error.value = errorText(reason); await captcha(); }
  finally { busy.value = false; }
}
onMounted(captcha);
</script>
