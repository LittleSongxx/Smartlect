<template>
  <section class="page">
    <header class="page-heading">
      <div>
        <p class="eyebrow">YOUR DATA</p>
        <h1>AI 数据与隐私</h1>
        <p class="muted">这里管理导购偏好与会话记忆，不是账号注销，也不会导出或删除订单、支付记录。</p>
      </div>
    </header>
    <p v-if="!session" class="panel muted" role="status">正在核对登录状态…</p>
    <p v-else-if="session.actor.subject_type !== 'user'" class="panel">
      请先<RouterLink :to="loginTo">登录</RouterLink>查看本人导购数据。访客咨询不会保存长期偏好。
    </p>
    <template v-else>
      <p v-if="error" class="notice error" role="alert">{{ error }}</p>
      <p v-if="notice" class="notice" role="status">{{ notice }}</p>
      <section class="panel">
        <h2>导购偏好</h2>
        <p class="muted">这些内容会帮助导购理解您，可随时删除。需要补充或改写时，请到购物偏好页。</p>
        <p v-if="!preferences.length" class="muted">暂无长期偏好。</p>
        <div v-for="item in preferences" :key="item.preference_key" class="preference-row">
          <div>
            <strong>{{ labels[item.preference_key] || item.preference_key }}</strong>
            <p>{{ formatPreference(item) }}</p>
            <small class="muted">{{ item.source === 'explicit' ? '您明确填写' : '会话推断' }} · 版本 {{ item.version }}</small>
          </div>
          <button type="button" :disabled="busy" @click="remove(item.preference_key)">删除</button>
        </div>
        <p class="actions"><RouterLink to="/shopping-profile">前往购物偏好</RouterLink></p>
      </section>
      <section class="panel">
        <h2>会话记忆</h2>
        <p class="muted">清除后，导购不再使用此前的对话摘要与已保存偏好。订单、支付与售后记录不受影响。</p>
        <button class="primary" type="button" :disabled="busy" @click="clearMemory">清除导购记忆与偏好</button>
      </section>
    </template>
  </section>
</template>
<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { aiGet, aiWrite, errorText, loadSession, ownerKey, session } from '@/api/client';
import { money } from '@/utils/assistant';
import { confirmAction } from '@/utils/confirm';
import { loginTarget } from '@/utils/navigation';

const preferences = ref<Record<string, any>[]>([]);
const busy = ref(false);
const error = ref('');
const notice = ref('');
const route = useRoute();
const loginTo = computed(() => loginTarget(route.path, route.fullPath));
const labels: Record<string, string> = {
  purpose: '主要用途',
  budget_max_cents: '最高预算',
  likes: '喜欢的特点',
  avoid: '希望避开的特点',
  categories: '关注品类'
};
const owner = computed(() => (session.value ? ownerKey(session.value.actor) : ''));

function formatPreference(item: Record<string, any>) {
  if (item.preference_key === 'budget_max_cents') return money(item.value);
  return Array.isArray(item.value) ? item.value.join('、') : item.value;
}

async function load() {
  if (session.value?.actor.subject_type !== 'user') return;
  const before = owner.value;
  try {
    const data = await aiGet<Record<string, any>[]>('/preferences');
    if (before === owner.value) preferences.value = data;
  } catch (reason) {
    error.value = errorText(reason);
  }
}

async function remove(preferenceKey: string) {
  if (busy.value) return;
  busy.value = true;
  error.value = '';
  notice.value = '';
  try {
    await aiWrite(`/preferences/${preferenceKey}`, undefined, 'DELETE');
    await load();
    notice.value = '偏好已删除。';
  } catch (reason) {
    error.value = errorText(reason);
  } finally {
    busy.value = false;
  }
}

async function clearMemory() {
  if (busy.value) return;
  const ok = await confirmAction('将清除导购会话记忆和已保存偏好。订单与支付记录不会删除。', {
    title: '清除导购数据',
    confirmButtonText: '清除'
  });
  if (!ok) return;
  busy.value = true;
  error.value = '';
  notice.value = '';
  try {
    await aiWrite('/memory', undefined, 'DELETE');
    await load();
    notice.value = '导购记忆与偏好已清除。';
  } catch (reason) {
    error.value = errorText(reason);
  } finally {
    busy.value = false;
  }
}

watch(owner, () => {
  preferences.value = [];
  error.value = '';
  notice.value = '';
  void load();
}, { immediate: true });

async function bootstrap() {
  if (session.value) return;
  try {
    await loadSession();
  } catch (reason) {
    error.value = errorText(reason);
  }
}

void bootstrap();
</script>
<style scoped>
.preference-row { display: flex; justify-content: space-between; align-items: center; gap: 18px; padding: 18px 0; border-bottom: 1px solid #e4d9c8; }
.preference-row:last-of-type { border-bottom: 0; }
.preference-row p { margin: 8px 0; }
.actions { margin: 16px 0 0; }
</style>
