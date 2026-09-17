<template>
  <div class="ads-page" aria-label="活动与授权管理">
    <PageHeader title="投放概览" description="曝光免费，合法点击按 CPC 计费。余额与花费以服务器累计账户为准。">
      <template #actions>
        <el-button type="primary" :loading="busy" @click="refresh">刷新事实</el-button>
      </template>
    </PageHeader>

    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" class="table-gap" />
    <el-alert v-if="notice" type="success" :title="notice" show-icon :closable="false" class="table-gap" />
    <el-alert v-if="!canWrite" type="warning" show-icon :closable="false" class="table-gap"
      title="当前会话无管理写权限；所有操作仍由服务器验权。" />

    <div class="stat-row">
      <div class="stat"><span>累计已花费</span><strong><Price :price="snapshot.account?.spent_cents" /></strong></div>
      <div class="stat"><span>授权累计上限</span><strong><Price :price="snapshot.account?.budget_cap_cents" /></strong></div>
      <div class="stat">
        <span>累计剩余额度</span>
        <strong><Price :price="snapshot.account ? snapshot.account.budget_cap_cents - snapshot.account.spent_cents - snapshot.account.reservations_cents : undefined" /></strong>
      </div>
      <div class="stat"><span>实际曝光 / 点击</span><strong>{{ snapshot.impressions ?? '待核对' }} / {{ snapshot.clicks ?? '待核对' }}</strong></div>
      <div class="stat"><span>活动 / 素材</span><strong>{{ snapshot.campaigns.length }} / {{ snapshot.creatives.length }}</strong></div>
      <div class="stat"><span>当前数据</span><strong class="small">{{ refreshedAt ? timestamp(refreshedAt) : '尚未读取' }}</strong></div>
    </div>

    <div class="table-data-card table-gap">
      <div class="card-head">
        <h4 class="card-title">活动和素材</h4>
        <el-select v-model="selectedGrant" class="select-grant" placeholder="执行所用授权" style="width: 220px">
          <el-option label="请选择" value="" />
          <el-option v-for="item in snapshot.grants" :key="item.grant_id" :value="item.grant_id"
            :label="`${grantStatusText(item)} · v${item.version}`" />
        </el-select>
      </div>
      <el-empty v-if="!snapshot.campaigns.length" description="暂无活动，创建草稿后开始。" :image-size="70" />
      <article v-for="item in snapshot.campaigns" :key="item.campaign_id" class="plan-card">
        <div class="plan-head">
          <div>
            <h3>{{ item.name }}</h3>
            <StatusTag :label="campaignStatusText(item.status)" :tone="badgeTone(item.status)" />
            <span class="muted-note">v{{ item.version }} · {{ catalog.find(sku => sku.product_id === item.product_id)?.product_name || item.product_id }}</span>
          </div>
          <div class="meta-line">
            预算 <Price :price="item.budget_cents" /> · 已花 <Price :price="item.spent_cents" /> · CPC <Price :price="item.cpc_cents" />
          </div>
        </div>
        <el-alert v-if="item.pause_reason" type="warning" :closable="false" show-icon :title="`暂停原因：${pauseReasonText(item.pause_reason)}`" class="table-gap" />
        <div class="button-row">
          <el-button v-for="type in campaignActions(item)" :key="type" :disabled="busy || !canWrite" @click="prepare(type, item)">{{ actionLabels[type] }}</el-button>
          <el-button :disabled="busy || !canWrite" @click="prepare('set_budget', item)">调整预算</el-button>
        </div>
        <article v-for="asset in snapshot.creatives.filter(row => row.campaign_id === item.campaign_id)" :key="asset.creative_id" class="creative">
          <p class="creative-copy">{{ asset.copy_text }}</p>
          <small class="muted-note">{{ campaignStatusText(asset.status) }} · v{{ asset.version }}</small>
          <div class="button-row">
            <el-button v-for="type in creativeActions(asset)" :key="type" size="small" :disabled="busy || !canWrite" @click="prepare(type, item, asset)">{{ actionLabels[type] }}</el-button>
            <el-button size="small" :disabled="busy || !canWrite" @click="prepare('replace_creative', item, asset)">替换文案</el-button>
          </div>
        </article>
        <GrowthTechDetails title="活动原始凭据" :value="item" />
      </article>
    </div>

    <div v-if="operation" class="table-data-card table-gap">
      <!-- fieldset 保留：它是"表单整体禁用"的契约点，也承载已迁移测试的断言；
           标题必须放在 form 内，页面按标题文本定位表单 -->
      <fieldset :disabled="busy || !canWrite">
        <el-form class="operation" label-width="168px" @submit.prevent="execute">
          <h4 class="card-title">核对本次动作</h4>
          <p class="op-summary">{{ operation.revoke ? '撤销授权并保护暂停' : actionLabels[operation.type] }} · {{ operation.target }}</p>
          <el-form-item v-if="operation.type === 'set_budget'" label="新的活动预算（整数分）">
            <el-input v-model="operation.budget" inputmode="numeric" :disabled="!!pending" />
          </el-form-item>
          <el-form-item v-if="operation.type === 'replace_creative'" label="新文案">
            <el-input v-model="operation.copy" type="textarea" :rows="3" maxlength="1000" :disabled="!!pending" />
          </el-form-item>
          <el-form-item label="动作原因">
            <el-input v-model="operation.reason" maxlength="128" :disabled="!!pending" />
          </el-form-item>
          <GrowthTechDetails title="资源版本和授权" :value="pending?.body || operation" />
          <div class="button-row">
            <el-button type="primary" native-type="submit">{{ pending ? '使用原幂等键重试' : '确认执行本次动作' }}</el-button>
            <el-button v-if="pending && !operation.revoke" @click="queryAction">查询原动作结果</el-button>
            <el-button @click="operation = null; pending = null">关闭动作面板</el-button>
          </div>
          <p class="muted-note">网络失败时先查询原回执；重试保留原请求和版本。刷新页面仅重新读取事实。</p>
        </el-form>
      </fieldset>
    </div>

    <div class="table-data-card table-gap">
      <h4 class="card-title">当前授权</h4>
      <el-empty v-if="!snapshot.grants.length" description="暂无已批准授权。" :image-size="70" />
      <article v-for="item in snapshot.grants" :key="item.grant_id" class="plan-card">
        <div class="plan-head">
          <div>
            <strong>{{ grantStatusText(item) }}</strong>
            <StatusTag :label="item.status || (item.revoked_at ? 'REVOKED' : '已批准')" :tone="badgeTone(item.status || (item.revoked_at ? 'REVOKED' : 'APPROVED'))" />
            <p class="muted-note">版本 {{ item.version }} · 批准 {{ timestamp(item.approval_time || item.approved_at || item.created_at) }} · 到期 {{ timestamp(item.valid_until || item.envelope?.valid_until) }}</p>
          </div>
          <el-button :disabled="busy || !canWrite || !!item.revoked_at || item.status === 'REVOKED'" @click="prepareRevoke(item)">准备撤销</el-button>
        </div>
        <GrowthTechDetails title="审批人、范围与不可变 hash" :value="item" />
      </article>
    </div>

    <div class="table-data-card table-gap">
      <el-collapse v-model="panels">
        <el-collapse-item name="create" title="创建活动与素材">
          <div class="two-columns forms">
            <el-form class="sub-form" label-width="132px" @submit.prevent="saveCampaign">
              <h4>保存活动草稿</h4>
              <fieldset :disabled="busy || !canWrite">
                <el-form-item label="活动名称">
                  <el-input v-model="campaign.name" maxlength="200" />
                </el-form-item>
                <el-form-item label="选择真实在售 SKU">
                  <el-select v-model="selectedSku" class="select-sku" style="width: 100%" placeholder="选择商品与规格">
                    <el-option value="" label="选择商品与规格" />
                    <el-option v-for="sku in catalog" :key="skuKey(sku)" :value="skuKey(sku)"
                      :label="`${sku.product_name} · ${sku.sku_name || sku.sku_key} · ¥${money(sku.price_cents)} · 库存 ${sku.stock ?? '未知'}`" />
                  </el-select>
                </el-form-item>
                <p v-if="catalogError" class="muted-note">{{ catalogError }}；可展开并核对商品/SKU。</p>
                <el-collapse class="manual-sku">
                  <el-collapse-item name="manual" title="查看或手工填写商品/SKU">
                    <el-form-item label="真实商品 ID">
                      <el-input v-model="campaign.product_id" maxlength="64" :readonly="!!selectedSku" />
                    </el-form-item>
                    <el-form-item label="真实 SKU Key">
                      <el-input v-model="campaign.sku_key" maxlength="128" :readonly="!!selectedSku" placeholder="裸 propertyValueIdHash，不含商品 ID 前缀" />
                    </el-form-item>
                  </el-collapse-item>
                </el-collapse>
                <div class="two-columns">
                  <el-form-item label="活动预算（整数分）">
                    <el-input v-model="campaign.budget_cents" inputmode="numeric" />
                  </el-form-item>
                  <el-form-item label="CPC（整数分）">
                    <el-input v-model="campaign.cpc_cents" inputmode="numeric" />
                  </el-form-item>
                </div>
                <el-form-item>
                  <el-button type="primary" native-type="submit">保存 DRAFT</el-button>
                </el-form-item>
                <p class="muted-note">保存草稿后，需另行批准授权与启用。</p>
                <GrowthTechDetails title="草稿幂等 ID" :value="{ campaign_id: campaign.campaign_id }" />
              </fieldset>
            </el-form>
            <el-form class="sub-form" label-width="112px" @submit.prevent="saveCreative">
              <h4>保存素材草稿</h4>
              <fieldset :disabled="busy || !canWrite">
                <el-form-item label="所属活动">
                  <el-select v-model="creative.campaign_id" class="select-campaign" style="width: 100%" placeholder="选择明确的活动">
                    <el-option v-for="item in ownCampaigns" :key="item.campaign_id" :value="item.campaign_id" :label="item.name" />
                  </el-select>
                </el-form-item>
                <el-form-item label="素材文案">
                  <el-input v-model="creative.copy_text" type="textarea" :rows="5" maxlength="1000" />
                </el-form-item>
                <el-form-item>
                  <el-button type="primary" native-type="submit">保存素材 DRAFT</el-button>
                </el-form-item>
                <GrowthTechDetails title="素材幂等 ID" :value="{ creative_id: creative.creative_id }" />
              </fieldset>
            </el-form>
          </div>
        </el-collapse-item>

        <el-collapse-item name="grant" title="批准或更新授权范围">
          <div ref="grantPanel" class="grant-panel">
            <el-form class="operation" label-width="168px" @submit.prevent="approve">
              <h4>明确批准稳定授权</h4>
              <p class="muted-note">所选产品、动作、有效期和累计上限构成授权范围；后续计划继续共享累计花费。</p>
              <el-alert v-if="merchantPlan" type="info" show-icon :closable="false" class="table-gap"
                :title="`本次审批绑定经营计划 ${merchantPlan.plan_id} · v${merchantPlan.version}`">
                <p>{{ merchantPlan.spec?.summary }}</p>
                <GrowthTechDetails title="待批准计划及证据" :value="merchantPlan" />
                <el-button :disabled="busy" @click="$emit('close-plan')">返回经营计划</el-button>
              </el-alert>
              <fieldset :disabled="busy || !canWrite">
                <div class="two-columns">
                  <el-form-item label="经营目标">
                    <el-input v-model="grant.objective" maxlength="1000" :readonly="!!merchantPlan" />
                  </el-form-item>
                  <el-form-item label="首次计划 ID">
                    <el-input v-model="grant.initial_plan_id" maxlength="128" :readonly="!!merchantPlan" />
                  </el-form-item>
                </div>
                <div class="two-columns">
                  <el-form-item label="首次计划版本">
                    <el-input v-model="grant.initial_plan_version" inputmode="numeric" :readonly="!!merchantPlan" />
                  </el-form-item>
                  <el-form-item label="授权有效期（本地时间）">
                    <el-input v-model="grant.valid_until" type="datetime-local" />
                  </el-form-item>
                </div>
                <div class="two-columns">
                  <el-form-item label="累计总上限（整数分）">
                    <el-input v-model="grant.budget_cap_cents" inputmode="numeric" />
                  </el-form-item>
                  <el-form-item label="每次预算最大变动（整数分）">
                    <el-input v-model="grant.max_budget_change_cents" inputmode="numeric" />
                  </el-form-item>
                </div>
                <el-form-item label="批准的真实产品范围">
                  <el-checkbox-group v-model="grant.product_scope">
                    <el-checkbox v-for="id in productIds" :key="id" class="check" :value="id" :disabled="!!merchantPlan">商品 {{ id }}</el-checkbox>
                  </el-checkbox-group>
                  <p v-if="!productIds.length" class="muted-note">先保存真实商品对应的活动草稿。</p>
                </el-form-item>
                <el-form-item label="允许的动作">
                  <el-checkbox-group v-model="grant.allowed_action_types">
                    <el-checkbox v-for="(label, type) in actionLabels" :key="type" class="check" :value="type">{{ label }}</el-checkbox>
                  </el-checkbox-group>
                </el-form-item>
                <template v-if="grant.allowed_action_types.includes('set_recommendation_policy')">
                  <p class="muted-note">策略会影响其所属作用域的推荐，产品范围必须完整覆盖服务端要求的资源。</p>
                  <el-form-item label="推荐策略范围">
                    <div>
                      <el-checkbox-group v-model="grant.policy_rankings" class="inline-group">
                        <el-checkbox v-for="ranking in ['rule','content']" :key="ranking" class="check" :value="ranking">{{ ranking === 'rule' ? '规则排序' : '内容排序' }}（{{ ranking }}）</el-checkbox>
                      </el-checkbox-group>
                      <el-checkbox-group v-model="grant.policy_groups" class="inline-group">
                        <el-checkbox v-for="group in ['control','treatment','all']" :key="group" class="check" :value="group">{{ ({control:'对照组',treatment:'实验组',all:'两组统一'})[group] }}（{{ group }}）</el-checkbox>
                      </el-checkbox-group>
                    </div>
                  </el-form-item>
                  <div class="two-columns">
                    <el-form-item label="单项权重上限（0–20 整数）">
                      <el-input v-model="grant.policy_max_weight" type="number" min="0" max="20" step="1" />
                    </el-form-item>
                    <el-form-item label="单路候选数量上限（0–20 整数）">
                      <el-input v-model="grant.policy_max_quota" type="number" min="0" max="20" step="1" />
                    </el-form-item>
                  </div>
                </template>
                <el-form-item label="替代既有授权 ID">
                  <el-input v-model="grant.replaces_grant_id" maxlength="128" placeholder="仅重新批准时填写" />
                </el-form-item>
                <p v-if="grant.replaces_grant_id" class="muted-note">替代授权会先保护暂停当前范围内的投放。计划没有明确启用或恢复动作时，投放将保持暂停；扩大预算本身不会恢复投放。</p>
                <GrowthTechDetails title="本次完整授权范围与资源版本" :value="grantPreview" />
                <el-checkbox v-model="approved" class="approval">我已核对上述产品、动作、有效期和累计上限，明确批准此授权。</el-checkbox>
                <el-form-item>
                  <el-button type="primary" native-type="submit" :disabled="!approved">批准并保存稳定授权</el-button>
                </el-form-item>
              </fieldset>
            </el-form>
          </div>
        </el-collapse-item>

        <el-collapse-item name="advanced" title="高级：库存观测、账户与动作回执">
          <GrowthTechDetails v-if="snapshot.account" title="稳定预算账户原始凭据" :value="snapshot.account" />
          <section class="advanced-block">
            <h4>库存观测</h4>
            <p class="muted-note">本地观测序号用于保护暂停；Java 继续决定交易库存。正库存读取不会自动恢复已暂停投放。</p>
            <el-empty v-if="!snapshot.observations.length" description="尚无库存观测。启用、恢复和流量入口会重新查询。" :image-size="60" />
            <article v-for="(item, index) in snapshot.observations" :key="item.observation_id || index" class="plan-card">
              <p>商品 {{ item.product_id }} / {{ item.sku_key }} · 库存 {{ item.stock ?? '未知' }}</p>
              <p class="muted-note">请求开始 {{ timestamp(item.query_started_at) }} · 响应 {{ timestamp(item.query_completed_at || item.response_at) }}</p>
              <GrowthTechDetails title="观测凭据" :value="item" />
            </article>
          </section>
          <section class="advanced-block">
            <h4>动作回执</h4>
            <el-empty v-if="!snapshot.actions.length" description="尚无动作记录。" :image-size="60" />
            <article v-for="item in snapshot.actions" :key="item.action_id" class="plan-card">
              <p>{{ item.status || item.result?.status || '查看结果' }} · {{ item.request?.reason_code || item.reason_code }}</p>
              <GrowthTechDetails :title="item.action_id" :value="item" />
            </article>
            <GrowthTechDetails v-if="lastReceipt" title="最近请求回执" :value="lastReceipt" />
          </section>
        </el-collapse-item>
      </el-collapse>
    </div>
  </div>
