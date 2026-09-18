<template>
  <div class="knowledge-page">
    <PageHeader title="知识文档与版本" description="草稿保存后单独发布，撤回后不再用于新的客服引用。">
      <template #actions>
        <el-select v-model="sourceFilter" aria-label="来源筛选" placeholder="全部来源" style="width: 150px">
          <el-option label="全部来源" value="" />
          <el-option label="手动编写" value="MANUAL" />
          <el-option label="商品自动导入" value="PRODUCT_AUTO" />
        </el-select>
        <el-button :disabled="busy || !canWrite" @click="importing = true">从商品导入</el-button>
        <el-button type="primary" :loading="busy" @click="refresh">刷新文档</el-button>
      </template>
    </PageHeader>

    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" class="table-gap" />
    <el-alert v-if="notice" type="success" :title="notice" show-icon :closable="false" class="table-gap" />

    <div class="table-data-card table-gap">
      <h4 class="card-title">创建草稿 / 新版本</h4>
      <el-form label-width="112px" class="doc-form" @submit.prevent="save">
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="稳定文档 ID">
              <el-input v-model="form.doc_id" maxlength="128" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="标题">
              <el-input v-model="form.title" maxlength="256" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="来源标识">
          <el-input v-model="form.source_uri" maxlength="512" placeholder="例如 smartlect:policy:returns" />
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="可见范围">
              <el-select v-model="form.acl" style="width: 100%">
                <el-option label="所有访客" value="PUBLIC" />
                <el-option label="已登录用户" value="USER" />
                <el-option label="商家" value="MERCHANT" />
                <el-option label="指定主体" value="ACTOR" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item v-if="form.acl === 'ACTOR'" label="指定主体 ID">
              <el-input v-model="form.acl_actor_id" maxlength="64" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="有效起始时间">
              <el-input v-model="form.valid_from" type="datetime-local" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="有效结束时间">
              <el-input v-model="form.valid_until" type="datetime-local" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-collapse class="doc-collapse">
          <el-collapse-item title="关联产品、类目和事实索引">
            <el-form-item label="产品 ID">
              <el-input v-model="productIds" placeholder="逗号分隔" />
            </el-form-item>
            <el-form-item label="类目 ID">
              <el-input v-model="categoryIds" placeholder="逗号分隔" />
            </el-form-item>
            <el-form-item label="事实索引 JSON">
              <el-input v-model="factsText" type="textarea" :rows="3" placeholder="值必须逐字出现在正文" />
            </el-form-item>
          </el-collapse-item>
        </el-collapse>
        <el-form-item label="正文">
          <el-input v-model="form.body" type="textarea" :rows="9" maxlength="40000" show-word-limit />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" native-type="submit" :disabled="uncertain || busy || !canWrite">保存新的 DRAFT 版本</el-button>
        </el-form-item>
        <el-alert
          v-if="uncertain"
          type="warning"
          :closable="false"
          show-icon
          title="保存结果待核对。先刷新文档列表，核实版本后再继续编辑。"
          class="table-gap"
        />
        <p class="muted-note">同一文档 ID 会新增版本；发布前请核对正文、范围与有效期。</p>
      </el-form>
    </div>

    <div class="table-data-card table-gap">
      <h4 class="card-title">商品投影与索引同步失败（自动重试 {{ opsNote }}）</h4>
      <el-alert v-if="opsSummaryError" type="info" :title="opsSummaryError" :closable="false" />
      <template v-else>
        <p class="muted-note">
          投影任务失败后每 60 秒自动重投（90 秒退避，至多 {{ projectionMaxAttempts }} 次）；
          索引任务失败需人工重试。Java 侧入队耗尽会落 MQ 补偿日志自动重放。
        </p>
        <el-table v-if="failedProjections.length" :data="failedProjections" stripe size="small" class="table-gap">
          <el-table-column prop="product_id" label="商品" width="140" />
          <el-table-column prop="attempt" label="尝试" width="70" />
          <el-table-column prop="error_type" label="错误" width="180" show-overflow-tooltip />
          <el-table-column prop="message" label="说明" min-width="200" show-overflow-tooltip />
          <el-table-column prop="updated_at" label="更新时间" width="180" />
          <el-table-column label="操作" width="110" fixed="right">
            <template #default="{ row }">
              <el-button size="small" @click="retryProjection(row.product_id)">重新入队</el-button>
            </template>
          </el-table-column>
        </el-table>
        <p v-else class="muted-note">没有失败的投影任务。</p>
        <el-table v-if="failedIndexJobs.length" :data="failedIndexJobs" stripe size="small" class="table-gap">
          <el-table-column prop="doc_id" label="文档" min-width="180" show-overflow-tooltip />
          <el-table-column prop="version" label="版本" width="70" />
          <el-table-column prop="error_type" label="错误" width="160" show-overflow-tooltip />
          <el-table-column prop="message" label="说明" min-width="200" show-overflow-tooltip />
          <el-table-column prop="updated_at" label="更新时间" width="180" />
          <el-table-column label="操作" width="110" fixed="right">
            <template #default="{ row }">
              <el-button size="small" @click="retryIndexJob(row.job_id)">重试索引</el-button>
            </template>
          </el-table-column>
        </el-table>
        <p v-else class="muted-note">没有失败的索引任务。</p>
      </template>
    </div>

    <div class="table-data-card table-gap">
      <h4 class="card-title">服务器文档列表</h4>
      <el-table v-loading="busy" :data="filteredDocuments" stripe size="small">
        <el-table-column prop="title" label="标题" min-width="180" show-overflow-tooltip />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <StatusTag :label="knowledgeStatusText(row.status)" :tone="badgeTone(row.status)" />
          </template>
        </el-table-column>
        <el-table-column label="来源" width="110">
          <template #default="{ row }">
            <StatusTag v-if="row.source_type === 'PRODUCT_AUTO'" label="商品自动" tone="info" />
            <span v-else class="muted-note">手动</span>
          </template>
        </el-table-column>
        <el-table-column label="范围" width="100">
          <template #default="{ row }">{{ aclText(row.acl) }}</template>
        </el-table-column>
        <el-table-column label="版本" width="70">
          <template #default="{ row }">v{{ row.version }}</template>
        </el-table-column>
        <el-table-column label="有效期" min-width="180">
          <template #default="{ row }">{{ timestamp(row.valid_from) }} — {{ timestamp(row.valid_until) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" :disabled="busy || !canWrite" @click="edit(row)">读取并编辑新版本</el-button>
            <el-button v-if="row.status === 'DRAFT'" link type="primary" :disabled="busy || !canWrite" @click="review(row, 'publish')">核对发布</el-button>
            <el-button v-if="row.status !== 'WITHDRAWN'" link :disabled="busy || !canWrite" @click="review(row, 'withdraw')">核对撤回</el-button>
          </template>
        </el-table-column>
        <template #empty><el-empty description="暂无文档。" :image-size="70" /></template>
      </el-table>
    </div>

    <div v-if="importing" class="table-data-card table-gap">
      <h4 class="card-title">从商品导入知识草稿</h4>
      <p class="muted-note">
        从 Java 商品服务拉取在售商品的描述/参数/价格库存，生成「商品自动」来源的 DRAFT 文档；重复导入按商品覆盖旧草稿，
        不碰手动文档与已发布版本。导入后请核对正文再发布。
      </p>
      <el-form label-width="96px" class="operation" @submit.prevent="submitImport">
        <el-form-item label="导入范围">
          <el-radio-group v-model="importForm.mode">
            <el-radio value="all">全部在售商品（每次最多 200 个）</el-radio>
            <el-radio value="ids">指定商品 ID</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="importForm.mode === 'ids'" label="商品 ID">
          <el-input v-model="importForm.ids" placeholder="例如 12, 15, 20" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" native-type="submit" :disabled="busy || !canWrite || (importForm.mode === 'ids' && !importForm.ids.trim())">开始导入</el-button>
          <el-button :disabled="busy" @click="importing = false">关闭</el-button>
        </el-form-item>
      </el-form>
    </div>

    <div v-if="selected" class="table-data-card table-gap">
      <h4 class="card-title">{{ selected.action === 'publish' ? '确认发布' : '确认撤回' }}：{{ selected.title }} · v{{ selected.version }}</h4>
      <el-form class="operation" @submit.prevent="transition">
        <p>文档 {{ selected.doc_id }}，范围 {{ selected.acl }}，有效期至 {{ timestamp(selected.valid_until) }}。</p>
        <el-collapse>
          <el-collapse-item title="本次所核对的正文">
            <p class="doc-body">{{ selected.body }}</p>
            <GrowthTechDetails
              title="校验信息"
              :value="{ checksum: selected.checksum, source_uri: selected.source_uri, acl: selected.acl, acl_actor_id: selected.acl_actor_id }"
            />
          </el-collapse-item>
        </el-collapse>
        <p v-if="selected.action === 'publish'" class="muted-note">
          发布后进入异步向量索引（未配置向量模型时直接以关键词检索上线）；进度在「AI 资产 · 知识索引」查看。
        </p>
        <el-form-item>
          <el-button type="primary" native-type="submit" :disabled="busy || !canWrite">确认{{ selected.action === 'publish' ? '发布此版本' : '撤回此版本' }}</el-button>
          <el-button :disabled="busy" @click="selected = null">关闭</el-button>
        </el-form-item>
      </el-form>
    </div>
  </div>
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
const sourceFilter = ref(''); const importing = ref(false); const importForm = reactive({ mode: 'all', ids: '' });
const filteredDocuments = computed(() => sourceFilter.value ? documents.value.filter(item => (item.source_type || 'MANUAL') === sourceFilter.value) : documents.value);
const canWrite = computed(() => hasAdminPermission(session.value?.actor, 'admin:legacy'));
async function work(task) { if (busy.value) return; busy.value = true; error.value = ''; notice.value = ''; try { await task(); } catch (reason) { error.value = errorText(reason); } finally { busy.value = false; } }
async function read() { documents.value = await aiGet('/knowledge'); }

