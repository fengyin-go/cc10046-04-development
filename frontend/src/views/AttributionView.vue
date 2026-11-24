<template>
  <section class="page" data-module="source_attribution">
    <header class="page-head">
      <div>
        <h2>来源归属</h2>
        <p class="page-desc">
          把采集原始行按批次标签归属给收件人：来源确认、撤回、现场补发与归属交付全程留痕
        </p>
      </div>
    </header>

    <p v-if="message" class="page-desc" data-testid="attr-message">{{ message }}</p>
    <p v-if="errorMessage" class="error-text" data-testid="attr-error">{{ errorMessage }}</p>

    <!-- 操作区：登记原始行 / 撤回 / 确认 / 现场补发 / 交付 -->
    <div class="stat-row">
      <article class="stat-card">
        <h3>登记采集原始行并归属</h3>
        <form class="attr-form" @submit.prevent="onRegister">
          <label v-for="field in registerFields" :key="field.key" class="create-field">
            <span>{{ field.label }}</span>
            <input v-model="registerForm[field.key]" :data-testid="`reg-${field.key}`" />
          </label>
          <button class="btn primary" data-testid="submit-register" type="submit">登记并归属</button>
        </form>
      </article>

      <article class="stat-card">
        <h3>来源撤回（只影响后续交付）</h3>
        <form class="attr-form" @submit.prevent="onWithdraw">
          <label class="create-field"><span>批次标签</span><input v-model="withdrawForm.batch_label" data-testid="wd-batch" /></label>
          <label class="create-field"><span>来源方</span><input v-model="withdrawForm.source" data-testid="wd-source" /></label>
          <button class="btn" data-testid="submit-withdraw" type="submit">撤回该来源</button>
        </form>
      </article>

      <article class="stat-card">
        <h3>按原始凭据确认（含迟到确认）</h3>
        <form class="attr-form" @submit.prevent="onConfirm">
          <label class="create-field"><span>批次标签</span><input v-model="confirmForm.batch_label" data-testid="cf-batch" /></label>
          <label class="create-field"><span>来源方</span><input v-model="confirmForm.source" data-testid="cf-source" /></label>
          <label class="create-field"><span>货号</span><input v-model="confirmForm.sku" data-testid="cf-sku" /></label>
          <label class="create-field"><span>收件人</span><input v-model="confirmForm.recipient" data-testid="cf-recipient" /></label>
          <button class="btn primary" data-testid="submit-confirm" type="submit">确认来源</button>
        </form>
      </article>
    </div>

    <div class="stat-row">
      <article class="stat-card">
        <h3>现场补发（凭据齐备同时确认）</h3>
        <form class="attr-form" @submit.prevent="onOnSite">
          <label class="create-field"><span>批次标签</span><input v-model="onSiteForm.batch_label" data-testid="os-batch" /></label>
          <label class="create-field"><span>来源方</span><input v-model="onSiteForm.source" data-testid="os-source" /></label>
          <label class="create-field"><span>货号</span><input v-model="onSiteForm.sku" data-testid="os-sku" /></label>
          <label class="create-field"><span>报价</span><input v-model="onSiteForm.quote" data-testid="os-quote" /></label>
          <label class="create-field"><span>收件人</span><input v-model="onSiteForm.recipient" data-testid="os-recipient" /></label>
          <label class="create-field"><span>来源凭据</span><input v-model="onSiteForm.evidence.来源凭据" data-testid="os-evidence" /></label>
          <button class="btn primary" data-testid="submit-onsite" type="submit">补发并确认</button>
        </form>
      </article>

      <article class="stat-card">
        <h3>归属交付批次（导出通道消费归属记录）</h3>
        <form class="attr-form" @submit.prevent="onDeliver">
          <label class="create-field"><span>批次标签</span><input v-model="deliverForm.batch_label" data-testid="dv-batch" /></label>
          <label class="create-field"><span>收件人</span><input v-model="deliverForm.recipient" data-testid="dv-recipient" /></label>
          <button class="btn primary" data-testid="submit-deliver" type="submit">组装交付批次</button>
        </form>
        <ul v-if="lastDelivery.length" class="attr-list" data-testid="delivery-lines">
          <li v-for="line in lastDelivery" :key="line.key">
            {{ line.货号 }}｜来源 {{ line.来源方 }}｜报价 {{ line.报价 }}｜{{ line.原始凭据 }}
          </li>
        </ul>
      </article>

      <article class="stat-card">
        <h3>收件方受限视图 / 货号确认状态</h3>
        <form class="attr-form" @submit.prevent="onRecipientView">
          <label class="create-field"><span>批次标签</span><input v-model="viewForm.batch_label" data-testid="vw-batch" /></label>
          <label class="create-field"><span>收件人</span><input v-model="viewForm.recipient" data-testid="vw-recipient" /></label>
          <button class="btn" data-testid="submit-view" type="submit">查看归属给我的原始行</button>
        </form>
        <ul v-if="recipientRows.length" class="attr-list" data-testid="recipient-rows">
          <li v-for="row in recipientRows" :key="row.key">
            {{ row.货号 }}｜来源 {{ row.来源方 }}｜报价 {{ row.报价 }}
          </li>
        </ul>
      </article>
    </div>

    <!-- 归属记录表 -->
    <table class="data-table" data-testid="attribution-table">
      <thead>
        <tr>
          <th v-for="column in meta.fields" :key="column">{{ column }}</th>
          <th>当前状态</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :data-status="String(row.status)">
          <td v-for="column in meta.fields" :key="column">{{ row[column] ?? '—' }}</td>
          <td>{{ row.status }}</td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="meta.fields.length + 1" class="empty-state">暂无来源归属记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条来源归属记录</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { listEntries } from '@/api/backend-service'
