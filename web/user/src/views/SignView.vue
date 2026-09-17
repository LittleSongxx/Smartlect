<template>
  <div class="sign-page">
    <section class="sign-stats">
      <div class="stats-row">
        <div class="stat-card">
          <p class="stat-value">{{ signData.continuousDays }}</p>
          <p class="stat-label">连续签到</p>
        </div>
        <div class="stat-card">
          <p class="stat-value">{{ signData.totalSignDays }}</p>
          <p class="stat-label">累计签到</p>
        </div>
        <div class="stat-card">
          <p class="stat-value">{{ signData.supplementCount }}</p>
          <p class="stat-label">补签次数</p>
        </div>
      </div>
      <p class="stats-tip">累计签到 30 天获得 1 次补签次数</p>
    </section>

    <section class="sign-reward-hint">
      <svg class="hint-icon" viewBox="0 0 20 20" width="16" height="16" fill="none">
        <rect x="2" y="4" width="16" height="4" rx="1" fill="var(--primary)"/>
        <path d="M4 8v7a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V8" stroke="var(--primary)" stroke-width="1.2"/>
        <path d="M10 4V17M7 2l3 2 3-2" stroke="var(--primary)" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
      <span>连续签到满 <strong>7</strong> 天、<strong>14</strong> 天、<strong>21</strong> 天……即送优惠券奖励！</span>
    </section>

    <section class="calendar-card card">
      <header class="calendar-head">
        <button type="button" class="nav-btn" @click="prevMonth">‹</button>
        <h3>{{ currentYear }}年{{ currentMonth + 1 }}月</h3>
        <button type="button" class="nav-btn" @click="nextMonth">›</button>
      </header>

      <div class="week-row">
        <span v-for="w in weekdays" :key="w">{{ w }}</span>
      </div>

      <div class="days-grid">
        <button
          v-for="(day, index) in calendarDays"
          :key="index"
          type="button"
          class="day-cell"
          :class="day.className"
          :disabled="!day.date"
          @click="handleDayClick(day)"
        >
          <span class="day-num">{{ day.day }}</span>
          <span v-if="day.signed" class="signed-mark">✓</span>
          <span v-if="day.supplement" class="sup-tag">补</span>
        </button>
      </div>
    </section>

    <footer class="sign-action">
      <el-button type="primary" size="large" round :disabled="todaySigned" @click="doSign">
        {{ todaySigned ? '今日已签到' : '立即签到' }}
      </el-button>
    </footer>

    <el-dialog v-model="supplementVisible" title="补签确认" width="90%" style="max-width: 360px">
      <p>确定消耗 1 次补签机会，补签 {{ supplementLabel }} 吗？</p>
      <template #footer>
        <el-button @click="supplementVisible = false">取消</el-button>
        <el-button type="primary" :loading="supplementLoading" @click="doSupplement">确认补签</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { signApi } from '@/api/modules';
import { ElMessageBox } from 'element-plus';
import { toast } from '@/utils/toast';
import { usePageRefresh } from '@/composables/pullRefresh';

const weekdays = ['日', '一', '二', '三', '四', '五', '六'];
const today = new Date();
const currentYear = ref(today.getFullYear());
const currentMonth = ref(today.getMonth());
const todaySigned = ref(false);
const supplementVisible = ref(false);
const supplementLoading = ref(false);
const supplementLabel = ref('');
const supplementDateParam = ref('');

const signData = reactive({
  continuousDays: 0,
  supplementCount: 0,
  totalSignDays: 0,
  signDays: [] as string[]
});

const yearMonth = () =>
  `${currentYear.value}${String(currentMonth.value + 1).padStart(2, '0')}`;

