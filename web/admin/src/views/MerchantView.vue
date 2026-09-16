<template>
  <div class="merchant-page" aria-label="商家经营助手">
    <PageHeader title="从新事实规划下一轮" description="先核对点击、费用、净成交与库存，再决定执行或等待。每次运行只产生一份计划。">
      <template #actions>
        <el-button type="primary" :loading="busy" @click="refresh">刷新经营事实</el-button>
      </template>
    </PageHeader>

    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" class="table-gap">
      <el-button v-if="draftRequired" link type="primary" @click="$emit('review-grant')">去活动页创建草稿</el-button>
    </el-alert>
    <el-alert v-if="notice || initialNotice" type="success" :title="notice || initialNotice" show-icon :closable="false" class="table-gap" />

    <div class="stat-row">
      <div class="stat"><span>最近观测净成交</span><strong><Price :price="netRevenue" /></strong></div>
      <div class="stat"><span>最近观测退款</span><strong><Price :price="latestObservation?.summary?.refunded_cents" /></strong></div>
      <div class="stat"><span>累计广告花费</span><strong><Price :price="snapshot.account?.spent_cents" /></strong></div>
      <div class="stat"><span>累计授权上限</span><strong><Price :price="snapshot.account?.budget_cap_cents" /></strong></div>
    </div>

    <p class="muted-note">
      {{ latestObservation ? `最近规划观测于 ${timestamp(latestObservation.observed_at)}` : '尚未生成经营观测，请先在商城产生浏览或交易，再生成计划。' }}
      <template v-if="latestObservation">
        · 广告曝光 / 点击 {{ latestObservation.summary?.impressions ?? '未知' }} / {{ latestObservation.summary?.clicks ?? '未知' }}
        · 推荐曝光 / 点击 {{ latestObservation.summary?.recommendation_impressions ?? '未知' }} / {{ latestObservation.summary?.recommendation_clicks ?? '未知' }}
      </template>
    </p>
    <el-alert :title="nextStep" type="info" :closable="false" class="table-gap" />
    <el-alert v-if="pollNotice" :title="pollNotice" type="info" :closable="false" class="table-gap" />

    <div class="table-data-card table-gap">
      <h4 class="card-title">经营计划</h4>
      <el-empty v-if="!snapshot.plans.length" description="暂无计划。先提交明确目标，等待服务器保存观测和计划。" :image-size="70" />
      <article v-for="(plan, planIndex) in snapshot.plans" :key="plan.plan_id" class="plan-card">
        <div class="plan-head">
          <div>
            <p class="muted-note">{{ planIndex === 0 ? '最新计划' : '历史计划' }}</p>
            <h3>{{ plan.spec?.objective }}</h3>
            <StatusTag :label="statusText(plan.status)" :tone="badgeTone(plan.status)" />
            <StatusTag :label="modeText(plan.spec?.model_mode)" />
          </div>
          <div class="plan-budget">计划预算 <Price :price="plan.spec?.planned_budget_cents" /></div>
        </div>
        <p class="plan-summary">{{ plan.spec?.summary }}</p>
        <div class="meta-line">
          <span>适用产品：{{ (plan.spec?.product_scope || []).map(id => productName(id)).join('、') || '未报告' }}</span>
          <span>期间：{{ periodText(plan.spec?.period) }}</span>
        </div>
        <section v-if="plan.diagnosis?.length" class="diagnoses">
          <h4>候选解释与支持事实</h4>
          <article v-for="(item, index) in plan.diagnosis" :key="index">
            <strong>{{ diagnosisLabels[item.code] || item.code }}</strong>
            <p class="plan-summary">{{ item.explanation }}</p>
            <p class="muted-note">{{ item.evidence_ids?.length ? `已引用 ${item.evidence_ids.length} 条证据` : '未提供证据' }}</p>
            <GrowthTechDetails title="对应观测事实" :value="item.observed_facts" />
          </article>
          <p class="muted-note">候选解释不证明因果关系；证据不足时应继续观察。</p>
        </section>
        <h4>建议动作（{{ plan.spec?.actions?.length ?? 0 }}）</h4>
        <ol class="plan-actions">
          <li v-for="(action, index) in plan.spec?.actions || []" :key="index">
            <strong>{{ actionLabels[action.action_type] || action.action_type }}</strong>
            <template v-if="action.campaign_id"> · 指定活动</template>
            <template v-if="action.creative_id"> · 指定素材</template>
            · 所见版本 {{ action.expected_version }}
            <p v-if="action.budget_cents !== undefined">新活动预算 <Price :price="action.budget_cents" /></p>
            <p v-if="action.copy_text" class="plan-summary">{{ action.copy_text }}</p>
            <GrowthTechDetails title="完整动作、策略参数与依赖" :value="action" />
          </li>
        </ol>
        <h4>下一轮需要观察的信号</h4>
        <div class="chip-row">
          <span v-for="(signal, index) in plan.spec?.expected_signals || []" :key="index" class="signal-chip">{{ signal }}</span>
        </div>
        <p class="muted-note">{{ plan.spec?.evidence_ids?.length ? `引用 ${plan.spec.evidence_ids.length} 条证据` : '未提供引用证据' }}</p>
        <div class="button-row">
          <el-button v-if="plan.spec?.actions?.length" :disabled="busy || !canWrite || !!running" @click="execute(plan)">核对授权并执行 / 恢复回执</el-button>
          <el-button
            v-if="plan.spec?.actions?.length && (!plan.grant_id || ['WAIT_MERCHANT','WAIT_APPROVAL','WAIT_USER'].includes(plan.status))"
            type="primary"
            :disabled="busy || !canWrite"
            @click="$emit('review-grant', plan)"
          >查看计划并明确批准授权</el-button>
        </div>
        <el-alert
          v-if="['WAIT_MERCHANT','WAIT_APPROVAL','WAIT_USER'].includes(plan.status)"
          type="warning"
          :closable="false"
          show-icon
          title="此计划等待商家批准授权范围。批准页面会绑定本计划与当前资源版本。"
          class="table-gap"
        />
        <el-alert
          v-if="['WAIT_OUTCOME','WAIT_OBSERVATION'].includes(plan.status)"
          type="info"
          :closable="false"
          show-icon
          title="等待下一轮实际新曝光、点击或 Java 结果；页面不会自动创建新的规划运行。"
          class="table-gap"
        />
        <GrowthTechDetails
          title="授权 hash、前后值与执行回执"
          :value="{ grant_id: plan.grant_id, envelope_hash: plan.envelope_hash, action_receipts: plan.action_receipts, spec: plan.spec }"
        />
      </article>
    </div>

    <div class="table-data-card table-gap">
      <h4 class="card-title">准备下一轮经营</h4>
      <el-form label-width="96px" class="plan-form" @submit.prevent="start">
        <el-form-item label="目标和约束">
          <el-input
            v-model="objective"
            type="textarea"
            :rows="3"
            maxlength="1000"
            :readonly="!!pendingStart"
            placeholder="例如：结合顾客浏览和成交结果，调整商品展示与推广文案。"
          />
        </el-form-item>
        <el-collapse class="plan-advanced">
          <el-collapse-item title="规划范围与高级设置">
            <el-form-item label="产品范围">
              <el-checkbox-group v-model="productScope" :disabled="!!pendingStart">
                <el-checkbox v-for="product in products" :key="product.product_id" :value="product.product_id">
                  {{ product.product_name }} · {{ product.product_id }}
                </el-checkbox>
              </el-checkbox-group>
              <p v-if="catalogError" class="muted-note">{{ catalogError }}</p>
            </el-form-item>
            <el-form-item label="计划预算约束">
              <el-input v-model="plannedBudget" inputmode="numeric" pattern="[0-9]*" :readonly="!!pendingStart" placeholder="可选，整数分；不代表批准，留空使用当前已建活动预算总额" />
            </el-form-item>
            <el-form-item label="规划方式">
              <el-select v-model="mode" :disabled="!!pendingStart" style="width: 320px">
                <el-option label="真实模型（服务器配置的 qwen3.7-plus）" value="live" />
                <el-option label="确定性规则基线" value="rule" />
              </el-select>
            </el-form-item>
          </el-collapse-item>
        </el-collapse>
        <el-form-item>
          <el-button type="primary" native-type="submit" :disabled="busy || !canWrite || !!running">{{ pendingStart ? '使用原请求 ID 重试' : '基于新观测生成计划' }}</el-button>
        </el-form-item>
        <p v-if="pendingStart" class="muted-note">原请求 {{ pendingStart.request_id }} 的结果待核对。重试保留目标和模式，不创建另一个请求 ID。</p>
        <p class="muted-note">先在商城浏览、咨询或完成交易，再基于新观测生成计划。授权内动作可自动执行，越界时在“活动与授权”明确批准；之后回到商城查看新展示。</p>
      </el-form>
    </div>

    <div class="table-data-card table-gap">
      <el-collapse>
        <el-collapse-item title="高级：观测明细、运行记录与经验审核">
          <section class="advanced-block">
            <h4>观测与证据</h4>
            <el-empty v-if="!snapshot.observations.length" description="尚无经营观测。" :image-size="60" />
            <article v-for="observation in snapshot.observations" :key="observation.observation_id" class="record">
              <div>
                <h4>{{ timestamp(observation.observed_at) }}</h4>
                <p class="muted-note">轮次 {{ observation.round_id ?? '未报告' }} · 消费水位 {{ text(observation.watermark) }}</p>
              </div>
              <div v-if="observationMetrics(observation.summary).length" class="chip-row">
                <span v-for="item in observationMetrics(observation.summary)" :key="item.key" class="metric-chip">
                  {{ item.label }}
                  <strong v-if="item.money"><Price :price="item.value" /></strong>
                  <strong v-else>{{ item.value }}</strong>
                </span>
              </div>
              <p v-else class="plan-summary">{{ text(observation.summary) }}</p>
              <dl class="evidence-facts">
                <div v-for="fact in observation.facts || []" :key="fact.evidence_id">
                  <dt>{{ fact.metric }}：{{ text(fact.value) }}</dt>
                  <dd>{{ fact.evidence_id }} · {{ fact.kind }} · {{ fact.source }} · 发生 {{ timestamp(fact.occurred_at) }}</dd>
                </div>
              </dl>
              <GrowthTechDetails title="样本成熟度与活动指标" :value="{ maturity: observation.maturity, campaigns: observation.campaigns }" />
            </article>
          </section>

          <section class="advanced-block">
            <h4>运行与实际模型用量</h4>
            <el-empty v-if="!snapshot.runs.length" description="暂无经营运行。" :image-size="60" />
            <article v-for="run in snapshot.runs" :key="run.agent_run_id" class="record">
              <div class="record-head">
                <div>
                  <strong>{{ run.agent_run_id }}</strong>
                  <StatusTag :label="statusText(run.state)" :tone="badgeTone(run.state)" />
                  <StatusTag :label="modeText(run.result?.model_mode || run.context?.model_mode || run.model_mode)" />
                  <p class="muted-note">创建 {{ timestamp(run.created_at) }}<template v-if="run.parent_run_id"> · 父运行 {{ run.parent_run_id }}</template></p>
                </div>
                <el-button :disabled="busy" @click="readRun(run.agent_run_id)">查询此运行</el-button>
              </div>
              <p v-if="run.state === 'RUNNING'" role="status" class="muted-note">正在执行有界任务，页面只查询已保存进度。</p>
              <p class="muted-note">
                实际调用 {{ run.context?.model_calls ?? '未知' }} · 已记录尝试 {{ run.context?.model_attempts?.length ?? '未知' }}
                · 输入 Token {{ usage(run, 'input_tokens') ?? '未知' }} · 输出 Token {{ usage(run, 'output_tokens') ?? '未知' }}
                · 费用估算 ¥{{ usage(run, 'cost_estimate_cny') ?? '未知' }}
              </p>
              <GrowthDecisionCard :decision="run.result?.decision" :checks="run.result?.checks" />
              <GrowthTechDetails title="实际调用、版本、用量与结果凭据" :value="{ context: run.context, result: run.result }" />
            </article>
            <el-alert v-if="pollNotice" :title="pollNotice" type="info" :closable="false" />
          </section>

          <section class="advanced-block">
            <h4>经营经验审核</h4>
            <p class="muted-note">模型建议先保存为 DRAFT，人工认可后才可供后续经营使用。</p>
            <el-empty v-if="!snapshot.memories.length" description="暂无待审核经验。" :image-size="60" />
            <article v-for="memory in snapshot.memories" :key="memory.memory_id" class="record">
              <StatusTag :label="memory.status" :tone="badgeTone(memory.status)" />
              {{ memory.memory_id }} · v{{ memory.version }}
              <p class="plan-summary">{{ text(memory.content) }}</p>
              <p class="muted-note">{{ memory.evidence_ids?.length ? `已引用 ${memory.evidence_ids.length} 条证据` : '未提供证据' }}</p>
              <el-button
                v-if="memory.status === 'DRAFT'"
                :disabled="busy || !canWrite"
                @click="reviewMemory = memory; reviewedContent = memory.content; memoryApproved = false"
              >核对并批准这条经验</el-button>
            </article>
          </section>
          <el-form v-if="reviewMemory" class="operation" label-width="96px" @submit.prevent="approveMemory">
            <h3>明确批准经营经验</h3>
            <h4>模型原草稿</h4>
            <p class="plan-summary">{{ text(reviewMemory.content) }}</p>
            <p>版本 {{ reviewMemory.version }} · 来源计划 {{ reviewMemory.plan_id }}</p>
            <p class="muted-note">{{ reviewMemory.evidence_ids?.length ? `已引用 ${reviewMemory.evidence_ids.length} 条证据` : '未提供证据' }}</p>
            <el-form-item label="可复用正文">
              <el-input v-model="reviewedContent" type="textarea" :rows="5" maxlength="2000" :disabled="busy" @input="memoryApproved = false" />
            </el-form-item>
            <p class="muted-note">请删改缺乏证据的结论。只有下方明确批准的正文会供后续经营使用；原草稿仍保留在来源计划中。</p>
            <el-checkbox v-model="memoryApproved" class="approval" :disabled="busy">我已核对正文和证据，认可这条经验可供后续经营复用。</el-checkbox>
            <div class="button-row">
              <el-button type="primary" native-type="submit" :disabled="busy || !canWrite || !memoryApproved || !reviewedContent.trim()">批准此版本经验</el-button>
              <el-button :disabled="busy" @click="reviewMemory = null">暂不批准</el-button>
            </div>
          </el-form>
        </el-collapse-item>
      </el-collapse>
    </div>
  </div>
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