import {
  confirmAttribution,
  confirmOnSite,
  deliverAttributed,
  fetchRecipientView,
  registerRawRow,
  withdrawSource,
} from '@/api/attribution'
import { moduleMeta } from '@/data/modules'
import type { EntryRow } from '@/data/types'

type RegisterForm = {
  batch_label: string
  source: string
  sku: string
  quote: string
  recipient: string
  credential: string
}

type DeliveryLine = {
  key: string
  货号: string
  来源方: string
  报价: string | number
  原始凭据: string
}

type RecipientRow = {
  key: string
  原始行标识: string
  货号: string
  来源方: string
  报价: string | number
}

type ApiRecord = Record<string, unknown>

const meta = moduleMeta('source_attribution')
const rows = ref<EntryRow[]>([])
const total = ref(0)
const message = ref('')
const errorMessage = ref('')
const lastDelivery = ref<DeliveryLine[]>([])
const recipientRows = ref<RecipientRow[]>([])

const registerFields: { key: keyof RegisterForm; label: string }[] = [
  { key: 'batch_label', label: '批次标签' },
  { key: 'source', label: '来源方' },
  { key: 'sku', label: '货号' },
  { key: 'quote', label: '报价' },
  { key: 'recipient', label: '收件人' },
  { key: 'credential', label: '来源凭据' },
]

const emptyRegister = (): RegisterForm => ({
  batch_label: '',
  source: '',
  sku: '',
  quote: '',
  recipient: '',
  credential: '',
})
const registerForm = ref<RegisterForm>(emptyRegister())
const withdrawForm = ref({ batch_label: '', source: '' })
const confirmForm = ref({ batch_label: '', source: '', sku: '', recipient: '' })
const onSiteForm = ref({
  batch_label: '',
  source: '',
  sku: '',
  quote: '',
  recipient: '',
  evidence: { 报价快照: '', 来源凭据: '', 采集时间: '' },
})
const deliverForm = ref({ batch_label: '', recipient: '' })
const viewForm = ref({ batch_label: '', recipient: '' })

function asString(value: unknown): string {
  return value === null || value === undefined ? '' : String(value)
}

function flash(text: string, isError = false) {
  if (isError) {
    errorMessage.value = text
    message.value = ''
  } else {
    message.value = text
    errorMessage.value = ''
  }
}