const calendarDays = computed(() => {
  const days: Array<{
    day: number;
    date: string | null;
    signed: boolean;
    supplement: boolean;
    className: string;
  }> = [];

  const firstDay = new Date(currentYear.value, currentMonth.value, 1);
  const lastDay = new Date(currentYear.value, currentMonth.value + 1, 0);
  const startDayOfWeek = firstDay.getDay();
  const totalDays = lastDay.getDate();
  const prevLastDay = new Date(currentYear.value, currentMonth.value, 0).getDate();

  for (let i = startDayOfWeek - 1; i >= 0; i--) {
    days.push({ day: prevLastDay - i, date: null, signed: false, supplement: false, className: 'is-other' });
  }

  for (let d = 1; d <= totalDays; d++) {
    const dateStr = `${yearMonth()}${String(d).padStart(2, '0')}`;
    const isToday =
      d === today.getDate() &&
      currentMonth.value === today.getMonth() &&
      currentYear.value === today.getFullYear();
    const isPast =
      currentYear.value < today.getFullYear() ||
      (currentYear.value === today.getFullYear() && currentMonth.value < today.getMonth()) ||
      (isToday === false &&
        currentYear.value === today.getFullYear() &&
        currentMonth.value === today.getMonth() &&
        d < today.getDate());

    const signed = signData.signDays.includes(dateStr);
    const canSupplement = !signed && !isToday && isPast && signData.supplementCount > 0;

    let className = '';
    if (isToday) className += ' is-today';
    if (signed) className += ' is-signed';
    if (canSupplement) className += ' can-supplement';

    days.push({
      day: d,
      date: dateStr,
      signed,
      supplement: canSupplement,
      className
    });

    if (isToday) todaySigned.value = signed;
  }

  const remain = 42 - days.length;
  for (let i = 1; i <= remain; i++) {
    days.push({ day: i, date: null, signed: false, supplement: false, className: 'is-other' });
  }

  return days;
});

const loadSignCalendar = async () => {
  const data = await signApi.getSignCalendar(yearMonth());
  signData.continuousDays = data?.continuousDays ?? 0;
  signData.supplementCount = data?.supplementCount ?? 0;
  signData.totalSignDays = data?.totalSignDays ?? 0;
  signData.signDays = data?.signDays ?? [];
};

const prevMonth = () => {
  if (currentMonth.value === 0) {
    currentMonth.value = 11;
    currentYear.value--;
  } else {
    currentMonth.value--;
  }
  loadSignCalendar();
};

const nextMonth = () => {
  if (currentMonth.value === 11) {
    currentMonth.value = 0;
    currentYear.value++;
  } else {
    currentMonth.value++;
  }
  loadSignCalendar();
};

const doSign = async () => {
  if (todaySigned.value) return;
  try {
    await signApi.sign();
    toast.success('签到成功');
    await loadSignCalendar();
  } catch (reason: any) {
    toast.error(reason?.info || reason?.message || '签到失败，请稍后重试');
    await loadSignCalendar();
    return;
  }
  const days = signData.continuousDays;
  if (days > 0 && days % 7 === 0) {
    ElMessageBox.alert(
      `连续签到 ${days} 天，恭喜您获得签到奖励！请前往「优惠券」查看。`,
      '签到奖励',
      {
        confirmButtonText: '知道了',
        type: 'success',
        customClass: 'sign-reward-alert',
        showClose: false,
        roundButton: true
      }
    );
  }
};

const handleDayClick = (day: { supplement?: boolean; date?: string | null; day: number }) => {
  if (!day.supplement || !day.date) return;
  supplementLabel.value = `${currentYear.value}年${currentMonth.value + 1}月${day.day}日`;
  supplementDateParam.value = day.date;
  supplementVisible.value = true;
};

const doSupplement = async () => {
  supplementLoading.value = true;
  try {
    await signApi.msign(supplementDateParam.value);
    supplementVisible.value = false;
    toast.success('补签成功');
    loadSignCalendar();
  } finally {
    supplementLoading.value = false;
  }
};

onMounted(loadSignCalendar);
usePageRefresh(loadSignCalendar);
</script>

<style scoped lang="scss">
@use '@/styles/variables' as *;

.sign-page {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
  box-sizing: border-box;
}

.sign-stats {
  display: flex;
  flex-direction: column;
  align-items: center;
  flex-shrink: 0;
  width: 100%;
}

.stats-row {
  display: flex;
  justify-content: center;
  align-items: stretch;
  gap: 8px;
  width: 100%;
  max-width: 360px;
}

