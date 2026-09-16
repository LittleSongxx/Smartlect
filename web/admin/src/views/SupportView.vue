<template>
  <div class="support-page">
    <PageHeader title="人工客服工单" description="接管后自动回复和新交易确认会被服务端阻止；回复由人工明确提交。">
      <template #actions>
        <el-button type="primary" :loading="busy" @click="refresh">刷新工单</el-button>
      </template>
    </PageHeader>

    <el-alert v-if="error" type="error" :title="error" show-icon :closable="false" class="table-gap" />
    <el-alert v-if="notice" type="success" :title="notice" show-icon :closable="false" class="table-gap" />

    <div class="table-data-card">
      <el-empty v-if="!tickets.length" description="暂无人工工单。" :image-size="80" />
      <article v-for="item in tickets" :key="item.ticket_id" class="ticket">
        <div class="ticket-head">
          <div class="ticket-title">
            <h3>{{ ticketReasonText(item.reason) }}</h3>
            <StatusTag :label="ticketStatusText(item.status)" :tone="badgeTone(item.status)" />
            <span class="muted-note">v{{ item.version }}</span>
            <p class="muted-note">创建 {{ timestamp(item.created_at) }} · 当前接管人 {{ item.assigned_actor_id || '待分配' }}</p>
          </div>
          <div class="button-row">
            <el-button :disabled="busy || !canManage(item)" @click="view(item)">查看会话</el-button>
            <el-button v-if="item.status === 'OPEN'" type="primary" :disabled="busy || !canManage(item)" @click="update(item, 'take_over')">接管</el-button>
            <el-button v-if="item.status !== 'CLOSED'" :disabled="busy || !canManage(item)" @click="closing = item">核对结束</el-button>
          </div>
        </div>
        <p v-if="item.resolution" class="resolution">最近人工回复：{{ item.resolution }}</p>
        <GrowthTechDetails title="移交证据和工单凭据" :value="item" />
        <el-form
          v-if="item.status === 'TAKEN_OVER' && canManage(item)"
          label-width="72px"
          class="reply-form"
          @submit.prevent="update(item, 'reply')"
        >
          <el-form-item label="人工回复">
            <el-input
              v-model="replies[item.ticket_id]"
              type="textarea"
              :rows="3"
              maxlength="4000"
              show-word-limit
              :disabled="busy"
              placeholder="写清处理结论与依据；提交后工单状态由服务端返回"
            />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" native-type="submit" :disabled="busy || !replies[item.ticket_id]?.trim()">提交人工回复</el-button>
          </el-form-item>
        </el-form>
      </article>
    </div>

    <div v-if="detail" class="table-data-card support-detail table-gap" aria-label="工单会话详情">
      <div class="ticket-head">
        <div class="ticket-title">
          <h3>工单会话详情</h3>
          <p class="muted-note">
            {{ ticketStatusText(detail.ticket.status) }} · {{ detail.conversation.subject_type }} {{ detail.conversation.actor_id }}
          </p>
        </div>
        <el-button :disabled="busy" @click="detail = null">收起会话</el-button>
      </div>

      <el-button v-if="detail.next_before_sequence" size="small" :disabled="busy" @click="older">加载更早消息</el-button>
      <el-empty v-if="!detail.messages.length" description="此会话尚无消息。" :image-size="60" />
      <article v-for="message in detail.messages" :key="message.message_id" class="support-message">
        <p class="muted-note">{{ speaker(message) }} · {{ timestamp(message.created_at) }} · #{{ message.sequence }}</p>
        <p class="message-body">{{ message.content }}</p>
      </article>

      <section v-if="detail.runs.length" aria-label="关联助手运行与引用">
        <h3>关联助手运行与引用</h3>
        <article v-for="run in detail.runs" :key="run.agent_run_id" class="plan-card">
          <p><StatusTag :label="run.state" /> {{ modeText(run.model_mode) }}</p>
          <p v-if="run.result.answer_status">回答状态：{{ run.result.answer_status }}</p>
          <GrowthDecisionCard :decision="run.result.decision" :checks="run.result.checks" />
          <p v-if="run.result.error || run.result.wait_reason" class="muted-note">{{ run.result.error || run.result.wait_reason }}</p>
          <el-collapse v-if="run.result.citations?.length">
            <el-collapse-item :title="`回复时保存的引用（${run.result.citations.length}）`">
              <p class="muted-note">以下为当时引用记录；当前政策适用性仍需核对。</p>
              <article v-for="source in run.result.citations" :key="`${source.doc_id}:${source.version}:${source.chunk_id}`" class="citation">
                <p><strong>{{ source.title }}</strong> · v{{ source.version }}</p>
                <p class="muted-note">{{ source.source_uri }} · {{ source.heading }} · 行 {{ source.start_line }}–{{ source.end_line }}</p>
                <p class="message-body">{{ source.content }}</p>
              </article>
            </el-collapse-item>
          </el-collapse>
        </article>
      </section>

      <section aria-label="已保存交易提案">
        <h3>已保存交易提案</h3>
        <p class="muted-note">提案与回执仅供人工核对；接管、回复或结束工单均不代表用户确认交易。</p>
        <p v-if="!detail.proposals.length" class="muted-note">已加载消息未关联交易提案。</p>
        <article v-for="proposal in detail.proposals" :key="proposal.proposal_id" class="plan-card">
          <p>
            <strong>{{ actionName(proposal.action_type) }}</strong> ·
            <StatusTag :label="proposalStatusText(proposal.status)" />
          </p>
          <p class="muted-note">
            版本 {{ proposal.version }} · 用户确认 {{ proposal.approved === true ? '已批准' : proposal.approved === false ? '已拒绝' : '尚无确认' }}
            · 结果 {{ proposal.outcome || '待核对' }} · 有效期 {{ timestamp(proposal.expires_at) }}
          </p>
          <p v-if="proposal.quote_total_cents != null">原报价金额：¥{{ money(proposal.quote_total_cents) }}</p>
          <GrowthTechDetails
            title="交易参数与已保存回执"
            :value="{ parameters: proposal.parameters, receipt: proposal.receipt, proposal_id: proposal.proposal_id }"
          />
        </article>
      </section>
    </div>

    <div v-if="closing" class="table-data-card table-gap">
      <h3>确认结束工单</h3>
      <p class="muted-note">{{ closing.ticket_id }} · 当前 v{{ closing.version }}。确认问题已处理后结束人工服务。</p>
      <div class="button-row">
        <el-button type="primary" :loading="busy" @click="update(closing, 'close')">确认结束</el-button>
        <el-button :disabled="busy" @click="closing = null">返回处理</el-button>
      </div>
    </div>
  </div>
