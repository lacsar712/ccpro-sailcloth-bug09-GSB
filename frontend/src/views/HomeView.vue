<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import api from '../api'

const lofts = ref([])
const rolls = ref([])
const dips = ref([])
const todayKey = ref('')
const totalDipCount = ref(0)
const todayDipCount = ref(0)
const error = ref('')
const panelError = ref('')
const selectedId = ref(null)
const panelBusy = ref(false)

const statusLabel = { raw: '原布', dipping: '浸渍中', cured: '已固化' }

const dipForm = reactive({
  startedAt: '',
  resinPct: 28,
  cureHours: '',
  notes: '',
})

// datetime-local 不带时区：默认值取服务器时区(Asia/Shanghai)墙钟时间，
// 提交时也显式按 +08:00 解释，保证新写入落进服务器自然日的今天组，
// 与工人浏览器/容器所在时区无关。
function shanghaiNowInput() {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).formatToParts(new Date())
  const p = Object.fromEntries(parts.map((x) => [x.type, x.value]))
  return `${p.year}-${p.month}-${p.day}T${p.hour === '24' ? '00' : p.hour}:${p.minute}`
}

function asShanghaiIso(localInput) {
  const withSeconds = localInput.length === 16 ? `${localInput}:00` : localInput
  return `${withSeconds}+08:00`
}

const selected = computed(() => rolls.value.find((r) => r.id === selectedId.value) || null)

const rollsByLoft = computed(() => {
  return lofts.value.map((loft) => ({
    loft,
    rolls: rolls.value.filter((r) => r.loftId === loft.id),
  }))
})

const selectedDips = computed(() => {
  if (!selectedId.value) return []
  return dips.value.filter((d) => d.rollId === selectedId.value)
})

// 流水分组完全以后端给的服务器自然日 dayKey 为准，前端不再做时区折叠。
const feedGroups = computed(() => {
  const groups = []
  const index = new Map()
  for (const row of dips.value) {
    let g = index.get(row.dayKey)
    if (!g) {
      g = { key: row.dayKey, rows: [] }
      index.set(row.dayKey, g)
      groups.push(g)
    }
    g.rows.push(row)
  }
  return groups.map((g) => ({ ...g, label: dayLabel(g.key) }))
})

function dayLabel(key) {
  if (key === todayKey.value) return '今天'
  if (todayKey.value) {
    const [y, m, d] = todayKey.value.split('-').map(Number)
    const prev = new Date(y, m - 1, d - 1)
    const py = prev.getFullYear()
    const pm = String(prev.getMonth() + 1).padStart(2, '0')
    const pd = String(prev.getDate()).padStart(2, '0')
    if (key === `${py}-${pm}-${pd}`) return '昨天'
  }
  return key
}

async function load() {
  error.value = ''
  try {
    const [l, r, d, t] = await Promise.all([
      api.get('/lofts/'),
      api.get('/rolls/'),
      api.get('/dips/'),
      api.get('/dips/today/'),
    ])
    lofts.value = l.data.results || l.data
    rolls.value = r.data.results || r.data
    // 挂签/流水「总条数」用分页器 count，直接对库，不取本页数组长度
    totalDipCount.value =
      typeof d.data.count === 'number' ? d.data.count : (d.data.results || d.data).length
    dips.value = d.data.results || d.data
    // 「今天组」整条口径（含条数）都由服务器自然日接口给出
    todayKey.value = t.data.today || ''
    todayDipCount.value = t.data.count ?? (t.data.results || []).length
  } catch {
    error.value = '晾晒架加载失败'
  }
}

function openRoll(roll) {
  selectedId.value = roll.id
  panelError.value = ''
  dipForm.startedAt = shanghaiNowInput()
  dipForm.resinPct = 28
  dipForm.cureHours = ''
  dipForm.notes = ''
}

function closePanel() {
  selectedId.value = null
  panelError.value = ''
}

async function setStatus(status) {
  if (!selected.value) return
  panelError.value = ''
  panelBusy.value = true
  try {
    await api.patch(`/rolls/${selected.value.id}/`, { status })
    await load()
  } catch (e) {
    const data = e.response?.data
    panelError.value =
      data?.status?.[0] ||
      data?.detail ||
      '状态更新失败（标「已固化」需最近浸渍固化时长 ≥ 12 小时）'
  } finally {
    panelBusy.value = false
  }
}

