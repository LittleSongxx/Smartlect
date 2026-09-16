<template>
  <section class="growth-console">
    <div class="section-heading">
      <div>
        <h2>知识文档与版本</h2>
        <p class="muted">草稿保存后单独发布，撤回后不再用于新的客服引用。</p>
      </div>
      <button @click="refresh" :disabled="busy">刷新文档</button>
    </div>
    <p v-if="error" class="notice error" role="alert">{{ error }}</p>
    <p v-if="notice" class="notice" role="status">{{ notice }}</p>
    <form class="panel" @submit.prevent="save">
      <h3>创建草稿 / 新版本</h3>
      <fieldset :disabled="busy || !canWrite">
        <div class="two-columns">
          <label>稳定文档 ID<input v-model="form.doc_id" required maxlength="128"></label>
          <label>标题<input v-model="form.title" required maxlength="256"></label>
        </div>
        <label>来源标识<input v-model="form.source_uri" required maxlength="512" placeholder="例如 smartlect:policy:returns"></label>
        <div class="two-columns">
          <label>可见范围<select v-model="form.acl">
            <option value="PUBLIC">所有访客</option>
            <option value="USER">已登录用户</option>
            <option value="MERCHANT">商家</option>
            <option value="ACTOR">指定主体</option>
          </select></label>
          <label v-if="form.acl === 'ACTOR'">指定主体 ID<input v-model="form.acl_actor_id" required maxlength="64"></label>
        </div>
        <div class="two-columns">
          <label>有效起始时间<input v-model="form.valid_from" type="datetime-local" required></label>
          <label>有效结束时间<input v-model="form.valid_until" type="datetime-local" required></label>
        </div>
        <details>
          <summary>关联产品、类目和事实索引</summary>
          <label>产品 ID（逗号分隔）<input v-model="productIds"></label>
          <label>类目 ID（逗号分隔）<input v-model="categoryIds"></label>
          <label>事实索引 JSON（值必须逐字出现在正文）<textarea v-model="factsText" rows="3"></textarea></label>
        </details>
        <label>正文<textarea v-model="form.body" required rows="9" maxlength="40000"></textarea></label>
        <button class="primary" :disabled="uncertain">保存新的 DRAFT 版本</button>
        <p class="muted">同一文档 ID 会新增版本；发布前请核对正文、范围与有效期。</p>
        <p v-if="uncertain" class="notice">保存结果待核对。先刷新文档列表，核实版本后再继续编辑。</p>
      </fieldset>
    </form>
    <section class="panel">
      <h3>服务器文档列表</h3>
      <p v-if="!documents.length" class="empty-state">暂无文档。</p>
      <article v-for="item in documents" :key="`${item.doc_id}:${item.version}`" class="plan-card">
        <div class="section-heading">
          <div>
            <h3>{{ item.title }}</h3>
            <span class="badge" :class="badgeTone(item.status)">{{ knowledgeStatusText(item.status) }}</span>
            <span class="muted">{{ aclText(item.acl) }} · v{{ item.version }}</span>
            <p class="muted">{{ timestamp(item.valid_from) }} — {{ timestamp(item.valid_until) }}</p>
          </div>
          <div class="button-row">
            <button @click="edit(item)" :disabled="busy || !canWrite">读取并编辑新版本</button>
            <button v-if="item.status === 'DRAFT'" @click="review(item, 'publish')" :disabled="busy || !canWrite">核对发布</button>
            <button v-if="item.status !== 'WITHDRAWN'" @click="review(item, 'withdraw')" :disabled="busy || !canWrite">核对撤回</button>
          </div>
        </div>
        <GrowthTechDetails title="版本、校验和与发布凭据" :value="item" />
      </article>
    </section>
    <form v-if="selected" class="panel operation" @submit.prevent="transition">
      <h3>{{ selected.action === 'publish' ? '确认发布' : '确认撤回' }}：{{ selected.title }} · v{{ selected.version }}</h3>
      <p>文档 {{ selected.doc_id }}，范围 {{ selected.acl }}，有效期至 {{ timestamp(selected.valid_until) }}。</p>
      <details open>
        <summary>本次所核对的正文</summary>
        <p class="creative-copy">{{ selected.body }}</p>
        <GrowthTechDetails title="校验信息" :value="{ checksum: selected.checksum, source_uri: selected.source_uri, acl: selected.acl, acl_actor_id: selected.acl_actor_id }" />
      </details>
      <p v-if="selected.action === 'publish'" class="muted">发布后进入异步向量索引（未配置向量模型时直接以关键词检索上线）；进度在「AI 资产 · 知识索引」查看。</p>
      <div class="button-row">
        <button class="primary" :disabled="busy || !canWrite">确认{{ selected.action === 'publish' ? '发布此版本' : '撤回此版本' }}</button>
        <button type="button" @click="selected = null" :disabled="busy">关闭</button>
      </div>
    </form>
  </section>
