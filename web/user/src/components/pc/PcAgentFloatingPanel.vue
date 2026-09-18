<template>
  <Teleport to="body">
    <Transition name="pc-agent-fade">
      <div
        v-if="pcAgentPanel.visible"
        class="pc-agent-float-root ignore"
        role="dialog"
        aria-label="智能客服"
        @click.self="pcAgentPanel.close()"
      >
        <section class="pc-agent-float-panel agent-page" @click.stop>
          <header class="pc-agent-float-head">
            <div class="head-title">
              <el-icon class="head-icon" :size="18"><ChatDotRound /></el-icon>
              <div class="head-copy">
                <span>智能客服</span>
                <small>{{ connection }}</small>
              </div>
            </div>
            <div class="head-actions">
              <button type="button" :disabled="busy" @click="restore()">刷新</button>
              <button type="button" :disabled="busy" @click="newConversation">新会话</button>
              <button type="button" class="btn-close" aria-label="关闭" @click="pcAgentPanel.close()">
                <el-icon :size="18"><Close /></el-icon>
              </button>
            </div>
          </header>
          <AgentWorkspace compact />
        </section>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { ChatDotRound, Close } from '@element-plus/icons-vue';
import AgentWorkspace from '@/views/agent/AgentWorkspace.vue';
import { useAgentSession } from '@/composables/useAgentSession';
import { usePcAgentPanelStore } from '@/stores/pcAgentPanel';

const pcAgentPanel = usePcAgentPanelStore();
const { busy, connection, restore, newConversation } = useAgentSession();
</script>

<style scoped lang="scss">
@use '@/styles/variables' as *;

.pc-agent-float-root {
  position: fixed;
  inset: 0;
  z-index: $z-index-float-agent;
  background: rgba(60, 40, 20, 0.28);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 20px;
  box-sizing: border-box;
}

.pc-agent-float-panel {
  flex: 0 0 auto;
  align-self: center;
  width: min(560px, calc(100vw - 40px));
  height: min(800px, calc(100vh - 48px));
  min-height: 600px;
  max-width: 560px;
  display: flex;
  flex-direction: column;
  background: $color-card;
  border-radius: 16px;
  box-shadow: 0 16px 48px rgba(60, 40, 20, 0.16);
  overflow: hidden;
  border: 1px solid $color-border-gray;
}

.pc-agent-float-head {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  border-bottom: 1px solid $color-border-gray;
  background: linear-gradient(90deg, rgba($color-primary, 0.08), transparent);

  .head-title {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
  }

  .head-copy {
    display: flex;
    flex-direction: column;
    min-width: 0;

    span {
      font-size: 15px;
      font-weight: 600;
      color: $color-text-title;
    }

    small {
      font-size: 11px;
      color: $color-text-muted;
    }
  }

  .head-icon {
    color: $color-primary;
  }

  .head-actions {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-shrink: 0;
  }

  .head-actions button {
    border: 0;
    background: transparent;
    color: $color-text-body;
    font-size: 12px;
    padding: 6px 8px;
    border-radius: $radius-sm;
    white-space: nowrap;
  }

  .head-actions button:hover:enabled {
    background: $color-bg-subtle;
    color: $color-text-title;
  }

  .btn-close {
    display: grid;
    place-items: center;
    width: 32px;
    height: 32px;
    padding: 0;
    color: $color-text-muted;
  }
}

.pc-agent-fade-enter-active,
.pc-agent-fade-leave-active {
  transition: opacity 0.2s ease;

  .pc-agent-float-panel {
    transition: transform 0.22s ease, opacity 0.2s ease;
  }
}

.pc-agent-fade-enter-from,
.pc-agent-fade-leave-to {
  opacity: 0;

  .pc-agent-float-panel {
    transform: scale(0.96);
    opacity: 0;
  }
}
</style>
