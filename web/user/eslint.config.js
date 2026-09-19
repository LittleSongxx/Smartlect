import js from '@eslint/js'
import pluginVue from 'eslint-plugin-vue'
import tsParser from '@typescript-eslint/parser'
import tsPlugin from '@typescript-eslint/eslint-plugin'
import globals from 'globals'

// 最小正确性检查：eslint recommended + vue flat/essential，不接风格规则、不进 CI 门禁。
// script lang="ts" 交给 @typescript-eslint/parser 解析。
export default [
  { ignores: ['dist/**', 'node_modules/**', 'coverage/**'] },
  js.configs.recommended,
  ...pluginVue.configs['flat/essential'],
  {
    files: ['**/*.vue'],
    languageOptions: {
      parserOptions: { parser: tsParser, sourceType: 'module', ecmaVersion: 'latest' },
      globals: { ...globals.browser }
    },
    plugins: { '@typescript-eslint': tsPlugin },
    rules: {
      // TS 类型（DOM lib）由编译器检查，core no-undef 只会误报 EventListener 之类
      'no-undef': 'off',
      // core 规则不识别 TS 类型注解（会把 (blob: Blob) => 的 blob 报成未用），换 ts 插件版
      'no-unused-vars': 'off',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }]
    }
  },
  {
    files: ['**/*.ts', '**/*.js', '**/*.mjs'],
    languageOptions: {
      parser: tsParser,
      sourceType: 'module',
      ecmaVersion: 'latest',
      globals: { ...globals.browser }
    },
    plugins: { '@typescript-eslint': tsPlugin },
    rules: {
      // TS 类型（DOM lib）由编译器检查，core no-undef 只会误报 EventListener 之类
      'no-undef': 'off',
      // core 规则不识别 TS 类型注解（会把 (blob: Blob) => 的 blob 报成未用），换 ts 插件版
      'no-unused-vars': 'off',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }]
    }
  },
  {
    // 布局型 Transition：RouterView 换组件触发过渡，宿主 div 常驻（规则假定内容可卸载）
    files: ['src/layouts/PcSubPageLayout.vue'],
    rules: { 'vue/require-toggle-inside-transition': 'off' }
  },
  {
    // 签到日历既有模式：computed 组装日历时顺带刷新 todaySigned（拆分 computed 排期）
    files: ['src/views/SignView.vue'],
    rules: { 'vue/no-side-effects-in-computed-properties': 'off' }
  },
  {
    files: ['tests/**/*.ts', 'vitest.config.ts', 'vite.config.ts'],
    languageOptions: { globals: { ...globals.browser, ...globals.node } }
  },
  {
    rules: {
      'no-empty': ['error', { allowEmptyCatch: true }]
    }
  },
  {
    // 既有模式：地址表单直接编辑对象 prop 的字段（defineModel 化重构另行排期）
    files: ['src/components/business/AddressFormFields.vue'],
    rules: { 'vue/no-mutating-props': 'off' }
  }
]