<style scoped lang="scss">
.merchant-page {
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

  .stat-row {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 12px;
    margin-bottom: 12px;

    .stat {
      display: flex;
      flex-direction: column;
      gap: 6px;
      padding: 14px 16px;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);

      span {
        color: var(--text-2);
        font-size: 13px;
      }

      strong {
        font-size: 22px;
        color: var(--money);
      }
    }
  }

  .plan-form {
    padding: 16px;

    :deep(.el-collapse) {
      margin-bottom: 12px;
    }
  }

  .plan-card {
    padding: 14px 16px;
    border-bottom: 1px solid var(--border-soft);

    &:last-child {
      border-bottom: 0;
    }
  }

  .plan-head {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 12px;

    h3 {
      margin: 2px 0 6px;
      font-size: 15px;
      color: var(--text);
    }
  }

  .plan-budget {
    flex-shrink: 0;
    color: var(--text-2);
    font-size: 13px;
  }

  .plan-summary {
    margin: 6px 0;
    color: var(--text);
  }

  .meta-line {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    color: var(--text-2);
    font-size: 13px;
  }

  .diagnoses article,
  .record {
    padding: 10px 0;
    border-top: 1px dashed var(--border-soft);
  }

  .record-head {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 12px;
  }

  .advanced-block {
    padding: 8px 0 14px;

    h4 {
      margin: 0 0 8px;
      font-size: 14px;
      color: var(--text);
    }
  }

  .chip-row {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin: 6px 0;
  }

  .signal-chip,
  .metric-chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    background: var(--surface-soft);
    border: 1px solid var(--border-soft);
    border-radius: var(--radius-pill);
    font-size: 12px;
    color: var(--text-2);
  }

  .evidence-facts {
    margin: 6px 0 0;

    dt {
      color: var(--text);
      font-size: 13px;
    }

    dd {
      margin: 2px 0 8px;
      color: var(--text-3);
      font-size: 12px;
    }
  }

  .plan-actions {
    margin: 6px 0 12px;
    padding-left: 20px;

    li {
      margin-bottom: 8px;
    }
  }

  .operation {
    padding: 16px;

    :deep(h3) {
      margin: 0 0 10px;
      font-size: 16px;
      color: var(--text);
    }
  }
}
</style>