</template>
<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue';
import { session, aiGet, aiWrite, loadSession, integer, errorText, timestamp, actionLabels, money } from '../api/client';
import { hasAdminPermission } from '../utils/adminAccess';
import { badgeTone, campaignStatusText, grantStatusText } from '../utils/growthDisplay';
import GrowthTechDetails from '../components/GrowthTechDetails.vue';
import Price from '../components/SmartlectPrice.vue';
const props = defineProps({ merchantPlan: { type: Object, default: null } });
const emit = defineEmits(['grant-approved', 'close-plan']);
const snapshot = ref({ campaigns: [], creatives: [], grants: [], account: null, actions: [], observations: [] });
const busy = ref(false); const error = ref(''); const notice = ref(''); const refreshedAt = ref(''); const lastReceipt = ref(null);
const canWrite = computed(() => hasAdminPermission(session.value?.actor, 'admin:legacy'));
const pauseReasonText = (reason) => ({
  grant_replaced: '授权已被新版本替换',
  grant_expired: '授权已过期',
  budget_exhausted: '累计预算已用尽',
  stock_unavailable: '库存不足，已保护暂停',
  stockout: '库存不足，已保护暂停',
  merchant_manual_pause: '商家手动暂停',
  policy_paused: '策略要求暂停',
}[reason] || reason);
const campaign = reactive({ campaign_id: crypto.randomUUID(), name: '', product_id: '', sku_key: '', budget_cents: '1000', cpc_cents: '10' });
const catalog = ref([]); const catalogError = ref(''); const selectedSku = ref('');
const skuKey = sku => JSON.stringify([sku.product_id, sku.sku_key]);
function chooseSku() { const sku = catalog.value.find(item => skuKey(item) === selectedSku.value); campaign.product_id = sku?.product_id || ''; campaign.sku_key = sku?.sku_key || ''; }
async function readCatalog() {
  try {
    // 响应缺失 items 时不能把 ref 赋成 undefined：模板里的 catalog.find(...) 会让整块
    // 活动卡片渲染抛错（脚手架曾经返回过 {}）。
    catalog.value = (await aiGet('/ads/catalog')).items ?? [];
    catalogError.value = '';
  } catch (reason) { catalog.value = []; catalogError.value = errorText(reason); }
}
// 选中的 SKU 一旦变化就同步 product_id/sku_key：el-select 的程序化设值不会触发原生 change，
// 用 watch 同时覆盖"用户点选"和"程序化设值"两条路径。
watch(selectedSku, () => { const sku = catalog.value.find(item => skuKey(item) === selectedSku.value); campaign.product_id = sku?.product_id || ''; campaign.sku_key = sku?.sku_key || ''; });
const creative = reactive({ creative_id: crypto.randomUUID(), campaign_id: '', copy_text: '' });
const localDate = new Date(Date.now() + 86400000); localDate.setMinutes(localDate.getMinutes() - localDate.getTimezoneOffset());
const grant = reactive({ grant_id: crypto.randomUUID(), initial_plan_id: crypto.randomUUID(), initial_plan_version: '1', objective: '在批准范围内运行模拟投放并观察净成交', product_scope: [], allowed_action_types: Object.keys(actionLabels).filter(type => type !== 'set_recommendation_policy'), budget_cap_cents: '1000', max_budget_change_cents: '500', valid_until: localDate.toISOString().slice(0, 16), replaces_grant_id: '', policy_rankings: [], policy_groups: [], policy_max_weight: '0', policy_max_quota: '0' });
const grantPanel = ref(null);
// 折叠面板状态；经营页带着计划跳过来时自动展开授权面板（等价于原来的 <details :open="!!merchantPlan">）
const panels = ref(props.merchantPlan ? ['grant'] : []);
watch(() => props.merchantPlan, plan => {
  if (plan) panels.value = [...new Set([...panels.value, 'grant'])];
});
const approved = ref(false); const selectedGrant = ref(''); const operation = ref(null); const pending = ref(null);
const ownCampaigns = computed(() => snapshot.value.campaigns.filter(item => item.owner_id === session.value?.actor.actor_id));
const productIds = computed(() => [...new Set([...ownCampaigns.value.map(item => item.product_id), ...(props.merchantPlan?.spec?.product_scope || [])])]);
const grantPreview = computed(() => {
  const campaigns = ownCampaigns.value.filter(item => grant.product_scope.includes(item.product_id));
  const ids = new Set(campaigns.map(item => item.campaign_id));
  const creatives = snapshot.value.creatives.filter(item => item.owner_id === session.value?.actor.actor_id && ids.has(item.campaign_id));
  return { grant_id: grant.grant_id, initial_plan_id: grant.initial_plan_id, initial_plan_version: Number(grant.initial_plan_version),
    envelope: { objective: grant.objective, product_scope: [...grant.product_scope], allowed_action_types: [...grant.allowed_action_types], budget_cap_cents: Number(grant.budget_cap_cents), max_budget_change_cents: Number(grant.max_budget_change_cents), valid_until: Number.isFinite(new Date(grant.valid_until).getTime()) ? new Date(grant.valid_until).toISOString() : null, ...(grant.allowed_action_types.includes('set_recommendation_policy') ? { recommendation_policy_range: { rankings: [...grant.policy_rankings], groups: [...grant.policy_groups], max_weight: Number(grant.policy_max_weight), max_quota: Number(grant.policy_max_quota) } } : {}) },
    expected_campaign_versions: Object.fromEntries(campaigns.map(item => [item.campaign_id, item.version])),
    expected_creative_versions: Object.fromEntries(creatives.map(item => [item.creative_id, item.version])),
    ...(grant.replaces_grant_id ? { replaces_grant_id: grant.replaces_grant_id } : {}), ...(props.merchantPlan ? { merchant_plan_id: props.merchantPlan.plan_id } : {}),
    displayed_resources: { campaigns, creatives },
  };
});
watch(grant, () => { approved.value = false; }, { deep: true, flush: 'sync' });
async function refresh() {
  await work(async () => { await loadSession(); await Promise.all([read(), readCatalog()]); });
}
async function read() {
  const data = await aiGet('/ads');
  snapshot.value = { ...data, campaigns: data.campaigns || [], creatives: data.creatives || [], grants: data.grants || [], account: data.account || null, actions: data.actions || [], observations: data.observations || [] };
  refreshedAt.value = new Date().toISOString(); approved.value = false;
}
async function work(task) {
  if (busy.value) return; busy.value = true; error.value = ''; notice.value = '';
  try { await task(); } catch (reason) { error.value = errorText(reason); if (session.value) { try { await read(); } catch { /* Keep the original refusal visible when the read also fails. */ } } } finally { busy.value = false; }
}
async function saveCampaign() {
  await work(async () => { if (!campaign.product_id || !campaign.sku_key) throw new Error('请选择真实在售 SKU，或展开并填写已核对的商品/SKU。'); lastReceipt.value = await aiWrite('/ads/campaigns', { ...campaign, budget_cents: integer(campaign.budget_cents, '预算'), cpc_cents: integer(campaign.cpc_cents, 'CPC', 1) }); campaign.campaign_id = crypto.randomUUID(); notice.value = '活动草稿已保存。'; await read(); });
}
async function saveCreative() {
  await work(async () => { lastReceipt.value = await aiWrite('/ads/creatives', { ...creative }); creative.creative_id = crypto.randomUUID(); notice.value = '素材草稿已保存。'; await read(); });
}
async function approve() {
  if (!approved.value) return;
  await work(async () => {
    if (!grant.product_scope.length || !grant.allowed_action_types.length) throw new Error('请明确选择产品范围和允许动作。');
    const validUntil = new Date(grant.valid_until); if (!(validUntil.getTime() > Date.now())) throw new Error('授权有效期必须晚于当前时间。');
    if (grant.allowed_action_types.includes('set_recommendation_policy') && (!grant.policy_rankings.length || !grant.policy_groups.length || integer(grant.policy_max_weight, '权重上限') > 20 || integer(grant.policy_max_quota, '候选数量上限') > 20)) throw new Error('请明确选择排序方式、实验组，并将权重与候选数量上限设为 0–20 整数。');
    integer(grant.initial_plan_version, '计划版本', 1); integer(grant.budget_cap_cents, '累计上限'); integer(grant.max_budget_change_cents, '每次预算变动');
    const { displayed_resources, ...payload } = grantPreview.value;
    lastReceipt.value = await aiWrite('/ads/grants', payload);
    selectedGrant.value = grant.grant_id; grant.grant_id = crypto.randomUUID(); approved.value = false; notice.value = '稳定授权已保存；活动和素材需另行启用。'; await read();
    if (props.merchantPlan) emit('grant-approved');
  });
}
const campaignActions = item => item.status === 'DRAFT' ? ['activate_campaign'] : item.status === 'ACTIVE' ? ['pause_campaign'] : ['PAUSED', 'EXHAUSTED'].includes(item.status) ? ['resume_campaign'] : [];
const creativeActions = item => item.status === 'DRAFT' ? ['activate_creative'] : item.status === 'ACTIVE' ? ['pause_creative'] : ['PAUSED', 'EXHAUSTED'].includes(item.status) ? ['resume_creative'] : [];
function prepare(type, item, asset) {
  error.value = ''; const authorization = snapshot.value.grants.find(row => row.grant_id === selectedGrant.value);
  if (!authorization) { error.value = '请先选择本次执行所用的稳定授权。'; return; }
  pending.value = null; operation.value = { type, target: asset?.creative_id || item.campaign_id, campaign_id: item.campaign_id, ...(asset ? { creative_id: asset.creative_id } : {}), expected_version: asset?.version || item.version, grant_id: selectedGrant.value, plan_id: authorization.initial_plan_id, plan_version: authorization.initial_plan_version, budget: String(item.budget_cents), copy: asset?.copy_text || '', reason: 'merchant_manual' };
}
function prepareRevoke(item) { pending.value = null; operation.value = { revoke: true, target: item.grant_id, expected_version: item.version, reason: 'merchant_revoke' }; }
async function execute() {
  await work(async () => {
    if (!pending.value) {
      const item = operation.value; const actionId = crypto.randomUUID();
      if (item.revoke) pending.value = { path: `/ads/grants/${encodeURIComponent(item.target)}/revoke`, body: { action_id: actionId, idempotency_key: actionId, expected_version: item.expected_version, reason_code: item.reason } };
      else {
        const action = { action_type: item.type, campaign_id: item.campaign_id, expected_version: item.expected_version, ...(item.creative_id ? { creative_id: item.creative_id } : {}), ...(item.type === 'set_budget' ? { budget_cents: integer(item.budget, '新预算') } : {}), ...(item.type === 'replace_creative' ? { copy_text: item.copy } : {}) };
        pending.value = { path: '/ads/actions', body: { action_id: actionId, idempotency_key: actionId, grant_id: item.grant_id, plan_id: item.plan_id, plan_version: item.plan_version, reason_code: item.reason, evidence_ids: [], actions: [action] } };
      }
    }
    lastReceipt.value = await aiWrite(pending.value.path, pending.value.body); pending.value = null; operation.value = null; notice.value = '动作已返回，请核对回执与当前状态。'; await read();
  });
}
async function queryAction() { await work(async () => { lastReceipt.value = await aiGet(`/ads/actions/${encodeURIComponent(pending.value.body.action_id)}`); await read(); }); }
onMounted(async () => {
  await refresh();
  const plan = props.merchantPlan;
  if (plan) {
    grant.initial_plan_id = plan.plan_id; grant.initial_plan_version = String(plan.version); grant.objective = plan.spec.objective; grant.product_scope = [...plan.spec.product_scope];
    grant.allowed_action_types = [...new Set([...grant.allowed_action_types, ...plan.spec.actions.map(action => action.action_type)])];
    grant.budget_cap_cents = String(Math.max(snapshot.value.account?.budget_cap_cents || 0, plan.spec.planned_budget_cents || 0));
    grant.replaces_grant_id = snapshot.value.account?.grant_id || '';
    const policies = plan.spec.actions.filter(action => action.action_type === 'set_recommendation_policy').map(action => action.policy);
    grant.policy_rankings = [...new Set(policies.map(policy => policy.config.ranking))]; grant.policy_groups = [...new Set(policies.map(policy => policy.group))];
    grant.policy_max_weight = String(Math.max(0, ...policies.flatMap(policy => Object.values(policy.config.weights)))); grant.policy_max_quota = String(Math.max(0, ...policies.flatMap(policy => Object.values(policy.config.quotas))));
    await nextTick(); grantPanel.value?.scrollIntoView?.({ block: 'start' });
  }
});
</script>

