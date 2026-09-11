<template>
  <section class="page">
    <header class="page-heading"><div><p class="eyebrow">YOUR ADDRESSES</p><h1>送到您指定的地方</h1><p class="muted">保存本人收货信息，下单确认卡会使用这里的地址。</p></div>
      <button type="button" :disabled="busy" @click="load">刷新地址</button></header>
    <p v-if="!session" class="panel muted" role="status">正在核对登录状态…</p>
    <p v-else-if="session.actor.subject_type !== 'user'" class="panel">请先<RouterLink :to="loginTo">登录</RouterLink>管理收货地址。</p>
    <p v-if="error" class="notice error" role="alert">{{ error }}</p>
    <p v-if="notice" class="notice" role="status">{{ notice }}</p>
    <template v-if="session?.actor.subject_type === 'user'">
      <article v-for="item in addresses" :key="item.addressId" class="panel">
        <p><strong>{{ item.addressee }}</strong> · {{ item.phone }}<span v-if="item.defaultType === 1" class="muted"> · 默认</span></p>
        <p>{{ item.address }}</p>
        <div class="actions-inline">
          <button type="button" :disabled="busy" @click="edit(item)">编辑</button>
          <button type="button" :disabled="busy || item.defaultType === 1" @click="makeDefault(item.addressId)">设为默认</button>
          <button type="button" :disabled="busy" @click="remove(item.addressId)">删除</button>
        </div>
      </article>
      <p v-if="!addresses.length && !busy" class="panel muted">还没有收货地址，请先添加一条。</p>
      <form class="panel" @submit.prevent="save">
        <h2>{{ form.addressId ? '编辑地址' : '新增地址' }}</h2>
        <label>收件人<input v-model="form.addressee" required maxlength="40" /></label>
        <label>手机号<input v-model="form.phone" required maxlength="20" /></label>
        <label>详细地址<textarea v-model="form.address" required maxlength="200" rows="3"></textarea></label>
        <label class="check"><input v-model="form.defaultType" type="checkbox" :true-value="1" :false-value="0" />设为默认地址</label>
        <div class="actions-inline">
          <button class="primary" type="submit" :disabled="busy">{{ form.addressId ? '保存修改' : '添加地址' }}</button>
          <button v-if="form.addressId" type="button" :disabled="busy" @click="resetForm">取消编辑</button>
        </div>
      </form>
    </template>
  </section>
</template>
<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { errorText, javaGet, javaPost, ownerKey, session } from '@/api/client';
import { loginTarget, safeNext } from '@/utils/navigation';
const addresses = ref<Record<string, any>[]>([]);
const busy = ref(false); const error = ref(''); const notice = ref('');
const route = useRoute(); const router = useRouter();
const owner = computed(() => session.value ? ownerKey(session.value.actor) : '');
const loginTo = computed(() => loginTarget(route.path, route.fullPath));
const form = reactive({ addressId: '', addressee: '', phone: '', address: '', defaultType: 0 });
function resetForm() { form.addressId = ''; form.addressee = ''; form.phone = ''; form.address = ''; form.defaultType = addresses.value.length ? 0 : 1; }
function edit(item: Record<string, any>) {
  form.addressId = item.addressId; form.addressee = item.addressee || ''; form.phone = item.phone || '';
  form.address = item.address || ''; form.defaultType = item.defaultType === 1 ? 1 : 0;
}
async function load() {
  if (session.value?.actor.subject_type !== 'user') { addresses.value = []; return; }
  const requested = owner.value; busy.value = true; error.value = '';
  try {
    const data = await javaGet('/userAddress/loadDataList');
    if (requested !== owner.value) return;
    addresses.value = Array.isArray(data) ? data : [];
    if (!form.addressId) form.defaultType = addresses.value.length ? 0 : 1;
  } catch (reason) { error.value = errorText(reason); }
  finally { busy.value = false; }
}
async function save() {
  if (busy.value) return; busy.value = true; error.value = ''; notice.value = '';
  try {
    const body: Record<string, string | number> = {
      addressee: form.addressee.trim(), phone: form.phone.trim(), address: form.address.trim(), defaultType: form.defaultType,
    };
    if (form.addressId) {
      await javaPost('/userAddress/updateAddress', { ...body, addressId: form.addressId });
      notice.value = '地址已更新。';
    } else {
      await javaPost('/userAddress/addAddress', body);
      notice.value = '地址已添加。';
    }
    resetForm(); await load();
    const next = safeNext(route.query.next, '');
    if (next && addresses.value.length) await router.replace(next);
  } catch (reason) { error.value = errorText(reason); }
  finally { busy.value = false; }
}
async function makeDefault(addressId: string) {
  if (busy.value) return; busy.value = true; error.value = '';
  try { await javaPost('/userAddress/updateDefault', { addressId }); notice.value = '已设为默认地址。'; await load(); }
  catch (reason) { error.value = errorText(reason); } finally { busy.value = false; }
}
async function remove(addressId: string) {
  if (busy.value) return; busy.value = true; error.value = '';
  try { await javaPost('/userAddress/delAddress', { addressId }); notice.value = '地址已删除。'; if (form.addressId === addressId) resetForm(); await load(); }
  catch (reason) { error.value = errorText(reason); } finally { busy.value = false; }
}
watch(owner, () => { addresses.value = []; resetForm(); void load(); }, { immediate: true });
</script>
<style scoped>
.check { display: flex; align-items: center; gap: 8px; }
</style>