</template>
<script setup>
import { onMounted, reactive, ref } from 'vue';
import { session, aiGet, aiWrite, loadSession, errorText, timestamp, money } from '../api/client';
import { hasAdminPermission } from '../utils/adminAccess';
import { badgeTone, modeText, proposalStatusText, ticketReasonText, ticketStatusText } from '../utils/growthDisplay';
import GrowthTechDetails from '../components/GrowthTechDetails.vue';
import GrowthDecisionCard from '../components/GrowthDecisionCard.vue';
const tickets = ref([]); const replies = reactive({}); const closing = ref(null); const busy = ref(false); const error = ref(''); const notice = ref('');
const detail = ref(null);
const canManage = item => hasAdminPermission(session.value?.actor, 'admin:legacy') && (!item.assigned_actor_id || item.assigned_actor_id === session.value?.actor.actor_id);
const speaker = message => message.role === 'user' ? '用户' : message.message_id.startsWith('human-') ? '人工客服' : '助手';
const actionName = action => ({ order: '下单', cancel: '取消订单', refund: '退款', payment: '模拟付款' }[action] || action);
async function read() {
  const selected = detail.value?.ticket.ticket_id; detail.value = null;
  tickets.value = await aiGet('/support');
  const item = tickets.value.find(row => row.ticket_id === selected);
  if (item && canManage(item)) await readDetail(item);
}
async function readDetail(item) {
  detail.value = await aiGet(`/support/${encodeURIComponent(item.ticket_id)}`);
  tickets.value = tickets.value.map(row => row.ticket_id === item.ticket_id ? detail.value.ticket : row);
}
async function view(item) {
  if (busy.value || !canManage(item)) return; busy.value = true; error.value = ''; detail.value = null;
  try { await readDetail(item); } catch (reason) { error.value = errorText(reason); } finally { busy.value = false; }
}
async function older() {
  if (busy.value || !detail.value?.next_before_sequence) return; busy.value = true; error.value = '';
  try {
    const previous = detail.value;
    const page = await aiGet(`/support/${encodeURIComponent(previous.ticket.ticket_id)}?before_sequence=${previous.next_before_sequence}`);
    const merge = (key, id) => [...new Map([...previous[key], ...page[key]].map(row => [row[id], row])).values()];
    detail.value = { ...page, messages: merge('messages', 'message_id').sort((a, b) => a.sequence - b.sequence),
      runs: merge('runs', 'agent_run_id'), proposals: merge('proposals', 'proposal_id') };
    tickets.value = tickets.value.map(row => row.ticket_id === page.ticket.ticket_id ? page.ticket : row);
  } catch (reason) { detail.value = null; error.value = errorText(reason); } finally { busy.value = false; }
}
async function refresh() { if (busy.value) return; busy.value = true; error.value = ''; try { await loadSession(); await read(); } catch (reason) { error.value = errorText(reason); } finally { busy.value = false; } }
async function update(item, action) {
  if (busy.value) return; busy.value = true; error.value = ''; notice.value = '';
  try { await aiWrite(`/support/${encodeURIComponent(item.ticket_id)}`, { action, version: item.version, ...(action === 'reply' ? { reply: replies[item.ticket_id].trim() } : {}) }, 'PATCH');
    if (action === 'reply') delete replies[item.ticket_id]; closing.value = null; notice.value = '工单状态已返回，请核对当前记录。'; await read();
  } catch (reason) { error.value = `${errorText(reason)} 刷新工单后核对原状态；不会自动重发回复。`; } finally { busy.value = false; }
}
onMounted(refresh);
</script>

<style scoped lang="scss">
.support-page {
  .table-gap {
    margin-bottom: 12px;
  }

  .ticket {
    padding: 14px 16px;
    border-bottom: 1px solid var(--border-soft);

    &:last-child {
      border-bottom: 0;
    }
  }

  .ticket-head {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 12px;
    margin-bottom: 8px;
  }

  .ticket-title {
    min-width: 0;

    h3 {
      margin: 0 0 4px;
      font-size: 15px;
      color: var(--text);
    }
  }

  .resolution {
    margin: 0 0 8px;
    color: var(--text-2);
  }

  .reply-form {
    margin-top: 10px;
  }

  .message-body {
    margin: 0;
    color: var(--text);
    white-space: pre-wrap;
  }

  .support-message {
    padding: 10px 0;
    border-bottom: 1px dashed var(--border-soft);
  }

  .citation {
    padding: 10px 12px;
    border: 1px solid var(--border-soft);
    border-radius: var(--radius-sm);
    margin-bottom: 8px;
  }

  .plan-card {
    padding: 10px 0;
  }

  h3 {
    font-size: 15px;
    color: var(--text);
  }
}
</style>