</template>
<script setup>
import { computed, onMounted, reactive, ref } from 'vue';
import { session, aiGet, aiWrite, loadSession, errorText, timestamp } from '../api/client';
import { hasAdminPermission } from '../utils/adminAccess';
import { aclText, badgeTone, knowledgeStatusText } from '../utils/growthDisplay';
import GrowthTechDetails from '../components/GrowthTechDetails.vue';
const local = time => { const date = new Date(time); date.setMinutes(date.getMinutes() - date.getTimezoneOffset()); return date.toISOString().slice(0, 16); };
const form = reactive({ doc_id: crypto.randomUUID(), title: '', source_uri: '', language: 'zh-CN', acl: 'PUBLIC', acl_actor_id: '', body: '', valid_from: local(Date.now()), valid_until: local(Date.now() + 365 * 86400000) });
const productIds = ref(''); const categoryIds = ref(''); const factsText = ref('{}');
const documents = ref([]); const selected = ref(null); const busy = ref(false); const error = ref(''); const notice = ref(''); const uncertain = ref(false);
const canWrite = computed(() => hasAdminPermission(session.value?.actor, 'admin:legacy'));
async function work(task) { if (busy.value) return; busy.value = true; error.value = ''; notice.value = ''; try { await task(); } catch (reason) { error.value = errorText(reason); } finally { busy.value = false; } }
async function read() { documents.value = await aiGet('/knowledge'); }
async function refresh() { await work(async () => { await loadSession(); await read(); uncertain.value = false; }); }
async function save() {
  if (uncertain.value) return;
  await work(async () => {
    const payload = { ...form, product_ids: productIds.value.split(',').map(s => s.trim()).filter(Boolean), category_ids: categoryIds.value.split(',').map(s => s.trim()).filter(Boolean), facts: JSON.parse(factsText.value), valid_from: new Date(form.valid_from).toISOString(), valid_until: new Date(form.valid_until).toISOString() };
    if (payload.valid_from >= payload.valid_until) throw new Error('有效结束时间必须晚于开始时间。');
    if (form.acl !== 'ACTOR') delete payload.acl_actor_id;
    uncertain.value = true;
    const result = await aiWrite('/knowledge', payload); uncertain.value = false; notice.value = `已保存 ${result.doc_id} 的 DRAFT v${result.version}。`; await read();
  });
}
async function review(item, action) { await work(async () => { selected.value = { ...await aiGet(`/knowledge/${encodeURIComponent(item.doc_id)}/${item.version}`), action }; }); }
async function edit(item) { await work(async () => {
  const document = await aiGet(`/knowledge/${encodeURIComponent(item.doc_id)}/${item.version}`);
  for (const key of Object.keys(form)) if (document[key] !== undefined && document[key] !== null) form[key] = key.startsWith('valid_') ? local(document[key]) : document[key];
  productIds.value = (document.product_ids || []).join(','); categoryIds.value = (document.category_ids || []).join(','); factsText.value = JSON.stringify(document.facts || {}, null, 2); uncertain.value = false;
  notice.value = `已读取 ${item.doc_id} v${item.version}；保存时会新增 DRAFT 版本。`;
}); }
async function transition() { await work(async () => {
  const item = selected.value;
  const result = await aiWrite(`/knowledge/${encodeURIComponent(item.doc_id)}/${item.version}/${item.action}`, {});
  selected.value = null;
  if (item.action === 'publish' && result.job_id) {
    notice.value = `已提交发布：向量索引任务 ${result.job_id.slice(0, 8)} 排队中，索引完成后自动上线；进度见「AI 资产 · 知识索引」。`;
  } else {
    notice.value = '生命周期操作已返回，当前版本如下。';
  }
  await read();
}); }
onMounted(refresh);
</script>