.stat-card {
  flex: 1;
  min-width: 0;
  max-width: 112px;
  background: $color-card;
  border: 1px solid $color-border;
  border-radius: $radius-card;
  padding: 10px 6px;
  text-align: center;

  .stat-value {
    margin: 0;
    font-size: 20px;
    font-weight: 700;
    color: $color-primary;
    line-height: 1.1;
  }

  .stat-label {
    margin: 4px 0 0;
    font-size: 11px;
    color: $color-text-muted;
    white-space: nowrap;
  }
}

.stats-tip {
  margin: 6px 0 0;
  width: 100%;
  font-size: 11px;
  color: $color-text-muted;
  text-align: center;
}

.sign-reward-hint {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  margin: 0 auto;
  padding: 8px 14px;
  max-width: 360px;
  background: $color-primary-soft;
  border: 1px solid $color-primary-muted;
  border-radius: $radius-card;
  font-size: 12px;
  color: $color-text-body;
  line-height: 1.5;
  flex-shrink: 0;
  box-sizing: border-box;

  .hint-icon {
    flex-shrink: 0;
    display: block;
  }

  strong {
    color: $color-primary;
    font-weight: 700;
  }
}

.calendar-card {
  flex: 1 1 auto;
  min-height: 0;
  padding: 10px 10px 8px;
}

.calendar-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;

  h3 {
    margin: 0;
    font-size: 15px;
    font-weight: 600;
  }

  .nav-btn {
    border: none;
    background: $color-bg;
    width: 28px;
    height: 28px;
    border-radius: $radius-xs;
    cursor: pointer;
    font-size: 16px;
    line-height: 1;
    color: $color-text-body;
  }
}

.week-row {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  margin-bottom: 4px;

  span {
    text-align: center;
    font-size: 11px;
    color: $color-text-muted;
    padding: 2px 0;
    line-height: 1.2;
  }
}

.days-grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 3px;
}

.day-cell {
  height: 32px;
  border: none;
  border-radius: $radius-xs;
  background: #fafafa;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0;
  cursor: default;
  position: relative;
  padding: 0;

  .day-num {
    font-size: 12px;
    line-height: 1.1;
    color: $color-text-body;
  }

  &.is-other {
    opacity: 0.35;
  }

  &.is-today {
    box-shadow: inset 0 0 0 1.5px $color-primary;
  }

  &.is-signed {
    background: $color-primary-soft;

    .day-num {
      color: $color-primary;
      font-weight: 600;
    }

    .signed-mark {
      font-size: 9px;
      line-height: 1;
      color: $color-success;
    }
  }

  &.can-supplement {
    background: $color-primary-soft;
    cursor: pointer;

    .sup-tag {
      font-size: 9px;
      background: $color-primary;
      color: #fff;
      border-radius: $radius-xs;
      padding: 0 3px;
      line-height: 1.3;
    }
  }
}

.sign-action {
  flex-shrink: 0;
  display: flex;
  justify-content: center;
  padding: 4px 0 8px;

  :deep(.el-button) {
    width: 100%;
    max-width: 280px;
    height: 40px;
  }
}
</style>

<style lang="scss">
@use '@/styles/variables' as *;

.sign-reward-alert {
  border-radius: $radius-card;
  background: $color-card;
  border: 1px solid $color-border;
  max-width: 320px;
  padding: 4px;

  .el-message-box__header {
    padding: 20px 24px 4px;
  }

  .el-message-box__title {
    font-size: 17px;
    font-weight: 600;
    color: $color-text-title;
  }

  .el-message-box__status {
    font-size: 24px;
    position: static;
    display: inline-block;
    margin-right: 8px;
    vertical-align: middle;
  }

  .el-message-box__content {
    padding: 8px 24px 4px;
  }

  .el-message-box__message {
    font-size: 14px;
    line-height: 1.6;
    color: $color-text-body;
  }

  .el-message-box__btns {
    padding: 12px 24px 20px;
    display: flex;
    justify-content: center;

    .el-button {
      border-radius: $radius-card;
      padding: 8px 32px;
      min-width: 120px;
    }
  }
}
</style>
