import { request } from './client'

// 来源归属专属接口：与后端 /api/attributions 路由一一对应。
const BASE = '/api/attributions'

export type RawRowInput = {
  batch_label: string
  source: string
  sku: string
  quote: string | number
  recipient: string
  evidence?: Record<string, string | number>
}

export async function registerRawRow(input: RawRowInput): Promise<Record<string, unknown>> {
  const response = await request(`${BASE}/raw-rows`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
  return await response.json()
}

export async function withdrawSource(batchLabel: string, source: string): Promise<Record<string, unknown>> {
  const response = await request(`${BASE}/withdraw`, {
    method: 'POST',
    body: JSON.stringify({ batch_label: batchLabel, source }),
  })
  return await response.json()
}

export async function confirmAttribution(
  batchLabel: string,
  source: string,
  sku: string,
  recipient: string,
): Promise<Record<string, unknown>> {
  const response = await request(`${BASE}/confirm`, {
    method: 'POST',
    body: JSON.stringify({ batch_label: batchLabel, source, sku, recipient }),
  })
  return await response.json()
}

export async function confirmOnSite(
  input: RawRowInput,
): Promise<Record<string, unknown>> {
  const response = await request(`${BASE}/confirm-on-site`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
  return await response.json()
}

export async function fetchSkuStatus(
  batchLabel: string,
  sku: string,
): Promise<Record<string, unknown>> {
  const query = new URLSearchParams({ batch_label: batchLabel, sku }).toString()
  const response = await request(`${BASE}/sku-status?${query}`)
  return await response.json()
}

export async function fetchRecipientView(
  batchLabel: string,
  recipient: string,
): Promise<Record<string, unknown>> {
  const query = new URLSearchParams({ batch_label: batchLabel, recipient }).toString()
  const response = await request(`${BASE}/recipient-view?${query}`)
  return await response.json()
}

export async function deliverAttributed(
  batchLabel: string,
  recipient: string,
): Promise<Record<string, unknown>> {
  const response = await request(`${BASE}/deliver`, {
    method: 'POST',
    body: JSON.stringify({ batch_label: batchLabel, recipient }),
  })
  return await response.json()
}

export async function fetchDeliveries(
  batchLabel: string,
  recipient: string,
): Promise<Record<string, unknown>> {
  const query = new URLSearchParams({ batch_label: batchLabel, recipient }).toString()
  const response = await request(`${BASE}/deliveries?${query}`)
  return await response.json()
}
