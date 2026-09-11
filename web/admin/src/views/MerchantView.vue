<template>
  <section class="growth-console" aria-label="商家经营助手">
    <div class="section-heading">
      <div>
        <h2>从新事实规划下一轮</h2>
        <p class="muted">先核对点击、费用、净成交与库存，再决定执行或等待。每次运行只产生一份计划。</p>
      </div>
      <button @click="refresh" :disabled="busy">刷新经营事实</button>
    </div>
    <p v-if="error" class="notice error" role="alert">
      {{ error }}
      <button v-if="draftRequired" type="button" @click="$emit('review-grant')">去活动页创建草稿</button>
    </p>
    <p v-if="notice || initialNotice" class="notice" role="status">{{ notice || initialNotice }}</p>
    <div class="stats">
      <article><span>最近观测净成交</span><strong><Price :price="netRevenue" /></strong></article>
      <article><span>最近观测退款</span><strong><Price :price="latestObservation?.summary?.refunded_cents" /></strong></article>
      <article><span>累计广告花费</span><strong><Price :price="snapshot.account?.spent_cents" /></strong></article>
      <article><span>累计授权上限</span><strong><Price :price="snapshot.account?.budget_cap_cents" /></strong></article>
    </div>
    <p class="muted">
      {{ latestObservation ? `最近规划观测于 ${timestamp(latestObservation.observed_at)}` : '尚未生成经营观测，请先在商城产生浏览或交易，再生成计划。' }}
      <template v-if="latestObservation">
        · 广告曝光 / 点击 {{ latestObservation.summary?.impressions ?? '未知' }} / {{ latestObservation.summary?.clicks ?? '未知' }}
        · 推荐曝光 / 点击 {{ latestObservation.summary?.recommendation_impressions ?? '未知' }} / {{ latestObservation.summary?.recommendation_clicks ?? '未知' }}
      </template>
    </p>
    <p class="notice" role="status">{{ nextStep }}</p>
    <p v-if="pollNotice" class="notice">{{ pollNotice }}</p>

    <section class="panel">
      <h2>经营计划</h2>
      <p v-if="!snapshot.plans.length" class="empty-state">暂无计划。先提交明确目标，等待服务器保存观测和计划。</p>
      <article v-for="(plan, planIndex) in snapshot.plans" :key="plan.plan_id" class="plan-card">
        <div class="section-heading">
          <div>
            <p class="muted">{{ planIndex === 0 ? '最新计划' : '历史计划' }}</p>
            <h3>{{ plan.spec?.objective }}</h3>
            <span class="badge" :class="badgeTone(plan.status)">{{ statusText(plan.status) }}</span>
            <span class="badge">{{ modeText(plan.spec?.model_mode) }}</span>
          </div>
          <div class="plan-budget">计划预算 <Price :price="plan.spec?.planned_budget_cents" /></div>
        </div>
        <p class="creative-copy">{{ plan.spec?.summary }}</p>
        <div class="meta-line">
          <span>适用产品：{{ (plan.spec?.product_scope || []).map(id => productName(id)).join('、') || '未报告' }}</span>
          <span>期间：{{ periodText(plan.spec?.period) }}</span>
        </div>
        <section v-if="plan.diagnosis?.length" class="diagnoses">
          <h4>候选解释与支持事实</h4>
          <article v-for="(item, index) in plan.diagnosis" :key="index">
            <strong>{{ diagnosisLabels[item.code] || item.code }}</strong>
            <p class="creative-copy">{{ item.explanation }}</p>
            <p class="muted">{{ item.evidence_ids?.length ? `已引用 ${item.evidence_ids.length} 条证据` : '未提供证据' }}</p>
            <GrowthTechDetails title="对应观测事实" :value="item.observed_facts" />
          </article>
          <p class="muted">候选解释不证明因果关系；证据不足时应继续观察。</p>
        </section>
        <h4>建议动作（{{ plan.spec?.actions?.length ?? 0 }}）</h4>
        <ol class="plan-actions">
          <li v-for="(action, index) in plan.spec?.actions || []" :key="index">
            <strong>{{ actionLabels[action.action_type] || action.action_type }}</strong>
            <template v-if="action.campaign_id"> · 指定活动</template>
            <template v-if="action.creative_id"> · 指定素材</template>
            · 所见版本 {{ action.expected_version }}
            <p v-if="action.budget_cents !== undefined">新活动预算 <Price :price="action.budget_cents" /></p>
            <p v-if="action.copy_text" class="creative-copy">{{ action.copy_text }}</p>
            <GrowthTechDetails title="完整动作、策略参数与依赖" :value="action" />
          </li>
        </ol>
        <h4>下一轮需要观察的信号</h4>
        <div class="chip-row">
          <span v-for="(signal, index) in plan.spec?.expected_signals || []" :key="index" class="signal-chip">{{ signal }}</span>
        </div>
        <p class="muted">{{ plan.spec?.evidence_ids?.length ? `引用 ${plan.spec.evidence_ids.length} 条证据` : '未提供引用证据' }}</p>
        <div class="button-row">
          <button v-if="plan.spec?.actions?.length" @click="execute(plan)" :disabled="busy || !canWrite || !!running">核对授权并执行 / 恢复回执</button>
          <button v-if="plan.spec?.actions?.length && (!plan.grant_id || ['WAIT_MERCHANT','WAIT_APPROVAL','WAIT_USER'].includes(plan.status))" @click="$emit('review-grant', plan)" :disabled="busy || !canWrite">查看计划并明确批准授权</button>
        </div>
        <p v-if="['WAIT_MERCHANT','WAIT_APPROVAL','WAIT_USER'].includes(plan.status)" class="notice">此计划等待商家批准授权范围。批准页面会绑定本计划与当前资源版本。</p>
        <p v-if="['WAIT_OUTCOME','WAIT_OBSERVATION'].includes(plan.status)" class="notice">等待下一轮实际新曝光、点击或 Java 结果；页面不会自动创建新的规划运行。</p>
        <GrowthTechDetails title="授权 hash、前后值与执行回执" :value="{ grant_id: plan.grant_id, envelope_hash: plan.envelope_hash, action_receipts: plan.action_receipts, spec: plan.spec }" />
      </article>
    </section>

    <form class="panel" @submit.prevent="start">
      <h3>准备下一轮经营</h3>
      <fieldset :disabled="busy || !canWrite || !!running">
        <label>目标和约束<textarea v-model="objective" rows="3" required maxlength="1000" :readonly="!!pendingStart" placeholder="例如：结合顾客浏览和成交结果，调整商品展示与推广文案。"></textarea></label>
        <details>
          <summary>规划范围与高级设置</summary>
          <fieldset>
            <legend>规划产品范围（不选则使用当前已建活动产品）</legend>
            <label v-for="product in products" :key="product.product_id" class="check">
              <input v-model="productScope" type="checkbox" :value="product.product_id" :disabled="!!pendingStart">{{ product.product_name }} · {{ product.product_id }}
            </label>
            <p v-if="catalogError" class="muted">{{ catalogError }}</p>
          </fieldset>
          <label>计划预算约束（可选，整数分；不代表批准）<input v-model="plannedBudget" inputmode="numeric" pattern="[0-9]*" :readonly="!!pendingStart" placeholder="留空使用当前已建活动预算总额"></label>
          <label>规划方式<select v-model="mode" :disabled="!!pendingStart">
            <option value="live">真实模型（服务器配置的 qwen3.7-plus）</option>
            <option value="rule">确定性规则基线</option>
          </select></label>
        </details>
        <button class="primary">{{ pendingStart ? '使用原请求 ID 重试' : '基于新观测生成计划' }}</button>
        <p v-if="pendingStart" class="muted">原请求 {{ pendingStart.request_id }} 的结果待核对。重试保留目标和模式，不创建另一个请求 ID。</p>
        <p class="muted">先在商城浏览、咨询或完成交易，再基于新观测生成计划。授权内动作可自动执行，越界时在“活动与授权”明确批准；之后回到商城查看新展示。</p>
      </fieldset>
    </form>

    <details class="panel advanced-panel">
      <summary>高级：观测明细、运行记录与经验审核</summary>
      <section class="panel">
        <h2>观测与证据</h2>
        <p v-if="!snapshot.observations.length" class="muted">尚无经营观测。</p>
        <article v-for="observation in snapshot.observations" :key="observation.observation_id" class="record">
          <div class="section-heading">
            <div>
              <h3>{{ timestamp(observation.observed_at) }}</h3>
              <p class="muted">轮次 {{ observation.round_id ?? '未报告' }} · 消费水位 {{ text(observation.watermark) }}</p>
            </div>
          </div>
          <div v-if="observationMetrics(observation.summary).length" class="metric-row">
            <span v-for="item in observationMetrics(observation.summary)" :key="item.key" class="metric-chip">
              {{ item.label }}
              <strong v-if="item.money"><Price :price="item.value" /></strong>
              <strong v-else>{{ item.value }}</strong>
            </span>
          </div>
          <p v-else class="creative-copy">{{ text(observation.summary) }}</p>
          <dl class="evidence-facts">
            <div v-for="fact in observation.facts || []" :key="fact.evidence_id">
              <dt>{{ fact.metric }}：{{ text(fact.value) }}</dt>
              <dd>{{ fact.evidence_id }} · {{ fact.kind }} · {{ fact.source }} · 发生 {{ timestamp(fact.occurred_at) }}</dd>
            </div>
          </dl>
          <GrowthTechDetails title="样本成熟度与活动指标" :value="{ maturity: observation.maturity, campaigns: observation.campaigns }" />
        </article>
      </section>
      <section class="panel">
        <h2>运行与实际模型用量</h2>
        <p v-if="!snapshot.runs.length" class="muted">暂无经营运行。</p>
        <article v-for="run in snapshot.runs" :key="run.agent_run_id" class="record">
          <div class="section-heading">
            <div>
              <strong>{{ run.agent_run_id }}</strong>
              <span class="badge" :class="badgeTone(run.state)">{{ statusText(run.state) }}</span>
              <span class="badge">{{ modeText(run.result?.model_mode || run.context?.model_mode || run.model_mode) }}</span>
              <p class="muted">创建 {{ timestamp(run.created_at) }}<template v-if="run.parent_run_id"> · 父运行 {{ run.parent_run_id }}</template></p>
            </div>
            <button @click="readRun(run.agent_run_id)" :disabled="busy">查询此运行</button>
          </div>
          <p v-if="run.state === 'RUNNING'" role="status">正在执行有界任务，页面只查询已保存进度。</p>
          <p class="muted">实际调用 {{ run.context?.model_calls ?? '未知' }} · 已记录尝试 {{ run.context?.model_attempts?.length ?? '未知' }} · 输入 Token {{ usage(run, 'input_tokens') ?? '未知' }} · 输出 Token {{ usage(run, 'output_tokens') ?? '未知' }} · 费用估算 ¥{{ usage(run, 'cost_estimate_cny') ?? '未知' }}</p>
          <GrowthDecisionCard :decision="run.result?.decision" :checks="run.result?.checks" />
          <GrowthTechDetails title="实际调用、版本、用量与结果凭据" :value="{ context: run.context, result: run.result }" />
        </article>
        <p v-if="pollNotice" class="notice">{{ pollNotice }}</p>
      </section>
      <section class="panel">
        <h2>经营经验审核</h2>
        <p class="muted">模型建议先保存为 DRAFT，人工认可后才可供后续经营使用。</p>
        <p v-if="!snapshot.memories.length" class="muted">暂无待审核经验。</p>
        <article v-for="memory in snapshot.memories" :key="memory.memory_id" class="record">
          <span class="badge" :class="badgeTone(memory.status)">{{ memory.status }}</span>
          {{ memory.memory_id }} · v{{ memory.version }}
          <p class="creative-copy">{{ text(memory.content) }}</p>
          <p class="muted">{{ memory.evidence_ids?.length ? `已引用 ${memory.evidence_ids.length} 条证据` : '未提供证据' }}</p>
          <button v-if="memory.status === 'DRAFT'" @click="reviewMemory = memory; reviewedContent = memory.content; memoryApproved = false" :disabled="busy || !canWrite">核对并批准这条经验</button>
        </article>
      </section>
      <form v-if="reviewMemory" class="panel operation" @submit.prevent="approveMemory">
        <h3>明确批准经营经验</h3>
        <h4>模型原草稿</h4>
        <p class="creative-copy">{{ text(reviewMemory.content) }}</p>
        <p>版本 {{ reviewMemory.version }} · 来源计划 {{ reviewMemory.plan_id }}</p>
        <p class="muted">{{ reviewMemory.evidence_ids?.length ? `已引用 ${reviewMemory.evidence_ids.length} 条证据` : '未提供证据' }}</p>
        <label>审核后可复用的正文<textarea v-model="reviewedContent" @input="memoryApproved = false" required maxlength="2000" rows="5" :disabled="busy"></textarea></label>
        <p class="muted">请删改缺乏证据的结论。只有下方明确批准的正文会供后续经营使用；原草稿仍保留在来源计划中。</p>
        <label class="check approval"><input v-model="memoryApproved" type="checkbox" required :disabled="busy">我已核对正文和证据，认可这条经验可供后续经营复用。</label>
        <div class="button-row">
          <button class="primary" :disabled="busy || !canWrite || !memoryApproved || !reviewedContent.trim()">批准此版本经验</button>
          <button type="button" @click="reviewMemory = null" :disabled="busy">暂不批准</button>
        </div>
      </form>
    </details>
  </section>