async function logDip() {
  if (!selected.value) return
  panelError.value = ''
  panelBusy.value = true
  try {
    await api.post('/dips/', {
      rollId: selected.value.id,
      startedAt: asShanghaiIso(dipForm.startedAt),
      resinPct: dipForm.resinPct,
      cureHours:
        dipForm.cureHours === '' || dipForm.cureHours === null
          ? null
          : dipForm.cureHours,
      notes: dipForm.notes,
    })
    if (selected.value.status === 'raw') {
      try {
        await api.patch(`/rolls/${selected.value.id}/`, { status: 'dipping' })
      } catch {
        /* 浸渍已记；状态跟进失败不阻断 */
      }
    }
    dipForm.cureHours = ''
    dipForm.notes = ''
    dipForm.startedAt = shanghaiNowInput()
    await load()
  } catch (e) {
    panelError.value =
      e.response?.data?.detail ||
      JSON.stringify(e.response?.data) ||
      '登记浸渍失败'
  } finally {
    panelBusy.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="rack-page">
    <header class="rack-head">
      <div>
        <h1>帆布间晾晒架</h1>
        <p class="sub">按帆布间挂卷；点选布卷登记浸渍或标固化。固化规则：最近浸渍时长 ≥ 12 小时。</p>
      </div>
      <button class="btn secondary" type="button" @click="load">刷新架面</button>
    </header>

    <p v-if="error" class="error">{{ error }}</p>

    <div class="rack-floor">
      <section
        v-for="group in rollsByLoft"
        :key="group.loft.id"
        class="loft-bay"
      >
        <div class="bay-rail">
          <span class="bay-name">{{ group.loft.name }}</span>
          <span class="bay-meta">{{ group.loft.location || '工位' }} · {{ group.rolls.length }} 卷</span>
        </div>
        <div class="peg-row">
          <button
            v-for="roll in group.rolls"
            :key="roll.id"
            type="button"
            class="roll-chip"
            :class="[
              'chip-' + roll.status,
              { 'is-selected': selectedId === roll.id },
            ]"
            @click="openRoll(roll)"
          >
            <span class="peg" aria-hidden="true" />
            <span class="hang-tag" :class="'tag-' + roll.status">
              {{ statusLabel[roll.status] || roll.status }} · {{ roll.dipCount ?? 0 }} 笔
            </span>
            <span class="chip-code">{{ roll.rollCode }}</span>
            <span class="chip-gsm">{{ roll.fabricWeightGsm }} gsm</span>
          </button>
          <p v-if="!group.rolls.length" class="empty-bay">此间暂无布卷</p>
        </div>
      </section>
      <p v-if="!lofts.length && !error" class="hint">尚无帆布间数据</p>
    </div>

    <section class="dip-feed panel">
      <h2 class="feed-title">浸渍流水</h2>
      <p class="sub">
        今天组 {{ todayDipCount }} 条<span v-if="todayKey">（服务器自然日 {{ todayKey }}）</span>
        · 全库共 {{ totalDipCount }} 条
      </p>
      <p class="hint" style="margin: 0 0 12px">架下次要信息流；主操作在右侧布卷面板完成。</p>
      <template v-if="feedGroups.length">
        <div v-for="g in feedGroups" :key="g.key" class="feed-group">
          <h3 class="feed-day">
            {{ g.label }}
            <span class="feed-day-meta">{{ g.key }} · {{ g.rows.length }} 条</span>
          </h3>
          <ul class="feed-list">
            <li v-for="row in g.rows" :key="row.id">
              <strong>{{ row.rollCode }}</strong>
              <span class="feed-loft">{{ row.loftName }}</span>
              <span>{{ new Date(row.startedAt).toLocaleString() }}</span>
              <span>树脂 {{ row.resinPct }}%</span>
              <span>固化 {{ row.cureHours ?? '—' }} h</span>
            </li>
          </ul>
        </div>
      </template>
      <p v-else class="hint" style="margin:0">暂无浸渍记录</p>
    </section>

    <div
      v-if="selected"
      class="drawer-backdrop"
      @click.self="closePanel"
    />
    <aside v-if="selected" class="roll-drawer" aria-label="布卷操作">
      <header class="drawer-head">
        <div>
          <p class="drawer-kicker">{{ selected.loftName }}</p>
          <h2>{{ selected.rollCode }}</h2>
        </div>
        <button class="btn secondary" type="button" @click="closePanel">关闭</button>
      </header>

      <div class="drawer-status">
        <span class="hang-tag" :class="'tag-' + selected.status">
          {{ statusLabel[selected.status] }}
        </span>
        <span class="hint">{{ selected.fabricWeightGsm }} gsm</span>
      </div>
      <p v-if="selected.notes" class="hint">{{ selected.notes }}</p>
      <p v-if="panelError" class="error">{{ panelError }}</p>

      <div class="drawer-actions">
        <button
          class="btn secondary"
          type="button"
          :disabled="panelBusy || selected.status === 'raw'"
          @click="setStatus('raw')"
        >
          标为原布
        </button>
        <button
          class="btn secondary"
          type="button"
          :disabled="panelBusy || selected.status === 'dipping'"
          @click="setStatus('dipping')"
        >
          标为浸渍中
        </button>
        <button
          class="btn"
          type="button"
          :disabled="panelBusy || selected.status === 'cured'"
          @click="setStatus('cured')"
        >
          标为已固化
        </button>
      </div>

      <form class="drawer-form" @submit.prevent="logDip">
        <h3>登记浸渍</h3>
        <label>开始时间
          <input v-model="dipForm.startedAt" type="datetime-local" required />
        </label>
        <label>树脂 %
          <input v-model.number="dipForm.resinPct" type="number" step="0.1" required />
        </label>
        <label>固化时长 h（可空）
          <input v-model="dipForm.cureHours" type="number" step="0.1" />
        </label>
        <label>备注
          <input v-model="dipForm.notes" />
        </label>
        <button class="btn" type="submit" :disabled="panelBusy">写入浸渍记录</button>
      </form>

      <div class="drawer-history">
        <h3>本卷浸渍</h3>
        <ul v-if="selectedDips.length" class="feed-list compact">
          <li v-for="row in selectedDips" :key="row.id">
            <span>{{ new Date(row.startedAt).toLocaleString() }}</span>
            <span>{{ row.resinPct }}%</span>
            <span>{{ row.cureHours ?? '—' }} h</span>
          </li>
        </ul>
        <p v-else class="hint" style="margin:0">本卷尚无浸渍</p>
      </div>
    </aside>
  </div>
</template>