// 商品投影 / 知识索引同步失败审计（C9）：只读汇总 + 两条人工重试通道
const opsSummary = ref(null); const opsSummaryError = ref('');
const failedProjections = computed(() => opsSummary.value?.projection?.failed || []);
const failedIndexJobs = computed(() => opsSummary.value?.index?.failed || []);
const projectionMaxAttempts = computed(() => opsSummary.value?.projection?.max_attempts || 3);
const opsNote = computed(() => opsSummary.value ? '' : '…');
async function readOps() {
  try { opsSummary.value = await aiGet('/knowledgeOps/summary'); opsSummaryError.value = ''; }
  catch (reason) { opsSummary.value = null; opsSummaryError.value = errorText(reason); }
}
async function retryProjection(productId) {
  await work(async () => {
    await aiWrite(`/productProjection/${encodeURIComponent(productId)}/retry`);
    notice.value = `商品 ${productId} 已重新入队`;
    await readOps();
  });
}
async function retryIndexJob(jobId) {
  await work(async () => {
    await aiWrite(`/knowledgeIndex/jobs/${encodeURIComponent(jobId)}/retry`);
    notice.value = '索引任务已按同一文档版本重新提交';
    await readOps();
  });
}
async function refresh() { await work(async () => { await loadSession(); await read(); await readOps(); uncertain.value = false; }); }
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
    notice.value = result.index_state === 'DONE'
      ? `已发布。索引任务 ${result.job_id.slice(0, 8)} 已记为同步发布（当前无向量密钥，检索走 BM25）；详情见「AI 资产 · 知识索引」。`
      : `已提交发布：向量索引任务 ${result.job_id.slice(0, 8)} 排队中，索引完成后自动上线；进度见「AI 资产 · 知识索引」。`;
  } else {
    notice.value = '生命周期操作已返回，当前版本如下。';
  }
  await read();
}); }
async function submitImport() { await work(async () => {
  const body = importForm.mode === 'ids'
    ? { productIds: importForm.ids.split(/[,，\s]+/).map(s => s.trim()).filter(Boolean) }
    : {};
  const summary = await aiWrite('/knowledgeImport/products', body);
  const parts = [`导入 ${summary.imported.length} 个`];
  if (summary.skipped.length) parts.push(`跳过 ${summary.skipped.length} 个（无可引用内容）`);
  if (summary.failed.length) parts.push(`失败 ${summary.failed.length} 个`);
  if (summary.published_pending_review.length) parts.push(`${summary.published_pending_review.length} 个商品存在已发布旧版，重导入后请确认是否撤回旧版`);
  if (summary.truncated) parts.push('本次已达 200 个上限，可再次执行继续导入');
  notice.value = parts.join('；') + '。' + (summary.note || '');
  importing.value = false; await read();
}); }
onMounted(refresh);
</script>

<style scoped lang="scss">
.knowledge-page {
  .table-gap {
    margin-bottom: 12px;
  }

  .card-title {
    margin: 0;
    padding: 14px 16px;
    font-size: 15px;
    color: var(--text);
    border-bottom: 1px solid var(--border-soft);
  }

  .doc-form {
    padding: 16px;
  }

  .doc-collapse {
    padding: 0 16px;
  }

  .doc-body {
    margin: 0;
    white-space: pre-wrap;
    color: var(--text);
  }

  :deep(.el-table .cell) {
    word-break: break-word;
  }
}
</style>