</template>
<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { session, aiGet, aiWrite, loadSession, errorText, timestamp, actionLabels, integer } from '../api/client';
import { hasAdminPermission } from '../utils/adminAccess';
import { badgeTone, diagnosisLabels, modeText, observationMetrics, periodText, productLabel, statusText, text } from '../utils/growthDisplay';
import GrowthTechDetails from '../components/GrowthTechDetails.vue';
import GrowthDecisionCard from '../components/GrowthDecisionCard.vue';
import Price from '../components/SmartlectPrice.vue';
defineProps({ initialNotice: { type: String, default: '' } });
defineEmits(['review-grant']);
const snapshot = ref({ observations: [], plans: [], runs: [], memories: [], account: null, grant: null });
const objective = ref('根据当前商品、顾客行为和交易结果，提出并执行授权范围内的下一步经营动作，说明依据与后续观察方式。');
const mode = ref('live'); const busy = ref(false); const error = ref(''); const notice = ref(''); const pendingStart = ref(null); const reviewMemory = ref(null); const memoryApproved = ref(false); const pollNotice = ref('');
const reviewedContent = ref('');
const products = ref([]); const productScope = ref([]); const plannedBudget = ref(''); const catalogError = ref('');
const canWrite = computed(() => hasAdminPermission(session.value?.actor, 'admin:legacy'));
const draftRequired = computed(() => error.value.includes('活动草稿') || error.value.includes('merchant_campaign_draft_required'));
const running = computed(() => snapshot.value.runs.find(run => run.state === 'RUNNING'));
const latestObservation = computed(() => snapshot.value.observations[0]);
const netRevenue = computed(() => {
  const summary = latestObservation.value?.summary;
  return Number.isSafeInteger(summary?.paid_cents) && Number.isSafeInteger(summary?.refunded_cents) ? summary.paid_cents - summary.refunded_cents : undefined;
});
const nextStep = computed(() => {
  if (running.value) return '正在基于新观测规划，本页会查询并展示本轮结果。';
  const plan = snapshot.value.plans[0];
  if (!plan) return '下一步：设定经营目标，生成第一份计划。首次启用推广需要明确批准授权范围。';
  if (['WAIT_MERCHANT', 'WAIT_APPROVAL', 'WAIT_USER'].includes(plan.status)) return '下一步：核对最新计划并明确批准所需授权，然后继续执行。';
  if (['FAILED', 'PARTIALLY_APPLIED', 'UNKNOWN', 'EXECUTING'].includes(plan.status)) return '下一步：查看原计划执行结果，先核对并恢复已有回执。';
  return '下一步：回到商城浏览调整后的商品或推广，产生新点击、咨询或交易，再基于新观测规划下一轮。';
});
const productName = (id) => productLabel(id, products.value);
let alive = true; let timer; let pollEpoch = 0;
function stopPolling() { clearTimeout(timer); pollEpoch++; }
function usage(run, key) {
  const calls = run.context?.model_attempts;
  if (!Array.isArray(calls) || !calls.length) return null;
  const values = calls.map(call => key === 'cost_estimate_cny' ? call.cost_estimate_cny : call.usage?.[key]);
  return values.every(value => typeof value === 'number' && Number.isFinite(value)) ? values.reduce((a,b) => a+b, 0) : null;
}
async function read() {
  const data = await aiGet('/merchant');
  if (!alive) return;
  snapshot.value = { ...data, observations: data.observations || [], plans: data.plans || [], runs: data.runs || [], memories: data.memories || [] };
}
async function readCatalog() { try { const result = await aiGet('/ads/catalog'); if (alive) { products.value = [...new Map(result.items.map(item => [item.product_id,item])).values()]; catalogError.value = ''; } } catch (reason) { catalogError.value = errorText(reason); } }
async function work(task) {
  if (busy.value) return; busy.value = true; error.value = ''; notice.value = '';
  try { await task(); } catch (reason) { error.value = errorText(reason); if (session.value) { try { await read(); } catch { /* Retain the original refusal. */ } } } finally { busy.value = false; }
}
function poll(run) {
  stopPolling(); pollNotice.value = ''; if (!run || run.state !== 'RUNNING') return;
  const epoch = pollEpoch; const deadline = Date.now() + 120000; let attempts = 0;
  const next = async () => {
    if (!alive || epoch !== pollEpoch) return;
    if (Date.now() >= deadline || attempts++ >= 60) { pollNotice.value = '本轮只读查询已达到上限；可手动刷新查看已保存结果。'; return; }
    try {
      const current = await aiGet(`/merchant/runs/${encodeURIComponent(run.agent_run_id)}`);
      if (!alive || epoch !== pollEpoch) return;
      const index = snapshot.value.runs.findIndex(item => item.agent_run_id === current.agent_run_id);
      if (index >= 0) snapshot.value.runs[index] = current;
      if (current.state !== 'RUNNING') { await read(); return; }
      timer = setTimeout(next, 2000);
    } catch (reason) { if (alive && epoch === pollEpoch) pollNotice.value = `${errorText(reason)} 已停止自动查询，可手动刷新；不会重新提交运行。`; }
  };
  timer = setTimeout(next, 2000);
}
async function refresh() { stopPolling(); await work(async () => { await loadSession(); await Promise.all([read(), readCatalog()]); poll(running.value); }); }
async function start() {
  if (running.value) return;
  await work(async () => {
    if (!objective.value.trim()) throw new Error('请填写明确的经营目标。');
    pendingStart.value ||= { request_id: crypto.randomUUID(), objective: objective.value.trim(), mode: mode.value, ...(productScope.value.length ? { product_scope: [...productScope.value] } : {}), ...(String(plannedBudget.value).trim() ? { planned_budget_cents: integer(plannedBudget.value, '计划预算') } : {}) };
    let run;
    try { run = await aiWrite('/merchant/runs', pendingStart.value); } catch (reason) { if (reason.status >= 400 && reason.status < 500) pendingStart.value = null; throw reason; }
    pendingStart.value = null;
    notice.value = run.plan_recovery_required ? '原计划执行结果尚未核对；请先恢复原计划回执。' : run.unchanged_observation ? '尚无新的成熟观测，本次未启动模型；等待实际新结果。' : '请求已保存；以下运行状态与结果来自服务器。';
    await read(); poll(run.agent_run_id ? run : running.value);
  });
}
async function readRun(id) { await work(async () => { const run = await aiGet(`/merchant/runs/${encodeURIComponent(id)}`); await read(); poll(run); }); }
async function execute(plan) { await work(async () => { await aiWrite(`/merchant/plans/${encodeURIComponent(plan.plan_id)}/execute`, { expected_version: plan.version }); notice.value = '执行器已返回；请核对授权、状态与逐项回执。'; await read(); }); }
async function approveMemory() {
  if (!memoryApproved.value) return;
  await work(async () => {
    if (!reviewedContent.value.trim()) throw new Error('请填写审核后可复用的正文。');
    await aiWrite(`/merchant/memories/${encodeURIComponent(reviewMemory.value.memory_id)}/approve`, { expected_version: reviewMemory.value.version, reviewed_content: reviewedContent.value });
    reviewMemory.value = null; memoryApproved.value = false; notice.value = '此版本经验的审批结果已保存。'; await read();
  });
}
onMounted(refresh);
onUnmounted(() => { alive = false; stopPolling(); });
</script>
