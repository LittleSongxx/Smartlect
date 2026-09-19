import js from '@eslint/js'
import pluginVue from 'eslint-plugin-vue'
import globals from 'globals'

// 最小正确性检查：eslint recommended + vue flat/essential，不接风格规则、不进 CI 门禁。
// admin 存量代码较旧：未用变量先降为 warn（逐步清零），几个 legacy 组件模式按规则豁免。
export default [
  { ignores: ['dist/**', 'node_modules/**'] },
  js.configs.recommended,
  ...pluginVue.configs['flat/essential'],
  {
    files: ['**/*.vue', '**/*.js', '**/*.mjs'],
    languageOptions: {
      sourceType: 'module',
      ecmaVersion: 'latest',
      globals: { ...globals.browser }
    }
  },
  {
    files: ['vite.config.js', 'tests/**/*.js'],
    languageOptions: { globals: { ...globals.browser, ...globals.node } }
  },
  {
    rules: {
      'no-empty': ['error', { allowEmptyCatch: true }],
      // 存量清零前的过渡口径：新代码不该再欠账，warn 不挡构建
      'no-unused-vars': ['warn', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      // 全局注册的单名组件（Avatar/Cover/Dialog/Drawer/Price/Table）是项目既有命名约定
      'vue/multi-word-component-names': 'off',
      // main.js 全局注册的 Dialog/Table 与 HTML 保留名撞名是既有事实
      'vue/no-reserved-component-names': 'off',
      // legacy 封装组件：Table/Dialog/Drawer 直接编辑 props / .sync / 未声明 emits，
      // 行为已被现有页面依赖，重构另行排期
      'vue/no-mutating-props': 'off',
      'vue/no-deprecated-v-bind-sync': 'off',
      'vue/valid-define-emits': 'off',
      'no-async-promise-executor': 'off'
    }
  }
]
