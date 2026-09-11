<template>
  <section class="page"><header class="page-heading"><div><p class="eyebrow">YOUR PREFERENCES</p><h1>告诉导购您在意什么</h1><p class="muted">这些偏好帮助导购理解您，随时可以修改或删除。不会替代您对交易的确认。</p></div></header>
    <p v-if="!session" class="panel muted" role="status">正在核对登录状态…</p>
    <p v-else-if="session.actor.subject_type !== 'user'" class="panel">请先<RouterLink :to="loginTo">登录</RouterLink>管理本人购物偏好。访客咨询无需保存长期偏好。</p>
    <template v-else>
      <p v-if="error" class="notice error" role="alert">{{ error }}</p><p v-if="notice" class="notice" role="status">{{ notice }}</p>
      <form class="panel preference-form" @submit.prevent="save">
        <label>偏好类型<select v-model="key" @change="input = ''"><option v-for="(label, name) in labels" :key="name" :value="name">{{ label }}</option></select></label>
        <label>{{ key === 'budget_max_cents' ? '最高预算（元）' : '偏好内容' }}<input v-model="input" :type="key === 'budget_max_cents' ? 'number' : 'text'" :step="key === 'budget_max_cents' ? '0.01' : undefined" min="0" maxlength="300" required :placeholder="arrayKeys.includes(key) ? '多个值以中文或英文逗号分隔' : ''" /></label>
        <button class="primary" type="submit" :disabled="busy">保存此项偏好</button>
      </form>
      <section class="panel"><h2>已保存的偏好</h2><p v-if="!preferences.length" class="muted">暂无长期偏好。</p>
        <div v-for="item in preferences" :key="item.preference_key" class="preference-row"><div><strong>{{ labels[item.preference_key] || item.preference_key }}</strong><p>{{ item.preference_key === 'budget_max_cents' ? money(item.value) : Array.isArray(item.value) ? item.value.join('、') : item.value }}</p>
          <small class="muted">{{ item.source === 'explicit' ? '您明确填写' : '会话推断' }} · 版本 {{ item.version }}</small></div>
          <button type="button" :disabled="busy" @click="remove(item.preference_key)">删除</button>
        </div>
      </section>
    </template>
  </section>
</template>
<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { aiGet, aiWrite, errorText, loadSession, ownerKey, session } from '@/api/client';
import { money } from '@/utils/assistant';
import { loginTarget } from '@/utils/navigation';
const preferences = ref<Record<string, any>[]>([]); const key = ref('purpose'); const input = ref('');
const busy = ref(false); const error = ref(''); const notice = ref('');
const route = useRoute();
const loginTo = computed(() => loginTarget(route.path, route.fullPath));
const labels: Record<string, string> = { purpose: '主要用途', budget_max_cents: '最高预算', likes: '喜欢的特点', avoid: '希望避开的特点', categories: '关注品类' };
const arrayKeys = ['likes', 'avoid', 'categories'];
const owner = computed(() => session.value ? ownerKey(session.value.actor) : '');
async function load() {
  if (session.value?.actor.subject_type !== 'user') return;
  const before = owner.value;
  try { const data = await aiGet<Record<string, any>[]>('/preferences'); if (before === owner.value) preferences.value = data; }
  catch (reason) { error.value = errorText(reason); }
}
async function save() {
  if (busy.value) return; busy.value = true; error.value = ''; notice.value = '';
  try {
    let value: string | string[] | number = String(input.value).trim();
    if (key.value === 'budget_max_cents') {
      if (!/^\d+(\.\d{1,2})?$/.test(value)) throw new Error('预算最多保留两位小数。');
      const [whole, fraction = ''] = value.split('.'); value = Number(whole) * 100 + Number(fraction.padEnd(2, '0'));
      if (!Number.isSafeInteger(value)) throw new Error('预算金额超出有效范围。');
    } else if (arrayKeys.includes(key.value)) value = value.split(/[,，]/).map((part) => part.trim()).filter(Boolean);
    await aiWrite(`/preferences/${key.value}`, { value }, 'PUT'); await load(); notice.value = '偏好已保存。'; input.value = '';
  } catch (reason) { error.value = errorText(reason); } finally { busy.value = false; }
}
async function remove(preferenceKey: string) {
  if (busy.value) return; busy.value = true; error.value = ''; notice.value = '';
  try { await aiWrite(`/preferences/${preferenceKey}`, undefined, 'DELETE'); await load(); notice.value = '偏好已删除。'; }
  catch (reason) { error.value = errorText(reason); } finally { busy.value = false; }
}
watch(owner, () => { preferences.value = []; input.value = ''; error.value = ''; notice.value = ''; void load(); }, { immediate: true });
async function bootstrap() {
  if (session.value) return;
  try { await loadSession(); } catch (reason) { error.value = errorText(reason); }
}
void bootstrap();
</script>
<style scoped>
.preference-form { max-width: 600px; }
.preference-row { display: flex; justify-content: space-between; align-items: center; gap: 18px; padding: 18px 0; border-bottom: 1px solid #e4d9c8; }
.preference-row:last-child { border-bottom: 0; }
.preference-row p { margin: 8px 0; }
</style>