<style scoped lang="scss">
.ads-page {
  .table-gap {
    margin-bottom: 12px;
  }

  .card-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    padding: 12px 16px;
    border-bottom: 1px solid var(--border-soft);

    .card-title {
      padding: 0;
      border-bottom: 0;
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

  .meta-line {
    flex-shrink: 0;
    color: var(--text-2);
    font-size: 13px;
  }

  .creative {
    margin: 10px 0 0;
    padding: 10px 12px;
    background: var(--surface-soft);
    border: 1px solid var(--border-soft);
    border-radius: var(--radius-sm);
  }

  .creative-copy {
    margin: 0 0 6px;
    color: var(--text);
    white-space: pre-wrap;
  }

  .operation,
  .sub-form {
    padding: 16px;

    h4 {
      margin: 0 0 10px;
      font-size: 15px;
      color: var(--text);
    }
  }

  .op-summary {
    margin: 0 0 12px;
    color: var(--text);
  }

  .forms {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
    gap: 16px;
  }

  .two-columns {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 0 12px;
  }

  .inline-group {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 16px;
    margin-bottom: 6px;
  }

  .manual-sku {
    margin-bottom: 12px;
  }

  .grant-panel {
    padding: 4px 0;
  }

  .advanced-block {
    padding: 8px 0 14px;

    h4 {
      margin: 0 0 8px;
      font-size: 14px;
      color: var(--text);
    }
  }

  :deep(.el-checkbox.check) {
    margin-right: 16px;
  }
}
</style>
