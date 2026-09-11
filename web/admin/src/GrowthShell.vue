<template>
  <p v-if="loading" class="loading" role="status">正在核对管理会话…</p>
  <Account v-else-if="!session" />
  <div v-else class="layout">
    <aside class="left-side"><div class="logo"><p class="eyebrow">SMARTLECT</p><strong>商家工作台</strong><p class="muted">智选商城经营助手</p></div>
      <nav aria-label="管理导航"><button v-for="item in pages" :key="item.id" :class="{ active: page === item.id }" :aria-current="page === item.id ? 'page' : undefined" @click="navigate(item.id)">{{ item.label }}</button></nav>
    </aside>
    <div class="right"><header class="top"><div><p class="eyebrow">SMARTLECT ADMIN</p><h1>{{ pages.find(item => item.id === page)?.label }}</h1></div><div class="top-actions"><span class="badge">{{ scopes.find(scope => scope.execution_scope_id === session.actor.execution_scope_id)?.label || '当前店铺' }}</span><details class="scope-settings"><summary>范围与会话</summary><label class="scope-picker">经营范围<select :value="session.actor.execution_scope_id" @change="changeScope($event.target.value)" :disabled="switchingScope || !scopes.length"><option v-for="scope in scopes" :key="scope.execution_scope_id" :value="scope.execution_scope_id">{{ scope.label }}</option></select></label><small>商家 {{ session.actor.actor_id }}</small></details><button @click="logout" :disabled="loggingOut || switchingScope">退出登录</button></div></header>
      <main :key="ownerKey(session)" class="right-body"><p v-if="error" role="alert" class="notice error">{{ error }}</p>
        <RouterView v-slot="{ Component }">
          <component :is="Component" :merchant-plan="page === 'ads' ? approvalPlan : null" :initial-notice="page === 'merchant' ? merchantNotice : ''" @grant-approved="grantApproved" @close-plan="navigate('merchant')" @review-grant="reviewGrant" />
        </RouterView>
      </main>
    </div>
  </div>
</template>
<script setup>
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { session, ownerKey, loadSession, javaPost, errorText, aiGet, selectScope } from './api/client';
import Account from './views/Account.vue';
const pages = [{ id: 'merchant', label: '经营助手' }, { id: 'ads', label: '活动与授权' }, { id: 'knowledge', label: '知识库' }, { id: 'support', label: '人工客服' }];
const router = useRouter();
const route = useRoute();
const page = computed(() => pages.some(item => item.id === route.name) ? route.name : 'merchant');
const loading = ref(true); const loggingOut = ref(false); const error = ref('');
const approvalPlan = ref(null); const merchantNotice = ref('');
const scopes = ref([]); const switchingScope = ref(false);
function navigate(id) { approvalPlan.value = null; merchantNotice.value = ''; router.push({ name: id }); }
function reviewGrant(plan) { approvalPlan.value = plan || null; merchantNotice.value = ''; router.push({ name: 'ads' }); }
function grantApproved() { approvalPlan.value = null; merchantNotice.value = '稳定授权已保存；请核对计划状态，并通过执行器继续或恢复原回执。'; router.push({ name: 'merchant' }); }
watch(() => ownerKey(session.value), async () => {
  approvalPlan.value = null; merchantNotice.value = ''; scopes.value = [];
  if (session.value) { try { scopes.value = (await aiGet('/scopes')).items; } catch (reason) { error.value = errorText(reason); } }
});
async function changeScope(id) {
  if (switchingScope.value || id === session.value?.actor.execution_scope_id) return;
  switchingScope.value = true; error.value = '';
  try { await selectScope(id); } catch (reason) { error.value = errorText(reason); } finally { switchingScope.value = false; }
}
onMounted(async () => { try { await loadSession(); } catch (reason) { if (reason.status !== 401) error.value = errorText(reason); } finally { loading.value = false; } });
async function logout() {
  if (loggingOut.value) return; loggingOut.value = true;
  try { await javaPost('/account/logout'); router.push({ name: 'merchant' }); } catch (reason) { error.value = errorText(reason); } finally { loggingOut.value = false; }
}
</script>