async function reload() {
  try {
    const payload = await listEntries('source_attribution', {})
    rows.value = payload.items
    total.value = payload.total
  } catch (error) {
    flash(error instanceof Error ? error.message : '归属记录读取失败', true)
  }
}

async function onRegister() {
  try {
    const form = registerForm.value
    const result = (await registerRawRow({
      batch_label: form.batch_label,
      source: form.source,
      sku: form.sku,
      quote: form.quote,
      recipient: form.recipient,
      evidence: {
        报价快照: `${form.source} 对 ${form.sku} 的原始报价 ${form.quote}`,
        来源凭据: form.credential,
        采集时间: new Date().toISOString(),
      },
    })) as ApiRecord
    flash(asString(result.message) || '原始行已登记并归属')
    registerForm.value = emptyRegister()
    await reload()
  } catch (error) {
    flash(error instanceof Error ? error.message : '登记失败', true)
  }
}

async function onWithdraw() {
  try {
    const result = (await withdrawSource(
      withdrawForm.value.batch_label,
      withdrawForm.value.source,
    )) as ApiRecord
    flash(asString(result.message) || '来源已撤回')
    await reload()
  } catch (error) {
    flash(error instanceof Error ? error.message : '撤回失败', true)
  }
}

async function onConfirm() {
  try {
    const form = confirmForm.value
    const result = (await confirmAttribution(
      form.batch_label,
      form.source,
      form.sku,
      form.recipient,
    )) as ApiRecord
    flash(asString(result.message) || '确认完成')
    await reload()
  } catch (error) {
    flash(error instanceof Error ? error.message : '确认失败', true)
  }
}

async function onOnSite() {
  try {
    const form = onSiteForm.value
    const result = (await confirmOnSite({
      batch_label: form.batch_label,
      source: form.source,
      sku: form.sku,
      quote: form.quote,
      recipient: form.recipient,
      evidence: {
        报价快照: `${form.source} 对 ${form.sku} 的原始报价 ${form.quote}`,
        来源凭据: form.evidence.来源凭据,
        采集时间: new Date().toISOString(),
      },
    })) as ApiRecord
    flash(asString(result.message) || '现场补发处理完成')
    await reload()
  } catch (error) {
    flash(error instanceof Error ? error.message : '现场补发失败', true)
  }
}

async function onDeliver() {
  try {
    const result = (await deliverAttributed(
      deliverForm.value.batch_label,
      deliverForm.value.recipient,
    )) as ApiRecord
    const lines = (result.lines as ApiRecord[] | undefined) ?? []
    lastDelivery.value = lines.map((line) => ({
      key: `${asString(line.货号)}-${asString(line.原始行标识)}`,
      货号: asString(line.货号),
      来源方: asString(line.来源方),
      报价: (line.报价 as string | number) ?? '',
      原始凭据: asString(line.原始凭据),
    }))
    flash(asString(result.message) || '交付批次已组装')
    await reload()
  } catch (error) {
    flash(error instanceof Error ? error.message : '交付失败', true)
  }
}

async function onRecipientView() {
  try {
    const result = (await fetchRecipientView(
      viewForm.value.batch_label,
      viewForm.value.recipient,
    )) as ApiRecord
    const rawRows = (result.raw_rows as ApiRecord[] | undefined) ?? []
    recipientRows.value = rawRows.map((row) => ({
      key: asString(row.原始行标识),
      原始行标识: asString(row.原始行标识),
      货号: asString(row.货号),
      来源方: asString(row.来源方),
      报价: (row.报价 as string | number) ?? '',
    }))
    flash(asString(result.message) || '收件人视图已刷新')
  } catch (error) {
    flash(error instanceof Error ? error.message : '收件人视图读取失败', true)
  }
}

onMounted(reload)
</script>

<style scoped>
.attr-form {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.attr-list {
  margin: 8px 0 0;
  padding-left: 18px;
  font-size: 12px;
}
h3 {
  margin: 0 0 8px;
  font-size: 14px;
}
</style>
